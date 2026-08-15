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
    status: Literal["draft", "reviewed", "published", "disabled"] = "draft"
    confidence: float = 0.0
    source: Dict[str, Any] = Field(default_factory=dict)
    review: Dict[str, Any] = Field(default_factory=dict)
    stats: Dict[str, Any] = Field(default_factory=dict)

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
    "structured_lookup",
    "sql_first",  # legacy：历史评测/轨迹兼容
    "standard_sop",
    "dynamic_orchestration",
]


class AttemptedPathResult(BaseModel):
    """记录分层尝试链中单一路径的执行结果。"""
    path: ServiceMode
    status: Literal["success", "insufficient", "no_match", "failed", "skipped"] = "skipped"
    reason: Optional[str] = None


class IntentResult(BaseModel):
    """L0~L4 意图识别结果，由 IntentClassifier 输出。"""
    intent_level: IntentLevel = "L1"
    primary_level: IntentLevel = "L1"
    intent_type: str = ""
    parameters: Dict[str, Any] = Field(default_factory=dict)
    required_capabilities: List[str] = Field(default_factory=list)
    matched_sop: Optional[str] = None
    service_mode: ServiceMode = "semantic_retrieval"
    execution_plan: List[ServiceMode] = Field(default_factory=list)
    attempted_paths: List[AttemptedPathResult] = Field(default_factory=list)
    final_path: Optional[ServiceMode] = None
    fallback_reason: Optional[str] = None
    reason: Optional[str] = None


class GapAnalysis(BaseModel):
    """知识盲区分析项。"""
    gap_description: str = ""
    suggested_sources: List[str] = Field(default_factory=list)


class AgentResponse(BaseModel):
    """Agent 标准响应结构。"""
    content: str
    data: Optional[Dict[str, Any]] = None
    gap_analysis: Optional[List[GapAnalysis]] = None
    confidence_breakdown: Optional[Dict[str, List[str]]] = None


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


class ScopeContext(BaseModel):
    """检索/会话范围上下文（门牌号）。默认 default 库，但链路上传递必须显式。"""
    library_id: str = "default"
    doc_ids: List[str] = Field(default_factory=list)
    filters: Dict[str, Any] = Field(default_factory=dict)
    source: str = "request"
    request_id: Optional[str] = None


class RouteDebug(BaseModel):
    """路由决策的可观测投影（SSE 首帧与 evals 落盘共用词汇）。"""
    level: Optional[IntentLevel] = None
    service_mode: Optional[ServiceMode] = None
    confidence: float = 0.0
    reason: Optional[str] = None
    fallback: bool = False


class RouteDecision(BaseModel):
    """Router 派工单：请求进入执行前的路由决策。意图可以错，scope 不能漏。"""
    intent_result: IntentResult = Field(default_factory=IntentResult)
    scene: str = "qa"
    scope: ScopeContext = Field(default_factory=ScopeContext)
    attempts: List[str] = Field(default_factory=list)
    confidence: float = 0.0
    route_debug: RouteDebug = Field(default_factory=RouteDebug)
    fallback: bool = False


EvidenceKind = Literal["text", "table", "formula", "clause", "graph_entity", "sop_step"]


class Evidence(BaseModel):
    """统一证据模型：正文/表格/公式/条款/图谱实体/SOP 步骤统一结构；citations 仅作展示投影。"""
    evidence_id: str
    kind: EvidenceKind = "text"
    doc_id: str = ""
    doc_title: str = ""
    content: str = ""
    page_idx: Optional[int] = None
    page_label: Optional[str] = None
    section_path: str = ""
    score: float = 0.0
    source: str = ""
    library_id: str = "default"
    metadata: Dict[str, Any] = Field(default_factory=dict)
