"""Agent 工具契约与适配层（P2.1，§6.3）。

循环层不直接修改外部工具包；通过 `AgentTool` 适配现有 BaseTool / 检索器 / 图谱。
外部工具注册表经 engtool_registry 端口消费（适配器内惰性 import）。
"""
import json
import logging
import os
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional

from angineer_core.base_contracts import Evidence

logger = logging.getLogger(__name__)


def _context_top_n() -> int:
    """rerank 后进 agent 上下文的条数（ANGINEER_CONTEXT_TOP_N，默认 15）。

    离线覆盖度量（38 道翻转题）：top10 金标要点覆盖 ~64%，top15 ~70%，top20 ~71%；
    v0.2.23 的 top10 截断被证实是答案漏要点的主因，改默认 15 并用 env 留调节口。
    """
    try:
        return max(1, int(os.getenv("ANGINEER_CONTEXT_TOP_N", "15") or "15"))
    except (ValueError, TypeError):
        return 15


def _evidence_cap_est() -> int:
    """证据体积软帽（est 口径 = chars//2；ANGINEER_EVIDENCE_CAP_EST 默认 80000，0=关帽）。

    挂装配公共末端、覆盖全部检索 kind。est 对中文低估约 2x（req-chat-history-bloat §3），
    软帽只求把病态包砍到量级正常，精确顶由 llm_client 的 400 钳制兜底（plan-evidence-admission §2）。
    """
    try:
        return max(0, int(os.environ.get("ANGINEER_EVIDENCE_CAP_EST", "80000") or "80000"))
    except (TypeError, ValueError):
        return 80_000


def _apply_evidence_cap(items: list) -> "tuple[list, int]":
    """软帽按 rank 装填：装得下整条留；装不下但剩余预算 ≥200 字符→截尾保留；
    剩余预算 <200 字符→整条丢（cap_dropped 计数，截尾不计）。返回 (保留条目, cap_dropped)。"""
    cap = _evidence_cap_est()
    if cap <= 0 or not items:
        return items, 0
    budget = cap * 2  # est→字符：est = chars//2
    kept: list = []
    dropped = 0
    for item in items:
        text = str(getattr(item, "text", "") or "")
        cost = len(text)
        if cost <= budget:
            kept.append(item)
            budget -= cost
            continue
        if budget >= 200:
            item.text = text[:budget]
            kept.append(item)
            budget = 0
            continue
        dropped += 1
    if dropped:
        logger.warning(
            "证据软帽截尾：cap_est=%d 丢弃 %d/%d 条（est=chars//2，400 钳制兜底）",
            cap, dropped, len(items),
        )
    return kept, dropped


def _cap_entity_objects(entities: list) -> "tuple[list, int]":
    """entity_search 纯实体结果不经 _assemble_search_result，软帽就地补装：
    按 rank 装填、超帽整条丢（实体短小、不做截尾）。返回 (保留实体, cap_dropped)。"""
    cap = _evidence_cap_est()
    if cap <= 0 or not entities:
        return entities, 0
    budget = cap * 2
    kept: list = []
    dropped = 0
    for entity in entities:
        cost = len(json.dumps(_serialize_model(entity), ensure_ascii=False, default=str))
        if cost <= budget:
            kept.append(entity)
            budget -= cost
        else:
            dropped += 1
    if dropped:
        logger.warning("实体软帽截断：cap_est=%d 丢弃 %d/%d 条", cap, dropped, len(entities))
    return kept, dropped


def _admission_mode() -> str:
    """上桌触发模式（ANGINEER_ADMISSION_MODE）：oversize（默认）| all | off（逃生口）。"""
    value = os.environ.get("ANGINEER_ADMISSION_MODE", "oversize").strip().lower()
    return value if value in ("off", "all", "oversize") else "oversize"


def _maybe_admit_evidence(query: str, items: list) -> "tuple[list, Optional[Dict[str, Any]]]":
    """证据上桌（LLM 定员出 listA）：仅 knowledge_search 文本条目、rerank 截 15 后调用。

    触发判定读**帽前 est**（原始 top15 体积，plan-evidence-admission §2 口径）；
    oversize=仅 est>ANGINEER_ADMISSION_TRIGGER_EST 的病态包走上桌；
    all=每题都过判官（prompt 经济性：实测判 1 条目仅剩 ~17%，可答题 prompt 减 60%+；
    代价 +1 判官调用/题，答质过闸前默认仍 oversize）。
    判官任何异常 → fail-open 全量放行（fallback=True，计数置 None），永不过滤层打死回答。
    """
    mode = _admission_mode()
    if mode == "off" or not items:
        return items, None
    pre_cap_est = sum(len(str(getattr(item, "text", "") or "")) for item in items) // 2
    if mode == "oversize":
        try:
            trigger = int(os.environ.get("ANGINEER_ADMISSION_TRIGGER_EST", "90000") or "90000")
        except (TypeError, ValueError):
            trigger = 90_000
        if pre_cap_est <= trigger:
            return items, None
    from angineer_core.retrieval_pipeline import admit_evidence

    try:
        return admit_evidence(query, items)
    except Exception as exc:  # noqa: BLE001 fail-open：判官接线层异常也不许吞掉证据
        logger.warning("证据上桌判官接线异常（fail-open 全量放行）: %s", exc)
        return items, {
            "kept": None, "dropped": None, "quarreled": None, "exempted": None,
            "fallback": True,
            "judge_config": os.environ.get("ANGINEER_ADMISSION_LLM_CONFIG", "").strip() or None,
            "judge_ms": None,
        }


def _evidence_grade_enabled() -> bool:
    """证据相关性标注开关（拒答根因方案①）：默认开；关时同时建议回退
    ANGINEER_QA_PROMPT_VERSION=v10（V11 规则 17 引用该标签）。"""
    return os.environ.get("ANGINEER_EVIDENCE_GRADE", "1").strip().lower() not in ("0", "false", "off")


def _relevance_label(item: Any) -> str:
    """证据相关性标签「【相关性 档 分】」：只认 rerank 分（0-1）；
    无 rerank 分返回空串——融合分数未校准，不拿来冒充相关性。"""
    raw_score = getattr(item, "rerank_score", None)
    if raw_score is None:
        return ""
    try:
        score = float(raw_score)
    except (TypeError, ValueError):
        return ""
    try:
        low = float(os.environ.get("ANGINEER_EVIDENCE_GRADE_LOW", "0.25"))
        high = float(os.environ.get("ANGINEER_EVIDENCE_GRADE_HIGH", "0.6"))
    except (TypeError, ValueError):
        low, high = 0.25, 0.6
    grade = "低" if score < low else ("高" if score >= high else "中")
    return f"【相关性 {grade} {score:.2f}】"


def _normalize_query(query: str) -> str:
    """条款号归一化走端口（docs-core 适配器）；未注册时原样返回（命中率优化，非正确性依赖）。"""
    from angineer_core import ports

    normalizer = ports.get_query_normalizer()
    if normalizer is None:
        logger.warning("normalize_query 端口未注册（组装层应注入 docs-core 适配器），跳过条款号归一化")
        return query
    return normalizer(query)


def _get_engtool_registry() -> Any:
    """外部工具注册表走端口（惰性 import 在适配器内）；未注册返回 None。"""
    from angineer_core import ports

    registry_fn = ports.get_engtool_registry()
    if registry_fn is None:
        return None
    return registry_fn()


@dataclass
class AgentTool:
    """循环层工具。"""

    name: str
    description: str  # 给模型看的中文描述
    parameters_schema: Dict[str, Any]  # JSON Schema，进 prompt / 校验
    handler: Callable[..., Dict[str, Any]]  # 实际执行体
    read_only: bool = False  # 检索类 True；权限与审计用
    execution_mode: str = "parallel"  # parallel | sequential
    timeout_s: int = 120  # 覆盖默认超时

    def to_schema_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "parameters": self.parameters_schema,
        }


@dataclass
class ToolResult:
    """工具执行结果。"""

    call_id: str
    name: str
    content: str  # 喂回模型的文本（JSON 序列化）
    is_error: bool = False
    terminate: bool = False  # P3 举旗：整批全票才提前停
    raw: Dict[str, Any] = field(default_factory=dict)  # citations 等，进 meta 不进 content


def _default_schema() -> Dict[str, Any]:
    return {"type": "object", "properties": {}}


class EngtoolAdapter:
    """包装外部工具注册表（BaseTool）中的工具。"""

    @staticmethod
    def from_registry(
        name: str,
        description: Optional[str] = None,
        parameters_schema: Optional[Dict[str, Any]] = None,
        *,
        config_name: Optional[str] = None,
        mode: Optional[str] = None,
        read_only: bool = False,
        execution_mode: str = "parallel",
        timeout_s: int = 120,
    ) -> AgentTool:
        def handler(**kwargs: Any) -> Dict[str, Any]:
            registry = _get_engtool_registry()
            if registry is None:
                raise LookupError("engtool_registry 端口未注册（组装层应注入适配器）")
            tool = registry.get_tool(name)
            if tool is None:
                raise LookupError(f"Tool not found: {name}")
            run_kwargs = dict(kwargs)
            if config_name:
                run_kwargs["config_name"] = config_name
            if mode:
                run_kwargs["mode"] = mode
            result = tool.run(**run_kwargs)
            if result is None:
                result = {}
            if not isinstance(result, dict):
                result = {"result": result}
            return result

        return AgentTool(
            name=name,
            description=description or name,
            parameters_schema=parameters_schema or _default_schema(),
            handler=handler,
            read_only=read_only,
            execution_mode=execution_mode,
            timeout_s=timeout_s,
        )


def _serialize_model(value: Any) -> Dict[str, Any]:
    if hasattr(value, "model_dump"):
        return value.model_dump(mode="json")
    if hasattr(value, "__dataclass_fields__"):
        return {
            key: _serialize_value(getattr(value, key))
            for key in value.__dataclass_fields__
        }
    return dict(value or {})


def _serialize_value(value: Any) -> Any:
    if hasattr(value, "model_dump"):
        return value.model_dump(mode="json")
    if hasattr(value, "__dataclass_fields__"):
        return {key: _serialize_value(getattr(value, key)) for key in value.__dataclass_fields__}
    if isinstance(value, (list, tuple)):
        return [_serialize_value(item) for item in value]
    if isinstance(value, dict):
        return {str(key): _serialize_value(val) for key, val in value.items()}
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return str(value)


class MarkerAllocator:
    """run 级引用标记分配器：每个工具前缀全局递增。

    线程安全（F3 共享 allocator：预检线程与主路线程共用同一实例）；mark/rollback
    服务于预检失败/放弃时的孤儿号段回收——回收只回退不前进，防踩掉主路新号段。
    """

    def __init__(self) -> None:
        self._counters: Dict[str, int] = {}
        self._lock = threading.Lock()

    def next(self, prefix: str) -> str:
        with self._lock:
            n = self._counters.get(prefix, 0) + 1
            self._counters[prefix] = n
        return f"{prefix}{n}"

    def mark(self) -> Dict[str, int]:
        """取当前计数快照（预检起飞前调用，失败/放弃时按它回收）。"""
        with self._lock:
            return dict(self._counters)

    def rollback(self, mark: Dict[str, int]) -> None:
        """回收到快照水位：快照里没有的前缀一律归零（预检新建号段整体回收）；
        只回退、不前进（绝不放大别人的计数）。"""
        with self._lock:
            for prefix in list(self._counters.keys()):
                target = mark.get(prefix, 0)
                if target <= self._counters[prefix]:
                    self._counters[prefix] = target


def _assign_cites(items: list, allocator: MarkerAllocator, prefix: str) -> None:
    for item in items:
        metadata = getattr(item, "metadata", None)
        if metadata is not None:
            metadata["cite"] = allocator.next(prefix)


def _keep_per_doc_blocks(items: list, *, total_cap: int = 30) -> list:
    """检索块去重 + 总量上限：完全相同的块只保留一次，总块数 cap，保持原排序。

    不限制单文档块数：gold 文档多块命中时证据完整性优先，
    （早期按每 doc 3 块截断的版本实测砍掉关键块导致拒答，已回退）。
    """
    kept: List[Any] = []
    seen_ids: set = set()
    for item in items:
        item_id = str(getattr(item, "item_id", "") or "")
        if item_id and item_id in seen_ids:
            continue
        if item_id:
            seen_ids.add(item_id)
        kept.append(item)
        if len(kept) >= total_cap:
            break
    return kept


def _items_to_evidences(items: list, *, kind: str, source: str, library_id: str) -> List[Dict[str, Any]]:
    """RetrievedItem 列表 → Evidence 序列化 dict（统一证据模型；items 字段保留做展示兼容）。"""
    evidences: List[Dict[str, Any]] = []
    for item in items:
        metadata = getattr(item, "metadata", None) or {}
        # 阶段三 P0（评审 P0-1）：多库扇出下逐图标源——item 自带 library_id 优先，
        # 空值回退入参（集合首库）；整批赋首库会把跨库证据全标错
        item_lib = str(metadata.get("library_id") or "").strip()
        evidence = Evidence(
            evidence_id=str(getattr(item, "item_id", "") or ""),
            kind=kind,
            doc_id=str(getattr(item, "doc_id", "") or ""),
            doc_title=str(metadata.get("doc_title") or getattr(item, "title", "") or ""),
            content=str(getattr(item, "text", "") or ""),
            page_idx=metadata.get("page_idx"),
            page_label=metadata.get("page_label"),
            section_path=str(metadata.get("section_path") or ""),
            score=float(getattr(item, "rerank_score", None) or getattr(item, "score", 0.0) or 0.0),
            source=source,
            library_id=item_lib or library_id,
            metadata={
                "cite": metadata.get("cite"),
                "citation_target_id": getattr(item, "citation_target_id", None),
                "fusion_sources": metadata.get("fusion_sources") or [],
            },
        )
        evidences.append(evidence.model_dump(mode="json"))
    return evidences


def _entities_to_evidences(entities: list, *, library_id: str) -> List[Dict[str, Any]]:
    """图谱实体 → Evidence 序列化 dict（kind=graph_entity）。"""
    evidences: List[Dict[str, Any]] = []
    for entity in entities:
        data = _serialize_model(entity)
        evidence = Evidence(
            evidence_id=str(data.get("entity_id") or data.get("id") or data.get("name") or ""),
            kind="graph_entity",
            content=str(data.get("description") or data.get("name") or ""),
            source="graph",
            library_id=library_id,
            metadata=data,
        )
        evidences.append(evidence.model_dump(mode="json"))
    return evidences


# ---------------------------------------------------------------------------
# 检索 memo（需求 §5.2 基础并行的复用机制，ANGINEER_ROUTE_PARALLEL 总闸）
#
# 语义：预检方（aichat-api route_pre.fire_speculative_first_search）与消费方（agent_loop
# 首轮注入）先后以**逐参一致**的参数调 _run_knowledge_search；memo 按"单发"复用——
# 命中即弹出，绝不变陈旧缓存跨请求复用。键含全部影响结果的参数（prefix 区分 K/E 来源）。
# doc_nodes 不进键：预检方与消费方都经同一 _load_doc_nodes(scope) 取数，内容一致；
# 其产物（citations 标题）已固化在 memo 值里，因此预检方必须传真实 doc_nodes，否则宁可不预检。
# ---------------------------------------------------------------------------
_SEARCH_MEMO: Dict[Any, Any] = {}
_SEARCH_MEMO_LOCK = threading.Lock()
_SEARCH_MEMO_TTL_SECONDS = 120.0  # 分类最坏尾延迟 ~5s，120s 留足裕度；单发语义下过期项只占内存
_SEARCH_MEMO_MAX = 16
# 三态 memo（施工单 docs/plan-retrieval-speedup-v3.md 变更 A/F3，2026-10-03）：值要么是
# 成品 tuple (ts, result, run_ms)，要么是 _SearchPending（预检在途）。主路 pop 命中成品直接
# 复用（现语义）；撞见在途则等待（预算=Σ各 rerank 端点超时+召回余量，硬顶 90s<tool_timeout
# 120×0.8），预检写完成品即唤醒；无条目/超时/取消/预检失败 → 回落自跑并回收孤儿号段。
# ANGINEER_MEMO_INFLIGHT=0 回退旧行为（只存成品、不等待）。
MEMO_INFLIGHT_ENV = "ANGINEER_MEMO_INFLIGHT"


def route_parallel_enabled() -> bool:
    return (os.getenv("ANGINEER_ROUTE_PARALLEL", "true") or "").strip().lower() in ("true", "1", "yes", "on")


def _memo_inflight_enabled() -> bool:
    return (os.getenv(MEMO_INFLIGHT_ENV, "1") or "").strip().lower() in ("1", "true", "on", "yes")


def _env_float(name: str, default: float) -> float:
    try:
        return float(os.getenv(name) or default)
    except (TypeError, ValueError):
        return default


class _SearchPending:
    """预检在途条目：主路在 event 上等；写完成品或失败/放弃时收敛（单发语义）。"""

    __slots__ = ("event", "result", "run_ms", "failed", "abandoned", "allocator", "alloc_mark")

    def __init__(
        self,
        allocator: Optional["MarkerAllocator"] = None,
        alloc_mark: Optional[Dict[str, int]] = None,
    ) -> None:
        self.event = threading.Event()
        self.result: Optional[Dict[str, Any]] = None
        self.run_ms: Optional[int] = None
        self.failed = False
        self.abandoned = False
        self.allocator = allocator
        self.alloc_mark = alloc_mark


def _search_memo_wait_budget() -> float:
    """主路等待预检的预算：Σ(各 rerank 端点超时)＋召回余量，硬顶 90s（<tool_timeout 120×0.8）。"""
    override = os.getenv("ANGINEER_MEMO_WAIT_BUDGET_SEC")
    if override:
        try:
            return max(0.05, float(override))
        except (TypeError, ValueError):
            pass
    try:
        from angineer_core.retrieval_pipeline import estimated_rerank_wait_seconds

        rerank_budget = estimated_rerank_wait_seconds()
    except Exception:  # noqa: BLE001 — 预算算不出就退默认值
        rerank_budget = 10.0
    return min(90.0, rerank_budget + _env_float("ANGINEER_MEMO_RECALL_ALLOWANCE_SEC", 6.0))


def _search_memo_begin(key, allocator: Optional["MarkerAllocator"] = None) -> Optional[_SearchPending]:
    """预检起飞：按 key 登记在途条目（INFLIGHT 关/键空/已有条目时返回 None 走旧语义）。"""
    if key is None or not _memo_inflight_enabled():
        return None
    alloc_mark = allocator.mark() if allocator is not None else None
    pending = _SearchPending(allocator=allocator, alloc_mark=alloc_mark)
    with _SEARCH_MEMO_LOCK:
        if key in _SEARCH_MEMO:
            return None
        _SEARCH_MEMO[key] = pending
    return pending


def _search_memo_pop(key, cancel_event: Optional[threading.Event] = None):
    """主路取 memo：成品命中复用；在途等待（预算内）复用；其余返回 None（回落自跑）。

    返回 (result, prefetch_ms, wait_ms)；wait_ms=本方等待时长（思考面板「等待预检」用）。
    """
    if key is None:
        return None
    now = time.time()
    with _SEARCH_MEMO_LOCK:
        entry = _SEARCH_MEMO.get(key)
        # 顺手清理过期成品，防长尾堆积（在途条目不在此清理，由等待方/预检方收敛）
        for k in [
            k
            for k, v in _SEARCH_MEMO.items()
            if isinstance(v, tuple) and now - v[0] > _SEARCH_MEMO_TTL_SECONDS
        ]:
            _SEARCH_MEMO.pop(k, None)
    if entry is None:
        return None
    if isinstance(entry, _SearchPending):
        if not _memo_inflight_enabled():
            return None
        budget = _search_memo_wait_budget()
        deadline = time.monotonic() + budget
        while not entry.event.wait(timeout=0.05):
            if cancel_event is not None and cancel_event.is_set():
                break
            if time.monotonic() >= deadline:
                break
        with _SEARCH_MEMO_LOCK:
            if _SEARCH_MEMO.get(key) is entry:
                _SEARCH_MEMO.pop(key, None)  # 单发语义：摘除即消费/作废
        if entry.event.is_set() and not entry.failed and not entry.abandoned and entry.result is not None:
            wait_ms = int((time.monotonic() - (deadline - budget)) * 1000)
            return entry.result, entry.run_ms, wait_ms
        # 超时/取消/预检失败：放弃等待，回收孤儿号段（迟到方写结果作废）
        entry.abandoned = True
        if entry.allocator is not None and entry.alloc_mark is not None:
            entry.allocator.rollback(entry.alloc_mark)
        return None
    if (now - entry[0]) > _SEARCH_MEMO_TTL_SECONDS:
        return None
    # 返回 (result, run_ms, 0)：run_ms= 预检方真实检索耗时，供消费方标注「并行预检 X.Xs」（2026-09-30）
    return entry[1], (entry[2] if len(entry) > 2 else None), 0


def _search_memo_store(
    key,
    result,
    run_ms: Optional[int] = None,
    pending: Optional[_SearchPending] = None,
) -> None:
    """存成品；预检在途时改为填充并唤醒。失败/异常结果不存成品，标记失败并回收号段。"""
    if key is None:
        return
    if pending is not None:
        failed = not isinstance(result, dict) or bool(result.get("error"))
        with _SEARCH_MEMO_LOCK:
            if _SEARCH_MEMO.get(key) is pending:
                _SEARCH_MEMO.pop(key, None)
        if pending.abandoned:
            return  # 等待方已放弃并自行回收：迟到结果作废，不得再回滚（会踩掉主路新号段）
        if failed:
            pending.failed = True
            if pending.allocator is not None and pending.alloc_mark is not None:
                pending.allocator.rollback(pending.alloc_mark)
            pending.event.set()  # 唤醒等待方立即回落自跑，不等预算烧完
            return
        pending.result = result
        pending.run_ms = int(run_ms) if run_ms is not None else None
        with _SEARCH_MEMO_LOCK:
            # 回写成品条目：预检先完成、主路后到时仍能在 TTL 窗口内命中（单发语义不变）
            if key not in _SEARCH_MEMO:
                _SEARCH_MEMO[key] = (time.time(), result, int(run_ms) if run_ms is not None else None)
        pending.event.set()
        return
    if not isinstance(result, dict) or result.get("error"):
        return  # 失败结果不入 memo（现语义）
    with _SEARCH_MEMO_LOCK:
        if len(_SEARCH_MEMO) >= _SEARCH_MEMO_MAX:
            done_keys = [k for k, v in _SEARCH_MEMO.items() if isinstance(v, tuple)]
            if done_keys:
                oldest = min(done_keys, key=lambda k: _SEARCH_MEMO[k][0])
                _SEARCH_MEMO.pop(oldest, None)
        _SEARCH_MEMO[key] = (time.time(), result, int(run_ms) if run_ms is not None else None)


def _search_memo_key(kwargs: Dict[str, Any]):
    if not route_parallel_enabled():
        return None
    # 阶段三 D8：库维度取集合（strip 去空白后排序去重，与 scope_hash_for 归一口径
    # 对齐）；无集合时回退单值——单元素集合与旧单值同键（赌博式预检与主路同源构键，不串桶）
    library_scope = tuple(sorted(
        {str(x).strip() for x in (kwargs.get("library_ids") or ()) if str(x).strip()}
    )) or (str(kwargs.get("library_id") or "default"),)
    return (
        kwargs.get("query"),
        library_scope,
        tuple(kwargs.get("doc_ids") or ()),
        kwargs.get("top_k"),
        kwargs.get("task_type"),
        repr(kwargs.get("filters")),
        kwargs.get("dense") is None,
        kwargs.get("sparse") is None,
        kwargs.get("clause") is None,
        kwargs.get("formula") is None,
        kwargs.get("prefix"),
        kwargs.get("rerank"),
        kwargs.get("retrieval_client") is None,
        kwargs.get("config_name"),
        kwargs.get("mode"),
    )


def _record_retrieval_stages(
    path: str,
    result: Dict[str, Any],
    *,
    query: str,
    task_type: str,
    top_k: int,
    library_id: str,
    library_ids: Optional[List[str]] = None,
) -> None:
    """检索分段计时落盘（req-table-retrieval-latency §10 方案 E）。

    stage_times 由 docs-core 返回值上浮（docs-core 不感知观测设施），此处选择性消费落
    data/ops/retrieval-<日>.jsonl；run_id 由 ops_metrics 上下文自动附带。memo 命中与
    赌博式预检（route_parallel）路径经过本调用点（真检索），memo 命中复用则不经过——
    没有检索发生就不记假数据。失败静默（观测不影响检索）。"""
    stages = result.get("stage_times") if isinstance(result, dict) else None
    if not stages:
        return
    try:
        from angineer_core.ops_metrics import record_event

        record_event(
            "retrieval",
            {
                "path": path,
                "stages": {k: round(float(v), 4) for k, v in stages.items()},
                "dur_ms": int(round(sum(float(v) for v in stages.values()) * 1000)),
                "query": str(query or "")[:40],
                "task_type": task_type,
                "top_k": top_k,
                "library_id": library_id,
                # 阶段三 D8：多库运维归因不再全记首库——libs 记集合（与分段计时日志同口径）
                "libs": ",".join(map(str, library_ids)) if library_ids else library_id,
            },
        )
    except Exception:  # noqa: BLE001
        logger.debug("retrieval 分段落盘失败（忽略）", exc_info=True)


def _run_knowledge_search(**kwargs) -> Dict[str, Any]:
    """memo 壳（F3 三态）：预检侧（_from_speculative）先登记在途再跑实现；主路撞见在途
    等待复用、成品直接复用、其余回落自跑（键构造见上，失败/放弃回收语义见 memo 区块）。

    cancel_event/_from_speculative 是壳层控制键：本壳消费，不透传 impl（impl 签名无此二参，
    透传即 TypeError——v0.2.88 生产实踩，热修 5d7cc15 之后）。"""
    speculative = bool(kwargs.pop("_from_speculative", False))
    ce = kwargs.pop("cancel_event", None)
    ce = ce if isinstance(ce, threading.Event) else None
    key = _search_memo_key(kwargs)
    if not speculative:
        hit = _search_memo_pop(key, cancel_event=ce)
        if hit is not None:
            result, prefetch_ms, wait_ms = hit
            logging.getLogger(__name__).info(
                "knowledge_search 命中赌博式预检缓存（route_parallel）: %r", str(kwargs.get("query"))[:40]
            )
            # 私有键（"_" 前缀不进 LLM 投影、随 raw 供链路展示）：_prefetch_ms=预检真实耗时
            # （2026-09-30）；_memo_wait_ms=主路等待预检时长（F3，思考面板「等待预检」用）
            if isinstance(result, dict):
                if prefetch_ms is not None:
                    result = {**result, "_prefetch_ms": int(prefetch_ms)}
                if wait_ms:
                    result = {**result, "_memo_wait_ms": int(wait_ms)}
            return result
        _t0 = time.monotonic()
        result = _run_knowledge_search_impl(**kwargs)
        run_ms = int((time.monotonic() - _t0) * 1000)
        if key is not None and isinstance(result, dict) and not result.get("error"):
            _search_memo_store(key, result, run_ms)
        return result
    pending = _search_memo_begin(key, allocator=kwargs.get("marker_allocator"))
    _t0 = time.monotonic()
    try:
        result = _run_knowledge_search_impl(**kwargs)
    except Exception:
        _search_memo_store(key, {"error": "speculative_search_failed"}, pending=pending)
        raise
    run_ms = int((time.monotonic() - _t0) * 1000)
    if isinstance(result, dict) and not result.get("error"):
        _search_memo_store(key, result, run_ms, pending=pending)
    else:
        _search_memo_store(key, {"error": "speculative_search_failed"}, pending=pending)
    return result


def _run_knowledge_search_impl(
    *,
    query: str,
    library_id: str = "default",
    library_ids: Optional[List[str]] = None,
    doc_ids: Optional[List[str]] = None,
    doc_nodes: Optional[List[Any]] = None,
    top_k: int = 20,
    task_type: str = "content_qa",
    filters: Any = None,
    dense: Any = None,
    sparse: Any = None,
    clause: Any = None,
    formula: Any = None,
    prefix: str = "K",
    marker_allocator: Optional[MarkerAllocator] = None,
    rerank: bool = False,
    retrieval_client: Any = None,
    config_name: Optional[str] = None,
    mode: str = "instruct",
) -> Dict[str, Any]:
    """执行知识库正文检索（HTTP 优先，失败回退本地进程内检索），供 knowledge_search 与 entity_search 回退共用。

    3b：配置 ANGINEER_DOCS_API_URL（或显式注入 retrieval_client）时走 docs-api HTTP 检索，
    失败回退本地进程内检索；本地召回配方经 knowledge_local_search 端口消费
    （docs-core 适配器），未注册时按降级语义返回 error dict。
    """
    # 中文数字条款号转阿拉伯数字（"第六十条"→"第60条"），提升 ClauseResolver 精确命中率
    query = _normalize_query(query)
    nodes = list(doc_nodes or [])
    doc_title_map = {
        str(getattr(node, "id", "") or ""): str(getattr(node, "title", "") or "")
        for node in nodes
    }
    # 阶段三 D8：仅在显式传集合时上浮 scope.library_ids（旧调用结果 shape 不变）
    scope: Optional[Dict[str, Any]] = None
    if library_ids:
        scope = {
            "library_id": library_id,
            "library_ids": list(library_ids),
            "doc_ids": list(doc_ids or []),
        }
    if retrieval_client is None:
        from angineer_core.docs_retrieval_client import client_from_env

        retrieval_client = client_from_env()
    if retrieval_client is not None:
        try:
            _t = time.perf_counter()
            items, http_stages = retrieval_client.retrieve(
                mode="text",
                query=query,
                library_id=library_id,
                doc_ids=doc_ids,
                top_k=top_k,
                task_type=task_type,
                filters=filters,
                library_ids=library_ids or None,
            )
            logger.info(
                "knowledge_search 分段计时: docs_api=%.2fs items=%d query=%r libs=%s",
                time.perf_counter() - _t, len(items), query[:40],
                ",".join(map(str, library_ids)) if library_ids else library_id,
            )
            _record_retrieval_stages(
                "knowledge_search",
                {"stage_times": http_stages},
                query=query, task_type=task_type, top_k=top_k, library_id=library_id,
                library_ids=library_ids,
            )
            result = _assemble_search_result(
                query=query, items=items, library_id=library_id,
                doc_title_map=doc_title_map, prefix=prefix,
                marker_allocator=marker_allocator, rerank=rerank, task_type=task_type,
                kind="text", source="knowledge_search",
                config_name=config_name, mode=mode,
            )
            if scope:
                result["scope"] = scope
            return result
        except Exception as exc:  # noqa: BLE001
            logger.warning("docs-api 检索失败，回退本地进程内检索: %s", exc)

    from angineer_core import ports

    local_search = ports.get_knowledge_local_search()
    if local_search is None:
        logger.warning("knowledge_local_search 端口未注册（组装层应注入 docs-core 适配器）")
        return {"error": "本地知识检索不可用（端口未注册）"}
    result = local_search(
        query=query,
        library_id=library_id,
        doc_ids=doc_ids,
        top_k=top_k,
        task_type=task_type,
        filters=filters,
        nodes=nodes,
        dense=dense,
        sparse=sparse,
        clause=clause,
        formula=formula,
        # 阶段三 D8：仅显式传集合时才给端口 library_ids——旧调用端口 kwargs 逐位
        # 不变（根 tests/angineer-core/test_ports_contract.py 钉死端口形参集，
        # 无条件塞 library_ids=None 即破严格签名 fake 的契约，10-04 评审 blocking）
        **({"library_ids": library_ids} if library_ids else {}),
    )
    _record_retrieval_stages(
        "knowledge_search", result, query=query, task_type=task_type, top_k=top_k, library_id=library_id,
        library_ids=library_ids,
    )
    if "error" in result:
        return result
    items = _keep_per_doc_blocks(result.get("items") or [])
    assembled = _assemble_search_result(
        query=query, items=items, library_id=library_id,
        doc_title_map=doc_title_map, prefix=prefix,
        marker_allocator=marker_allocator, rerank=rerank, task_type=task_type,
        kind="text", source="knowledge_search",
        config_name=config_name, mode=mode,
    )
    if scope:
        assembled["scope"] = scope
    return assembled


def _assemble_search_result(
    *,
    query: str,
    items: list,
    library_id: str,
    doc_title_map: Dict[str, str],
    prefix: str,
    marker_allocator: Optional[MarkerAllocator],
    rerank: bool,
    task_type: str,
    kind: str,
    source: str,
    config_name: Optional[str] = None,
    mode: str = "instruct",
) -> Dict[str, Any]:
    """检索后装配：rerank → 上桌（仅文本）→ 引用标记 → doc_title 前缀 → 软帽 → items/evidences/citations。"""
    admission_meta: Optional[Dict[str, Any]] = None
    if rerank:
        from angineer_core.retrieval_pipeline import rerank_candidates

        dense_degraded = any(
            bool((getattr(item, "metadata", None) or {}).get("embedding_fallback"))
            for item in items
        )
        _t = time.perf_counter()
        items = rerank_candidates(
            query,
            items,
            task_type=task_type,
            dense_degraded=dense_degraded,
            config_name=config_name,
            mode=mode,
        )
        logger.info(
            "%s rerank 计时: %.2fs candidates=%d query=%r",
            source, time.perf_counter() - _t, len(items), str(query or "")[:40],
        )
        # rerank 已排序：截断进 agent 上下文，控制 prompt 长度（prefill 耗时与输入成正比）
        items = list(items[:_context_top_n()])
        if kind == "text":
            # 证据上桌只吃 rerank 截断后的 top15 文本条目（table/entity 只走硬帽）
            items, admission_meta = _maybe_admit_evidence(query, items)
    _assign_cites(items, marker_allocator or MarkerAllocator(), prefix)
    grade_on = _evidence_grade_enabled()
    for item in items:
        doc_title = doc_title_map.get(str(item.doc_id or ""), "") or str(item.metadata.get("doc_title") or "")
        if doc_title:
            item.metadata["doc_title"] = doc_title
            text_prefix = f"《{doc_title}》"
            text = str(item.text or "")
            if text and text_prefix not in text:
                item.text = f"{text_prefix} {text}"
        if grade_on:
            label = _relevance_label(item)
            if label:
                item.metadata["relevance"] = label
                text = str(item.text or "")
                if text and not text.startswith("【相关性"):
                    item.text = f"{label} {text}"
    # 证据体积软帽：公共末端、覆盖全部 kind（knowledge/table/entity 回退正文）
    items, cap_dropped = _apply_evidence_cap(items)
    if admission_meta is not None or cap_dropped:
        # 决策留痕走 `_` 私有键：不进 LLM 投影（agent_loop 剥 `_` 前缀）、随 raw 进 meta 供评测链聚合
        block = dict(admission_meta or {})
        for key in ("kept", "dropped", "quarreled", "exempted", "fallback", "judge_config", "judge_ms"):
            block.setdefault(key, None)
        block["cap_dropped"] = cap_dropped
        result = {"_admission": block}
    else:
        result = {}
    result["items"] = [_serialize_model(item) for item in items]
    result["total"] = len(items)
    if grade_on and items:
        result["relevance_scale"] = (
            "相关性为检索系统对『证据是否回答本问题』的独立打分（0-1）："
            "<0.25 低（不得作为结论依据）｜0.25-0.6 中｜≥0.6 高；"
            "全部低分＝知识库不含该题答案，应拒答"
        )
    result["evidences"] = _items_to_evidences(items, kind=kind, source=source, library_id=library_id)
    citations = _build_relevant_citations(query, items)
    if citations:
        result["citations"] = citations
    return result


def _build_relevant_citations(query: str, items: list, limit: int = 5) -> List[Dict[str, Any]]:
    """从融合候选中挑选"真正有用"的引用：经 relevant_citations 端口消费（docs-core 适配器）。

    未注册时降级为不返回引用（结果仍带 items/evidences，引用是增强字段）。
    """
    if not items:
        return []
    from angineer_core import ports

    citations_fn = ports.get_relevant_citations()
    if citations_fn is None:
        logger.warning("relevant_citations 端口未注册（组装层应注入 docs-core 适配器），跳过引用挑选")
        return []
    return citations_fn(query, items, limit)


class RetrieverAdapter:
    """包装 step09_query 五路检索器与图谱检索。"""

    @staticmethod
    def knowledge_search(
        *,
        library_id: str = "default",
        library_ids: Optional[List[str]] = None,
        doc_ids: Optional[List[str]] = None,
        doc_nodes: Optional[List[Any]] = None,
        top_k: int = 20,
        task_type: str = "content_qa",
        filters: Any = None,
        dense: Any = None,
        sparse: Any = None,
        clause: Any = None,
        marker_allocator: Optional[MarkerAllocator] = None,
        rerank: bool = False,
        retrieval_client: Any = None,
        config_name: Optional[str] = None,
        mode: str = "instruct",
    ) -> AgentTool:
        doc_ids_bound = doc_ids

        def handler(
            query: Optional[str] = None,
            doc_ids: Optional[List[str]] = None,
            *,
            cancel_event: Optional[threading.Event] = None,
            _from_speculative: bool = False,
            **_kwargs: Any,
        ) -> Dict[str, Any]:
            if not query:
                return {"error": "缺少 query 参数"}
            return _run_knowledge_search(
                query=query,
                library_id=library_id,
                library_ids=library_ids,
                doc_ids=doc_ids if doc_ids else doc_ids_bound,
                doc_nodes=doc_nodes,
                top_k=top_k,
                task_type=task_type,
                filters=filters,
                dense=dense,
                sparse=sparse,
                clause=clause,
                prefix="K",
                marker_allocator=marker_allocator,
                rerank=rerank,
                retrieval_client=retrieval_client,
                config_name=config_name,
                mode=mode,
                cancel_event=cancel_event,
                _from_speculative=_from_speculative,
            )

        return AgentTool(
            name="knowledge_search",
            description="在知识库正文中检索规范条文、概念、定义与条款，返回候选段落。概念/定义/“XX 是什么”类问题应优先使用本工具。",
            parameters_schema={
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "检索问句"},
                    "doc_ids": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "可选：只在指定文档内检索。历史证据被压缩成 [已压缩…] 摘要行时，可用其中标注的 doc_id 回看原文",
                    },
                },
                "required": ["query"],
            },
            handler=handler,
            read_only=True,
        )

    @staticmethod
    def table_search(
        *,
        library_id: str = "default",
        doc_ids: Optional[List[str]] = None,
        doc_nodes: Optional[List[Any]] = None,
        top_k: int = 20,
        filters: Any = None,
        table: Any = None,
        formula: Any = None,
        marker_allocator: Optional[MarkerAllocator] = None,
        rerank: bool = False,
        retrieval_client: Any = None,
        config_name: Optional[str] = None,
        mode: str = "instruct",
    ) -> AgentTool:
        def handler(query: Optional[str] = None, **_kwargs: Any) -> Dict[str, Any]:
            if not query:
                return {"error": "缺少 query 参数"}
            client = retrieval_client
            if client is None:
                from angineer_core.docs_retrieval_client import client_from_env

                client = client_from_env()
            if client is not None:
                try:
                    items, http_stages = client.retrieve(
                        mode="table",
                        query=query,
                        library_id=library_id,
                        doc_ids=doc_ids,
                        top_k=top_k,
                        filters=filters,
                    )
                    _record_retrieval_stages(
                        "table_search",
                        {"stage_times": http_stages},
                        query=query, task_type="table_qa", top_k=top_k, library_id=library_id,
                    )
                    return _assemble_search_result(
                        query=query, items=items, library_id=library_id,
                        doc_title_map={}, prefix="T",
                        marker_allocator=marker_allocator, rerank=rerank, task_type="table_qa",
                        kind="table", source="table_search",
                        config_name=config_name, mode=mode,
                    )
                except Exception as exc:  # noqa: BLE001
                    logger.warning("docs-api 表格检索失败，回退本地进程内检索: %s", exc)

            from angineer_core import ports

            local_search = ports.get_table_local_search()
            if local_search is None:
                logger.warning("table_local_search 端口未注册（组装层应注入 docs-core 适配器）")
                return {"error": "本地表格检索不可用（端口未注册）"}
            local_result = local_search(
                query=query,
                library_id=library_id,
                doc_ids=doc_ids,
                top_k=top_k,
                filters=filters,
                nodes=list(doc_nodes or []),
                table=table,
                formula=formula,
            )
            _record_retrieval_stages(
                "table_search", local_result, query=query, task_type="table_qa", top_k=top_k, library_id=library_id
            )
            if "error" in local_result:
                return local_result
            return _assemble_search_result(
                query=query, items=local_result.get("items") or [], library_id=library_id,
                doc_title_map={}, prefix="T",
                marker_allocator=marker_allocator, rerank=rerank, task_type="table_qa",
                kind="table", source="table_search",
                config_name=config_name, mode=mode,
            )

        return AgentTool(
            name="table_search",
            description="在知识库中检索表格、公式与计算依据，返回包含完整行数值的候选条目。"
                       "查表/取值/数值/尺度/吨级类问题必须优先使用本工具，且 query 必须使用用户原始问题原文，不要改写或添加词汇。",
            parameters_schema={
                "type": "object",
                "properties": {"query": {"type": "string", "description": "检索问句（使用用户原始问题原文）"}},
                "required": ["query"],
            },
            handler=handler,
            read_only=True,
        )

    @staticmethod
    def entity_search(
        *,
        library_id: str,
        db_path: Optional[str] = None,
        limit: int = 20,
        doc_ids: Optional[List[str]] = None,
        doc_nodes: Optional[List[Any]] = None,
        top_k: int = 20,
        task_type: str = "content_qa",
        filters: Any = None,
        marker_allocator: Optional[MarkerAllocator] = None,
        rerank: bool = False,
        retrieval_client: Any = None,
        config_name: Optional[str] = None,
        mode: str = "instruct",
    ) -> AgentTool:
        def handler(query: Optional[str] = None, **_kwargs: Any) -> Dict[str, Any]:
            if not query:
                return {"error": "缺少 query 参数"}
            from angineer_core.docs_retrieval_client import client_from_env, local_fallback_disabled

            # HTTP 优先（docs-api /internal/entity-search）；未配置或失败时回退进程内直开 GraphStore。
            # ANGINEER_DISABLE_LOCAL_FALLBACK=1 时禁止本地回退（消灭跨进程直读 SQLite）。
            entities: Optional[List[Any]] = None
            client = retrieval_client if retrieval_client is not None else client_from_env()
            if client is not None:
                try:
                    entities = client.entity_search(query=query, library_id=library_id, limit=limit)
                except Exception as exc:  # noqa: BLE001
                    if local_fallback_disabled():
                        return {"error": f"docs-api 图谱检索失败（本地回退已禁用）: {exc}"}
                    logger.warning("docs-api 图谱检索失败，回退本地直查: %s", exc)
            elif local_fallback_disabled():
                return {"error": "未配置 ANGINEER_DOCS_API_URL 且本地回退已禁用（ANGINEER_DISABLE_LOCAL_FALLBACK=1）"}

            if entities is None:
                from angineer_core import ports

                # KG_DB_PATH 回退留在编排层；端口只吃解析好的 db_path
                graph_db = db_path or os.environ.get("KG_DB_PATH") or None
                local_entities = ports.get_entity_local_search()
                if local_entities is None:
                    logger.warning("entity_local_search 端口未注册（组装层应注入 docs-core 适配器）")
                    entities = []
                else:
                    entities = local_entities(
                        query=query, library_id=library_id, db_path=graph_db, limit=limit
                    )
            # 图谱实体按 library_id 隔离（P3 起 graph_entities 有 scope 列）；scope 随行返回供前端/evals 追踪。
            entities, entity_cap_dropped = _cap_entity_objects(entities)
            result: Dict[str, Any] = {
                "entities": [_serialize_model(entity) for entity in entities],
                "total": len(entities),
                "scope": {"library_id": library_id, "doc_ids": list(doc_ids or [])},
            }
            if entity_cap_dropped:
                result["_admission"] = {"cap_dropped": entity_cap_dropped}
            result["evidences"] = _entities_to_evidences(entities, library_id=library_id)
            if not entities:
                # 图谱无实体时自动回退正文检索，避免“是什么/定义”类问题被误判为无证据
                fallback = _run_knowledge_search(
                    query=query,
                    library_id=library_id,
                    doc_ids=doc_ids,
                    doc_nodes=doc_nodes,
                    top_k=top_k,
                    task_type=task_type,
                    filters=filters,
                    prefix="E",
                    marker_allocator=marker_allocator,
                    rerank=rerank,
                    retrieval_client=retrieval_client,
                    config_name=config_name,
                    mode=mode,
                )
                if fallback.get("error"):
                    result["fallback_error"] = fallback["error"]
                else:
                    result["items"] = fallback.get("items") or []
                    result["citations"] = fallback.get("citations") or []
                    result["evidences"] = result["evidences"] + (fallback.get("evidences") or [])
                    result["note"] = "知识图谱未找到匹配实体，已自动检索知识库正文，请基于 items 字段中的证据回答。"
            return result

        return AgentTool(
            name="entity_search",
            description="在知识图谱中检索实体及其关系，返回实体条目；仅适用于图谱实体关系类问题。若图谱无匹配，会自动回退检索知识库正文（items 字段）。",
            parameters_schema={
                "type": "object",
                "properties": {"query": {"type": "string", "description": "实体关键词"}},
                "required": ["query"],
            },
            handler=handler,
            read_only=True,
        )


def _run_knowledge_stats(library_id: Optional[str] = None) -> Dict[str, Any]:
    """知识库统计聚合：HTTP 优先（ANGINEER_DOCS_API_URL），失败/未配置回退进程内直查 SQLite。

    口径与 docs-api GET /api/knowledge/stats 一致：文档以 nodes 表为准（deleted=0 排除软删），
    上传/存储以 parse_records 为准（status<>'deleted'）。
    """
    from angineer_core.docs_retrieval_client import client_from_env, local_fallback_disabled

    client = client_from_env()
    if client is not None:
        try:
            import requests

            base_url = client.base_url.rstrip("/")
            resp = requests.get(
                f"{base_url}/api/knowledge/stats",
                params={"library_id": library_id} if library_id else {},
                timeout=client.timeout,
            )
            resp.raise_for_status()
            return resp.json()
        except Exception as exc:  # noqa: BLE001
            if local_fallback_disabled():
                return {"error": f"docs-api 统计接口失败（本地回退已禁用）: {exc}"}
            logger.warning("docs-api 统计接口失败，回退本地直查: %s", exc)
    elif local_fallback_disabled():
        return {"error": "未配置 ANGINEER_DOCS_API_URL 且本地回退已禁用（ANGINEER_DISABLE_LOCAL_FALLBACK=1）"}

    return _run_local_stats(library_id)


def _run_local_stats(library_id: Optional[str]) -> Dict[str, Any]:
    """进程内直查 SQLite 的统计兜底，经 local_stats 端口消费（docs-core 适配器）。"""
    from angineer_core import ports

    local = ports.get_local_stats()
    if local is None:
        logger.warning("local_stats 端口未注册（组装层应注入 docs-core 适配器）")
        return {"error": "本地统计不可用（端口未注册）"}
    return local(library_id)


class StatsAdapter:
    """知识库统计工具（原 meta_query 通道专用；废路由后下沉 L1 统一工具箱，2026-10-02）。"""

    @staticmethod
    def knowledge_stats(*, default_library_id: Optional[str] = None) -> AgentTool:
        def handler(library_id: Optional[str] = None, **_kwargs: Any) -> Dict[str, Any]:
            # 未填/空 = 未指定 → 回落会话库（模型习惯性把缺省参数填成空串，不能当全库信号，2026-09-29 串库）；
            # 显式 all/*/全部 才是全库汇总
            raw = str(library_id).strip() if library_id is not None else ""
            if raw.lower() in ("all", "*", "全部"):
                effective_library = None
            else:
                effective_library = raw or default_library_id
            return _run_knowledge_stats(library_id=effective_library)

        return AgentTool(
            name="knowledge_stats",
            description=(
                "查询知识库的统计信息：文档总数、各状态/各库分布、上传趋势（近7天/30天/按月）、"
                "文件格式分布、总页数与平均页数、存储占用，以及文档标题清单（documents.titles，最多 100 条）。"
                "当用户询问知识库规模、数量、分布、趋势，或问「库里有哪些文章/规范、收录了什么」"
                "这类标题列举问题时使用：列举类回答直接基于 documents.titles（按问题关键词筛选标题）。"
                "只在问题问知识库本身时使用；问某篇文档的正文内容/条款原文，请改用 knowledge_search。"
            ),
            parameters_schema={
                "type": "object",
                "properties": {
                    "library_id": {
                        "type": "string",
                        "description": "限定统计的知识库 id；缺省或传空=当前会话所在库；仅当用户明确问全部/各个知识库整体情况时传 \"all\" 表示全库汇总",
                    }
                },
            },
            handler=handler,
            read_only=True,
        )


class SopRunnerAdapter:
    """SOP 执行工具（P4 接入）：IntentClassifier 路由 → SopRunner.run_sop → 步骤 trace。"""

    @staticmethod
    def sop_execute(
        *,
        timeout_s: int = 300,
        sops: Optional[List[Any]] = None,
        sop_loader: Any = None,
        classifier: Any = None,
        llm_client: Any = None,
        config_name: Optional[str] = None,
        mode: str = "instruct",
        runner: Any = None,
        memory: Any = None,
        step_callback: Optional[Callable[[Dict[str, Any]], None]] = None,
        library_id: str = "default",
        doc_ids: Optional[List[str]] = None,
    ) -> AgentTool:
        def handler(
            sop_query: Optional[str] = None,
            args: Optional[Dict[str, Any]] = None,
            **_kwargs: Any,
        ) -> Dict[str, Any]:
            from angineer_core.base_config import SOP_ROUTE_CONFIDENCE_THRESHOLD

            query = str(sop_query or "").strip()
            if not query:
                return {"error": "缺少 sop_query 参数"}

            if classifier is None:
                from angineer_core.classifier import IntentClassifier

                available = list(sops or [])
                if not available and sop_loader is not None:
                    available = list(sop_loader.load_all() or [])
                published = [
                    sop for sop in available if getattr(sop, "status", "published") == "published"
                ]
                if not published:
                    return {"error": "无可执行的已发布 SOP"}
                effective_classifier = IntentClassifier(published, llm_client=llm_client)
            else:
                effective_classifier = classifier

            route_result = effective_classifier.route(
                query, config_name=config_name, mode=mode
            )
            selected_sop = route_result.sop
            if selected_sop is None or route_result.confidence < SOP_ROUTE_CONFIDENCE_THRESHOLD:
                return {
                    "error": "未匹配到合适的 SOP",
                    "reason": route_result.reason or "SOP 路由未命中",
                    "confidence": route_result.confidence,
                }

            from angineer_core.sop_runner import SopRunner

            executor = runner
            if executor is None:
                executor = SopRunner(
                    config_name=config_name,
                    mode=mode,
                    memory=memory,
                    llm_client=llm_client,
                    library_id=library_id,
                    doc_ids=doc_ids,
                )

            initial_context = {"user_query": query}
            initial_context.update(route_result.args or {})
            if isinstance(args, dict):
                initial_context.update(args)

            final_context = executor.run_sop(
                selected_sop, initial_context, step_callback=step_callback
            )
            sop_trace = SopRunner._build_sop_trace(executor, selected_sop)
            citations = SopRunner._build_citations_from_sop_trace(executor)
            success_steps = sum(1 for s in sop_trace if s.get("status") == "success")
            failed_steps = sum(1 for s in sop_trace if s.get("status") not in ("success", "pending"))
            return {
                "sop_id": selected_sop.id,
                "sop_name": selected_sop.name_zh or selected_sop.name_en or selected_sop.id,
                "confidence": route_result.confidence,
                "summary": (
                    f"命中 SOP {selected_sop.id}，执行 {len(sop_trace)} 步，"
                    f"成功 {success_steps} 步，失败 {failed_steps} 步"
                ),
                "steps": [
                    {
                        "step_id": s.get("step_id"),
                        "step_name": s.get("step_name"),
                        "status": s.get("status"),
                        "outputs": s.get("outputs"),
                    }
                    for s in sop_trace
                ],
                "final_context": final_context or {},
                "sop_trace": sop_trace,
                "citations": citations,
                "route_reason": route_result.reason or "",
            }

        return AgentTool(
            name="sop_execute",
            description="执行一条标准作业程序（SOP），返回计算/查表结果与步骤轨迹。",
            parameters_schema={
                "type": "object",
                "properties": {
                    "sop_query": {"type": "string", "description": "要交给 SOP 路由的问题"},
                    "args": {"type": "object", "description": "SOP 所需参数"},
                },
                "required": ["sop_query"],
            },
            handler=handler,
            read_only=False,
            execution_mode="sequential",
            timeout_s=timeout_s,
        )


def result_to_content(value: Dict[str, Any]) -> str:
    """把 handler 返回的 dict 序列化为喂回模型的文本。"""
    return json.dumps(value, ensure_ascii=False, default=str)
