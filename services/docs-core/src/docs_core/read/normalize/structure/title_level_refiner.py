"""标题层级 LLM 校正器（阶段二：输入解耦为 CanonicalBlock，两条后端统一生效）。

原 ``solo/LLM_refiner_titles.py`` 迁移重命名而来。输入从 solo row dict 改为
CanonicalBlock 列表：``backend_level`` 取 ``block.title_level``（solo=规则层级、
popo=4B level），置信度策略见 ``estimate_backend_level_confidence``（G6）。
"""
import json
import re
from typing import Any, Callable, Dict, List, Optional, Tuple, TYPE_CHECKING

if TYPE_CHECKING:
    from ai_inference.llm_client import LLMClient
    from docs_core.read.organize.types import CanonicalBlock


DEFAULT_CONFIDENCE_THRESHOLD = 0.85


def llm_refine_title_levels(
    title_items: list[dict[str, Any]],
    llm_client: Optional["LLMClient"] = None,
    llm_model: Optional[str] = None,
) -> tuple[dict[str, tuple[int, float]], str]:
    """用 LLM 细化标题层级并返回 {block_id: (level, confidence)} 与状态。"""
    if not llm_client:
        return {}, "not_configured"
    if not title_items:
        return {}, "ok"

    mini_items: list[dict[str, Any]] = []
    for item in title_items:
        mini_items.append({
            "block_id": item["block_id"],
            "text": item["text"][:160],
            "backend_level": item.get("backend_level"),
        })

    system_prompt = (
        "你是文档结构分析器。根据标题文本的编号层级判断标题级别(>=1，不限制上限)。"
        "如果是目录项也按编号层级判断。仅返回JSON对象："
        '{"items":[{"block_id":"...","level":1,"confidence":0.95}]}'
    )
    user_prompt = json.dumps({"items": mini_items}, ensure_ascii=False)

    try:
        result_text = llm_client.chat(
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
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
                uid = item.get("block_id") or item.get("block_uid")
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


def estimate_backend_level_confidence(
    text: str,
    backend_level: Optional[int],
    *,
    backend: str = "auto",
    source: str = "",
) -> float:
    """后端层级置信度（G6）：

    - solo：编号正则命中 0.95 / 原始 level 0.6 / 无 0.0（与 infer_title_level 一致）
    - popo：4B 无 confidence 字段，按编号正则回退 0.8 / 纯文本 0.3
    - auto：按 block.source（mineru-popo 之外视为 solo）
    """
    if backend_level is None:
        return 0.0
    numbered = bool(re.match(r"^\d+(?:\.\d+)*", (text or "").strip()))
    if backend == "solo" or (backend == "auto" and source != "mineru-popo"):
        return 0.95 if numbered else 0.6
    return 0.8 if numbered else 0.3


def _default_confidence(
    block: "CanonicalBlock",
    backend_level: Optional[int],
    backend: str,
) -> float:
    text = block.text_clean or block.text or ""
    return estimate_backend_level_confidence(
        text,
        backend_level,
        backend=backend,
        source=str(getattr(block, "source", "") or ""),
    )


def resolve_title_level_refinement(
    blocks: List["CanonicalBlock"],
    llm_client: Optional["LLMClient"] = None,
    *,
    use_llm: bool = True,
    llm_model: Optional[str] = None,
    confidence_threshold: float = DEFAULT_CONFIDENCE_THRESHOLD,
    backend: str = "auto",
    confidence_resolver: Optional[Callable[["CanonicalBlock", Optional[int]], float]] = None,
) -> tuple[list[dict[str, Any]], dict[str, tuple[int, float]], str]:
    """从 CanonicalBlock 列表提取标题候选并执行层级 LLM 细化。

    - backend_level 取 ``block.title_level``（solo 传规则层级、popo 传 4B level）
    - 置信度 ≥ 阈值时跳过 LLM 调用（成本控制）
    - 返回 (title_candidates, llm_levels, status)
    """
    title_candidates: list[dict[str, Any]] = []
    for block in blocks:
        if getattr(block, "block_type", None) != "title":
            continue
        text = block.text_clean or block.text or ""
        if not text:
            continue
        backend_level = getattr(block, "title_level", None)
        confidence = (
            confidence_resolver(block, backend_level)
            if confidence_resolver is not None
            else _default_confidence(block, backend_level, backend)
        )
        title_candidates.append({
            "block_id": block.block_id,
            "text": text,
            "backend_level": backend_level,
            "confidence": float(confidence or 0.0),
        })

    llm_levels: dict[str, tuple[int, float]] = {}
    llm_status = "disabled"
    if use_llm and llm_client and title_candidates:
        below_threshold = [
            item for item in title_candidates
            if float(item["confidence"] or 0.0) < confidence_threshold
        ]
        if not below_threshold:
            llm_status = "skipped_by_confidence"
        else:
            llm_levels, llm_status = llm_refine_title_levels(
                below_threshold,
                llm_client,
                llm_model,
            )
    return title_candidates, llm_levels, llm_status


__all__ = [
    "DEFAULT_CONFIDENCE_THRESHOLD",
    "estimate_backend_level_confidence",
    "llm_refine_title_levels",
    "resolve_title_level_refinement",
]
