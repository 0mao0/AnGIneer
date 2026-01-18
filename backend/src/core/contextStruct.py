from typing import List, Dict, Any, Optional
from pydantic import BaseModel, Field

class Step(BaseModel):
    """
    定义SOP中的原子执行步骤。
    Attributes:
        id (str): 步骤唯一标识符，用于在Memory中引用 (例如 ${step_id.outputs})。
        tool (str): 要调用的工具名称 (ToolRegistry中的key)。
        inputs (Dict): 传递给工具的参数。支持上下文引用 (例如 "${user_query}")。
        outputs (Dict): 定义如何处理工具的返回结果。映射关系: { "context_key": "tool_output_path" }。
        next_step_id (str): (可选) 下一步骤ID，用于非线性流程控制。
    """
    id: str
    name: Optional[str] = None # Legacy support
    name_zh: Optional[str] = None
    name_en: Optional[str] = None
    description: Optional[str] = None # Legacy support
    description_zh: Optional[str] = None
    description_en: Optional[str] = None
    tool: str
    # Map from tool argument name to value or context reference
    # e.g. {"location": "${user_query}", "days": 3}
    inputs: Dict[str, Any] = Field(default_factory=dict)
    # Define what keys to extract from tool output to update context
    # e.g. {"weather_info": "result"} -> context["weather_info"] = tool_output["result"]
    outputs: Dict[str, str] = Field(default_factory=dict)
    
    # Next step logic could be here, but for now simple linear or list index based
    next_step_id: Optional[str] = None
    on_failure: Optional[str] = None # Jump to this step id on failure
    
    # 混合架构新增字段
    notes: Optional[str] = None # 步骤的注意事项、特殊逻辑描述（来自SOP文本）
    analysis_status: Optional[str] = "pending" # pending, analyzed

class SOP(BaseModel):
    """
    标准作业程序 (Standard Operating Procedure) 定义。
    这是Agent执行任务的"剧本"。
    """
    id: str
    name_zh: Optional[str] = None
    name_en: Optional[str] = None
    description: Optional[str] = None # Legacy support
    description_zh: Optional[str] = None
    description_en: Optional[str] = None
    steps: List[Step]
    
    def get_step(self, step_id: str) -> Optional[Step]:
        for step in self.steps:
            if step.id == step_id:
                return step
        return None

class AgentResponse(BaseModel):
    """Standard response from Router or other agents"""
    content: str
    data: Optional[Dict[str, Any]] = None
