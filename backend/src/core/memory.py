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
    # 执行历史：已执行步骤的列表（情节记忆）
    history: List[StepRecord] = Field(default_factory=list)
    # 临时工作记忆：用于当前工具执行（短期/工具级记忆）
    # 每个步骤执行后会被清理
    working_memory: Dict[str, Any] = Field(default_factory=dict)
    
    def update_context(self, updates: Dict[str, Any]):
        """更新持久化的全局上下文。"""
        self.global_context.update(updates)

    def set_working_memory(self, data: Dict[str, Any]):
        """为当前操作设置临时数据。"""
        self.working_memory = data
        
    def clear_working_memory(self):
        """清理临时数据。"""
        self.working_memory = {}
        
    def add_history(self, record: StepRecord):
        """添加一条执行记录到历史。"""
        self.history.append(record)
        
    def resolve_value(self, value: Any) -> Any:
        """
        解析变量，例如 ${var_name} 或 ${step_id.output_key}
        """
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
        # 0. 检查工作记忆 (最高优先级 - 局部作用域)
        if key in self.working_memory:
            return self.working_memory[key]
        
        # 1. 检查全局上下文，支持点号嵌套访问
        if "." in key:
            parts = key.split(".")
            val = self.global_context
            found = True
            for part in parts:
                if isinstance(val, dict) and part in val:
                    val = val[part]
                else:
                    found = False
                    break
            if found:
                return val
        elif key in self.global_context:
            return self.global_context[key]
            
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
