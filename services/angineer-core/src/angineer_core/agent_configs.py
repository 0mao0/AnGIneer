"""P3.1 知识问答 + P4.1 大题型 agent 循环配置装配。"""
import json
import os
import re
from typing import Any, Dict, List, Optional

from angineer_core.agent_loop import AgentLoopConfig, TurnContext
from angineer_core.agent_messages import AgentMessage, is_half_refusal_text, is_refusal_text
from angineer_core.agent_tools import (
    AgentTool,
    EngtoolAdapter,
    RetrieverAdapter,
    SopRunnerAdapter,
)
from angineer_core.prompts.agent_configs import (  # noqa: F401  # P5 资产化后 re-export，保持旧导入兼容
    COMPLEX_AGENT_SYSTEM_PROMPT,
    FOLLOWUP_QUESTION_RULE,
    QA_AGENT_SYSTEM_PROMPT,
)
from angineer_core.tool_codec import TextToolCallCodec


_MARKER_RE = re.compile(r"\[([KTE]\d+)\]")


def _env_flag(name: str, default: bool = False) -> bool:
    """通用 env 布尔开关解析：true/1/yes/on 视为开，其余视为关。"""
    raw = os.getenv(name, "")
    return raw.strip().lower() in ("true", "1", "yes", "on")


def _load_qa_system_prompt() -> str:
    """按 ANGINEER_QA_PROMPT_VERSION 加载 QA 档系统提示（默认最新注册版本）。"""
    from angineer_core.prompts import load

    version = os.getenv("ANGINEER_QA_PROMPT_VERSION", "latest").strip() or "latest"
    return load("agent_configs.qa_system_prompt", version)


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


def _looks_like_tool_error_answer(answer: str) -> bool:
    """检测模型把工具/API 相关 JSON 当成最终答案输出的情况。

    覆盖两类：
    - 错误 JSON：{"error": "No such tool: ...", "error_code": 404}
    - 工具调用 JSON 泄漏：{"name": "knowledge_search", "arguments": {...}}
    """
    text = (answer or "").strip()
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

    返回 (新答案, 说明文案)；无需处理时返回 None。
    """
    from angineer_core.qa_pipeline import REFUSAL_ANSWER_TEXT
    from angineer_core.retrieval_pipeline import has_unsupported_claim, has_unsupported_reference
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
            )
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

            evidence_text = "\n".join(evidence_parts)
            no_evidence = not evidence_text.strip()
            if enforce_evidence and no_evidence:
                return (
                    _refusal_text(),
                    "边界规则：未检索到有效证据，拒绝给出最终结论（enforce_evidence）",
                )
            if answer and has_unsupported_reference(answer, evidence_text):
                return (
                    _refusal_text(),
                    "边界规则：最终回答引用了未检索到的规范/背景，已替换为拒答话术",
                )
            if _env_flag("ANGINEER_GUARD_CLAIM") and answer and has_unsupported_claim(answer, evidence_text):
                return (
                    _refusal_text(),
                    "边界规则：最终回答包含证据中未出现的数值/专名（ANGINEER_GUARD_CLAIM），已替换为拒答话术",
                )
            if _env_flag("ANGINEER_GUARD_HALF_REFUSAL") and answer and is_half_refusal_text(answer):
                return (
                    _refusal_text(),
                    "边界规则：检测到半拒答（先声明证据不足又继续作答，ANGINEER_GUARD_HALF_REFUSAL），已替换为拒答话术",
                )
            if answer and is_refusal_text(answer):
                refusal_note = (
                    "边界规则：已有有效证据但最终回答仍为拒答，保留原回答"
                    if evidence_text.strip()
                    else "边界规则：最终回答为拒答，保留原回答"
                )
                return (
                    answer,
                    refusal_note,
                )
        markers = _MARKER_RE.findall(answer)
        valid = _valid_markers(added_messages)
        bad = [m for m in markers if m not in valid]
        if bad:
            cleaned = _MARKER_RE.sub(lambda m: m.group(0) if m.group(1) in valid else "", answer)
            return (cleaned, f"边界规则：检测到 {len(bad)} 个无效引用标记，已移除")
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

    return AgentLoopConfig(
        llm=llm,
        tools=[],
        system_prompt=CHAT_SYSTEM_PROMPT,
        max_turns=1,
        config_name=config_name,
        mode=mode,
        codec=TextToolCallCodec(),
    )


def _followup_question_enabled() -> bool:
    """ANGINEER_FOLLOWUP_QUESTION 开关解析：true/1/yes/on 视为开，其余视为关（默认开）。"""
    return os.getenv("ANGINEER_FOLLOWUP_QUESTION", "true").strip().lower() in ("true", "1", "yes", "on")


def build_qa_config(
    *,
    llm: Any,
    doc_nodes: Optional[List[Any]] = None,
    library_id: str = "default",
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
) -> AgentLoopConfig:
    """装配 QA 档 agent 循环：三个只读检索工具 + 内联 QA prompt（P5 前）。"""
    effective_tools = tools
    if effective_tools is None:
        effective_knowledge_task_type = knowledge_task_type or task_type
        effective_table_task_type = table_task_type or task_type
        knowledge_tool = RetrieverAdapter.knowledge_search(
            library_id=library_id,
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
        effective_tools = (
            [table_tool, knowledge_tool, entity_tool]
            if table_first
            else [knowledge_tool, table_tool, entity_tool]
        )

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
    )


def _estimate_tokens(messages: List[AgentMessage]) -> int:
    """粗估 token：与 main.py 现有口径一致，字符数 // 2。"""
    return sum(len(message.content or "") for message in messages) // 2


def _summarize_tool_raw(raw: Dict[str, Any]) -> str:
    """把工具 raw 结果压缩为一行要点（仅用于预算压缩后的摘要）。"""
    if not isinstance(raw, dict):
        return str(raw)[:120]
    sop_trace = raw.get("sop_trace")
    if isinstance(sop_trace, list):
        success = sum(1 for s in sop_trace if s.get("status") == "success")
        return f"SOP {raw.get('sop_id', '')} 执行 {len(sop_trace)} 步，成功 {success} 步"
    if "items" in raw:
        items = raw.get("items") or []
        return f"检索到 {raw.get('total', len(items))} 条候选"
    if "entities" in raw:
        entities = raw.get("entities") or []
        return f"图谱检索到 {raw.get('total', len(entities))} 个实体"
    if raw.get("error"):
        return f"工具出错: {raw['error']}"
    return json.dumps(raw, ensure_ascii=False, default=str)[:120]


def make_budget_transformer(max_tokens_est: int = 100_000):
    """P4.3 闸门一：超预算时按 oldest-first 压缩工具结果。

    压缩摘要 lazily 生成一次并缓存进消息 meta（``_budget_summary``），
    后续轮次直接复用，不重复计算。
    """

    def transform(messages: List[AgentMessage]) -> List[AgentMessage]:
        if _estimate_tokens(messages) <= max_tokens_est:
            return messages
        for message in messages:
            if _estimate_tokens(messages) <= max_tokens_est:
                break
            if message.role != "tool":
                continue
            summary = message.meta.get("_budget_summary")
            if not summary:
                summary = _summarize_tool_raw(message.meta)
                message.meta["_budget_summary"] = summary
            message.content = (
                f"[已压缩: 工具 {message.name or 'unknown'} 的结果，要点: {summary}]"
            )
        return messages

    return transform


def make_budget_stopper(threshold: int = 120_000):
    """P4.3 闸门二：turn 结束估算超阈值 → 循环优雅停止（reason=should_stop）。"""

    def should_stop(context: TurnContext) -> bool:
        return _estimate_tokens(context.messages) > threshold

    return should_stop


def build_complex_config(
    *,
    llm: Any,
    doc_nodes: Optional[List[Any]] = None,
    library_id: str = "default",
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
    max_tokens_est: int = 100_000,
    budget_threshold: int = 120_000,
    route_note: Optional[str] = None,
    marker_allocator: Optional[Any] = None,
) -> AgentLoopConfig:
    """P4.1 大题型 agent 循环：QA 三件套 + SOP 执行 + 计算/查表/条件分支。"""
    if tools is None:
        qa_tools = [
            RetrieverAdapter.knowledge_search(
                library_id=library_id,
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
                "table_lookup",
                description="从规范表格中查询取值。输入 table_name（表名）、query_conditions（查询条件）、target_column（目标列，可选）、file_name（规范文件名，可选）。",
                parameters_schema={
                    "type": "object",
                    "properties": {
                        "table_name": {"type": "string", "description": "表名"},
                        "query_conditions": {
                            "type": ["string", "object"],
                            "description": "查询条件，如 {\"船型\": \"杂货船\"}",
                        },
                        "target_column": {"type": "string", "description": "目标列"},
                        "file_name": {"type": "string", "description": "规范文件名"},
                    },
                    "required": ["table_name", "query_conditions"],
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

    return AgentLoopConfig(
        llm=llm,
        config_name=config_name,
        mode=mode,
        tools=effective_tools,
        system_prompt=system_prompt,
        max_turns=max_turns,
        codec=TextToolCallCodec(),
        transform_context=make_budget_transformer(max_tokens_est=max_tokens_est),
        should_stop_after_turn=make_budget_stopper(threshold=budget_threshold),
        route_note=route_note,
    )
