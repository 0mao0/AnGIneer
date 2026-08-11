"""P7 终态查询入口：classifier → agent_policy → run_agent_loop。

供 evals 与内部调用使用，返回与旧 /api/query（Dispatcher.dispatch）兼容的字段结构；
不依赖 HTTP / FastAPI / asyncio，可在 daemon 线程中直接调用。
"""
import logging
import time
import uuid
from typing import Any, Dict, List, Optional

from angineer_core.agent_loop import AgentLoopConfig, run_agent_loop
from angineer_core.agent_messages import AgentMessage

logger = logging.getLogger(__name__)


def _load_doc_nodes(library_id: str, doc_ids: Optional[List[str]]) -> list:
    """加载知识库 document 节点；失败时返回空列表（检索工具降级）。"""
    try:
        from docs_core.docs_service import get_docs_service

        kp = get_docs_service()
        nodes = [n for n in kp.list_nodes(library_id) if getattr(n, "type", "") == "document"]
        if doc_ids:
            ids = set(str(doc_id) for doc_id in doc_ids if str(doc_id).strip())
            nodes = [n for n in nodes if getattr(n, "id", "") in ids]
        return nodes
    except Exception as exc:  # noqa: BLE001
        logger.warning("加载知识库节点失败，agent 检索工具将无节点: %s", exc)
        return []


def _default_intent_result():
    from angineer_core.base_contracts import IntentResult

    return IntentResult(
        intent_level="L1",
        primary_level="L1",
        service_mode="semantic_retrieval",
        execution_plan=["semantic_retrieval"],
    )


def _intent_to_dict(intent_result: Any) -> Dict[str, Any]:
    if hasattr(intent_result, "model_dump"):
        try:
            return intent_result.model_dump(mode="json")
        except Exception:  # noqa: BLE001
            pass
    data = dict(getattr(intent_result, "__dict__", {}) or {})
    return {k: v for k, v in data.items() if not k.startswith("_")}


def run_policy_query(
    query: str,
    library_id: str = "default",
    doc_ids: Optional[List[str]] = None,
    config_name: Optional[str] = None,
    mode: str = "instruct",
    sop_loader: Any = None,
    inline_citations: Optional[List[Dict[str, Any]]] = None,
    stage_callback=None,
    step_callback=None,  # noqa: ARG001  # SOP 步骤回调由 agent 工具内部处理，这里保持签名兼容
) -> Dict[str, Any]:
    """策略化查询：返回与旧 /api/query 相同结构的字典。"""
    started_at = time.time()
    query_id = f"q-{uuid.uuid4().hex[:12]}"
    doc_ids = list(doc_ids or [])
    inline_citations = list(inline_citations or [])

    try:
        from angineer_core.agent_policy import build_attempts, format_route_note
        from angineer_core.agent_tools import MarkerAllocator
        from angineer_core.classifier import IntentClassifier
        from ai_inference.llm_client import get_llm_client

        # 1. 意图判断
        t0 = time.time()
        intent_result = _default_intent_result()
        try:
            sops = list(sop_loader.load_all() or []) if sop_loader is not None else []
            intent_result = IntentClassifier(sops).classify_intent(
                query, config_name=config_name, mode=mode
            )
        except Exception as exc:  # noqa: BLE001
            if getattr(exc, "fatal", False):
                raise
            logger.warning("意图分级失败，默认 L1: %s", exc)
        intent_seconds = round(time.time() - t0, 3)

        # 2. 策略展开 + 执行
        t1 = time.time()
        allocator = MarkerAllocator()
        attempts = build_attempts(
            intent_result=intent_result,
            scene="docs",
            library_id=library_id,
            doc_ids=doc_ids,
            load_nodes=lambda: _load_doc_nodes(library_id, doc_ids),
            llm_factory=get_llm_client,
            config_name=config_name,
            mode=mode,
            sop_loader=sop_loader,
            marker_allocator=allocator,
        )
        config = AgentLoopConfig(
            llm=get_llm_client(),
            tools=[],
            system_prompt="",
            max_turns=1,
            attempts=attempts,
            route_note=format_route_note(intent_result),
        )
        events: list = []
        messages: List[AgentMessage] = [AgentMessage(role="user", content=query)]
        added = run_agent_loop(messages, config, emit=events.append)
        loop_seconds = round(time.time() - t1, 3)

        run_end = next((e for e in reversed(events) if e.type == "run_end"), None)
        run_payload = run_end.payload if run_end else {}
        reason = str(run_payload.get("reason") or "completed")
        turns = int(run_payload.get("turns") or 0)
        notes = [str(n.get("detail") or "") for n in run_payload.get("notes") or []]

        # 3. 抽取答案 / 证据 / 引用 / SOP trace
        final_assistant = next(
            (m for m in reversed(added) if m.role == "assistant" and not m.tool_calls),
            None,
        )
        answer = final_assistant.content if final_assistant else ""

        tool_messages = [m for m in added if m.role == "tool"]
        retrieved_items: List[Dict[str, Any]] = []
        seen_ids = set()
        citations: List[Dict[str, Any]] = []
        seen_cites = set()
        sop_trace: List[Dict[str, Any]] = []
        for message in tool_messages:
            raw = message.meta or {}
            for item in raw.get("items") or []:
                if not isinstance(item, dict):
                    continue
                item_id = str(item.get("item_id") or "")
                if item_id and item_id in seen_ids:
                    continue
                if item_id:
                    seen_ids.add(item_id)
                retrieved_items.append(item)
            for citation in raw.get("citations") or []:
                if not isinstance(citation, dict):
                    continue
                cite_key = str(citation.get("target_id") or "") + str(citation.get("marker") or "")
                if cite_key and cite_key in seen_cites:
                    continue
                if cite_key:
                    seen_cites.add(cite_key)
                citations.append(citation)
            if message.name == "sop_execute" and isinstance(raw.get("sop_trace"), list):
                sop_trace.extend(raw["sop_trace"])

        strategy = f"policy_{intent_result.intent_level}_{intent_result.service_mode} (turns={turns}, reason={reason})"
        fallback_used = any("回退" in n or "进入下一段" in n for n in notes)
        stage_timings = {"intent": intent_seconds, "agent_loop": loop_seconds}
        retrieval_debug = {
            "agent": {
                "turns": turns,
                "tool_calls": len(tool_messages),
                "reason": reason,
                "strategy": "policy_agent",
            },
            "agent_events": [event.model_dump(mode="json") for event in events],
        }
        route_debug = {
            "route_kind": "policy",
            "primary_level": intent_result.primary_level or intent_result.intent_level,
            "execution_plan": list(intent_result.execution_plan or [intent_result.service_mode]),
            "reason": intent_result.reason or "",
            "attempted_paths": [],
            "final_path": None,
            "fallback_reason": None,
        }
        flow_debug = {
            "flow_type": "policy_agent",
            "summary": f"策略化路径完成（{reason}）",
        }

        if stage_callback is not None:
            try:
                stage_callback({
                    "stage": "intent",
                    "stage_timings": stage_timings,
                    "intent": _intent_to_dict(intent_result),
                    "answer": answer,
                    "citations": citations,
                    "retrieved_items": retrieved_items,
                })
            except Exception as exc:  # noqa: BLE001
                logger.warning("stage_callback 异常（已忽略）: %s", exc)

        from angineer_core.prompts import versions as _prompt_versions

        return {
            "query_id": query_id,
            "session_key": "",
            "intent": _intent_to_dict(intent_result),
            "answer": answer or "",
            "citations": citations,
            "retrieved_items": retrieved_items,
            "sql": None,
            "fallback_used": fallback_used,
            "latency_ms": int((time.time() - started_at) * 1000),
            "strategy": strategy,
            "system_prompt": "",
            "retrieval_debug": retrieval_debug,
            "runtime_flags": [],
            "route_debug": route_debug,
            "flow_debug": flow_debug,
            "stage_timings": stage_timings,
            "prompt_versions": dict(_prompt_versions()),
            "inline_citation_count": len(inline_citations),
            "sop_trace": sop_trace,
            "gap_analysis": None,
            "confidence_breakdown": None,
        }
    except Exception as exc:  # noqa: BLE001
        logger.error("策略化查询失败: %s", exc, exc_info=True)
        return {"error": f"评测查询失败: {exc}"}
