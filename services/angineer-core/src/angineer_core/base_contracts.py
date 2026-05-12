"""
angineer-core 数据契约定义。

包含组件间通信的所有标准数据结构：
- SOP / Step：标准作业程序定义
- IntentResult / IntentLevel / ServiceMode：意图分类输出
- AgentResponse：Agent 响应格式
- IntentResponse / ActionResponse / StepParseResponse / ArgsExtractResponse：LLM 响应解析格式
"""
from typing import List, Dict, Any, Literal, Optional
from pydantic import BaseModel, Field


class InlineCitationDraftValue(BaseModel):
    """结构化正文（支持内联引用的草稿值）。"""
    content: str = ""
    citations: List[Dict[str, Any]] = Field(default_factory=list)


class Step(BaseModel):
    """定义 SOP 中的原子执行步骤。"""
    id: str
    name: Optional[str] = None
    name_zh: Optional[str] = None
    name_en: Optional[str] = None
    description: InlineCitationDraftValue = Field(default_factory=InlineCitationDraftValue)
    description_zh: Optional[str] = None
    description_en: Optional[str] = None
    tool: str
    inputs: Dict[str, Any] = Field(default_factory=dict)
    outputs: Dict[str, str] = Field(default_factory=dict)
    next_step_id: Optional[str] = None
    on_failure: Optional[str] = None
    notes: Optional[str] = None
    analysis_status: Optional[str] = "pending"


class SOP(BaseModel):
    """标准作业程序定义。"""
    id: str
    name_zh: Optional[str] = None
    name_en: Optional[str] = None
    description: Optional[str] = None
    description_zh: Optional[str] = None
    description_en: Optional[str] = None
    steps: List[Step]
    blackboard: Optional[Dict[str, Any]] = None

    def get_step(self, step_id: str) -> Optional[Step]:
        """根据 ID 查找步骤。"""
        for step in self.steps:
            if step.id == step_id:
                return step
        return None


IntentLevel = Literal["L0", "L1", "L2", "L3", "L4"]

ServiceMode = Literal[
    "casual_chat",
    "semantic_retrieval",
    "sql_first",
    "standard_sop",
    "dynamic_orchestration",
]


class IntentResult(BaseModel):
    """L0~L4 意图识别结果，由 IntentClassifier 输出。"""
    intent_level: IntentLevel = "L1"
    intent_type: str = ""
    parameters: Dict[str, Any] = Field(default_factory=dict)
    required_capabilities: List[str] = Field(default_factory=list)
    matched_sop: Optional[str] = None
    service_mode: ServiceMode = "semantic_retrieval"
    reason: Optional[str] = None


class AgentResponse(BaseModel):
    """Agent 标准响应结构。"""
    content: str
    data: Optional[Dict[str, Any]] = None


class IntentResponse(BaseModel):
    """意图分类响应结构。"""
    sop_id: Optional[str] = None
    reason: Optional[str] = None


class ActionResponse(BaseModel):
    """步骤执行动作响应结构。"""
    action: str
    question: Optional[str] = None
    query: Optional[str] = None
    table_name: Optional[str] = None
    conditions: Optional[Dict[str, Any]] = None
    target_column: Optional[str] = None
    tool: Optional[str] = None
    inputs: Optional[Dict[str, Any]] = None
    value: Optional[Any] = None
    reason: Optional[str] = None


class StepParseResponse(BaseModel):
    """SOP 步骤解析响应结构。"""
    id: str
    name: Optional[str] = None
    description: Optional[str] = None
    tool: str
    inputs: Dict[str, Any] = {}
    outputs: Dict[str, str] = {}
    notes: Optional[str] = None


class ArgsExtractResponse(BaseModel):
    """参数提取响应结构。"""
    args: Dict[str, Any] = {}


class RouteResult(BaseModel):
    """SOP 路由结果，由 IntentClassifier.route() 输出。"""
    sop: Optional[Any] = None
    args: Dict[str, Any] = Field(default_factory=dict)
    reason: Optional[str] = None
    confidence: float = 0.0
    candidates: List[Dict[str, Any]] = Field(default_factory=list)
