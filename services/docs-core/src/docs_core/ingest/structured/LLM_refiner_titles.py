"""标题相关的 LLM 特殊细化能力。"""
import json
from typing import Any, Callable, Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from angineer_core.infra.llm_client import LLMClient


def llm_refine_title_levels(
    title_items: list[dict[str, Any]],
    llm_client: Optional["LLMClient"] = None,
    llm_model: Optional[str] = None,
) -> tuple[dict[str, tuple[int, float]], str]:
    """用 LLM 细化标题层级并返回状态。"""
    if not llm_client:
        return {}, "not_configured"

    if not title_items:
        return {}, "ok"

    mini_items: list[dict[str, Any]] = []
    for item in title_items:
        mini_items.append({
            "block_uid": item["block_uid"],
            "text": item["plain_text"][:160],
            "rule_level": item.get("rule_level"),
        })

    system_prompt = (
        "你是文档结构分析器。根据标题文本的编号层级判断标题级别(>=1，不限制上限)。"
        "如果是目录项也按编号层级判断。仅返回JSON对象："
        '{"items":[{"block_uid":"...","level":1,"confidence":0.95}]}'
    )
    user_prompt = json.dumps({"items": mini_items}, ensure_ascii=False)

    try:
        result_text = llm_client.chat(
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt}
            ],
            temperature=0.0,
            model=llm_model,
        )

        result = json.loads(result_text)
        arr = result.get("items") if isinstance(result, dict) else result
        refined: dict[str, tuple[int, float]] = {}

        if isinstance(arr, list):
            for item in arr:
                if not isinstance(item, dict):
                    continue
                uid = item.get("block_uid")
                level = item.get("level")
                conf = item.get("confidence", 0.8)
                if isinstance(uid, str) and isinstance(level, int) and level >= 1:
                    confidence = float(conf) if isinstance(conf, (int, float)) else 0.8
                    confidence = max(0.0, min(1.0, confidence))
                    refined[uid] = (level, confidence)

        if refined:
            return refined, "ok"
        return {}, "empty_result"

    except Exception as error:
        return {}, f"error:{str(error)[:50]}"


def resolve_title_level_refinement(
    rows: list[dict[str, Any]],
    infer_title_level_func: Callable[[str, Any], tuple[Optional[int], float, str]],
    llm_client: Optional["LLMClient"] = None,
    use_llm: bool = True,
    llm_model: Optional[str] = None,
) -> tuple[list[dict[str, Any]], dict[str, tuple[int, float]], str]:
    """从结构化行中提取标题候选并执行标题层级 LLM 细化。"""
    title_candidates: list[dict[str, Any]] = []
    for row in rows:
        if row.get("block_type") != "title":
            continue
        content = row.get("content_json")
        raw_level = content.get("level") if isinstance(content, dict) else None
        rule_level, _, _ = infer_title_level_func(str(row.get("plain_text") or ""), raw_level)
        title_candidates.append(
            {
                "block_uid": row["block_uid"],
                "plain_text": str(row.get("plain_text") or ""),
                "rule_level": rule_level,
            }
        )

    llm_levels: dict[str, tuple[int, float]] = {}
    llm_status = "disabled"
    if use_llm and llm_client and title_candidates:
        llm_levels, llm_status = llm_refine_title_levels(title_candidates, llm_client, llm_model)
    return title_candidates, llm_levels, llm_status


__all__ = [
    "llm_refine_title_levels",
    "resolve_title_level_refinement",
]
