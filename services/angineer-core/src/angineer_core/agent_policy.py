"""L0-L4 策略层：把意图分级结果展开成引擎可执行的 Attempt 列表。

只做“用什么配置、按什么顺序、何时回退”，不碰引擎内部。
"""
from typing import Any, Callable, List, Optional

from angineer_core.agent_loop import AgentLoopConfig, AttemptConfig
from angineer_core.agent_messages import AgentMessage, is_refusal_text


def _last_answer(messages: List[AgentMessage]) -> Optional[str]:
    for message in reversed(messages):
        if message.role == "assistant" and not message.tool_calls:
            return message.content or ""
    return None


def _has_evidence(messages: List[AgentMessage]) -> bool:
    for message in messages:
        if message.role != "tool" or message.is_error:
            continue
        try:
            import json

            raw = json.loads(message.content or "{}")
        except Exception:
            continue
        if isinstance(raw, dict) and isinstance(raw.get("items"), list) and any(
            isinstance(item, dict) and bool((item.get("metadata") or {}).get("cite"))
            for item in raw["items"]
        ):
            return True
    return False


def _answer_usable(messages: List[AgentMessage]) -> bool:
    answer = _last_answer(messages) or ""
    return bool(answer.strip()) and not is_refusal_text(answer)


# meta_query 通道的"答非所问"话术：统计工具答不了内容题时的典型回复（中英文）。
# 命中即视为本段失败，回退 L1 正文检索。模式保持窄口径，避免误伤空库等合法统计回答。
_META_NON_ANSWER_PATTERNS = (
    "不包含", "不涵盖", "未包含", "未涵盖", "没有收录",
    "仅提供", "仅涵盖", "仅统计",
    "do not contain", "does not contain", "not contain information",
    "only provides metadata", "only covers", "only includes metadata",
    "no information about", "not available in the knowledge base",
)


def _meta_answer_usable(messages: List[AgentMessage]) -> bool:
    """meta 段成功口径：答案可用 且 不是"统计数据答不了内容题"的话术。"""
    answer = (_last_answer(messages) or "").strip()
    if not answer or is_refusal_text(answer):
        return False
    lowered = answer.lower()
    return not any(pattern.lower() in lowered for pattern in _META_NON_ANSWER_PATTERNS)


def _l0_attempt(load_nodes: Callable[[], list], llm_factory: Callable, config_name, mode) -> AttemptConfig:
    from angineer_core.agent_configs import build_chat_config

    def factory() -> AgentLoopConfig:
        return build_chat_config(llm=llm_factory(), config_name=config_name, mode=mode)

    return AttemptConfig(
        name="L0 闲聊直答",
        config_factory=factory,
        success_check=_answer_usable,
    )


def _meta_attempt(llm_factory: Callable, config_name, mode, library_id) -> AttemptConfig:
    from angineer_core.agent_configs import build_meta_config

    def factory() -> AgentLoopConfig:
        return build_meta_config(llm=llm_factory(), config_name=config_name, mode=mode, library_id=library_id)

    return AttemptConfig(
        name="统计/元数据查询",
        config_factory=factory,
        success_check=_meta_answer_usable,
        requires_tools=True,
        fallback_note="统计通道无法回答该问题（可能误入 meta_query），回退 L1 正文检索",
    )


def _l1_attempt(load_nodes, llm_factory, library_id, doc_ids, config_name, mode, enforce_evidence, marker_allocator) -> AttemptConfig:
    from angineer_core.agent_configs import build_qa_config

    def factory() -> AgentLoopConfig:
        return build_qa_config(
            llm=llm_factory(),
            doc_nodes=load_nodes(),
            library_id=library_id,
            doc_ids=doc_ids,
            task_type="content_qa",
            max_turns=3,
            config_name=config_name,
            mode=mode,
            enforce_evidence=enforce_evidence,
            marker_allocator=marker_allocator,
        )

    return AttemptConfig(
        name="L1 语义检索",
        config_factory=factory,
        success_check=_answer_usable,
        fallback_note="L1 未检索到足够证据，进入拒答收尾",
        requires_tools=True,
    )


def _l2_attempt(load_nodes, llm_factory, library_id, doc_ids, config_name, mode, marker_allocator) -> AttemptConfig:
    from angineer_core.agent_configs import build_qa_config

    def factory() -> AgentLoopConfig:
        return build_qa_config(
            llm=llm_factory(),
            doc_nodes=load_nodes(),
            library_id=library_id,
            doc_ids=doc_ids,
            task_type="table_qa",
            knowledge_task_type="content_qa",
            max_turns=3,
            config_name=config_name,
            mode=mode,
            enforce_evidence=True,
            marker_allocator=marker_allocator,
        )

    def success(added: List[AgentMessage]) -> bool:
        return _has_evidence(added) and _answer_usable(added)

    return AttemptConfig(
        name="L2 条款/表格定位",
        config_factory=factory,
        success_check=success,
        fallback_note="L2 表格/条款定位未命中，回退 L1 语义检索",
        requires_tools=True,
    )


def build_attempts(
    *,
    intent_result: Any,
    scene: str,
    library_id: str,
    doc_ids: List[str],
    load_nodes: Callable[[], list],
    llm_factory: Callable,
    config_name: Optional[str] = None,
    mode: str = "instruct",
    sop_loader: Any = None,
    marker_allocator: Any = None,
) -> List[AttemptConfig]:
    level = str(getattr(intent_result, "intent_level", "") or "")
    service_mode = str(getattr(intent_result, "service_mode", "") or "")

    # meta_query 优先于一切 level 分支：service_mode 精确命中统计通道
    if service_mode == "meta_query":
        # 独木桥改双段：统计通道答非所问（误路由的内容题）时自动回退 L1 正文检索
        return [
            _meta_attempt(llm_factory, config_name, mode, library_id),
            _l1_attempt(load_nodes, llm_factory, library_id, doc_ids, config_name, mode, enforce_evidence=False, marker_allocator=marker_allocator),
        ]
    if level == "L0" or service_mode == "casual_chat":
        return [_l0_attempt(load_nodes, llm_factory, config_name, mode)]
    if level in ("L3", "L4") or service_mode in ("standard_sop", "dynamic_orchestration") or scene in ("complex", "sop", "sops"):
        # 本计划范围外：沿用 complex 档（后续计划补 SOP 全链）
        from angineer_core.agent_configs import build_complex_config

        sops = list(sop_loader.load_all() or []) if sop_loader is not None else None

        def complex_factory() -> AgentLoopConfig:
            return build_complex_config(
                llm=llm_factory(),
                doc_nodes=load_nodes(),
                library_id=library_id,
                doc_ids=doc_ids,
                max_turns=8,
                config_name=config_name,
                mode=mode,
                sops=sops,
                sop_loader=sop_loader,
                marker_allocator=marker_allocator,
            )

        return [AttemptConfig(
            name="L3/L4 复杂任务",
            config_factory=complex_factory,
            success_check=_answer_usable,
            requires_tools=True,
        )]
    if level == "L2" or service_mode in ("structured_lookup", "sql_first"):
        return [
            _l2_attempt(load_nodes, llm_factory, library_id, doc_ids, config_name, mode, marker_allocator),
            _l1_attempt(load_nodes, llm_factory, library_id, doc_ids, config_name, mode, enforce_evidence=False, marker_allocator=marker_allocator),
        ]
    return [_l1_attempt(load_nodes, llm_factory, library_id, doc_ids, config_name, mode, enforce_evidence=True, marker_allocator=marker_allocator)]


def format_route_note(intent_result: Any) -> Optional[str]:
    if intent_result is None:
        return None
    level_labels = {
        "L0": "闲聊直答", "L1": "正文问答", "L2": "条款/表格定位",
        "L3": "规范计算", "L4": "复杂综合任务",
    }
    level = str(getattr(intent_result, "intent_level", "") or "")
    intent_type = str(getattr(intent_result, "intent_type", "") or "")
    service_mode = str(getattr(intent_result, "service_mode", "") or "")
    reason = str(getattr(intent_result, "reason", "") or "").strip()
    if service_mode == "meta_query":
        note = "意图判断：统计/元数据查询 → 策略 meta_query"
    else:
        note = f"意图判断：{level_labels.get(level, level)}（{level}）→ 策略 {service_mode}"
    return f"{note}（{reason}）" if reason else note
