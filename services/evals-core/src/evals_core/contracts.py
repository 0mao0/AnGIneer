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
    question_id: Optional[str] = None
    save: bool = True
    doc_ids: Optional[List[str]] = None
    resume_run_id: Optional[str] = None
    config_name: Optional[str] = None
    # 运行（被测）模型即 config_name；judge_config_name 为 UI 新增评测弹框选定的评价模型，
    # 判分候选链首位、失败回退环境链，并记入 run manifest
    judge_config_name: Optional[str] = None
    # UI「重来」：原地清空该 run 旧明细与进度、复用同一记录重跑全部题目（与 resume_run_id 互斥）
    restart_run_id: Optional[str] = None
    # 仅配合 resume_run_id：这些题跳过问答链路，复用存量 prediction 仅重判分（judge fallback 补判）
    rescore_question_ids: Optional[List[str]] = None
    # 用户在「已有评测正在运行」弹框里点了确定：跳过占用拦截，与在跑评测并发（POST /runs 否则返 409）
    allow_concurrent: bool = False
    # 本 run 的并行 worker 数；缺省沿用 EVAL_CONCURRENCY（多道并行跑矩阵时按道限流用）
    workers: Optional[int] = None
    # §7.7 注入实验：「答案收尾形态」注入文本（仅 QA 档与 L3 复杂档提示词追加；原文与
    # 开关态记进 run manifest）。缺省 None＝现行为逐字节不变，chat 侧不暴露。
    answer_format: Optional[str] = None


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


class CreateFolderRequest(BaseModel):
    """创建文件夹请求。"""
    folder_id: str
    title: str
    category: str = "knowledge"
    parent_folder_id: str = ""


class UpdateFolderRequest(BaseModel):
    """更新文件夹请求。"""
    title: Optional[str] = None
    category: Optional[str] = None
    parent_folder_id: Optional[str] = None
    sort_order: Optional[int] = None


class MoveDatasetRequest(BaseModel):
    """移动数据集请求。"""
    folder_id: str = ""
    sort_order: int = 0
