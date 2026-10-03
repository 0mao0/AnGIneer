"""Router 前置（阶段 1b）：请求先过 route_request 拿派工单 RouteDecision，再进执行。

硬规则：意图可以错，scope 不能漏；分类失败不再 intent_result=None 静默，
而是 RouteDecision.fallback=True + route_debug.fallback=true，由 SSE 首帧透出。
"""
import logging
import os
import threading
from typing import Any, Awaitable, Callable, List, Optional

from angineer_core.agent_events import AgentEvent
from angineer_core.base_contracts import RouteDebug, RouteDecision, ScopeContext

logger = logging.getLogger(__name__)

ROUTE_PRE_ENV = "ANGINEER_ROUTE_PRE"

ClassifyFn = Callable[[str, Optional[str], str], Awaitable[Any]]


def route_pre_enabled() -> bool:
    """ANGINEER_ROUTE_PRE=false 时回退旧内联分类路径（无 route_debug 首帧）。"""
    return os.getenv(ROUTE_PRE_ENV, "true").strip().lower() in ("true", "1", "yes", "on")


ROUTE_PARALLEL_ENV = "ANGINEER_ROUTE_PARALLEL"


def route_parallel_enabled() -> bool:
    """ANGINEER_ROUTE_PARALLEL（默认开；设 0/false/off 关闭为纯串行）：

    分类与首轮检索并行——请求进来即赌博式预检 knowledge_search（按 scene 默认猜 L1），
    分类返回后 L1 命中由 agent_loop 首轮注入经 _run_knowledge_search 的 memo 单发复用，
    分类延迟不再阻塞检索段。分类结果仍一票决定走哪段，路由正确性零风险；
    猜错（L2/L3/L4/闲聊）代价 = 一次 ~0.5s 的无效检索。

    注：本 docstring 原写"默认关、生产实测后再定"是引入期状态；默认值早已翻为 true
    （生产 .env 显式 =1，本地不设即默认开），2026-09-30 校正——曾据此误判"本地是串行"。
    """
    return os.getenv(ROUTE_PARALLEL_ENV, "true").strip().lower() in ("true", "1", "yes", "on")


def fire_speculative_first_search(query: str, library_id: Optional[str], doc_ids: Optional[List[str]],
                              load_nodes: Optional[Callable[[], list]] = None,
                              has_history: bool = True,
                              marker_allocator: Optional[Any] = None):
    """赌博式预检：乐观发起 L1 首轮检索（fire-and-forget 独立 daemon 线程）。

    参数必须与 agent_policy._l1_attempt → build_qa_config → RetrieverAdapter.knowledge_search
    的有效参数逐项一致（top_k=20 / task_type=content_qa / rerank=True / config_name=None /
    mode="instruct" / doc_nodes=同源 _load_doc_nodes 结果），否则 agent_tools 的检索 memo
    键对不齐，预检白做甚至污染 citations（doc_title_map 缺失）。拿不到 load_nodes 宁可不预检。

    marker_allocator（F3 共享 allocator）：主流程创建、预检与主路共用同一实例——预检的
    引用号段即主路号段，复用成品不重分配；失败/放弃由 memo 按快照回收（施工单变更 A）。

    跳过条件：短问（≤ANGINEER_INJECT_FOLLOWUP_CHARS）**且**有上文——§8.6 只在此组合下
    改写检索词，memo 键必不命中；首问短句（无上文）不改写，预检照常受益。
    """
    from angineer_core.agent_tools import route_parallel_enabled as _memo_enabled, RetrieverAdapter

    if not _memo_enabled() or load_nodes is None:
        return None
    q = (query or "").strip()
    if not q:
        return None
    try:
        threshold = int(os.getenv("ANGINEER_INJECT_FOLLOWUP_CHARS", "15"))
    except ValueError:
        threshold = 15
    if len(q) <= threshold and has_history:
        return None  # 有上文的短问才会被 §8.6 改写检索词；首问短句不改写，照常预检

    # 表题必输局不下注（req-table-retrieval-latency §11）：预检 memo 只服务 L1 路
    # （knowledge_search+content_qa+原查询），L2/L3 表题走 table_search（无 memo），
    # 预检=白扫全库表格还与真实检索 GIL 互拖（实测 table= 独跑 1.3~2.9s → 并发 5.1s）。
    # ANGINEER_SPECULATIVE_SKIP_TABLE=0 回退旧行为（照发预检）。
    _skip_table = (os.getenv("ANGINEER_SPECULATIVE_SKIP_TABLE", "1") or "").strip().lower()
    if _skip_table not in ("0", "false", "off", "no"):
        from docs_core.step09_query.agent_port import looks_like_table_query

        if looks_like_table_query(q):
            logger.info("赌博式预检跳过（表题必输局不下注）: %r", q[:40])
            return None

    try:
        doc_nodes = load_nodes()
    except Exception:  # noqa: BLE001
        return None

    def _run():
        try:
            tool = RetrieverAdapter.knowledge_search(
                library_id=library_id or "default",
                doc_ids=list(doc_ids or []),
                doc_nodes=doc_nodes,
                top_k=20,
                task_type="content_qa",
                filters=None,
                rerank=True,
                config_name=None,
                mode="instruct",
                marker_allocator=marker_allocator,
            )
            tool.handler(query=q, _from_speculative=True)
        except Exception:  # noqa: BLE001
            logger.debug("赌博式预检失败（忽略）", exc_info=True)

    thread = threading.Thread(target=_run, daemon=True, name="route-speculative")
    thread.start()
    return thread


async def route_request(
    *,
    query: str,
    scene: str,
    library_id: Optional[str],
    doc_ids: Optional[List[str]],
    config_name: Optional[str],
    mode: str,
    classify: ClassifyFn,
) -> RouteDecision:
    """生成本次请求的派工单；分类失败 -> fallback 决策（scope 仍显式保留）。"""
    scope = ScopeContext(library_id=library_id or "default", doc_ids=list(doc_ids or []))
    import time as _time

    _t0 = _time.perf_counter()
    intent_result = await classify(query, config_name, mode)
    classify_ms = int((_time.perf_counter() - _t0) * 1000)
    if intent_result is None:
        return RouteDecision(
            scene=scene,
            scope=scope,
            fallback=True,
            route_debug=RouteDebug(fallback=True, reason="classifier_error", classify_ms=classify_ms),
        )
    return RouteDecision(
        intent_result=intent_result,
        scene=scene,
        scope=scope,
        attempts=[str(m) for m in (intent_result.execution_plan or [])],
        route_debug=RouteDebug(
            level=intent_result.primary_level or intent_result.intent_level,
            service_mode=intent_result.service_mode,
            reason=intent_result.reason,
            classify_ms=classify_ms,
        ),
    )


def decision_intent_result(decision: RouteDecision):
    """fallback 决策沿用旧降级路径（intent_result=None -> 默认策略），行为不变。"""
    return None if decision.fallback else decision.intent_result


def route_debug_event(decision: RouteDecision) -> AgentEvent:
    """SSE 首帧：级别 / service_mode / confidence / reason / fallback + scope。"""
    return AgentEvent(
        type="route_debug",
        run_id="",
        payload={
            "route_debug": decision.route_debug.model_dump(),
            "scope": decision.scope.model_dump(),
            "attempts": list(decision.attempts),
        },
    )


def fallback_note_event() -> AgentEvent:
    """分类异常时前端可感知的说明帧。"""
    return AgentEvent(type="note", run_id="", payload={"detail": "路由失败，按默认策略走"})
