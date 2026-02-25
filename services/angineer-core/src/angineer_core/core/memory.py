"""
上下文记忆核心模块，负责黑板、执行历史与临时工作记忆管理。
"""
from typing import Dict, Any, List, Optional
import re
from pydantic import BaseModel, Field
from ..config import get_config, MemoryConfig
from ..infra.logger import get_logger

logger = get_logger(__name__)


class UndefinedVariableError(Exception):
    """
    未定义变量错误。
    当在严格模式下尝试解析未定义的变量时抛出。
    """
    
    def __init__(self, variable_name: str, context: Optional[str] = None):
        self.variable_name = variable_name
        self.context = context
        message = f"未定义的变量: ${{{variable_name}}}"
        if context:
            message += f" (上下文: {context})"
        super().__init__(message)


class StepRecord(BaseModel):
    """
    步骤执行记录，用于存储每个步骤的执行历史。
    """
    step_id: str
    tool_name: str
    inputs: Dict[str, Any]
    outputs: Any
    status: str = "success"
    error: Optional[str] = None


class Memory(BaseModel):
    """
    记忆管理类，负责维护全局上下文、执行历史和临时工作记忆。
    """
    
    global_context: Dict[str, Any] = Field(default_factory=dict)
    blackboard: Dict[str, Any] = Field(default_factory=dict)
    chat_context: List[Dict[str, Any]] = Field(default_factory=list)
    step_io: List[Dict[str, Any]] = Field(default_factory=list)
    tool_working_memory: Dict[str, Any] = Field(default_factory=dict)
    history: List[StepRecord] = Field(default_factory=list)
    
    _config: Optional[MemoryConfig] = None
    
    def __init__(self, **data):
        super().__init__(**data)
        self._config = get_config().memory
    
    def get_config(self) -> MemoryConfig:
        """获取内存配置。"""
        return self._config or get_config().memory
    
    def set_config(self, config: MemoryConfig):
        """设置内存配置。"""
        self._config = config
    
    def update_context(self, updates: Dict[str, Any]):
        """更新黑板数据并同步上下文快照。"""
        self.blackboard.update(updates)
        self._sync_global_context()
        logger.debug(f"黑板已更新: {list(updates.keys())}")

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
    
    def resolve_value(
        self,
        value: Any,
        strict: Optional[bool] = None,
        none_replacement: Optional[str] = None
    ) -> Any:
        """
        解析变量，例如 ${var_name} 或 ${step_id.output_key}。
        
        Args:
            value: 要解析的值，可能包含 ${variable} 占位符
            strict: 是否使用严格模式。True 时未定义变量抛出异常，
                    False 时使用替换值。默认使用配置值。
            none_replacement: 当变量值为 None 时的替换字符串。
                             默认使用配置值。
        
        Returns:
            解析后的值
        
        Raises:
            UndefinedVariableError: 在严格模式下遇到未定义变量时抛出
        """
        config = self.get_config()
        use_strict = strict if strict is not None else config.strict_mode
        replacement = none_replacement if none_replacement is not None else config.none_replacement
        
        if isinstance(value, dict):
            return {k: self.resolve_value(v, use_strict, replacement) for k, v in value.items()}
        
        if isinstance(value, list):
            return [self.resolve_value(v, use_strict, replacement) for v in value]
        
        if not isinstance(value, str):
            return value
        
        pattern = r"\$\{(.+?)\}"
        matches = re.findall(pattern, value)
        
        if not matches:
            return value
        
        if len(matches) == 1 and value.strip() == f"${{{matches[0]}}}":
            resolved = self._get_value(matches[0])
            if resolved is None:
                return self._handle_undefined(matches[0], use_strict, replacement)
            return resolved
        
        result = value
        for match in matches:
            resolved = self._get_value(match)
            if resolved is None:
                resolved = self._handle_undefined(match, use_strict, replacement)
            result = result.replace(f"${{{match}}}", str(resolved))
        
        return result
    
    def _handle_undefined(
        self,
        variable_name: str,
        strict: bool,
        replacement: str
    ) -> Any:
        """
        处理未定义变量的情况。
        
        Args:
            variable_name: 变量名
            strict: 是否严格模式
            replacement: 替换值
        
        Returns:
            替换值（非严格模式）
        
        Raises:
            UndefinedVariableError: 严格模式下抛出
        """
        if strict:
            logger.error(f"未定义变量: ${{{variable_name}}}")
            raise UndefinedVariableError(
                variable_name,
                context=f"黑板键: {list(self.blackboard.keys())}"
            )
        
        logger.warning(f"变量 ${{{variable_name}}} 未定义，使用替换值: '{replacement}'")
        return replacement
        
    def _get_value(self, key: str) -> Any:
        """
        获取变量值，支持点号(.)嵌套访问。
        
        Args:
            key: 变量名，支持嵌套访问如 "step_id.output.field"
        
        Returns:
            变量值，未找到时返回 None
        """
        if key in self.tool_working_memory:
            return self.tool_working_memory[key]
        
        if key in self.blackboard:
            return self.blackboard[key]
        
        if "." in key:
            parts = key.split(".")
            
            val = self.blackboard
            found = True
            for part in parts:
                if isinstance(val, dict) and part in val:
                    val = val[part]
                else:
                    found = False
                    break
            if found:
                return val
            
            val = self.tool_working_memory
            found = True
            for part in parts:
                if isinstance(val, dict) and part in val:
                    val = val[part]
                else:
                    found = False
                    break
            if found:
                return val
        
        if key in self.get_context_snapshot():
            return self.get_context_snapshot()[key]
        
        if "." in key:
            step_id, field = key.split(".", 1)
            for record in reversed(self.history):
                if record.step_id == step_id:
                    if field == "output" or field == "outputs":
                        return record.outputs
                    if field.startswith("outputs."):
                        sub_key = field.split(".", 1)[1]
                        if isinstance(record.outputs, dict):
                            return record.outputs.get(sub_key)
        
        logger.debug(f"变量 ${{{key}}} 未找到")
        return None
    
    def has_variable(self, variable_name: str) -> bool:
        """
        检查变量是否存在。
        
        Args:
            variable_name: 变量名（不含 ${} 包裹）
        
        Returns:
            变量是否存在
        """
        return self._get_value(variable_name) is not None
    
    def list_available_variables(self) -> List[str]:
        """
        列出所有可用的变量名。
        
        Returns:
            可用变量名列表
        """
        variables = set()
        
        variables.update(self.tool_working_memory.keys())
        variables.update(self.blackboard.keys())
        
        for record in self.history:
            variables.add(f"{record.step_id}.output")
            if isinstance(record.outputs, dict):
                for key in record.outputs.keys():
                    variables.add(f"{record.step_id}.outputs.{key}")
        
        return sorted(list(variables))
