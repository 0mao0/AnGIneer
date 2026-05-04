"""API 请求/响应契约模型。"""
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field


class CreateDatasetRequest(BaseModel):
    """创建空测试集请求。"""
    dataset_id: str
    title: str
    category: str = "knowledge"
    description: str = ""
    library_id: str = "default"


class AddQuestionRequest(BaseModel):
    """向测试集添加单题请求。"""
    question_id: str
    question: str
    task_type: str = "definition"
    intent_level: str = "L1"
    library_id: str = "default"
    doc_ids: List[str] = Field(default_factory=list)
    difficulty: str = "easy"
    tags: List[str] = Field(default_factory=list)
    retrieval: Optional[Dict[str, Any]] = None
    answer: Optional[Dict[str, Any]] = None
    sql: Optional[Dict[str, Any]] = None
    sop: Optional[Dict[str, Any]] = None


class UpdateQuestionRequest(BaseModel):
    """编辑题目请求。"""
    question: Optional[str] = None
    task_type: Optional[str] = None
    intent_level: Optional[str] = None
    library_id: Optional[str] = None
    doc_ids: Optional[List[str]] = None
    difficulty: Optional[str] = None
    tags: Optional[List[str]] = None
    retrieval: Optional[Dict[str, Any]] = None
    answer: Optional[Dict[str, Any]] = None
    sql: Optional[Dict[str, Any]] = None
    sop: Optional[Dict[str, Any]] = None


class StartEvalRunRequest(BaseModel):
    """启动评测运行请求。"""
    dataset_id: str


class EvalRunProgress(BaseModel):
    """评测运行进度响应。"""
    run_id: str
    dataset_id: str
    status: str
    total_questions: int = 0
    completed_questions: int = 0
    started_at: str = ""
    completed_at: str = ""
    summary_scores: Optional[Dict[str, Any]] = None
    details: List[Dict[str, Any]] = Field(default_factory=list)


class CompareResult(BaseModel):
    """两次运行对比结果。"""
    run_a: EvalRunProgress
    run_b: EvalRunProgress
    score_diff: Dict[str, float] = Field(default_factory=dict)
    question_changes: List[Dict[str, Any]] = Field(default_factory=list)
