from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field


class ResearchProjectRecord(BaseModel):
    project_id: str
    title: str
    library_id: str
    doc_id: str
    doc_title: str = ""
    status: str = "created"
    created_at: str = ""
    updated_at: str = ""


class ResearchProjectCreate(BaseModel):
    title: str
    library_id: str
    doc_id: str
    doc_title: str = ""


class ResearchRunRecord(BaseModel):
    run_id: str
    project_id: str
    status: str = "pending"
    progress: float = 0.0
    stage: str = ""
    stage_message: str = ""
    stage_current: int = 0
    stage_total: int = 0
    stage_detail: str = ""
    started_at: str = ""
    finished_at: str = ""
    error: str = ""


class ResearchRunStart(BaseModel):
    project_id: str


class EvidencePacket(BaseModel):
    packet_id: str
    library_id: str
    doc_id: str
    doc_title: str = ""
    section_path: str = ""
    block_ids: List[str] = Field(default_factory=list)
    summary_text: str = ""
    raw_text: str = ""
    entities: List[str] = Field(default_factory=list)
    conditions: List[str] = Field(default_factory=list)
    formulas: List[str] = Field(default_factory=list)
    tables: List[str] = Field(default_factory=list)
    citations: List[Dict[str, Any]] = Field(default_factory=list)


class ResearchCandidateRecord(BaseModel):
    candidate_id: str
    run_id: str
    section_path: str = ""
    candidate_type: str = ""
    title: str = ""
    summary: str = ""
    evidence_block_ids: List[str] = Field(default_factory=list)
    raw_score: float = 0.0
    expected_inputs: Optional[Dict[str, Any]] = None
    expected_outputs: Optional[Dict[str, Any]] = None


class ResearchGapRecord(BaseModel):
    gap_id: str
    candidate_id: str
    gap_type: str = ""
    question: str = ""
    answer: str = ""
    severity: str = "medium"


class SopDraftRecord(BaseModel):
    draft_id: str
    run_id: str
    candidate_id: str
    title: str
    sop_id_suggested: str = ""
    json_path: str
    review_status: str = "generated"
    score_total: float = 0.0
    score_rule: float = 0.0
    score_model: float = 0.0
    evidence_block_ids: List[str] = Field(default_factory=list)
    created_at: str = ""
    updated_at: str = ""


class EvalDraftRecord(BaseModel):
    draft_id: str
    run_id: str
    source_sop_draft_id: str = ""
    dataset_title: str = ""
    question_count: int = 0
    json_path: str
    review_status: str = "generated"
    created_at: str = ""
    updated_at: str = ""


class ResearchReviewAction(BaseModel):
    target_type: str
    target_id: str
    decision: str
    reviewer: str
    comment: str = ""


class ResearchRunSummary(BaseModel):
    run_id: str
    project_id: str
    status: str = ""
    stage: str = ""
    progress: float = 0.0
    candidate_count: int = 0
    sop_draft_count: int = 0
    eval_draft_count: int = 0
    approval_count: int = 0
