"""评测题集数据模型定义。"""
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field


class RetrievalGold(BaseModel):
    """检索评测标准答案。"""
    gold_section_paths: List[str] = Field(default_factory=list)
    gold_chunk_ids: List[str] = Field(default_factory=list)
    gold_doc_ids: List[str] = Field(default_factory=list)
    gold_target_ids: List[str] = Field(default_factory=list)
    gold_target_types: List[str] = Field(default_factory=list)
    question_type: str = "definition_qa"
    notes: str = ""
    must_include_terms: List[str] = Field(default_factory=list)
    must_exclude_terms: List[str] = Field(default_factory=list)
    hard_negative_target_ids: List[str] = Field(default_factory=list)
    robustness_tags: List[str] = Field(default_factory=list)


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
    question_family: str = ""
    canonical_question_id: str = ""
    variant_type: str = "canonical"
    perturbation_tags: List[str] = Field(default_factory=list)
    retrieval: Optional[RetrievalGold] = None
    answer: Optional[AnswerGold] = None
    sql: Optional[SqlGold] = None
    sop: Optional[SopGold] = None
    # 探针断言块（clause-probe 类题集）：不跑生成/判官，只做路由层+检索层断言。
    # 结构不固定（expect_clause_direct / gold_num / precise_rank_max / xfail …），
    # 断言语义见 evals_core.runner.probe_eval。
    probe: Optional[Dict[str, Any]] = None
    # 意图路由金标块（intent-router 类题集）：不跑检索/生成/判官，只断言分类器产出的路由结果。
    # 结构 = level / mode / route / family / trap / rationale / strict_level / strict_mode / xfail，
    # 断言语义见 evals_core.runner.intent_eval。
    intent: Optional[Dict[str, Any]] = None


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
    question_family: str = ""
    canonical_question_id: str = ""
    variant_type: str = "canonical"
    perturbation_tags: List[str] = Field(default_factory=list)
    retrieval_gold: Optional[Dict[str, Any]] = None
    answer_gold: Optional[Dict[str, Any]] = None
    sql_gold: Optional[Dict[str, Any]] = None
    sop_gold: Optional[Dict[str, Any]] = None
    probe_gold: Optional[Dict[str, Any]] = None
    intent_gold: Optional[Dict[str, Any]] = None
    sort_order: int = 0
