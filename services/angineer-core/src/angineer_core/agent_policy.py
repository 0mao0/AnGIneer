"""L0-L4 策略层：把意图分级结果展开成引擎可执行的 Attempt 列表。

只做“用什么配置、按什么顺序、何时回退”，不碰引擎内部。
"""
import os
import re
from typing import Any, Callable, Dict, List, Optional

from angineer_core.agent_loop import AgentLoopConfig, AttemptConfig
from angineer_core.agent_messages import AgentMessage, is_refusal_text

# 选择题作答协议（2026-10-15 reviewed-exam 解剖）：题面是「下列关于…符合规范规定的是（A）…（D）」
# 型选择题时，模型常因题面措辞与规范原文不完全一致而整体自拒（8/50 错题即此形态）。本协议在
# 检出选择题壳（≥2 个选项标记）时注入 L1/L2 段的系统提示词（按 query 形状条件注入，非常驻）。
_MCQ_OPTION_RE = re.compile(r"[（(][A-D][)）]")


def _env_max_turns(name: str, default: int) -> int:
    """轮数预算的 env 覆盖（2026-10-18）：原值写死在 attempt 里，换任务形态只能改代码。

    Harvey LAB 实踩：枚举型题一题要遍历多个 matter，L1 只给 3 轮，模型第一轮调工具、
    第二轮被迫收尾；把轮数做成 env，评测/长任务按需放宽，产品默认值不变。"""
    try:
        return max(1, int(os.environ.get(name, str(default)) or default))
    except (TypeError, ValueError):
        return default


def _looks_like_mcq(query: Optional[str]) -> bool:
    """选择题识别：题面含 ≥2 个选项标记（A）～（D）即视为选择题（题型壳判定，不看语义）。"""
    return len(_MCQ_OPTION_RE.findall(str(query or ""))) >= 2


_MCQ_PROTOCOL = (
    "\n\n【选择题作答协议】本题为规范选择题：检索到相关条文后逐项比对，给出明确所选项及依据；"
    "题面措辞与规范原文不完全一致（同义改写、简写、选项语序差异）不构成「无证据」，"
    "不得因措辞差异整体拒答；仅在检索结果确实不覆盖该主题时才说明缺失。"
)


def _last_answer(messages: List[AgentMessage]) -> Optional[str]:
    for message in reversed(messages):
        if message.role == "assistant" and not message.tool_calls:
            return message.content or ""
    return None


def _has_evidence(messages: List[AgentMessage]) -> bool:
    """工具结果里是否带引用号（cite）。

    读法走 agent_configs._item_cite（顶层 + metadata 两形态）——只读 metadata 时
    投影形态恒 False，L2 档会被判「未命中」并次次回退 L1（2026-10-06 起实况，
    2026-10-16 定位）。
    """
    from angineer_core.agent_configs import _item_cite

    for message in messages:
        if message.role != "tool" or message.is_error:
            continue
        try:
            import json

            raw = json.loads(message.content or "{}")
        except Exception:
            continue
        if isinstance(raw, dict) and isinstance(raw.get("items"), list) and any(
            _item_cite(item) for item in raw["items"]
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


def _enum_context(query, library_id, llm, config_name, mode):
    """枚举题预取候选：开关/库白名单/判定任一不满足或抛错都返回 None（原链路零影响）。"""
    try:
        from angineer_core.enum_prefetch import build_enum_context

        return build_enum_context(
            query=str(query or ""),
            library_id=library_id,
            llm=llm,
            config_name=config_name,
            mode=mode,
        )
    except Exception as exc:  # noqa: BLE001 —— 预取失败不得阻断问答
        import logging

        logging.getLogger(__name__).warning("enum_prefetch 跳过: %s", exc)
        return None


def _date_context(query, library_id, llm, config_name, mode):
    """「最新/最近」日期预取：开关默认关；与枚举预取互斥（枚举优先）。"""
    try:
        from angineer_core.date_prefetch import build_date_context

        return build_date_context(
            query=str(query or ""),
            library_id=library_id,
            llm=llm,
            config_name=config_name,
            mode=mode,
        )
    except Exception as exc:  # noqa: BLE001
        import logging

        logging.getLogger(__name__).warning("date_prefetch 跳过: %s", exc)
        return None


def _prefetch_context(query, library_id, llm, config_name, mode):
    """两路预取只注入一路：枚举（穷举）优先，其次日期（最新/最近）。"""
    ctx = _enum_context(query, library_id, llm, config_name, mode)
    if ctx:
        return ctx
    return _date_context(query, library_id, llm, config_name, mode)


def _l1_attempt(load_nodes, llm_factory, library_id, doc_ids, config_name, mode, enforce_evidence, marker_allocator, library_ids=None, answer_format=None, query=None) -> AttemptConfig:
    from angineer_core.agent_configs import build_qa_config

    def factory() -> AgentLoopConfig:
        llm = llm_factory()
        enum_ctx = _prefetch_context(query, library_id, llm, config_name, mode)
        cfg = build_qa_config(
            llm=llm,
            doc_nodes=load_nodes(),
            library_id=library_id,
            library_ids=library_ids,
            doc_ids=doc_ids,
            task_type="content_qa",
            max_turns=_env_max_turns("ANGINEER_QA_MAX_TURNS", 6),
            config_name=config_name,
            mode=mode,
            enforce_evidence=enforce_evidence,
            marker_allocator=marker_allocator,
            answer_format=answer_format,
            enum_context=enum_ctx,
            audit_query=query,
        )
        if _looks_like_mcq(query):
            cfg.system_prompt = (cfg.system_prompt or "") + _MCQ_PROTOCOL
        return cfg

    return AttemptConfig(
        name="L1 语义检索",
        config_factory=factory,
        success_check=_answer_usable,
        fallback_note="L1 未检索到足够证据，进入拒答收尾",
        requires_tools=True,
        force_first_search=True,  # 需求 C：首轮直达证据，消灭空答重试轮
    )


def _l2_attempt(load_nodes, llm_factory, library_id, doc_ids, config_name, mode, marker_allocator, library_ids=None, answer_format=None, query=None) -> AttemptConfig:
    from angineer_core.agent_configs import build_qa_config

    def factory() -> AgentLoopConfig:
        cfg = build_qa_config(
            llm=llm_factory(),
            doc_nodes=load_nodes(),
            library_id=library_id,
            library_ids=library_ids,
            doc_ids=doc_ids,
            task_type="table_qa",
            knowledge_task_type="content_qa",
            max_turns=_env_max_turns("ANGINEER_QA_MAX_TURNS", 6),
            config_name=config_name,
            mode=mode,
            enforce_evidence=True,
            marker_allocator=marker_allocator,
            answer_format=answer_format,
        )
        if _looks_like_mcq(query):
            cfg.system_prompt = (cfg.system_prompt or "") + _MCQ_PROTOCOL
        return cfg

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


_SOP_HINT_MIN_SCORE = 0.10


def _build_sop_hint(query: Optional[str], sops: Optional[List[Any]]) -> Optional[str]:
    """L3 轻量引导（选 B）：TF-IDF 粗筛 top-1 命中（零 LLM 成本）→ 复杂档提示词注入。

    开关 ANGINEER_SOP_L3_HINT（默认开，=0 关）。预注册判据：开关关 / query 为空 /
    无命中 / 分数低于阈值 → 返回 None（复杂档提示词逐字节不变）。
    """
    if os.getenv("ANGINEER_SOP_L3_HINT", "1") == "0":
        return None
    if not query or not sops:
        return None
    try:
        from angineer_core.classifier import _build_sop_corpus, _keyword_recall

        doc_ids, documents = _build_sop_corpus(sops)
        hits = _keyword_recall(str(query), doc_ids, documents, top_k=1)
    except Exception:  # noqa: BLE001
        return None
    if not hits or hits[0][1] < _SOP_HINT_MIN_SCORE:
        return None
    top_id = hits[0][0]
    name = next((getattr(s, "name_zh", None) or getattr(s, "name_en", None) or s.id
                 for s in sops if s.id == top_id), top_id)
    return (
        f"本题经粗筛疑似适用标准 SOP「{name}」({top_id})。"
        "若题干参数与该流程匹配，请优先调用 sop_execute 执行标准流程，并以其实算结果为准；"
        "SOP 报缺参或步骤失败时：如实转述「缺什么 + 推荐值」，请用户确认补充后再算；"
        "严禁自行假设参数代算出最终数，严禁自拟/改换查表系数等中间值"
        "（2026-10-13 实踩：回答层自补 n=1.0/γ=3° 出假宽 145.44）；"
        "若判定不适用，忽略本条继续常规检索作答。"
    )


def build_attempts(
    *,
    intent_result: Any,
    query: Optional[str] = None,
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
    l4_synth: Optional[Any] = None,
    step_event: Optional[Callable[[Dict[str, Any]], None]] = None,
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
        sop_hint = _build_sop_hint(query, sops)

        def complex_factory() -> AgentLoopConfig:
            llm = llm_factory()
            enum_ctx = _prefetch_context(query, library_id, llm, config_name, mode)
            return build_complex_config(
                llm=llm,
                doc_nodes=load_nodes(),
                library_id=library_id,
                library_ids=library_ids,
                doc_ids=doc_ids,
                max_turns=_env_max_turns("ANGINEER_COMPLEX_MAX_TURNS", 12),
                config_name=config_name,
                mode=mode,
                sops=sops,
                sop_loader=sop_loader,
                marker_allocator=marker_allocator,
                sop_hint=sop_hint,
                l4_synth=l4_synth,
                answer_format=answer_format,
                # SOP 流程图事件通道（2026-10-14）：仅 chat SSE 链路传入，
                # 评测/REST 等调用方缺省 None，行为逐位不变
                step_event=step_event,
                # 与 L1/L2 同口径：复杂档答案必须过证据闸（2026-10-04 补装，防无证据出结论）
                final_answer_guard=make_final_answer_guard(enforce_evidence=True),
                enum_context=enum_ctx,
            )

        attempts = [AttemptConfig(
            name="L3/L4 复杂任务",
            config_factory=complex_factory,
            success_check=_answer_usable,
            fallback_note="复杂档未产出可用答案（SOP 无匹配或无证据），回退语义检索",
            requires_tools=True,
        )]
        # L3 兜底（2026-10-21 事故）：分类器把「题面只给公式、数值要查文档」的题误判 L3 时，
        # 复杂档按 SOP 路径走、无匹配即零证据拒答（financebench 150 题里 10 题命中，-4pp）。
        # 给 L3 追加一段语义检索：复杂档出可用答案不触发；拒答/空答时按 L1 取证据再答。
        # L4 不加——多方案/系统设计题没有「回退检索就能答」的等价形态。
        if level == "L3":
            attempts.append(_l1_attempt(
                load_nodes, llm_factory, library_id, doc_ids, config_name, mode,
                enforce_evidence=True, marker_allocator=marker_allocator,
                library_ids=library_ids, answer_format=answer_format, query=query))
        return attempts
    if level == "L2" or service_mode in ("structured_lookup", "sql_first"):
        return [
            _l2_attempt(load_nodes, llm_factory, library_id, doc_ids, config_name, mode, marker_allocator, library_ids=library_ids, answer_format=answer_format, query=query),
            _l1_attempt(load_nodes, llm_factory, library_id, doc_ids, config_name, mode, enforce_evidence=False, marker_allocator=marker_allocator, library_ids=library_ids, answer_format=answer_format, query=query),
        ]
    return [_l1_attempt(load_nodes, llm_factory, library_id, doc_ids, config_name, mode, enforce_evidence=True, marker_allocator=marker_allocator, library_ids=library_ids, answer_format=answer_format, query=query)]


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
