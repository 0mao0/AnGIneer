"""评测题集数据模型定义。"""
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field


class RetrievalGold(BaseModel):
    """检索评测标准答案。"""
    gold_section_paths: List[str] = Field(default_factory=list)
    gold_chunk_ids: List[str] = Field(default_factory=list)
    gold_doc_ids: List[str] = Field(default_factory=list)


class CorrectnessCheck(BaseModel):
    """单条结构化正确性断言。"""
    type: str = "contains_all"
    keywords: List[str] = Field(default_factory=list)


class AnswerGold(BaseModel):
    """回答评测标准答案。"""
    gold_answer: str = ""
    correctness_checks: List[CorrectnessCheck] = Field(default_factory=list)
    semantic_threshold: float = 0.65
    must_cite_target_ids: List[str] = Field(default_factory=list)
    must_cite_section_paths: List[str] = Field(default_factory=list)
    refusal_expected: bool = False


class SqlGold(BaseModel):
    """SQL 评测标准答案。"""
    expected_sql: str = ""
    expected_result: Optional[Dict[str, Any]] = None


class SopGold(BaseModel):
    """SOP 评测标准答案。"""
    expected_sop_id: str = ""
    expected_steps: List[str] = Field(default_factory=list)
    expected_result: Optional[Dict[str, Any]] = None


class EvalQuestionItem(BaseModel):
    """评测题目条目（对应 JSON 规范中的 item）。"""
    question_id: str
    question: str
    task_type: str = "definition"
    intent_level: str = "L1"
    library_id: str = "default"
    doc_ids: List[str] = Field(default_factory=list)
    difficulty: str = "easy"
    tags: List[str] = Field(default_factory=list)
    retrieval: Optional[RetrievalGold] = None
    answer: Optional[AnswerGold] = None
    sql: Optional[SqlGold] = None
    sop: Optional[SopGold] = None


class EvalDatasetMeta(BaseModel):
    """测试集元信息。"""
    dataset_id: str
    title: str
    category: str = "knowledge"
    description: str = ""
    schema_version: str = "eval.bundle.v2"
    version: str = "1.0"
    library_id: str = "default"


class EvalBundleV2(BaseModel):
    """评测题集完整结构（eval.bundle.v2）。"""
    dataset: EvalDatasetMeta
    items: List[EvalQuestionItem] = Field(default_factory=list)


class EvalDatasetRow(BaseModel):
    """数据库 eval_dataset 行映射。"""
    dataset_id: str
    title: str
    category: str = "knowledge"
    description: str = ""
    schema_version: str = "eval.bundle.v2"
    version: str = "1.0"
    library_id: str = "default"
    question_count: int = 0
    source_file: str = ""
    created_at: str = ""
    updated_at: str = ""


class EvalQuestionRow(BaseModel):
    """数据库 eval_question 行映射。"""
    question_id: str
    dataset_id: str
    question: str
    task_type: str = "definition"
    intent_level: str = "L1"
    difficulty: str = "easy"
    tags: List[str] = Field(default_factory=list)
    library_id: str = "default"
    doc_ids: List[str] = Field(default_factory=list)
    retrieval_gold: Optional[Dict[str, Any]] = None
    answer_gold: Optional[Dict[str, Any]] = None
    sql_gold: Optional[Dict[str, Any]] = None
    sop_gold: Optional[Dict[str, Any]] = None
    sort_order: int = 0
