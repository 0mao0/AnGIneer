"""P3.2 L1 agentic RAG 接入层（独立文件，避免继续喂胖 dispatcher）。"""
import logging
import time
from typing import Any, Dict, List, Optional, Tuple

from angineer_core.agent_loop import run_agent_loop
from angineer_core.agent_messages import AgentMessage
from angineer_core.agent_tools import AgentTool

logger = logging.getLogger(__name__)

_REFUSAL_TEXT = (
    "没有检索到足够证据支持最终结论。"
    "当前仅能确认已有片段与问题相关，但不足以安全地给出完整答案，请继续补充可核对的规范依据。"
)


def dispatch_semantic_agentic(
    *,
    query: str,
    doc_nodes: list,
    library_id: str,
    doc_ids: List[str],
    inline_citations: Optional[List[Dict[str, Any]]] = None,
    filters: Any = None,
    enforce_evidence: bool = False,
    task_type: str = "content_qa",
    max_turns: int = 3,
    llm: Any = None,
    config_name: Optional[str] = None,
    mode: str = "instruct",
    tools: Optional[List[AgentTool]] = None,
) -> Tuple[str, list, list, str, str, Dict, Dict[str, float], Dict[str, Any]]:
    """L1 agentic RAG：返回与 `Dispatcher._dispatch_semantic` 一致的 8 元组。

    retrieval_debug["agent"] 含 turns/tool_calls/reason/refusal 摘要，
    evals 的 enrich_prediction_trace 会自动带进 prediction。
    """
    from ai_inference.llm_client import get_llm_client
    from angineer_core.agent_configs import build_qa_config
    from angineer_core.retrieval_utils import (
        build_citations_from_retrieved,
        has_unsupported_reference,
    )
    from docs_core.step09_query.protocols.contracts import RetrievedItem

    llm = llm or get_llm_client()
    config = build_qa_config(
        llm=llm,
        doc_nodes=doc_nodes,
        library_id=library_id,
        doc_ids=doc_ids,
        filters=filters,
        task_type=task_type,
        max_turns=max_turns,
        inline_citations=inline_citations,
        config_name=config_name,
        mode=mode,
        tools=tools,
    )

    events: list = []
    messages: List[AgentMessage] = [AgentMessage(role="user", content=query)]
    started = time.time()
    added = run_agent_loop(messages, config, emit=events.append)
    loop_duration = round(time.time() - started, 2)

    run_end = next((event for event in reversed(events) if event.type == "run_end"), None)
    run_end_payload = run_end.payload if run_end else {}
    reason = str(run_end_payload.get("reason") or "error")
    turns = int(run_end_payload.get("turns") or 0)

    # 汇总工具返回的检索条目（tool 消息的 meta 里带 raw）
    all_items: List[RetrievedItem] = []
    tool_messages = [message for message in added if message.role == "tool"]
    for message in tool_messages:
        raw = message.meta or {}
        for entry in raw.get("items") or []:
            if not isinstance(entry, dict):
                continue
            try:
                all_items.append(RetrievedItem(**entry))
            except Exception:  # noqa: BLE001
                continue

    unique_items: List[RetrievedItem] = []
    seen_ids = set()
    for item in all_items:
        key = str(item.item_id or "")
        if key and key in seen_ids:
            continue
        if key:
            seen_ids.add(key)
        unique_items.append(item)

    retrieved_items = [item.model_dump(mode="json") for item in unique_items]
    try:
        citations = build_citations_from_retrieved(unique_items, doc_nodes or [])
    except Exception as exc:  # noqa: BLE001
        logger.warning("agentic 引用构建失败: %s", exc)
        citations = []

    evidence_text = "\n".join(item.text or "" for item in unique_items)
    final_assistant = next(
        (message for message in reversed(added) if message.role == "assistant"),
        None,
    )
    answer = final_assistant.content if final_assistant else ""

    no_evidence = not any((item.text or "").strip() for item in unique_items)
    refusal = bool(enforce_evidence and no_evidence)
    if refusal:
        # 对齐 legacy：enforce_evidence 且无有效证据 → 返回空，让调度链继续尝试后续路径
        answer = ""
    elif answer and has_unsupported_reference(answer, evidence_text):
        answer = _REFUSAL_TEXT

    strategy_desc = f"agentic_rag (turns={turns}, reason={reason})"
    retrieval_debug: Dict[str, Any] = {
        "agent": {
            "turns": turns,
            "tool_calls": len(tool_messages),
            "reason": reason,
            "strategy": "agentic_rag",
            "refusal": refusal,
            "task_type": task_type,
        },
        "agent_events": [event.model_dump(mode="json") for event in events],
    }
    timings: Dict[str, float] = {"agent_loop": loop_duration}
    runtime_flags: List[str] = []

    return (
        answer,
        citations,
        retrieved_items,
        strategy_desc,
        config.system_prompt,
        retrieval_debug,
        timings,
        runtime_flags,
    )
