"""evals-core 只读适配：题集简报 / 题集卡片 / 分页题目。

只 import 查询函数，不调任何写函数（红线：用户内容永远不写进正式题库，
投稿落 community.sqlite，晋升是人工另案）。
manager 惰性 import——本包被 aichat-api 挂载时 evals-core 已在 sys.path，
独立跑 pytest 时若缺包，仅相关用例会失败，不炸整包 import。
"""
from typing import Any, Dict, List, Optional, Tuple

# 题集卡片对外只留这几项（设计 §10：公开元信息白名单，防内部字段外泄）
_PUBLIC_META_KEYS = ("publisher", "domain", "mode", "purpose", "source_url", "source_note")


def _manager():
    from evals_core.dataset import manager  # noqa: PLC0415 惰性：避免包级硬依赖
    return manager


def list_dataset_briefs() -> List[Dict[str, Any]]:
    """全部题集简报（树装配用）。题集数 < 千级，全量取回内存筛绑定即可。"""
    rows = _manager().list_datasets()
    out: List[Dict[str, Any]] = []
    for row in rows:
        out.append({
            "dataset_id": row.get("dataset_id", ""),
            "title": row.get("title", "") or row.get("dataset_id", ""),
            "category": row.get("category", "") or "",
            "description": row.get("description", "") or "",
            "question_count": int(row.get("question_count") or 0),
        })
    return out


def dataset_card(dataset_id: str) -> Optional[Dict[str, Any]]:
    """题集详情卡片；不存在返回 None。meta 只放公开白名单键。"""
    row = _manager().get_dataset(dataset_id)
    if row is None:
        return None
    meta = row.get("meta") if isinstance(row.get("meta"), dict) else {}
    public_meta = {k: meta[k] for k in _PUBLIC_META_KEYS if meta.get(k)}
    return {
        "dataset_id": row.get("dataset_id", ""),
        "title": row.get("title", "") or row.get("dataset_id", ""),
        "category": row.get("category", "") or "",
        "description": row.get("description", "") or "",
        "question_count": int(row.get("question_count") or 0),
        "version": row.get("version", "") or "",
        "meta": public_meta,
    }


def list_questions(
    dataset_id: str,
    offset: int = 0,
    limit: int = 50,
    show_gold: bool = False,
) -> Tuple[List[Dict[str, Any]], int]:
    """分页取题（返回 (当页, 总数)）。

    show_gold=False 走列表投影（八个 gold 列不回传）——公开页恒 False，
    gold 是否公开属 §14-1 未决项，本参数仅 admin 内部复用留口子。
    """
    rows, total = _manager().list_questions_page(
        dataset_id, offset=offset, limit=limit, summary=not show_gold,
    )
    return rows, total
