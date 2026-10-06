"""P3.1 知识问答 + P4.1 大题型 agent 循环配置装配。"""
import json
import os
import re
from dataclasses import replace
from typing import Any, Dict, List, Optional

from angineer_core.agent_loop import _INJECTED_USER_PROMPTS, AgentLoopConfig, TurnContext
from angineer_core.agent_messages import AgentMessage, is_refusal_text, strip_half_refusal_lead
from angineer_core.agent_tools import (
    AgentTool,
    EngtoolAdapter,
    RetrieverAdapter,
    SopRunnerAdapter,
    StatsAdapter,
)
from angineer_core.prompts.agent_configs import (  # noqa: F401  # P5 资产化后 re-export，保持旧导入兼容
    COMPLEX_AGENT_SYSTEM_PROMPT,
    FOLLOWUP_QUESTION_RULE,
    QA_AGENT_SYSTEM_PROMPT,
)
from angineer_core.tool_codec import TextToolCallCodec


_MARKER_RE = re.compile(r"\[([KTE]\d+)\]")


def effective_qa_prompt_version() -> str:
    """当前进程实际生效的 QA 档 prompt 版本（env 指定或 latest）。

    供 run manifest / prediction 落库：registry latest 不等于生效版本，
    记录必须以本函数为准。
    """
    return os.getenv("ANGINEER_QA_PROMPT_VERSION", "latest").strip() or "latest"


def _load_qa_system_prompt() -> str:
    """按 ANGINEER_QA_PROMPT_VERSION 加载 QA 档系统提示（默认最新注册版本）。"""
    from angineer_core.prompts import load

    return load("agent_configs.qa_system_prompt", effective_qa_prompt_version())


def _valid_markers(added_messages: List[AgentMessage]) -> set:
    valid = set()
    for message in added_messages:
        if message.role != "tool":
            continue
        try:
            raw = json.loads(message.content or "{}")
        except Exception:  # noqa: BLE001
            continue
        for item in (raw.get("items") or []) if isinstance(raw, dict) else []:
            if isinstance(item, dict):
                cite = (item.get("metadata") or {}).get("cite")
                if cite:
                    valid.add(str(cite))
    return valid


def _build_inline_citation_context(inline_citations: List[Dict[str, Any]]) -> str:
    """把前端显式确认的引用对象转成高优先级证据文本（与 dispatcher 同款）。"""
    evidence_blocks: List[str] = []
    for item in inline_citations[:5]:
        reference = item.get("reference") if isinstance(item, dict) else {}
        if not isinstance(reference, dict):
            reference = {}
        label = str(item.get("label") or reference.get("label") or "").strip()
        doc_title = str(reference.get("docTitle") or reference.get("doc_title") or "").strip()
        section_path = str(reference.get("sectionPath") or reference.get("section_path") or "").strip()
        page_idx = reference.get("pageIdx", reference.get("page_idx", ""))
        content = str(reference.get("content") or reference.get("snippet") or "").strip()
        meta_parts = [
            part
            for part in (
                f"标签: {label}" if label else "",
                f"文档: {doc_title}" if doc_title else "",
                f"页码: {page_idx}" if page_idx else "",
                f"位置: {section_path}" if section_path else "",
            )
            if part
        ]
        block_parts: List[str] = []
        if meta_parts:
            block_parts.append("\n".join(meta_parts))
        if content:
            block_parts.append(f"证据内容:\n{content}")
        if block_parts:
            evidence_blocks.append("\n".join(block_parts))
    return "\n---\n".join(evidence_blocks)


_JSON_FENCE_RE = re.compile(r"^```(?:json)?\s*\n?(.*?)\n?\s*```\s*$", re.S)


def _strip_json_fence(text: str) -> str:
    """剥掉 ```json / ``` 代码围栏外壳。

    2026-10-04 occamy 实测（run-94c0ac9e9e3f / run-55a16e545304）：模型吐错误 JSON 与
    {"answer": ...} 信封时都带围栏，原 startswith("{") 判定直接落空、整段漏检——
    围栏只是模型的排版习惯，不是语义差异，判定前统一剥掉。"""
    body = (text or "").strip()
    m = _JSON_FENCE_RE.match(body)
    return m.group(1).strip() if m else body


def _unwrap_answer_envelope(answer: str) -> Optional[str]:
    """拆 ```json {"answer": "..."} 单键信封，返回内文；不是信封返回 None。

    occamy 会把整段作答（含拒答+「供参考」正文）包进工具风格的 answer 信封，不拆封则
    线上用户与评测判分看到的都是 JSON 外壳。保守三把锁防误伤「用户点名要 JSON 输出」：
    必须剥围栏后能解析为 dict、键集必须只有 "answer"、值必须是非空字符串；
    任何一把不满足都原样放过。"""
    text = _strip_json_fence(answer)
    if not text.startswith("{"):
        return None
    try:
        raw = json.loads(text)
    except Exception:  # noqa: BLE001
        return None
    if isinstance(raw, dict) and set(raw.keys()) == {"answer"} and isinstance(raw.get("answer"), str):
        inner = raw["answer"].strip()
        if inner:
            return inner
    return None


def _looks_like_tool_error_answer(answer: str) -> bool:
    """检测模型把工具/API 相关 JSON 当成最终答案输出的情况。

    覆盖两类：
    - 错误 JSON：{"error": "No such tool: ...", "error_code": 404}
    - 工具调用 JSON 泄漏：{"name": "knowledge_search", "arguments": {...}}
    """
    text = _strip_json_fence(answer)
    if not text.startswith("{"):
        return False
    try:
        raw = json.loads(text)
    except Exception:  # noqa: BLE001
        return False
    if not isinstance(raw, dict):
        return False
    if isinstance(raw.get("error"), str) or "error_code" in raw:
        return True
    if isinstance(raw.get("name"), str) and isinstance(raw.get("arguments"), dict):
        return True
    return False


def make_final_answer_guard(enforce_evidence: bool = True, followup_question: bool = False):
    """P6c 边界：检索过工具后，对最终回答做两层兜底。

    - enforce_evidence：工具全部无有效证据时，拒绝给出结论；
    - 未检索引用校验：答案中出现证据里没有的规范编号/题库背景时，替换为拒答话术。
    - 标记清理：无论是否调过工具，答案中的 [KTE] 标记必须真实存在于工具返回；
      没调工具时所有标记视为编造，一律移除（不因此拒答，避免误伤模型直接回答）。

    返回 (新答案, 说明文案, 结果码)；无需处理时返回 None。
    结果码为机器可读终态标注（观测用，agent_loop 据此修正 final_outcome）：
    tool_error_json / no_evidence / unsupported_reference / half_refusal_stripped /
    refusal_kept / markers_cleaned / answer_envelope_unwrapped；guard 返回 2 元组时按无结果码兼容。
    """
    from angineer_core.qa_pipeline import REFUSAL_ANSWER_TEXT
    from angineer_core.retrieval_pipeline import has_unsupported_reference
    from angineer_core.agent_messages import REFUSAL_FOLLOWUP_QUESTION

    def _refusal_text() -> str:
        if followup_question:
            return REFUSAL_ANSWER_TEXT + REFUSAL_FOLLOWUP_QUESTION
        return REFUSAL_ANSWER_TEXT

    def guard(added_messages: List[AgentMessage]):
        tool_messages = [m for m in added_messages if m.role == "tool"]
        final_assistant = next(
            (m for m in reversed(added_messages) if m.role == "assistant" and not m.tool_calls),
            None,
        )
        if final_assistant is None:
            return None

        answer = final_assistant.content or ""
        if _looks_like_tool_error_answer(answer):
            return (
                _refusal_text(),
                "边界规则：最终回答为工具/API 错误 JSON，已替换为拒答话术",
                "tool_error_json",
            )
        # 单键 answer 信封拆封：先拆再走证据/拒答/标记校验，让后续检查都作用在内文上
        unwrapped = _unwrap_answer_envelope(answer)
        envelope_unwrapped = unwrapped is not None
        if envelope_unwrapped:
            answer = unwrapped or ""
        # 守卫内共用：证据内生效的标记集合（无工具消息时为空集，所有标记视为编造）。
        # 所有保留正文的分支（half_refusal_stripped / refusal_kept / markers_cleaned）
        # 都必须过无效标记清理——refusal_kept 此前早退跳过清理，L2→L1 回退段
        # 跨轮照抄的 [K5] 裸给用户（2026-10-04 验收实测）
        valid_markers = _valid_markers(added_messages)

        def _clean_bad_markers(text: str) -> "tuple[str, int]":
            markers_found = _MARKER_RE.findall(text)
            bad_found = [m for m in markers_found if m not in valid_markers]
            if not bad_found:
                return text, 0
            cleaned = _MARKER_RE.sub(
                lambda m: m.group(0) if m.group(1) in valid_markers else "", text
            )
            return cleaned, len(bad_found)

        if tool_messages:
            evidence_parts: List[str] = []
            for message in tool_messages:
                try:
                    raw = json.loads(message.content or "{}")
                except Exception:  # noqa: BLE001
                    continue
                if isinstance(raw, dict) and isinstance(raw.get("items"), list):
                    for item in raw["items"]:
                        if not isinstance(item, dict):
                            continue
                        text = str(item.get("text") or "")
                        if text.strip():
                            evidence_parts.append(text.strip())
                elif isinstance(raw, dict) and any(k in raw for k in ("documents", "pages", "storage", "uploads")):
                    # P-1（废 meta 路由第二步）：knowledge_stats 返回无 items[]，把统计摘要纳入证据面——
                    # no_evidence 与 unsupported_reference 两道闸一并兼容（evidence_parts 定版方案，
                    # 否决「纯 stats 组合豁免 enforce_evidence」：那会重开无证据出数字的洞）
                    digest = "; ".join(
                        f"{k}={json.dumps(raw[k], ensure_ascii=False)[:200]}"
                        for k in ("documents", "pages", "storage", "uploads")
                        if k in raw
                    )
                    evidence_parts.append(f"[knowledge_stats] {digest}")

            evidence_text = "\n".join(evidence_parts)
            no_evidence = not evidence_text.strip()
            if enforce_evidence and no_evidence:
                return (
                    _refusal_text(),
                    "边界规则：未检索到有效证据，拒绝给出最终结论（enforce_evidence）",
                    "no_evidence",
                )
            if answer and has_unsupported_reference(answer, evidence_text):
                return (
                    _refusal_text(),
                    "边界规则：最终回答引用了未检索到的规范/背景，已替换为拒答话术",
                    "unsupported_reference",
                )
            stripped = strip_half_refusal_lead(answer)
            if stripped != answer:
                # 半拒答：模型先写了「没有检索到足够证据」又带着引用继续作答 —— 只删开头那句，
                # 保留正文（旧实现（ANGINEER_GUARD_HALF_REFUSAL）整体替换成纯拒答，会把事实一起丢掉）；
                # 正文里的无效标记同样剥净（有证据面时只剥证据外标记）
                stripped, bad_n = _clean_bad_markers(stripped)
                note = "边界规则：检测到半拒答（先声明无证据又继续作答），已删掉拒答开头、保留正文"
                if bad_n:
                    note += f"（另移除 {bad_n} 个无效引用标记）"
                return (
                    stripped,
                    note,
                    "half_refusal_stripped",
                )
            if answer and is_refusal_text(answer):
                refusal_note = (
                    "边界规则：已有有效证据但最终回答仍为拒答，保留原回答"
                    if evidence_text.strip()
                    else "边界规则：最终回答为拒答，保留原回答"
                )
                # 保留拒答+相邻片段形态，但跨轮照抄的无效标记必须剥净（本轮零命中时全剥）
                answer_cleaned, bad_n = _clean_bad_markers(answer)
                if bad_n:
                    refusal_note += f"（另移除 {bad_n} 个无效引用标记）"
                return (
                    answer_cleaned,
                    refusal_note,
                    "refusal_kept",
                )
        cleaned_body, bad_total = _clean_bad_markers(answer)
        if bad_total:
            return (cleaned_body, f"边界规则：检测到 {bad_total} 个无效引用标记，已移除", "markers_cleaned")
        if envelope_unwrapped:
            return (
                answer,
                "边界规则：最终回答为单键 {\"answer\"} 信封，已拆封取内文",
                "answer_envelope_unwrapped",
            )
        return None

    return guard


def build_chat_config(
    *,
    llm: Any,
    config_name: Optional[str] = None,
    mode: str = "instruct",
) -> AgentLoopConfig:
    """L0 闲聊直答档：无工具、单轮。"""
    from angineer_core.prompts.dispatcher import CHAT_SYSTEM_PROMPT

    budget_est = _chat_budget_tokens_est()
    chat_transformer = (
        make_budget_transformer(max_tokens_est=budget_est)
        if budget_est > 0
        else None
    )

    return AgentLoopConfig(
        llm=llm,
        tools=[],
        system_prompt=CHAT_SYSTEM_PROMPT,
        max_turns=1,
        config_name=config_name,
        mode=mode,
        codec=TextToolCallCodec(),
        transform_context=chat_transformer,
    )


# meta_query 档已随废 meta_query 路由删除（2026-10-02 第二步）：原 build_meta_config/
# _meta_budget_tokens_est（ANGINEER_META_BUDGET_TOKENS_EST）一并移除；
# knowledge_stats 下沉 build_qa_config 的 L1 统一工具箱，统计题与正文题同档由模型自选。


def _followup_question_enabled() -> bool:
    """ANGINEER_FOLLOWUP_QUESTION 开关解析：true/1/yes/on 视为开，其余视为关（默认开）。"""
    return os.getenv("ANGINEER_FOLLOWUP_QUESTION", "true").strip().lower() in ("true", "1", "yes", "on")


def _eager_compress_enabled() -> bool:
    """ANGINEER_EAGER_COMPRESS 开关解析（默认关）：每轮即压跨 run 工具结果为带 doc 指针的摘要，不等预算阈值。"""
    return os.getenv("ANGINEER_EAGER_COMPRESS", "false").strip().lower() in ("true", "1", "yes", "on")


def _budget_tokens_est(env_key: str, default: int) -> int:
    raw = os.getenv(env_key, str(default)).strip()
    try:
        return max(0, int(raw))
    except ValueError:
        return default


def _qa_budget_tokens_est() -> int:
    """QA 档预算阈值（plan-ttft-improvement 需求 A1；req-chat-history-bloat §5.1.3 收紧）。

    定值依据（2026-09-29 ops 回归，74 run 配对）：real/est 系数 p99=1.46；
    est [16k,20k) 桶 real max 22.4k 达标，est [20k,30k) 桶 real p50 31.8k 超标。
    16k est × 1.46 ≈ 23.4k real，对 25k 验收线留 1.6k 余量。设 0 关闭（回退）。
    """
    return _budget_tokens_est("ANGINEER_QA_BUDGET_TOKENS_EST", 16_000)


def _chat_budget_tokens_est() -> int:
    """L0 闲聊档预算阈值（req-chat-history-bloat §5.1.1）。

    L0 无工具无证据，闸只压历史轮残留的 tool 消息（此前 QA 轮的全量检索证据）——
    闲聊一句「你好」曾背上 73k prompt。裸装（无 protect_current_run）：当轮无工具结果可误压。
    设 0 关闭（回退）。
    """
    return _budget_tokens_est("ANGINEER_CHAT_BUDGET_TOKENS_EST", 12_000)


def _complex_budget_tokens_est() -> int:
    """complex 档预算阈值（req-chat-history-bloat §5.1.4 重估初值）。

    原 100k est 对 QA 场景形同虚设（L3 第 4 轮 real 61k 未触发）。complex 无
    protect_current_run（run 内轮间压缩是其原始语义），SOP 长 run 需要更早的证据余量，
    故不与 QA 档 16k 对齐、独立取 24k est（×p99 系数 1.46 ≈ 35k real；
    L3 当轮自超 25k 的题按需求 §4.1 豁免单列）。实测后再调。设 0 关闭（回退）。
    """
    return _budget_tokens_est("ANGINEER_COMPLEX_BUDGET_TOKENS_EST", 24_000)


def build_qa_config(
    *,
    llm: Any,
    doc_nodes: Optional[List[Any]] = None,
    library_id: str = "default",
    library_ids: Optional[List[str]] = None,
    doc_ids: Optional[List[str]] = None,
    filters: Any = None,
    task_type: str = "content_qa",
    knowledge_task_type: Optional[str] = None,
    table_task_type: Optional[str] = None,
    max_turns: int = 3,
    inline_citations: Optional[List[Dict[str, Any]]] = None,
    config_name: Optional[str] = None,
    mode: str = "instruct",
    tools: Optional[List[AgentTool]] = None,
    rerank: bool = True,
    enforce_evidence: bool = True,
    final_answer_guard: Optional[Any] = None,
    route_note: Optional[str] = None,
    marker_allocator: Optional[Any] = None,
    followup_question: Optional[bool] = None,
    max_tokens_est: Optional[int] = None,
) -> AgentLoopConfig:
    """装配 QA 档 agent 循环：四个只读工具（三检索 + 知识库统计）+ 内联 QA prompt（P5 前）。"""
    effective_tools = tools
    if effective_tools is None:
        effective_knowledge_task_type = knowledge_task_type or task_type
        effective_table_task_type = table_task_type or task_type
        knowledge_tool = RetrieverAdapter.knowledge_search(
            library_id=library_id,
            library_ids=library_ids,
            doc_ids=doc_ids,
            doc_nodes=doc_nodes,
            top_k=20,
            task_type=effective_knowledge_task_type,
            filters=filters,
            rerank=rerank,
            marker_allocator=marker_allocator,
            config_name=config_name,
            mode=mode,
        )
        table_tool = RetrieverAdapter.table_search(
            library_id=library_id,
            doc_ids=doc_ids,
            doc_nodes=doc_nodes,
            top_k=20,
            filters=filters,
            rerank=rerank,
            marker_allocator=marker_allocator,
            config_name=config_name,
            mode=mode,
        )
        entity_tool = RetrieverAdapter.entity_search(
            library_id=library_id,
            doc_ids=doc_ids,
            marker_allocator=marker_allocator,
            config_name=config_name,
            mode=mode,
        )
        # 查表/数值类任务把 table_search 排在首位，引导模型优先用它
        table_first = (
            str(effective_table_task_type).startswith("table_")
            or str(effective_table_task_type) in {"locate_table", "locate_qa"}
        )
        ordered = (
            [table_tool, knowledge_tool, entity_tool]
            if table_first
            else [knowledge_tool, table_tool, entity_tool]
        )
        # knowledge_stats 下沉 L1 统一工具箱（废 meta_query 路由第二步，2026-10-02）：
        # 统计题与正文题同档、模型按工具描述自选；工具描述已把「只在问知识库本身」边界写死（§2.5 暴露面）
        ordered.append(StatsAdapter.knowledge_stats(default_library_id=library_id))
        effective_tools = ordered

    system_prompt = _load_qa_system_prompt()
    explicit = _build_inline_citation_context(inline_citations or [])
    if explicit:
        system_prompt += "\n\n显式引用证据（用户已确认，优先级最高）：\n" + explicit

    followup_enabled = _followup_question_enabled() if followup_question is None else bool(followup_question)
    if followup_enabled:
        system_prompt += FOLLOWUP_QUESTION_RULE

    guard = final_answer_guard
    if guard is None:
        guard = make_final_answer_guard(
            enforce_evidence=enforce_evidence,
            followup_question=followup_enabled,
        )

    budget_est = _qa_budget_tokens_est() if max_tokens_est is None else int(max_tokens_est)
    qa_transformer = (
        make_budget_transformer(
            max_tokens_est=budget_est,
            protect_current_run=True,
            eager=_eager_compress_enabled(),
        )
        if budget_est > 0
        else None
    )

    return AgentLoopConfig(
        llm=llm,
        config_name=config_name,
        mode=mode,
        tools=effective_tools,
        system_prompt=system_prompt,
        max_turns=max_turns,
        codec=TextToolCallCodec(),
        final_answer_guard=guard,
        route_note=route_note,
        followup_question=followup_enabled,
        transform_context=qa_transformer,
    )


def _estimate_tokens(messages: List[AgentMessage]) -> int:
    """粗估 token：与 main.py 现有口径一致，字符数 // 2。"""
    return sum(len(message.content or "") for message in messages) // 2


def _summarize_tool_raw(raw: Dict[str, Any]) -> str:
    """把工具 raw 结果压缩为一行要点（仅用于预算压缩后的摘要）。

    检索类结果必须保留回看指针（doc 级：doc_id + 文档名 + cite 标记），
    模型后续可用 knowledge_search 的 doc_ids 参数按指针调取原文（显式回看），
    只写「检索到 N 条候选」会让跨轮指代（「刚才第二条规范」）彻底断链。
    入参约定：调用方传 message.meta（{"raw": ...} 外壳），此处先剥壳。
    """
    if isinstance(raw, dict) and "raw" in raw:
        raw = raw.get("raw")
    if not isinstance(raw, dict):
        return str(raw)[:120]
    sop_trace = raw.get("sop_trace")
    if isinstance(sop_trace, list):
        success = sum(1 for s in sop_trace if s.get("status") == "success")
        return f"SOP {raw.get('sop_id', '')} 执行 {len(sop_trace)} 步，成功 {success} 步"
    if "items" in raw:
        items = raw.get("items") or []
        return f"检索到 {raw.get('total', len(items))} 条候选{_item_pointer_keys(items)}"
    if "entities" in raw:
        entities = raw.get("entities") or []
        return f"图谱检索到 {raw.get('total', len(entities))} 个实体"
    if raw.get("error"):
        return f"工具出错: {raw['error']}"
    return json.dumps(raw, ensure_ascii=False, default=str)[:120]


def _item_pointer_keys(items: List[Any], limit: int = 6) -> str:
    """从检索候选中提取 doc 级回看指针（去重、限量、限长），无指针时返回空串。"""
    keys: List[str] = []
    seen: set = set()
    for item in items:
        if not isinstance(item, dict):
            continue
        doc_id = str(item.get("doc_id") or "")
        if not doc_id or doc_id in seen:
            continue
        seen.add(doc_id)
        meta = item.get("metadata") or {}
        title = str(meta.get("doc_title") or item.get("title") or "")[:24]
        cite = str(meta.get("cite") or "")
        tag = f"{cite}·{title}" if cite and title else (cite or title or doc_id)
        keys.append(f"{tag}[doc_id={doc_id}]")
        if len(keys) >= limit:
            break
    return f"，要点: {'、'.join(keys)}" if keys else ""


def _is_injected_user_prompt(content: Optional[str]) -> bool:
    """循环内部注入的 user 角色提示（retry/代检索脚手架）——protect_current_run 划界时跳过。

    修复（req-chat-history-bloat §5.1.3）：run 内 retry 注入的内部提示会把「最后一条 user」
    边界后移，当轮已产出的证据反落可压区——超阈值会话里重试轮拿不到证据作答。
    与 agent_loop._latest_user_query 同一跳过口径。
    """
    text = (content or "").strip()
    return bool(text) and text.startswith(_INJECTED_USER_PROMPTS)


def make_budget_transformer(max_tokens_est: int = 100_000, protect_current_run: bool = False, eager: bool = False):
    """P4.3 闸门一：超预算时按 oldest-first 压缩工具结果（投影式，copy-on-write）。

    2026-09-24（plan-ttft-improvement 需求 A1）：原版直接改写消息对象的 content，
    而 transform_context 吃的是 session.history 本体——压缩会永久写进内存 history
    并随 persist 落 chat.sqlite，与「压缩只作用于发给 LLM 的 messages」矛盾。
    现版只读原消息，被压缩条目换成新对象放进新列表返回，history 本体与落库保全量原文；
    摘要缓存在闭包内（键为对象 id，session.history 生命周期内稳定），不再写进 message.meta。
    总字数 running total 做整除 2 的口径与 _estimate_tokens（sum//2）逐位一致。

    protect_current_run=True（QA 档）：本 run 区间 = 最后一条 user 消息之后的消息，
    其中工具结果不压缩（当轮证据必须完整在手才能作答）；被压掉的只有更早轮次的
    跨 run 历史工具结果——这正是多轮膨胀的主因（每轮全量证据 dump 永久留存回灌）。
    压完仍可能超阈值：当轮证据是硬需求，宁可超限也不压当轮。
    complex 档保持 False（长 run 内部轮间压缩是它的原始语义）。

    eager=True（ANGINEER_EAGER_COMPRESS，仅 QA 档接线）：不等阈值，
    每轮都把「最后一条 user 之前」的跨 run 工具结果压成带 doc 指针的摘要——
    压掉的体积可用 knowledge_search 的 doc_ids 入参按指针回看（2026-10-06 起 schema 开放），
    损失从「永久丢失」降级为「按需可取」，因此不必再用阈值保护保真度。
    当 run 证据（最后一条 user 之后）任何模式下都不压。
    """

    summary_cache: Dict[int, str] = {}

    def transform(messages: List[AgentMessage]) -> List[AgentMessage]:
        total_chars = sum(len(message.content or "") for message in messages)
        last_user_index = -1
        if protect_current_run:
            for index, message in enumerate(messages):
                if message.role == "user" and not _is_injected_user_prompt(message.content):
                    last_user_index = index
        eager_active = eager and protect_current_run and last_user_index > 0
        if total_chars // 2 <= max_tokens_est and not eager_active:
            return messages
        result = list(messages)
        for index, message in enumerate(result):
            if not eager_active and total_chars // 2 <= max_tokens_est:
                break
            if message.role != "tool":
                continue
            if protect_current_run and index > last_user_index:
                continue
            if eager_active and index >= last_user_index:
                # eager 只压「最后一条 user 之前」的跨 run 历史；当 run 起点及其后全豁免
                continue
            summary = summary_cache.get(id(message))
            if summary is None:
                summary = _summarize_tool_raw(message.meta)
                summary_cache[id(message)] = summary
            compressed = (
                f"[已压缩: 工具 {message.name or 'unknown'} 的结果，要点: {summary}]"
            )
            total_chars += len(compressed) - len(message.content or "")
            result[index] = replace(message, content=compressed, meta=dict(message.meta))
        return result

    return transform


def _budget_stopper_est() -> int:
    """循环停止线（est=chars//2；ANGINEER_BUDGET_STOPPER_EST 默认 120000）。

    env 化动因（plan-evidence-admission §2 P2）：换小上下文模型时停止线随 .env 调，不再裸奔硬编码。"""
    return _budget_tokens_est("ANGINEER_BUDGET_STOPPER_EST", 120_000)


def make_budget_stopper(threshold: Optional[int] = None):
    """P4.3 闸门二：turn 结束估算超阈值 → 循环优雅停止（reason=should_stop）。

    threshold 显式传参优先（测试/特殊档位用）；不传读 ANGINEER_BUDGET_STOPPER_EST。"""
    resolved = threshold if threshold is not None else _budget_stopper_est()

    def should_stop(context: TurnContext) -> bool:
        return _estimate_tokens(context.messages) > resolved

    return should_stop


def build_complex_config(
    *,
    llm: Any,
    doc_nodes: Optional[List[Any]] = None,
    library_id: str = "default",
    library_ids: Optional[List[str]] = None,
    doc_ids: Optional[List[str]] = None,
    filters: Any = None,
    inline_citations: Optional[List[Dict[str, Any]]] = None,
    config_name: Optional[str] = None,
    mode: str = "instruct",
    tools: Optional[List[AgentTool]] = None,
    rerank: bool = True,
    sops: Optional[List[Any]] = None,
    sop_loader: Any = None,
    memory: Any = None,
    step_callback: Optional[Any] = None,
    max_turns: int = 8,
    max_tokens_est: Optional[int] = None,
    budget_threshold: Optional[int] = None,
    route_note: Optional[str] = None,
    marker_allocator: Optional[Any] = None,
    final_answer_guard: Optional[Any] = None,
) -> AgentLoopConfig:
    """P4.1 大题型 agent 循环：QA 三件套 + SOP 执行 + 计算/查表/条件分支。"""
    if tools is None:
        qa_tools = [
            RetrieverAdapter.knowledge_search(
                library_id=library_id,
                library_ids=library_ids,
                doc_ids=doc_ids,
                doc_nodes=doc_nodes,
                top_k=20,
                task_type="content_qa",
                filters=filters,
                rerank=rerank,
                marker_allocator=marker_allocator,
                config_name=config_name,
                mode=mode,
            ),
            RetrieverAdapter.table_search(
                library_id=library_id,
                doc_ids=doc_ids,
                doc_nodes=doc_nodes,
                top_k=20,
                filters=filters,
                rerank=rerank,
                marker_allocator=marker_allocator,
                config_name=config_name,
                mode=mode,
            ),
            RetrieverAdapter.entity_search(
                library_id=library_id,
                doc_ids=doc_ids,
                marker_allocator=marker_allocator,
                config_name=config_name,
                mode=mode,
            ),
        ]
        effective_tools = [
            *qa_tools,
            SopRunnerAdapter.sop_execute(
                sops=sops,
                sop_loader=sop_loader,
                llm_client=llm,
                config_name=config_name,
                mode=mode,
                memory=memory,
                step_callback=step_callback,
                library_id=library_id,
                doc_ids=doc_ids,
            ),
            EngtoolAdapter.from_registry(
                "calculator",
                description="工程计算器，支持变量替换与方程求解。输入 expression（表达式）、variables（变量字典）、solve_for（可选求解变量）。",
                parameters_schema={
                    "type": "object",
                    "properties": {
                        "expression": {"type": "string", "description": "数学表达式，如 T+Z0+Z1"},
                        "variables": {"type": "object", "description": "变量字典，如 {\"T\": 12.8}"},
                        "solve_for": {"type": "string", "description": "可选：要求解的变量名"},
                    },
                    "required": ["expression"],
                },
                read_only=False,
            ),
            EngtoolAdapter.from_registry(
                "conditional",
                description="条件分支工具：根据条件变量值选择不同执行路径。输入 condition_var、branches（分支列表）、default（默认值，可选）。",
                parameters_schema={
                    "type": "object",
                    "properties": {
                        "condition_var": {"type": ["string", "number"], "description": "条件变量值"},
                        "branches": {
                            "type": "array",
                            "items": {"type": "object"},
                            "description": "分支列表，每项含 match/value 或 table_lookup",
                        },
                        "default": {"description": "默认返回值"},
                    },
                    "required": ["condition_var"],
                },
                read_only=False,
            ),
        ]
    else:
        effective_tools = tools

    system_prompt = COMPLEX_AGENT_SYSTEM_PROMPT
    explicit = _build_inline_citation_context(inline_citations or [])
    if explicit:
        system_prompt += "\n\n显式引用证据（用户已确认，优先级最高）：\n" + explicit

    complex_followup = _followup_question_enabled()
    if complex_followup:
        system_prompt += FOLLOWUP_QUESTION_RULE

    complex_budget_est = _complex_budget_tokens_est() if max_tokens_est is None else int(max_tokens_est)
    complex_transformer = (
        make_budget_transformer(max_tokens_est=complex_budget_est)
        if complex_budget_est > 0
        else None
    )

    # 与 QA 档同款最终答案边界（2026-10-04 补装）：L3/L4 此前无 guard，occamy 实测把
    # 表格检索分配的 T 前缀写成正文 [K1]/[K3]（不照抄工具结果里的实际 cite 值），
    # 无效标记既不被剥除、前端也匹配不到引用项 → 用户看到裸 [K3] 文本
    guard = final_answer_guard
    if guard is None:
        guard = make_final_answer_guard(
            enforce_evidence=True,
            followup_question=complex_followup,
        )

    return AgentLoopConfig(
        llm=llm,
        config_name=config_name,
        mode=mode,
        tools=effective_tools,
        system_prompt=system_prompt,
        max_turns=max_turns,
        codec=TextToolCallCodec(),
        final_answer_guard=guard,
        followup_question=complex_followup,
        transform_context=complex_transformer,
        should_stop_after_turn=make_budget_stopper(threshold=budget_threshold),
        route_note=route_note,
    )
