"""计算 v1 resume 的剩余阶段（纯函数，便于单测）。"""
from typing import Dict, List

_PIPELINE_ORDER = [
    "source_prep", "convert", "raw_parse", "popo", "structure", "fts", "vectors", "graph",
]
_TERMINAL_DONE = {"completed", "skipped"}
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


def compute_resume_stages(requested_stages: str, stage_rows: List[Dict]) -> List[str]:
    """返回需要重跑的阶段（按流水线顺序）。

    stage_rows 来自 meta_store.list_parse_stages(doc_id)，每项含 stage/status。
    completed/skipped 视为已完成；running/failed/queued/缺失阶段都要续跑。
    """
    present = {str(r.get("stage") or "").strip() for r in stage_rows if r.get("stage")}
    status_map = {
        str(r.get("stage") or "").strip(): str(r.get("status") or "")
        for r in stage_rows
        if r.get("stage")
    }
    scope = _resolve_scope(requested_stages or "", present)
    return [key for key in scope if status_map.get(key) not in _TERMINAL_DONE]
