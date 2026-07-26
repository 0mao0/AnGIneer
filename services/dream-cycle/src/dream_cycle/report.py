"""Dream Cycle 报告数据模型。

定义每日运行报告及其所有子结构。
"""

from datetime import datetime
from typing import Optional, List, Dict, Any
from pydantic import BaseModel, Field


class TaskResult(BaseModel):
    """单个检查任务的结果。"""
    task_name: str = ""
    status: str = "success"  # success | warning | error | skipped
    message: str = ""
    duration_seconds: float = 0.0
    findings_count: int = 0
    auto_fixed_count: int = 0
    error_detail: Optional[str] = None


class OrphanEntity(BaseModel):
    """孤立实体候选。"""
    entity_id: str = ""
    entity_name: str = ""
    entity_layer: str = ""  # concept | condition | action
    age_days: int = 0
    suggested_action: str = "review"  # review | auto_mark_inactive


class DuplicateCandidate(BaseModel):
    """疑似重复实体对。"""
    entity_a_id: str = ""
    entity_a_name: str = ""
    entity_b_id: str = ""
    entity_b_name: str = ""
    match_method: str = ""  # edit_distance | alias_overlap | llm_semantic
    confidence: float = 0.0
    suggested_action: str = "review"  # review | auto_merge
    suggested_canonical_name: str = ""


class ContradictionCandidate(BaseModel):
    """疑似矛盾关系对。"""
    entity_subject: str = ""
    entity_object: str = ""
    relation_a: Dict[str, Any] = Field(default_factory=dict)
    relation_b: Dict[str, Any] = Field(default_factory=dict)
    contradiction_type: str = ""  # value_conflict | type_conflict | version_conflict
    suggested_resolution: str = ""
    confidence: float = 0.0


class StalenessCandidate(BaseModel):
    """疑似过期实体。"""
    entity_id: str = ""
    entity_name: str = ""
    source_doc_id: str = ""
    source_doc_title: str = ""
    superseded_by_doc_title: str = ""
    reason: str = ""


class SopHealthStats(BaseModel):
    """SOP 健康统计。"""
    total_sops: int = 0
    active_sops: int = 0
    total_steps: int = 0
    most_used_sop: str = ""
    least_used_sop: str = ""
    sops_with_missing_coverage: List[Dict[str, Any]] = Field(default_factory=list)
    avg_step_count: float = 0.0


class DreamCycleReport(BaseModel):
    """每日 Dream Cycle 运行报告。"""
    report_date: str = ""  # YYYY-MM-DD
    generated_at: str = ""
    run_duration_seconds: float = 0.0

    # 各任务结果
    task_results: List[TaskResult] = Field(default_factory=list)

    # 具体发现
    duplicate_candidates: List[DuplicateCandidate] = Field(default_factory=list)
    contradiction_candidates: List[ContradictionCandidate] = Field(default_factory=list)
    orphan_entities: List[OrphanEntity] = Field(default_factory=list)
    staleness_candidates: List[StalenessCandidate] = Field(default_factory=list)
    sop_health: Optional[SopHealthStats] = None

    # 统计汇总
    total_findings: int = 0
    total_auto_fixed: int = 0

    @classmethod
    def create_empty(cls, report_date: str = "") -> "DreamCycleReport":
        """创建一份空的当日报告。"""
        now = datetime.now()
        return cls(
            report_date=report_date or now.strftime("%Y-%m-%d"),
            generated_at=now.isoformat(),
        )

    def finalize(self, run_duration: float):
        """汇总统计数据。"""
        self.run_duration_seconds = round(run_duration, 2)
        self.total_findings = (
            len(self.duplicate_candidates)
            + len(self.contradiction_candidates)
            + len(self.orphan_entities)
            + len(self.staleness_candidates)
        )
        self.total_auto_fixed = sum(
            t.auto_fixed_count for t in self.task_results
        )
