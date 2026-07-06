"""
[已废弃] SOP Research Pipeline

原有 7 阶段 research pipeline (evidence_prepare → candidate_extract → socratic_expand →
sop_synthesize → eval_generate → rule_validate → score_and_rank) 已被 knowledge-graph 服务替代。

导入仍兼容，但 orchestrator 在 start_run() 会记录废弃警告。
"""

import warnings

warnings.warn(
    "sop_core.research is deprecated. Use knowledge_graph module instead.",
    DeprecationWarning,
    stacklevel=2,
)

# Re-export for backward compatibility
from sop_core.research.contracts import (
    EvalDraftRecord,
    EvidencePacket,
    ResearchCandidateRecord,
    ResearchGapRecord,
    ResearchProjectCreate,
    ResearchProjectRecord,
    ResearchReviewAction,
    ResearchRunRecord,
    ResearchRunStart,
    ResearchRunSummary,
    SopDraftRecord,
)
from sop_core.research.store import ResearchStore
from sop_core.research.graph_consumer import GraphConsumer
