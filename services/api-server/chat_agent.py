"""P7 API 层统一：agent 会话池与 SSE 帧映射。

按 ``scene:session_id`` 复用 AgentSession（qa/complex 档）；
``/api/chat`` 兼容帧映射与 ``/api/chat/agent`` 完整 AgentEvent 帧。
"""
import json
import logging
import threading
import time
from typing import Any, Dict, List, Optional

from angineer_core.agent_events import AgentEvent
from angineer_core.agent_loop import AgentLoopConfig
from angineer_core.agent_session import AgentSession

logger = logging.getLogger(__name__)

_POOL_MAX_SIZE = 200
_TTL_SECONDS = 3600 * 2

_AGENT_SESSION_POOL: Dict[str, AgentSession] = {}
_AGENT_SESSION_LAST_ACTIVE: Dict[str, float] = {}
_POOL_LOCK = threading.RLock()

_INTENT_TYPE_LABELS = {
    "casual_chat": "闲聊",
    "concept_resolution": "概念/定义问答",
    "locate_navigation": "定位问答",
    "clause_application": "条款应用",
    "standard_lookup": "规范查表",
    "clause_then_calculation": "条款+计算",
    "standard_calculation": "规范计算",
    "complex_task": "复杂综合任务",
}


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


def _format_route_note(intent_result) -> Optional[str]:
    """把意图分级结果转成思考过程第一条说明。"""
    if intent_result is None:
        return None
    level = str(getattr(intent_result, "intent_level", "") or "")
    intent_type = str(getattr(intent_result, "intent_type", "") or "")
    service_mode = str(getattr(intent_result, "service_mode", "") or "")
    reason = str(getattr(intent_result, "reason", "") or "").strip()
    type_label = _INTENT_TYPE_LABELS.get(intent_type, intent_type or "未知类型")
    level_label = {
        "L0": "闲聊直答",
        "L1": "正文问答",
        "L2": "条款/表格定位",
        "L3": "规范计算",
        "L4": "复杂综合任务",
    }.get(level, level or "")
    note = f"意图判断：{level_label}（{level}）→ 策略 {service_mode}"
    if reason:
        note += f"（{reason}）"
    return note


def make_config_factory(
    scene: str,
    library_id: str,
    doc_ids: Optional[List[str]],
    sop_loader: Any = None,
    intent_result: Any = None,
):
    """按 scene + 意图分级返回 qa/complex 档的 AgentLoopConfig 工厂。

    L3/L4（规范计算/复杂综合）与 sop 类 scene 走 complex 档（带 SOP/计算工具），
    其余走 qa 档（检索三件套）。
    """
    use_complex = bool(
        scene in ("complex", "sop", "sops")
        or (intent_result is not None and str(getattr(intent_result, "intent_level", "")) in ("L3", "L4"))
        or (intent_result is not None and str(getattr(intent_result, "service_mode", "")) in ("standard_sop", "dynamic_orchestration"))
    )
    route_note = _format_route_note(intent_result)

    def factory():
        from ai_inference.llm_client import get_llm_client
        from angineer_core.agent_configs import build_complex_config, build_qa_config

        nodes = _load_doc_nodes(library_id, doc_ids)
        llm = get_llm_client()
        if use_complex:
            return build_complex_config(
                llm=llm,
                doc_nodes=nodes,
                library_id=library_id,
                doc_ids=list(doc_ids or []),
                max_turns=8,
                sops=list(sop_loader.load_all() or []) if sop_loader is not None else None,
                sop_loader=sop_loader,
                route_note=route_note,
            )
        return build_qa_config(
            llm=llm,
            doc_nodes=nodes,
            library_id=library_id,
            doc_ids=list(doc_ids or []),
            max_turns=3,
            route_note=route_note,
        )

    return factory


def make_policy_config_factory(
    scene: str,
    library_id: str,
    doc_ids: Optional[List[str]],
    intent_result: Any,
    sop_loader: Any = None,
):
    """按意图分级返回策略化 AgentLoopConfig 工厂（attempts 由 agent_policy 展开）。"""

    def factory() -> AgentLoopConfig:
        from ai_inference.llm_client import get_llm_client
        from angineer_core.agent_loop import AgentLoopConfig
        from angineer_core.agent_policy import build_attempts, format_route_note
        from angineer_core.agent_tools import MarkerAllocator

        allocator = MarkerAllocator()
        attempts = build_attempts(
            intent_result=intent_result,
            scene=scene,
            library_id=library_id,
            doc_ids=list(doc_ids or []),
            load_nodes=lambda: _load_doc_nodes(library_id, doc_ids),
            llm_factory=get_llm_client,
            config_name=None,
            mode="instruct",
            sop_loader=sop_loader,
            marker_allocator=allocator,
        )
        return AgentLoopConfig(
            llm=get_llm_client(),
            tools=[],
            system_prompt="",
            max_turns=1,  # 仅无 attempts 时兜底；有 attempts 时预算由各段 config 决定
            attempts=attempts,
            route_note=format_route_note(intent_result),
        )

    return factory


def _make_config_factory(scene: str, library_id: str, doc_ids: Optional[List[str]]):
    """兼容别名：池化会话默认工厂（不携带单次意图）。"""
    return make_config_factory(scene, library_id, doc_ids)


def _evict_expired() -> None:
    now = time.time()
    expired = [k for k, v in _AGENT_SESSION_LAST_ACTIVE.items() if now - v > _TTL_SECONDS]
    for k in expired:
        _AGENT_SESSION_POOL.pop(k, None)
        _AGENT_SESSION_LAST_ACTIVE.pop(k, None)
    if len(_AGENT_SESSION_POOL) >= _POOL_MAX_SIZE:
        sorted_keys = sorted(_AGENT_SESSION_LAST_ACTIVE, key=lambda k: _AGENT_SESSION_LAST_ACTIVE[k])
        for k in sorted_keys[: max(1, len(sorted_keys) // 4)]:
            _AGENT_SESSION_POOL.pop(k, None)
            _AGENT_SESSION_LAST_ACTIVE.pop(k, None)


def get_agent_session(
    scene: str,
    session_id: Optional[str],
    library_id: str = "default",
    doc_ids: Optional[List[str]] = None,
) -> AgentSession:
    """按 ``scene:session_id`` 获取或创建 AgentSession（复用 history/steer）。"""
    key = f"{scene}:{session_id or 'default'}"
    with _POOL_LOCK:
        now = time.time()
        _evict_expired()
        session = _AGENT_SESSION_POOL.get(key)
        if session is None:
            session = AgentSession(_make_config_factory(scene, library_id, doc_ids or []))
            _AGENT_SESSION_POOL[key] = session
        _AGENT_SESSION_LAST_ACTIVE[key] = now
        return session


def create_standalone_session(
    scene: str = "qa",
    library_id: str = "default",
    doc_ids: Optional[List[str]] = None,
) -> AgentSession:
    """创建独立 AgentSession（不进入池），供 /api/chat 每次请求使用。"""
    return AgentSession(_make_config_factory(scene, library_id, doc_ids or []))


def find_session_by_run_id(run_id: str) -> Optional[AgentSession]:
    """按 active run_id 查找会话，供 steer 接口使用。"""
    with _POOL_LOCK:
        for session in _AGENT_SESSION_POOL.values():
            if session.active_run_id == run_id:
                return session
    return None


def map_event_to_chat_sse(event: AgentEvent) -> Optional[str]:
    """/api/chat 兼容帧映射：对外帧格式不变；返回 None 表示忽略该事件。"""
    if event.type == "message_delta":
        delta = str((event.payload or {}).get("delta") or "")
        if delta:
            return json.dumps({"type": "chunk", "content": delta}, ensure_ascii=False)
        return None
    if event.type == "run_end":
        usage = (event.payload or {}).get("usage") or {}
        return json.dumps(
            {
                "type": "end",
                "usage": {
                    "promptTokens": int(usage.get("prompt_tokens") or 0),
                    "completionTokens": int(usage.get("completion_tokens") or 0),
                },
            },
            ensure_ascii=False,
        )
    if event.type == "error":
        return json.dumps(
            {
                "type": "error",
                "error": str((event.payload or {}).get("message") or "未知错误"),
            },
            ensure_ascii=False,
        )
    return None


def map_event_to_agent_frame(event: AgentEvent) -> str:
    """/api/chat/agent 帧：AgentEvent 原样 JSON。"""
    return event.model_dump_json()
