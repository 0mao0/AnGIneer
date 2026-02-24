"""
上下文记忆核心模块，负责黑板、执行历史与临时工作记忆管理。
"""
from typing import Dict, Any, List, Optional
import re
from pydantic import BaseModel, Field

class StepRecord(BaseModel):
    """
    步骤执行记录，用于存储每个步骤的执行历史。
    """
    step_id: str
    tool_name: str
    inputs: Dict[str, Any]
    outputs: Any
    status: str = "success" # 状态：success (成功), failed (失败)
    error: Optional[str] = None

class Memory(BaseModel):
    """
    记忆管理类，负责维护全局上下文、执行历史和临时工作记忆。
    """
    # 全局上下文：跨会话共享（长期/任务级记忆）
    global_context: Dict[str, Any] = Field(default_factory=dict)
    blackboard: Dict[str, Any] = Field(default_factory=dict)
    chat_context: List[Dict[str, Any]] = Field(default_factory=list)
    step_io: List[Dict[str, Any]] = Field(default_factory=list)
    tool_working_memory: Dict[str, Any] = Field(default_factory=dict)
    # 执行历史：已执行步骤的列表（情节记忆）
    history: List[StepRecord] = Field(default_factory=list)
    
    def update_context(self, updates: Dict[str, Any]):
        """更新黑板数据并同步上下文快照。"""
        self.blackboard.update(updates)
        self._sync_global_context()

    def set_working_memory(self, data: Dict[str, Any]):
        """为当前操作设置临时数据。"""
        self.tool_working_memory = data
        self._sync_global_context()
        
    def clear_working_memory(self):
        """清理临时数据。"""
        self.tool_working_memory = {}
        self._sync_global_context()
        
    def add_history(self, record: StepRecord):
        """添加一条执行记录到历史。"""
        self.history.append(record)
        self._sync_global_context()

    def add_step_io(self, record: Dict[str, Any]):
        """记录单步执行输入输出。"""
        self.step_io.append(record)
        self._sync_global_context()

    def add_chat_message(self, role: str, content: str):
        """添加聊天记录。"""
        self.chat_context.append({"role": role, "content": content})
        self._sync_global_context()

    def get_context_snapshot(self) -> Dict[str, Any]:
        """获取用于上下文传递的聚合快照。"""
        self._sync_global_context()
        return self.global_context

    def _sync_global_context(self):
        """同步聚合上下文快照。"""
        self.global_context = {
            "blackboard": self.blackboard,
            "chat_context": self.chat_context,
            "step_io": self.step_io,
            "tool_working_memory": self.tool_working_memory,
            "history": [r.model_dump() for r in self.history]
        }
        
    def resolve_value(self, value: Any) -> Any:
        """
        解析变量，例如 ${var_name} 或 ${step_id.output_key}
        """
        if isinstance(value, dict):
            return {k: self.resolve_value(v) for k, v in value.items()}
        if isinstance(value, list):
            return [self.resolve_value(v) for v in value]
        if not isinstance(value, str):
            return value
            
        # 查找 ${variable} 模式
        pattern = r"\$\{(.+?)\}"
        matches = re.findall(pattern, value)
        
        if not matches:
            return value
            
        # 如果整个字符串就是一个变量，返回其实际类型
        if len(matches) == 1 and value.strip() == f"${{{matches[0]}}}":
            return self._get_value(matches[0])
            
        # 否则在字符串中进行替换
        result = value
        for match in matches:
            val = self._get_value(match)
            result = result.replace(f"${{{match}}}", str(val))
        return result
        
    def _get_value(self, key: str) -> Any:
        """
        获取变量值，支持点号(.)嵌套访问。
        """
        # 0. 检查工具工作记忆 (最高优先级 - 局部作用域)
        if key in self.tool_working_memory:
            return self.tool_working_memory[key]
        
        # 1. 检查黑板与全局上下文，支持点号嵌套访问
        if key in self.blackboard:
            return self.blackboard[key]
        if "." in key:
            parts = key.split(".")
            val = self.get_context_snapshot()
            found = True
            for part in parts:
                if isinstance(val, dict) and part in val:
                    val = val[part]
                else:
                    found = False
                    break
            if found:
                return val
        elif key in self.get_context_snapshot():
            return self.get_context_snapshot()[key]
            
        # 2. 检查历史记录 (高级用法: ${step_id.output})
        if "." in key:
            step_id, field = key.split(".", 1)
            for record in reversed(self.history):
                if record.step_id == step_id:
                    # 允许访问输入或输出
                    if field == "output" or field == "outputs":
                        return record.outputs
                    if field.startswith("outputs."):
                        sub_key = field.split(".", 1)[1]
                        if isinstance(record.outputs, dict):
                            return record.outputs.get(sub_key)
                    # 此处可添加更多逻辑
                    
        return None
