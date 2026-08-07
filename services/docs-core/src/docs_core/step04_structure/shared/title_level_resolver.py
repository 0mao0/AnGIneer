"""统一标题仲裁：adopt/consistent/disputed/review + 强分歧升级。

替代 popo_signal_level_fusion.fuse_level_signals 与
title_level_refiner.resolve_title_level_refinement 在 step04 的调用。
"""
import json
import logging
from typing import Any, Dict, List, Optional, Tuple

from docs_core.step04_structure.shared.title_level_refiner import llm_refine_title_levels

logger = logging.getLogger(__name__)

DEFAULT_CONFIDENCE_THRESHOLD = 0.85
STRUCT_STRONG_CONF = 0.9
STRUCT_WEAK_CONF = 0.75


def _structural_candidate(
    popo_level: Optional[int], tree_level: Optional[int]
) -> Tuple[Optional[int], float]:
    """返回 (候选级别, 结构置信度)。enriched 与 tree 冲突时视为无候选。"""
    if popo_level is not None and tree_level is not None:
        if popo_level == tree_level:
            return int(popo_level), STRUCT_STRONG_CONF
        return None, 0.0
    if popo_level is not None:
        return int(popo_level), STRUCT_WEAK_CONF
    if tree_level is not None:
        return int(tree_level), STRUCT_WEAK_CONF
    return None, 0.0


def _classify(rule_conf, cand_level, cand_conf, threshold) -> str:
    if cand_level is not None and cand_conf >= STRUCT_STRONG_CONF:
        return "disputed"          # 结构双一致强分歧：无论规则置信度都升级
    if rule_conf >= threshold:
        return "adopt"             # 高置信且无强分歧 → 规则胜出
    if cand_level is not None:
        return "disputed"          # 低置信 + 有分歧候选 → 双候选
    return "review"                # 低置信 + 无候选 → 单候选确认


def _llm_arbitrate_title_levels(
    disputed: List[Dict[str, Any]],
    llm_client: Any,
    llm_model: Optional[str],
) -> Tuple[Dict[str, int], str]:
    """双候选仲裁：rule_level + popo_level + part 上下文写入 prompt。"""
    mini_items = [
        {
            "block_id": node.get("block_uid") or node.get("id"),
            "text": str(node.get("plain_text") or "")[:160],
            "page_role": node.get("page_role"),
            "document_part": node.get("document_part"),
            "rule_level": node.get("derived_level") or node.get("title_level"),
            "popo_level": node.get("_popo_level"),
        }
        for node in disputed
    ]
    system_prompt = (
        "你是文档结构分析器。根据标题文本、页面角色(document_part/page_role)与候选级别判断标题级别(>=1)。"
        "rule_level 与 popo_level 仅作候选参考。front_matter 标题已由规则层扁平化，不参与仲裁。"
        '仅返回JSON对象：{"items":[{"block_id":"...","level":1,"confidence":0.95}]}'
    )
    try:
        result_text = llm_client.chat(
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": json.dumps({"items": mini_items}, ensure_ascii=False)},
            ],
            temperature=0.0,
            model=llm_model,
        )
        payload = json.loads(str(result_text))
        arr = payload.get("items") if isinstance(payload, dict) else payload
        refined: Dict[str, int] = {}
        for item in arr or []:
            if not isinstance(item, dict):
                continue
            uid = item.get("block_id") or item.get("block_uid")
            level = item.get("level")
            if isinstance(uid, str) and isinstance(level, int) and level >= 1:
                refined[uid] = level
        return refined, "ok" if refined else "empty_result"
    except Exception as error:
        return {}, f"error:{str(error)[:60]}"


def resolve_title_levels(
    nodes: List[Dict[str, Any]],
    *,
    popo_levels: Optional[Dict[str, int]] = None,
    tree_levels: Optional[Dict[str, int]] = None,
    llm_client: Any = None,
    llm_model: Optional[str] = None,
    use_llm: bool = False,
    confidence_threshold: float = DEFAULT_CONFIDENCE_THRESHOLD,
) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    """统一仲裁标题级别，返回 (更新后的 nodes, stats)。

    分类：adopt(不调 LLM) / consistent(不调 LLM) /
          disputed(LLM 双候选) / review(LLM 单候选)。
    """
    popo_levels = popo_levels or {}
    tree_levels = tree_levels or {}
    def _is_front_matter_flat_title(node: Dict[str, Any]) -> bool:
        return str(node.get("document_part") or "") == "front_matter"

    title_nodes = [
        node for node in nodes
        if str(node.get("block_type") or "").strip() == "title"
        and str(node.get("plain_text") or "").strip()
        and not _is_front_matter_flat_title(node)
    ]
    stats: Dict[str, Any] = {
        "total_titles": len(title_nodes),
        "popo_signals": 0,
        "consistent": 0,
        "adopt": 0,
        "disputed": 0,
        "review": 0,
        "llm_adopted": 0,
        "consistent_rate": None,
        "llm_status": "disabled",
    }
    if not title_nodes:
        return nodes, stats

    disputed: List[Dict[str, Any]] = []
    review: List[Dict[str, Any]] = []
    for node in title_nodes:
        uid = node.get("block_uid") or node.get("id")
        rule_level = node.get("derived_level") or node.get("title_level")
        rule_conf = float(
            node.get("derived_confidence")
            if node.get("derived_confidence") is not None
            else (node.get("confidence") or 0.0)
        )
        cand_level, cand_conf = _structural_candidate(
            popo_levels.get(uid), tree_levels.get(uid)
        )
        if cand_level is not None:
            stats["popo_signals"] += 1
            if cand_level == rule_level:
                stats["consistent"] += 1
        if cand_level is not None and cand_level == rule_level:
            kind = "adopt"  # 结构候选与规则一致：直接采用，不调 LLM
        else:
            kind = _classify(rule_conf, cand_level, cand_conf, confidence_threshold)
        if kind == "adopt":
            stats["adopt"] += 1
            continue
        tagged = dict(node)
        tagged["_popo_level"] = cand_level
        if kind == "disputed":
            disputed.append(tagged)
            stats["disputed"] += 1
        else:
            review.append(tagged)
            stats["review"] += 1

    if popo_levels or tree_levels:
        stats["consistent_rate"] = round(
            stats["consistent"] / stats["popo_signals"], 4
        ) if stats["popo_signals"] else None

    llm_levels: Dict[str, int] = {}
    if (disputed or review) and use_llm and llm_client:
        if disputed:
            llm_levels.update(
                _llm_arbitrate_title_levels(disputed, llm_client, llm_model)[0]
            )
        if review:
            review_items = [
                {
                    "block_id": node.get("block_uid") or node.get("id"),
                    "text": str(node.get("plain_text") or "")[:160],
                    "page_role": node.get("page_role"),
                    "document_part": node.get("document_part"),
                    "backend_level": node.get("derived_level") or node.get("title_level"),
                }
                for node in review
            ]
            review_levels, status = llm_refine_title_levels(
                review_items, llm_client, llm_model
            )
            llm_levels.update({uid: level for uid, (level, _conf) in review_levels.items()})
            stats["llm_status"] = status
        else:
            stats["llm_status"] = "ok"
    elif disputed or review:
        stats["llm_status"] = "disabled"

    if not llm_levels:
        return nodes, stats

    disputed_uids = {str(node.get("block_uid") or node.get("id")) for node in disputed}
    review_uids = {str(node.get("block_uid") or node.get("id")) for node in review}
    updated: List[Dict[str, Any]] = []
    for node in nodes:
        uid = node.get("block_uid") or node.get("id")
        level = llm_levels.get(uid)
        if level is not None and uid in disputed_uids | review_uids:
            node = dict(node)
            node["derived_level"] = level
            node["title_level"] = level
            node["derived_by"] = f"{node.get('derived_by') or 'rule'}+llm"
            node["derived_confidence"] = 0.95
            stats["llm_adopted"] += 1
        updated.append(node)
    return updated, stats


__all__ = [
    "DEFAULT_CONFIDENCE_THRESHOLD", "STRUCT_STRONG_CONF", "STRUCT_WEAK_CONF",
    "resolve_title_levels",
]
