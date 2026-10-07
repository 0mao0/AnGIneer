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


# meta_query 通道的"答非所问"话术特判已随废 meta_query 路由删除（2026-10-02 第二步）：
# 原 _META_NON_ANSWER_PATTERNS/_meta_answer_usable 仅服务 meta 独木桥，档位删除后无消费方。


def _l0_attempt(load_nodes: Callable[[], list], llm_factory: Callable, config_name, mode) -> AttemptConfig:
    from angineer_core.agent_configs import build_chat_config

    def factory() -> AgentLoopConfig:
        return build_chat_config(llm=llm_factory(), config_name=config_name, mode=mode)

    return AttemptConfig(
        name="L0 闲聊直答",
        config_factory=factory,
        success_check=_answer_usable,
    )


def _l1_attempt(load_nodes, llm_factory, library_id, doc_ids, config_name, mode, enforce_evidence, marker_allocator, library_ids=None, answer_format=None) -> AttemptConfig:
    from angineer_core.agent_configs import build_qa_config

    def factory() -> AgentLoopConfig:
        return build_qa_config(
            llm=llm_factory(),
            doc_nodes=load_nodes(),
            library_id=library_id,
            library_ids=library_ids,
            doc_ids=doc_ids,
            task_type="content_qa",
            max_turns=3,
            config_name=config_name,
            mode=mode,
            enforce_evidence=enforce_evidence,
            marker_allocator=marker_allocator,
            answer_format=answer_format,
        )

    return AttemptConfig(
        name="L1 语义检索",
        config_factory=factory,
        success_check=_answer_usable,
        fallback_note="L1 未检索到足够证据，进入拒答收尾",
        requires_tools=True,
        force_first_search=True,  # 需求 C：首轮直达证据，消灭空答重试轮
    )


def _l2_attempt(load_nodes, llm_factory, library_id, doc_ids, config_name, mode, marker_allocator, library_ids=None, answer_format=None) -> AttemptConfig:
    from angineer_core.agent_configs import build_qa_config

    def factory() -> AgentLoopConfig:
        return build_qa_config(
            llm=llm_factory(),
            doc_nodes=load_nodes(),
            library_id=library_id,
            library_ids=library_ids,
            doc_ids=doc_ids,
            task_type="table_qa",
            knowledge_task_type="content_qa",
            max_turns=3,
            config_name=config_name,
            mode=mode,
            enforce_evidence=True,
            marker_allocator=marker_allocator,
            answer_format=answer_format,
        )

    def success(added: List[AgentMessage]) -> bool:
        return _has_evidence(added) and _answer_usable(added)

    return AttemptConfig(
        name="L2 条款/表格定位",
        config_factory=factory,
        success_check=success,
        fallback_note="L2 表格/条款定位未命中，回退 L1 语义检索",
        requires_tools=True,
        # 计划①（09-26 业主拍板）：L2 也做首轮直达，但注入工具是 table_search 而非
        # knowledge_search（§4.5 范围修正）；实锤案例=「疏浚投资影响」题 L2 空答重试 37s
        force_first_search=True,
        first_search_tool="table_search",
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
    library_ids: Optional[List[str]] = None,
    answer_format: Optional[str] = None,
) -> List[AttemptConfig]:
    level = str(getattr(intent_result, "intent_level", "") or "")
    service_mode = str(getattr(intent_result, "service_mode", "") or "")

    # meta_query 特权岔道已废（2026-10-02 第二步）：路由只定编排深度（level），
    # 数据源选择下沉工具层由模型自选（knowledge_stats 已进 L1 工具箱）；
    # 历史 service_mode="meta_query" 残值经 Literal 校验后自然落 L1 默认档
    if level == "L0" or service_mode == "casual_chat":
        return [_l0_attempt(load_nodes, llm_factory, config_name, mode)]
    if level in ("L3", "L4") or service_mode in ("standard_sop", "dynamic_orchestration") or scene in ("complex", "sop", "sops"):
        # 本计划范围外：沿用 complex 档（后续计划补 SOP 全链）
        from angineer_core.agent_configs import build_complex_config, make_final_answer_guard

        sops = list(sop_loader.load_all() or []) if sop_loader is not None else None

        def complex_factory() -> AgentLoopConfig:
            return build_complex_config(
                llm=llm_factory(),
                doc_nodes=load_nodes(),
                library_id=library_id,
                library_ids=library_ids,
                doc_ids=doc_ids,
                max_turns=8,
                config_name=config_name,
                mode=mode,
                sops=sops,
                sop_loader=sop_loader,
                marker_allocator=marker_allocator,
                answer_format=answer_format,
                # 与 L1/L2 同口径：复杂档答案必须过证据闸（2026-10-04 补装，防无证据出结论）
                final_answer_guard=make_final_answer_guard(enforce_evidence=True),
            )

        return [AttemptConfig(
            name="L3/L4 复杂任务",
            config_factory=complex_factory,
            success_check=_answer_usable,
            requires_tools=True,
        )]
    if level == "L2" or service_mode in ("structured_lookup", "sql_first"):
        return [
            _l2_attempt(load_nodes, llm_factory, library_id, doc_ids, config_name, mode, marker_allocator, library_ids=library_ids, answer_format=answer_format),
            _l1_attempt(load_nodes, llm_factory, library_id, doc_ids, config_name, mode, enforce_evidence=False, marker_allocator=marker_allocator, library_ids=library_ids, answer_format=answer_format),
        ]
    return [_l1_attempt(load_nodes, llm_factory, library_id, doc_ids, config_name, mode, enforce_evidence=True, marker_allocator=marker_allocator, library_ids=library_ids, answer_format=answer_format)]


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
    note = f"意图判断：{level_labels.get(level, level)}（{level}）→ 策略 {service_mode}"
    # 分类耗时不再进文案（2026-09-27）：改由结构化 duration_ms 走思考过程耗时标签
    return f"{note}（{reason}）" if reason else note
