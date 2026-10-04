"""对话黑板（Blackboard 新对话模式）引擎内核：图模型 / 确定性蒸馏 / 召回渲染 / 读路径 transformer。

设计真相源：``docs/req-blackboard-conversation-mode.md``（BB）。本模块是**单一真相源**：
M0 离线壳（``evals_core.blackboard``）与生产读写路径（M1/M2）都从这里取实现，避免两份 join 口径。

三块职责：
1. **写路径**（M1）：``extract_ops`` 从本轮切片产出图增量 op（确定性部分：cites 边 + value 节点），
   ``validate_ops`` 按 BB §3.3 收口（白名单/悬挂边/单位/原文回查/批量与总量上限），
   ``distill_run`` 是**可被 SSE 与离线壳共同调用的入口函数**（arms §1 落地纪律 ②：不许内联在
   run_end 分支里，否则多轮评测走 ``run_policy_query`` 时蒸馏根本不触发）。
2. **读路径**（M2）：``recall`` 子图召回 + ``render`` 固定版式渲染段。
3. **prompt 装配**：``make_conv_graph_transformer``——历史 tool 原文移出、子图段插在**本轮提问之前**
   （BB §2 段序），主开关 ``ANGINEER_CONV_GRAPH`` **默认关**。

纪律：
- 开关默认关，关态与现状逐字一致（否则生产里找不到「臂 1 = 现状」）；
- **图上无可用节点时不许移除证据**（BB 2026-10-04 干跑护栏：D4 实测 13,248 est → 164 est 裸答）；
- est = 字符数 ÷ 2（``agent_configs._estimate_tokens`` 同口径）。
"""
from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

from .agent_loop import _INJECTED_USER_PROMPTS
from .agent_messages import AgentMessage

# —— 开关（默认关）——
CONV_GRAPH_ENV = "ANGINEER_CONV_GRAPH"
CONV_GRAPH_SUBGRAPH_EST_ENV = "ANGINEER_CONV_GRAPH_SUBGRAPH_EST"   # 渲染段 est 上限
_DEFAULT_SUBGRAPH_EST = 2000        # BB §7.2 闸 B
_DEFAULT_MAX_OPS = 120              # BB §3.3 单批次 op 上限（实测单轮 22~60 条：定 20 会丢一半引用；
                                    # 容量超限现在是**截断 + 注记**，不再整批拒收）
_DEFAULT_MAX_NODES = 500            # BB §3.3 单会话节点上限

MARKER_RE = re.compile(r"\[([KTE])(\d+)\]")
REFERENCE_RE = re.compile(
    r"第\s*[一二三四五六七八九十两0-9]+\s*(?:条|题|个|项|步)"
    r"|刚才|上一条|上一个|上面|上一轮|上一步|前述|那个|那条|那题"
    r"|^\s*[那这]"
)
_ORDINAL_NUM_RE = re.compile(r"第\s*([一二三四五六七八九十两0-9]+)\s*(?:条|题|个|项|步)")
_CN_DIGITS = {"一": 1, "二": 2, "两": 2, "三": 3, "四": 4, "五": 5,
              "六": 6, "七": 7, "八": 8, "九": 9, "十": 10}
VALUE_RE = re.compile(
    r"\b([A-Za-z][A-Za-z0-9_]{0,7})\s*[=＝]\s*(\d+(?:\.\d+)?)\s*"
    r"(m/s|m³|m3|m²|m2|mm|cm|km|m|t|kN|kPa|MPa|℃|%|h|s)\b"
)
_DOC_EXT_RE = re.compile(r"\.(pdf|docx?|xlsx?|pptx?)$", re.IGNORECASE)
# PDF 解析残留的 HTML 标签会直接进节点 key 与提示词（实测：`3<sub>.</sub> 4 码头设计水位和高程`）
_HTML_RE = re.compile(r"<[^>]{1,24}>")
_NODE_DOC_CHARS = 40        # 节点文档名上限
_NODE_LOCATOR_CHARS = 40    # 节点条款/章节上限（实测 section_path 可能是整句）
_CLIP_ELLIPSIS = "…"
_CODE_RE = re.compile(r"\b((?:JTS|JTJ|JTG|GB|CJJ|SL|DL|TB)\s?[A-Z]?\s?\d{1,5})\b", re.IGNORECASE)
_CLAUSE_RE = re.compile(r"\b\d{1,2}(?:\.\d{1,2}){1,3}\b")
_TOKEN_RE = re.compile(r"[A-Za-z]{2,}|\d{3,}|[\u4e00-\u9fff]{2,}")
_STOPWORDS = {
    "什么", "怎么", "怎样", "如何", "多少", "哪些", "哪个", "可以", "是否", "需要",
    "一下", "具体", "分别", "我们", "你们", "现在", "已经", "这个", "那个", "告诉",
    "规范", "要求", "规定", "请问", "还有", "就是", "什么说", "什么样",
}
OP_WHITELIST = ("add_node", "add_edge", "update_value", "mark_resolved")


def conv_graph_enabled() -> bool:
    """``ANGINEER_CONV_GRAPH`` 解析：true/1/yes/on 为开，未设置或其余一律关（同既有 env 布尔约定）。"""
    return os.getenv(CONV_GRAPH_ENV, "false").strip().lower() in ("true", "1", "yes", "on")


def subgraph_est_cap() -> int:
    raw = (os.getenv(CONV_GRAPH_SUBGRAPH_EST_ENV) or "").strip()
    try:
        return max(200, int(raw)) if raw else _DEFAULT_SUBGRAPH_EST
    except ValueError:
        return _DEFAULT_SUBGRAPH_EST


def _is_injected(content: Optional[str]) -> bool:
    text = (content or "").strip()
    return bool(text) and text.startswith(_INJECTED_USER_PROMPTS)


def strip_doc_extension(title: str) -> str:
    return _DOC_EXT_RE.sub("", str(title or "")).strip()


def strip_html(text: Any) -> str:
    """去掉解析残留的 HTML 标签（实测 <sub>/<sup> 会跟着 doc_title/section_path 进提示词）。"""
    return _HTML_RE.sub("", str(text or ""))


def clip_text(text: Any, limit: int) -> str:
    """压平空白 + 截断（节点 key 必须短：实测 section_path 有时是整句，会把渲染段撑长）。"""
    flat = " ".join(strip_html(text).split())
    return flat if len(flat) <= limit else flat[: max(1, limit - 1)] + _CLIP_ELLIPSIS


def last_section_segment(section_path: Any) -> str:
    parts = [p.strip() for p in str(section_path or "").split(" / ") if p.strip()]
    return parts[-1].rstrip("。. ") if parts else ""


def items_of(message: AgentMessage) -> List[Dict[str, Any]]:
    """取 tool 消息的 items。

    ⚠️ 内存态在 ``message.meta``（= ``result_raw``）；从 chat.sqlite 回读时 ``meta_json`` 已被裁成
    ``{name, tool_call_id}``，items 只在 ``content`` 的 JSON 里——两条路都要认（BB §3.1 实测）。
    """
    meta = message.meta if isinstance(message.meta, dict) else {}
    items = meta.get("items")
    if isinstance(items, list) and items:
        return [it for it in items if isinstance(it, dict)]
    try:
        raw = json.loads(message.content or "{}")
    except Exception:
        return []
    items = raw.get("items") if isinstance(raw, dict) else None
    return [it for it in items if isinstance(it, dict)] if isinstance(items, list) else []


# ——————————————————————————— 图模型 ———————————————————————————

@dataclass
class Node:
    node_id: str
    kind: str                 # clause | value | issue
    key: str
    doc_id: str = ""
    library_id: str = ""
    locator: str = ""
    doc_title: str = ""
    value: str = ""
    unit: str = ""
    first_run: int = 0
    last_run: int = 0
    status: str = "open"
    markers: List[str] = field(default_factory=list)


@dataclass
class Edge:
    kind: str                 # cites | derives
    src: str
    dst: str
    run: int
    marker: str = ""


@dataclass
class Graph:
    """内存态图（可从 op 列表重建，也可从 store 载入）。"""

    nodes: Dict[str, Node] = field(default_factory=dict)
    edges: List[Edge] = field(default_factory=list)
    runs: List[int] = field(default_factory=list)
    run_cites: Dict[int, List[str]] = field(default_factory=dict)

    def clause_nodes(self) -> List[Node]:
        return [n for n in self.nodes.values() if n.kind == "clause"]

    def value_nodes(self) -> List[Node]:
        return [n for n in self.nodes.values() if n.kind == "value"]


def clause_node_id(library_id: str, doc_id: str, locator: str) -> str:
    """clause 节点 id：(库, 文档, 条款) 三者齐备才唯一——同一条款跨库不撞车（BB §3.2）。"""
    return f"clause:{library_id or '-'}:{doc_id or '-'}:{locator or '-'}"


def _clause_node_from_item(item: Dict[str, Any]) -> Tuple[str, Dict[str, Any]]:
    md = item.get("metadata") if isinstance(item.get("metadata"), dict) else {}
    library_id = str(md.get("library_id") or "").strip()
    doc_id = str(item.get("doc_id") or "").strip()
    doc_title = clip_text(strip_doc_extension(str(md.get("doc_title") or "")), _NODE_DOC_CHARS)
    locator = clip_text(
        str(md.get("clause_id") or "") or last_section_segment(md.get("section_path"))
        or str(item.get("title") or ""),
        _NODE_LOCATOR_CHARS,
    )
    node_id = clause_node_id(library_id, doc_id, locator)
    display = "/".join(part for part in (doc_title or doc_id, locator) if part)
    return node_id, {
        "kind": "clause", "key": display, "doc_id": doc_id, "library_id": library_id,
        "locator": locator, "doc_title": doc_title,
    }


def extract_ops(messages: Sequence[AgentMessage], run_id: int = 1) -> List[Dict[str, Any]]:
    """从**一轮切片**抽确定性图增量 op（cites 边 + value 节点 + derives 边）。

    这是 BB §3.2「引用边可确定性重建」+ §3.3「值节点须带单位并能在原文回查」的实现；
    entity / issue 节点留给后续的小模型蒸馏（op 协议已为其预留 ``add_node`` type 字段）。
    """
    ops: List[Dict[str, Any]] = []
    item_by_marker: Dict[str, Dict[str, Any]] = {}
    src = f"assistant:{run_id}"
    cited_nodes: List[str] = []
    assistant_texts: List[str] = []

    for message in messages:
        if message.role == "tool":
            for item in items_of(message):
                md = item.get("metadata") if isinstance(item.get("metadata"), dict) else {}
                cite = str(md.get("cite") or "").strip()
                if cite:
                    item_by_marker.setdefault(cite, item)
        elif message.role == "assistant":
            assistant_texts.append(message.content or "")

    combined_text = "\n".join(assistant_texts)
    for text in assistant_texts:
        for prefix, number in MARKER_RE.findall(text):
            marker = f"{prefix}{number}"
            item = item_by_marker.get(marker)
            if item is None:
                continue
            node_id, payload = _clause_node_from_item(item)
            ops.append({"op": "add_node", "node_id": node_id, "run": run_id, **payload,
                        "marker": marker})
            ops.append({"op": "add_edge", "edge_id": f"cites:{run_id}:{marker}:{node_id}",
                        "type": "cites", "src": src, "dst": node_id, "run": run_id,
                        "meta": {"marker": marker}})
            if node_id not in cited_nodes:
                cited_nodes.append(node_id)

    for name, number, unit in VALUE_RE.findall(combined_text):
        literal = f"{name.strip()}={number}{unit}"
        # 原文回查（BB §3.3）：数值必须真的在本轮 assistant 原文里出现过
        if number not in combined_text:
            continue
        node_id = f"value:{name.strip()}:{number}{unit}"
        ops.append({"op": "add_node", "node_id": node_id, "run": run_id, "kind": "value",
                    "key": literal, "value": number, "unit": unit,
                    "source_run": run_id, "source_text": literal})
        for clause_id in cited_nodes:
            ops.append({"op": "add_edge", "edge_id": f"derives:{node_id}:{clause_id}",
                        "type": "derives", "src": node_id, "dst": clause_id, "run": run_id,
                        "meta": {}})
    return ops


def validate_ops(ops: Sequence[Dict[str, Any]], *, existing_node_ids: Iterable[str] = (),
                 assistant_text: str = "", max_ops: int = _DEFAULT_MAX_OPS,
                 max_nodes: int = _DEFAULT_MAX_NODES) -> Tuple[List[Dict[str, Any]], List[str], List[str]]:
    """BB §3.3 的 ops 校验：白名单 / 悬挂边 / 单位 / 原文回查 / 批量与总量上限。

    返回 ``(接受的 ops, 致命拒收原因, 容量注记)``——**致命与容量必须分开**：
    - 致命（非法 op / 悬挂边 / 缺单位 / 原文回查失败）→ 调用方按「整批不进图」处理（BB §3.3 原文）；
    - 容量（单批 ops 或节点数超上限）→ **截断 + 注记**，不整批拒收。
    ⚠️ 这条区分是 2026-10-05 端到端实测逼出来的：真实 19 轮会话里 7 轮（37%）的 ops 数是 22~60，
    按「超限即拒收」会把这些轮**整轮丢掉**（图规模从应有量级掉到 5 节点）。
    """
    accepted: List[Dict[str, Any]] = []
    rejected: List[str] = []
    notes: List[str] = []
    existing = list(existing_node_ids)
    known = set(existing)
    batch_nodes = {op["node_id"] for op in ops if op.get("op") == "add_node"}
    known |= batch_nodes
    if len(existing) + len(batch_nodes) > max_nodes:
        notes.append(f"节点数超上限 {max_nodes}（{len(existing) + len(batch_nodes)}）")
    for op in ops:
        name = op.get("op")
        if name not in OP_WHITELIST:
            rejected.append(f"非法 op: {name!r}")
            continue
        if name == "add_edge":
            # src 允许是**结构源** `assistant:<run>`（cites 边的起点是本轮回答，不是节点）；
            # dst 必须是已存在的节点（含本批次新增）——悬挂边是图损坏的主要形态（BB §3.3）。
            src, dst = op.get("src"), op.get("dst")
            src_ok = src in known or (isinstance(src, str) and src.startswith("assistant:"))
            if not src_ok or dst not in known:
                rejected.append(f"悬挂边: {op.get('edge_id')}")
                continue
        if name in ("add_node", "update_value") and op.get("kind") == "value":
            if not op.get("unit"):
                rejected.append(f"值节点缺单位: {op.get('node_id')}")
                continue
            literal = str(op.get("value") or "")
            if literal and assistant_text and literal not in assistant_text:
                rejected.append(f"值节点原文回查失败: {op.get('node_id')}")
                continue
        accepted.append(op)
    if len(accepted) > max_ops:
        notes.append(f"批次 ops 超上限 {max_ops}（{len(accepted)} 条）→ 截断保留前 {max_ops} 条")
        accepted = accepted[:max_ops]
    return accepted, rejected, notes


# ————————————————————— 内存态重建（离线 / 单测） —————————————————————

def build_graph(messages: Sequence[AgentMessage]) -> Graph:
    """按 run 顺序确定性重建内存态图（M0 离线壳与单测用；生产走 store）。"""
    graph = Graph()
    run_index = 0
    in_run = False
    slice_messages: List[AgentMessage] = []

    def flush() -> None:
        nonlocal in_run, slice_messages
        if in_run:
            _apply_ops_in_memory(graph, extract_ops(slice_messages, run_index))
        in_run = False
        slice_messages = []

    for message in messages:
        if message.role == "user" and not _is_injected(message.content):
            flush()
            run_index += 1
            graph.runs.append(run_index)
            in_run = True
            slice_messages = [message]
            continue
        if not in_run:
            continue
        slice_messages.append(message)
    flush()
    return graph


def _apply_ops_in_memory(graph: Graph, ops: Sequence[Dict[str, Any]]) -> None:
    for op in ops:
        if op["op"] == "add_node":
            node_id = op["node_id"]
            node = graph.nodes.get(node_id)
            if node is None:
                node = Node(node_id=node_id, kind=op.get("kind", "clause"), key=op.get("key", ""),
                            doc_id=op.get("doc_id", ""), library_id=op.get("library_id", ""),
                            locator=op.get("locator", ""), doc_title=op.get("doc_title", ""),
                            value=op.get("value", ""), unit=op.get("unit", ""),
                            first_run=op.get("run", 0), last_run=op.get("run", 0))
                graph.nodes[node_id] = node
            node.last_run = op.get("run", node.last_run)
            marker = op.get("marker")
            if marker and marker not in node.markers:
                node.markers.append(marker)
            if node.kind == "clause":
                graph.run_cites.setdefault(op.get("run", 0), [])
                if node_id not in graph.run_cites[op.get("run", 0)]:
                    graph.run_cites[op.get("run", 0)].append(node_id)
        elif op["op"] == "add_edge":
            graph.edges.append(Edge(kind=op.get("type", ""), src=op.get("src", ""),
                                    dst=op.get("dst", ""), run=op.get("run", 0),
                                    marker=(op.get("meta") or {}).get("marker", "")))


# ——————————————————————————— 读路径 ———————————————————————————

def ordinal_value(question: str) -> Optional[int]:
    match = _ORDINAL_NUM_RE.search(question or "")
    if not match:
        return None
    raw = match.group(1)
    if raw.isdigit():
        return int(raw)
    if raw == "十":
        return 10
    return _CN_DIGITS.get(raw[0])


def _tokens(question: str) -> List[str]:
    return [t for t in _TOKEN_RE.findall(question or "")
            if len(t) >= 2 and t not in _STOPWORDS]


def recall(graph: Graph, question: str, *, limit: int = 12) -> List[Node]:
    """子图召回（BB §4）：序数消解 → 编号/token 匹配 → 近邻兜底。

    兜底不是可选项（2026-10-04 干跑实测）：22 例真实追问里只靠「规范号/条款号」仅命中 4 例。
    序数要指向**最近一个产出过引用的轮**——本轮提问自己会开新 run，``runs[-1]`` 是空的当前轮。
    """
    picked: List[str] = []
    if REFERENCE_RE.search(question or "") and graph.runs:
        cited_runs = [r for r in graph.runs if graph.run_cites.get(r)]
        if cited_runs:
            cites = graph.run_cites.get(cited_runs[-1]) or []
            ordinal = ordinal_value(question)
            if ordinal is not None and ordinal >= 1:
                cites = cites[ordinal - 1: ordinal] or cites
            picked.extend(cites)

    codes = {m.group(1).replace(" ", "").upper() for m in _CODE_RE.finditer(question or "")}
    clauses = set(_CLAUSE_RE.findall(question or ""))
    tokens = _tokens(question)
    scored: List[Tuple[int, int, Node]] = []
    for node in graph.nodes.values():
        if node.kind != "clause":
            continue
        haystack = f"{node.doc_title}{node.locator}{node.key}".replace(" ", "").upper()
        score = 0
        if codes and any(code in haystack for code in codes):
            score += 3
        if clauses and any(clause in haystack for clause in clauses):
            score += 3
        score += sum(1 for token in tokens if token.upper() in haystack)
        if score:
            scored.append((score, node.last_run, node))
    scored.sort(key=lambda row: (-row[0], -row[1]))
    picked.extend(node.node_id for _s, _r, node in scored)
    picked.extend(node.node_id for node in graph.value_nodes())
    # 常驻段（BB §4）：未决事项每轮必带，体量小且与提问无关
    picked.extend(node.node_id for node in graph.nodes.values()
                  if node.kind == "issue" and node.status != "resolved")

    ordered: List[Node] = []
    seen = set()
    for node_id in picked:
        if node_id in seen:
            continue
        seen.add(node_id)
        node = graph.nodes.get(node_id)
        if node is not None:
            ordered.append(node)
        if len(ordered) >= limit:
            break
    if not ordered:
        ordered = sorted(graph.nodes.values(), key=lambda n: -n.last_run)[: min(limit, 5)]
    return ordered


def render(nodes: Iterable[Node], *, max_chars: int = 0) -> str:
    """固定版式渲染（BB §4）：按类型分节、每条一行、自描述（不带 [Kx]——跨 run 会撞号）。

    ``max_chars`` 默认 = ``subgraph_est_cap() * 2``（est = 字符数 ÷ 2）。
    """
    clauses = [n for n in nodes if n.kind == "clause"]
    values = [n for n in nodes if n.kind == "value"]
    issues = [n for n in nodes if n.kind == "issue" and n.status != "resolved"]
    if not clauses and not values and not issues:
        return ""
    lines: List[str] = ["【会话记忆·相关子图】"]
    for node in clauses:
        markers = f"；{'、'.join(node.markers)}" if node.markers else ""
        lines.append(f"- 条款｜{node.key}（第{node.last_run}轮引用{markers}）")
    for node in values:
        lines.append(f"- 数值｜{node.key}（第{node.last_run}轮算出）")
    for node in issues:
        lines.append(f"- 未决｜{node.key}（第{node.last_run}轮提出，待确认）")
    text = "\n".join(lines)
    limit = max_chars or subgraph_est_cap() * 2
    if len(text) > limit:
        text = text[: max(1, limit - 1)].rstrip() + "…"
    return text


# ————————————————————— 写路径入口（M1） —————————————————————

@dataclass
class DistillResult:
    run_id: int
    ops: List[Dict[str, Any]] = field(default_factory=list)
    accepted: List[Dict[str, Any]] = field(default_factory=list)
    rejected: List[str] = field(default_factory=list)
    notes: List[str] = field(default_factory=list)
    applied: bool = False
    note: str = ""

    @property
    def summary(self) -> Dict[str, Any]:
        return {"run_id": self.run_id, "ops": len(self.ops), "accepted": len(self.accepted),
                "rejected": self.rejected, "notes": self.notes, "applied": self.applied,
                "note": self.note}


def distill_run(slice_messages: Sequence[AgentMessage], *, run_id: int,
                existing_node_ids: Iterable[str] = (), store: Any = None,
                owner_key: str = "", session_id: str = "", scope_hash: str = "",
                library_ids: Optional[Sequence[str]] = None) -> DistillResult:
    """**蒸馏入口函数**（arms §1 落地纪律 ②）：SSE 的 run_end、离线壳、评测基建共同调用。

    - 输入取**内存切片**（``hist_list[hist_base:]`` 语义），不重读 chat.sqlite——断连兜底支的
      persist 是滞后的，重读会拿到不含本轮的库（arms §1 落地纪律 ③）；
    - 水位推进由 ``store.apply_ops`` 负责，调用方保证「persist 成功之后」再落图；
    - 无 ``store`` 时纯函数返回 ops（离线 / 单测）。
    """
    ops = extract_ops(slice_messages, run_id)
    assistant_text = "\n".join(m.content or "" for m in slice_messages if m.role == "assistant")
    accepted, rejected, notes = validate_ops(ops, existing_node_ids=existing_node_ids,
                                             assistant_text=assistant_text)
    result = DistillResult(run_id=run_id, ops=ops, accepted=accepted, rejected=rejected,
                           notes=notes)
    if rejected:
        # BB §3.3：**致命**问题（非法 op / 悬挂边 / 缺单位 / 回查失败）→ 整批不进图，不部分应用；
        # 容量超限走 notes（下面照常进图，只是被截断）
        result.note = "整批拒收（存在非法/悬挂/回查失败 op）"
        if store is not None:
            store.record_rejected(owner_key, session_id, run_id, ops, rejected,
                                  scope_hash=scope_hash, library_ids=library_ids)
        return result
    if store is None:
        result.note = "无 store：仅返回 ops"
        return result
    applied = store.apply_ops(owner_key, session_id, run_id, accepted, scope_hash=scope_hash,
                              library_ids=library_ids)
    result.applied = bool(applied)
    if notes:
        result.note = ("已进图（" + "；".join(notes) + "）") if applied else \
            "run 已处理过（幂等跳过）"
    else:
        result.note = "已进图" if applied else "run 已处理过（幂等跳过）"
    return result


# ——————————————— 读路径 transformer（M2 装配） ———————————————

def make_conv_graph_transformer(store: Any, *, owner_key: str, session_id: str,
                                question_getter=None):
    """把「历史 tool 原文移出 + 子图段插在本轮提问之前」做成 ``transform_context`` 回调。

    - 开关关 → 直接返回未改动列表（**关态与现状逐字一致**）；
    - 图上无可用节点 → 不移除证据（BB 干跑护栏）；
    - 子图段上限 = ``subgraph_est_cap()`` est（BB §7.2 闸 B），渲染自带截断。
    """

    def transform(messages: List[AgentMessage]) -> List[AgentMessage]:
        if not conv_graph_enabled() or store is None:
            return messages
        last_user = -1
        for index in range(len(messages) - 1, -1, -1):
            message = messages[index]
            if message.role == "user" and not _is_injected(message.content):
                last_user = index
                break
        if last_user <= 0:
            return messages
        question = messages[last_user].content or ""
        if question_getter is not None:
            question = question_getter(messages) or question
        graph = store.load_graph(owner_key, session_id)
        if not graph.nodes:
            return messages
        segment = render(recall(graph, question))
        if not segment:
            return messages
        kept = [m for index, m in enumerate(messages)
                if not (m.role == "tool" and index < last_user)]
        anchor = -1
        for index in range(len(kept) - 1, -1, -1):
            if kept[index].role == "user" and not _is_injected(kept[index].content):
                anchor = index
                break
        injected = AgentMessage(role="user", content=segment)
        if anchor < 0:
            return kept + [injected]
        return kept[:anchor] + [injected] + kept[anchor:]

    return transform
