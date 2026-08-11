"""P7 API 层统一：agent 会话池与 AgentEvent SSE 帧序列化。

按 ``scene:session_id`` 复用 AgentSession；``/api/chat/agent`` 直接输出
完整 AgentEvent 帧（旧 ``/api/chat`` 兼容帧映射已随旧端点删除）。
"""
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
    """兼容别名：池化会话默认工厂（policy 版，无单次意图时按 scene 路由）。"""
    return make_policy_config_factory(scene, library_id, doc_ids, intent_result=None)


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


def find_session_by_run_id(run_id: str) -> Optional[AgentSession]:
    """按 active run_id 查找会话，供 steer 接口使用。"""
    with _POOL_LOCK:
        for session in _AGENT_SESSION_POOL.values():
            if session.active_run_id == run_id:
                return session
    return None


def map_event_to_agent_frame(event: AgentEvent) -> str:
    """/api/chat/agent 帧：AgentEvent 原样 JSON。"""
    return event.model_dump_json()
