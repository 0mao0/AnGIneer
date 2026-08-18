"""计算 v1 resume 的剩余阶段（纯函数，便于单测）。"""
from typing import Dict, List, Optional

_PIPELINE_ORDER = [
    "source_prep", "convert", "raw_parse", "popo", "structure", "fts", "vectors", "graph",
]
_DEPENDENCY_SKIP_MARKERS = ("前置硬阶段", "依赖阶段失败")
DEFAULT_STAGES = ["structure"]


def _split_stages(raw: str) -> List[str]:
    if not raw or not raw.strip():
        return []
    if raw.strip().lower() == "all":
        return list(_PIPELINE_ORDER)
    return [s.strip() for s in raw.split(",") if s.strip()]


def _resolve_scope(requested_stages: str, present_keys: set) -> List[str]:
    """确定目标阶段范围；旧记录（无 stages）按已出现阶段推断并强制补 structure。"""
    if requested_stages and requested_stages.strip():
        keys = set(_split_stages(requested_stages))
        return [k for k in _PIPELINE_ORDER if k in keys]
    if not present_keys:
        return list(DEFAULT_STAGES)
    keys = set(present_keys)
    keys.add("structure")
    return [k for k in _PIPELINE_ORDER if k in keys]


def _is_dependency_skip(row: Optional[Dict]) -> bool:
    """依赖失败导致的连带 skipped 不能视为已完成，resume 时应重新调度。"""
    if not row:
        return False
    message = str(row.get("message") or "")
    return any(marker in message for marker in _DEPENDENCY_SKIP_MARKERS)


def compute_resume_stages(requested_stages: str, stage_rows: List[Dict]) -> List[str]:
    """返回需要重跑的阶段（按流水线顺序）。

    stage_rows 来自 meta_store.list_parse_stages(doc_id)，每项含 stage/status/message。
    completed 视为已完成；因前置依赖失败被连带 skipped（message 含依赖失败标记）的
    阶段需要重新调度；running/failed/queued/缺失阶段也要续跑。
    """
    present = {str(r.get("stage") or "").strip() for r in stage_rows if r.get("stage")}
    rows_by_stage = {
        str(r.get("stage") or "").strip(): r for r in stage_rows if r.get("stage")
    }
    status_map = {stage: str(r.get("status") or "") for stage, r in rows_by_stage.items()}
    scope = _resolve_scope(requested_stages or "", present)
    remaining = []
    for key in scope:
        status = status_map.get(key)
        if status == "completed":
            continue
        if status == "skipped" and not _is_dependency_skip(rows_by_stage.get(key)):
            continue
        remaining.append(key)
    return remaining
