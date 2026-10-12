"""chat-api 薄壳的会话池与策略工厂（最小版）。

与 aichat-api `chat_agent.py` 同源而**去运营面耦合**（2026-10-12 独立壳交付）：

- 无 owner 身份隔离位（自部署单租户场景，网络边界由调用方负责）；
- 无聊天历史落库（chat-history 是可选面；多轮连续性靠进程内 ``AgentSession.history``）；
- 节点清单走 ``policy_query._load_doc_nodes``（HTTP 优先→检索服务；未配 URL 且未装
  docs-core 时按空清单降级并留痕，与内部服务同语义）；
- 策略展开仍走 ``angineer_core.agent_policy.build_attempts``（内核单一实现在包内）。
"""
import logging
import threading
import time
from typing import Any, Callable, Dict, List, Optional

from angineer_core.agent_loop import AgentLoopConfig
from angineer_core.agent_session import AgentSession
from angineer_core.base_contracts import ScopeContext

logger = logging.getLogger(__name__)

_POOL_MAX_SIZE = 200
_TTL_SECONDS = 3600 * 2

_POOL: Dict[str, AgentSession] = {}
_LAST_ACTIVE: Dict[str, float] = {}
_POOL_LOCK = threading.RLock()


def is_multi_scope(library_ids: Optional[List[str]]) -> bool:
    """多库集合判定唯一谓词（len>1 才算多库，单元素按旧单库语义处理）。"""
    return len(list(library_ids or [])) > 1


def load_nodes_for(library_ids: List[str], doc_ids: Optional[List[str]]) -> list:
    """加载 scope 内 document 节点清单（多库逐库合并、按 id 去重）。

    HTTP 优先（ANGINEER_DOCS_API_URL → /api/knowledge/internal/doc-nodes）；
    未配置时按引擎降级语义（警告 + 空清单）返回，绝不抛错。
    """
    from angineer_core.policy_query import _load_doc_nodes

    ids = list(doc_ids or [])
    libs = [lib for lib in (library_ids or []) if lib]
    if not is_multi_scope(libs):
        return _load_doc_nodes(libs[0] if libs else "default", ids)
    seen: set = set()
    merged: list = []
    for lib in libs:
        for node in _load_doc_nodes(lib, ids):
            node_id = str(getattr(node, "id", "") or "")
            if node_id and node_id not in seen:
                seen.add(node_id)
                merged.append(node)
    return merged


def make_config_factory(
    scene: str,
    scope: ScopeContext,
    intent_result: Any,
    query: Optional[str] = None,
    route_debug: Any = None,
    marker_allocator: Any = None,
) -> Callable[[], AgentLoopConfig]:
    """按意图分级返回策略化 AgentLoopConfig 工厂（与内部服务同构，去 SOP/运营面）。

    scope 为唯一门牌号来源；``marker_allocator`` 预检与主路共用同一实例
    （route_parallel 关闭或无预检时 None → 工厂自建，同内部服务语义）。
    """

    def factory() -> AgentLoopConfig:
        from ai_inference.llm_client import get_llm_client
        from angineer_core.agent_policy import build_attempts, format_route_note
        from angineer_core.agent_tools import MarkerAllocator

        allocator = marker_allocator or MarkerAllocator()
        multi = is_multi_scope(scope.library_ids)
        attempts = build_attempts(
            intent_result=intent_result,
            scene=scene,
            library_id=scope.library_id,
            library_ids=list(scope.library_ids) if multi else None,
            doc_ids=list(scope.doc_ids),
            load_nodes=lambda: load_nodes_for(scope.library_ids, scope.doc_ids),
            llm_factory=get_llm_client,
            config_name=None,
            mode="instruct",
            sop_loader=None,  # SOP 发布面为可选注入：壳不依赖 sop-api
            query=query,
            marker_allocator=allocator,
        )
        return AgentLoopConfig(
            llm=get_llm_client(),
            tools=[],
            system_prompt="",
            max_turns=1,  # 仅无 attempts 时兜底；有 attempts 时预算由各段 config 决定
            attempts=attempts,
            route_note=format_route_note(intent_result),
            route_note_ms=getattr(route_debug, "classify_ms", None),
        )

    return factory


def _default_factory(scene: str) -> Callable[[], AgentLoopConfig]:
    """池内新会话的默认工厂（无单次意图时按 scene 路由；请求级工厂每次 run 覆盖）。"""
    scope = ScopeContext(library_id="default", doc_ids=[])
    return make_config_factory(scene, scope=scope, intent_result=None)


def _evict_expired() -> None:
    now = time.time()
    expired = [k for k, v in _LAST_ACTIVE.items() if now - v > _TTL_SECONDS]
    for k in expired:
        _POOL.pop(k, None)
        _LAST_ACTIVE.pop(k, None)
    if len(_POOL) >= _POOL_MAX_SIZE:
        sorted_keys = sorted(_LAST_ACTIVE, key=lambda k: _LAST_ACTIVE[k])
        for k in sorted_keys[: max(1, len(sorted_keys) // 4)]:
            _POOL.pop(k, None)
            _LAST_ACTIVE.pop(k, None)


def _pool_key(scene: str, session_id: Optional[str]) -> str:
    return f"{scene or 'qa'}:{session_id or 'default'}"


def get_agent_session(scene: str, session_id: Optional[str]) -> AgentSession:
    """按 ``scene:session_id`` 获取或创建 AgentSession（复用 history/steer）。"""
    key = _pool_key(scene, session_id)
    with _POOL_LOCK:
        now = time.time()
        _evict_expired()
        session = _POOL.get(key)
        if session is None:
            session = AgentSession(_default_factory(scene or "qa"))
            _POOL[key] = session
        _LAST_ACTIVE[key] = now
        return session


def _classify_intent_blocking(query: str, config_name: Optional[str], mode: str):
    """同步意图分类（LLM 调用），必须在 worker 线程执行。

    壳不注入 SOP 清单（``sops=[]``）：SOP 命中提示为可选面——
    未挂 sop-api 时分类照常，仅少一类候选提示。
    """
    from angineer_core.classifier import IntentClassifier

    return IntentClassifier([]).classify_intent(query, config_name=config_name, mode=mode)
