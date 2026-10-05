"""P7 API 层统一：agent 会话池与 AgentEvent SSE 帧序列化。

按 ``owner:scene:session_id`` 复用 AgentSession（阶段三 D6 去 scope_hash：scope 每轮经
config_factory 新鲜注入，会话可跨集合续接；owner 为身份隔离位）；
``/api/chat/agent`` 直接输出完整 AgentEvent 帧。
"""
import logging
import threading
import time
from typing import Any, Callable, Dict, List, Optional

from angineer_core.agent_events import AgentEvent
from angineer_core.agent_loop import AgentLoopConfig
from angineer_core.agent_session import AgentSession
from angineer_core.base_contracts import ScopeContext

logger = logging.getLogger(__name__)

_POOL_MAX_SIZE = 200
_TTL_SECONDS = 3600 * 2

_AGENT_SESSION_POOL: Dict[str, AgentSession] = {}
_AGENT_SESSION_LAST_ACTIVE: Dict[str, float] = {}
_POOL_LOCK = threading.RLock()

def _load_doc_nodes(library_id: str, doc_ids: Optional[List[str]]) -> list:
    """加载知识库 document 节点；失败时返回空列表（检索工具降级）。

    空列表会让 dense/sparse 直接跳过（`DenseRetriever.retrieve` 首行 `if not doc_nodes: return []`），
    检索恒为 0 条 → 边界规则判定「无证据」→ 模型输出拒答。这条链路此前**完全静默**
    （2026-09-11 生产与开发同时踩到：payload 干净、库里 26 篇文档，界面却说没有证据），
    所以空结果必须留痕：见下方 warning。
    """
    try:
        from docs_core.docs_service import get_docs_service

        kp = get_docs_service()
        all_nodes = list(kp.list_nodes(library_id))
        nodes = [n for n in all_nodes if getattr(n, "type", "") == "document"]
        if doc_ids:
            ids = set(str(doc_id) for doc_id in doc_ids if str(doc_id).strip())
            scoped = [n for n in nodes if getattr(n, "id", "") in ids]
            if not scoped:
                logger.warning(
                    "引用范围 doc_ids=%s 在知识库 %s 中匹配不到文档（库内 %d 篇），检索将为空",
                    sorted(ids), library_id, len(nodes),
                )
            nodes = scoped
        if not nodes:
            logger.warning(
                "知识库 %s 的 document 节点为空（该库节点总数 %d，进程内已加载库数 %d）："
                "检索工具将拿到空范围，回答会退化为「没有检索到足够证据」",
                library_id, len(all_nodes), len(kp.list_libraries()),
            )
        return nodes
    except Exception as exc:  # noqa: BLE001
        logger.warning("加载知识库节点失败，agent 检索工具将无节点: %s", exc)
        return []


def is_multi_scope(library_ids: Optional[List[str]]) -> bool:
    """多库集合判定唯一谓词（阶段三）：len>1 才算多库，单元素按旧单库语义处理。

    节点加载分支（_load_doc_nodes_multi vs 单库路径）与预检集合上浮（route_pre B1
    同口径）共用此谓词——「集合仅多库时上浮」的规则只写一遍，防三拷贝漂移。
    """
    return len(list(library_ids or [])) > 1


def _load_doc_nodes_multi(library_ids: List[str], doc_ids: Optional[List[str]]) -> list:
    """多库节点加载（阶段三）：逐库加载合并，按节点 id 去重（每库内部沿用 _load_doc_nodes 的告警语义）。"""
    seen: set = set()
    nodes: list = []
    for lib in library_ids:
        for node in _load_doc_nodes(lib, doc_ids):
            node_id = str(getattr(node, "id", "") or "")
            if node_id and node_id not in seen:
                seen.add(node_id)
                nodes.append(node)
    return nodes


def make_policy_config_factory(
    scene: str,
    scope: ScopeContext,
    intent_result: Any,
    sop_loader: Any = None,
    route_debug: Any = None,
    marker_allocator: Any = None,
):
    """按意图分级返回策略化 AgentLoopConfig 工厂（attempts 由 agent_policy 展开）。

    scope 为唯一门牌号来源：library_id/doc_ids 一律取自 ScopeContext。
    route_debug：路由可观测投影（含 classify_ms）——「意图判断」便签带分类耗时用（2026-09-27）。
    marker_allocator（F3 共享 allocator）：预检与主路共用同一实例（施工单变更 A）；
    None 时工厂自建（route_parallel 关闭或无预检的请求，现行为）。
    """

    def factory() -> AgentLoopConfig:
        from ai_inference.llm_client import get_llm_client
        from angineer_core.agent_loop import AgentLoopConfig
        from angineer_core.agent_policy import build_attempts, format_route_note
        from angineer_core.agent_tools import MarkerAllocator

        allocator = marker_allocator or MarkerAllocator()
        # 阶段三：集合仅在真正多库时上浮（谓词 is_multi_scope）——单库保持 None，
        # 旧单库调用的检索结果 shape 逐位不变（agent_tools D8 口径，兼容铁律 1）
        multi = is_multi_scope(scope.library_ids)
        attempts = build_attempts(
            intent_result=intent_result,
            scene=scene,
            library_id=scope.library_id,
            library_ids=list(scope.library_ids) if multi else None,
            doc_ids=list(scope.doc_ids),
            load_nodes=lambda: (
                _load_doc_nodes_multi(scope.library_ids, scope.doc_ids)
                if multi
                else _load_doc_nodes(scope.library_id, scope.doc_ids)
            ),
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
            route_note_ms=getattr(route_debug, "classify_ms", None),
        )

    return factory


def _make_config_factory(
    scene: str,
    library_id: str,
    doc_ids: Optional[List[str]],
    library_ids: Optional[List[str]] = None,
):
    """池化会话默认工厂（policy 版，无单次意图时按 scene 路由）。

    阶段三：library_ids 非空时集合进 ScopeContext（首项=主库，validator 同步 library_id）；
    缺省时回退单库 [library_id]——旧调用构造出的字段值不变（兼容铁律 3）。
    """
    scope = ScopeContext(
        library_ids=list(library_ids or []) or [library_id or "default"],
        doc_ids=list(doc_ids or []),
    )
    return make_policy_config_factory(scene, scope=scope, intent_result=None)


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


def _session_pool_key(
    scene: str,
    session_id: Optional[str],
    library_id: str,
    doc_ids: Optional[List[str]],
    owner: str = "",
) -> str:
    """池化 key：owner:scene:session_id（阶段三 D6：去 scope_hash——scope 每轮经
    config_factory 新鲜注入，会话可跨集合续接；library_id/doc_ids 参数保留仅兼容旧调用）。

    owner（``u:<id>``/``k:<id>``/``ip:<hash>``，来自 chat_auth.resolve_pool_owner）是身份隔离位：
    session_id 由客户端生成（``chat-<毫秒时间戳>`` 形状可枚举），缺了它不同主体会命中同一份 history。
    """
    return f"{owner or '-'}:{scene}:{session_id or 'default'}"


def get_agent_session(
    scene: str,
    session_id: Optional[str],
    library_id: str = "default",
    doc_ids: Optional[List[str]] = None,
    owner: str = "",
    history_loader: Optional[Callable[[], List[Any]]] = None,
    library_ids: Optional[List[str]] = None,
) -> AgentSession:
    """按 ``owner:scene:session_id`` 获取或创建 AgentSession（复用 history/steer）。

    阶段三 D6：池 key 不含 scope——同 session_id 换勾选集合续接同一会话；
    本轮实际检索范围由请求级 make_policy_config_factory(scope=...) 新鲜注入，与池无关。

    ``history_loader`` 只在**池内新建 session** 时调用一次（D11：池命中时内存 history
    已是真相，重复回灌会双写双序）；由组装层注入 DB 历史回灌，失败仅告警不阻断。
    """
    key = _session_pool_key(scene, session_id, library_id, doc_ids, owner)
    with _POOL_LOCK:
        now = time.time()
        _evict_expired()
        session = _AGENT_SESSION_POOL.get(key)
        if session is None:
            session = AgentSession(_make_config_factory(
                scene, library_id, doc_ids or [], library_ids=library_ids,
            ))
            if history_loader is not None:
                try:
                    session.history.extend(history_loader())
                except Exception as exc:  # noqa: BLE001
                    logger.warning("聊天历史回灌失败（按空历史继续）: %s", exc)
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
