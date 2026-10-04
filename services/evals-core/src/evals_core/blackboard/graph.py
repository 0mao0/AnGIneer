"""离线确定性会话图：cites 边重建 + value 节点 + 子图召回 + 固定版式渲染。

定位：M0 三臂里**臂 3 的离线替身**（生产读写路径要到 M1/M2），同时是这两步的可复用内核——
cites join 口径与 BB §3.2 完全一致（``[KTE]x`` × ``items[].metadata.cite``，限单 run），
value 节点按 BB §3.3 的「必须带单位 + 原文回查」两条红线产出。

**不调 LLM**：所以只有确定性产出的节点（clause / value），entity / issue 节点留给 M1 的
小模型蒸馏（届时本模块的接口不变，``build_graph`` 可换成「确定性骨架 + 模型增量 ops」）。
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

from angineer_core.agent_loop import _INJECTED_USER_PROMPTS
from angineer_core.agent_messages import AgentMessage

# 引用标记：三类前缀（K=knowledge_search / T=table_search / E=entity_search）
MARKER_RE = re.compile(r"\[([KTE])(\d+)\]")
# 序数 / 指示代词（BB §4 的「序数消解」靶面）。
# ⚠️ 拆两个正则：REFERENCE_RE 只判「是否指涉」，_ORDINAL_NUM_RE 单独取序号——
# 合成一个会让「刚才第二条…」在位置 0 先命中弱信号「刚才」（re.search 取最左匹配），
# 序号丢失后退化成「取上一轮全部」，第 2 条指涉被放大成整轮（首轮实跑就踩到）。
REFERENCE_RE = re.compile(
    r"第\s*[一二三四五六七八九十两0-9]+\s*(?:条|题|个|项|步)"
    r"|刚才|上一条|上一个|上面|上一轮|上一步|前述|那个|那条|那题"
    r"|^\s*[那这]"      # 承接式追问：「那抗倾稳定呢？」「这个怎么算」
)
_ORDINAL_NUM_RE = re.compile(r"第\s*([一二三四五六七八九十两0-9]+)\s*(?:条|题|个|项|步)")
_CN_DIGITS = {"一": 1, "二": 2, "两": 2, "三": 3, "四": 4, "五": 5,
              "六": 6, "七": 7, "八": 8, "九": 9, "十": 10}
# value 节点：`T=12.8m` / `Z0 = 0.4 m`（字母变量 + 数值 + 必须有单位，BB §3.3）
VALUE_RE = re.compile(
    r"\b([A-Za-z][A-Za-z0-9_]{0,7})\s*[=＝]\s*(\d+(?:\.\d+)?)\s*"
    r"(m/s|m³|m3|m²|m2|mm|cm|km|m|t|kN|kPa|MPa|℃|%|h|s)\b"
)
_DOC_EXT_RE = re.compile(r"\.(pdf|docx?|xlsx?|pptx?)$", re.IGNORECASE)
# 规范号（用于字符串召回：JTS 181 / JTG D60 / GB 50139 …）
_CODE_RE = re.compile(r"\b((?:JTS|JTJ|JTG|GB|CJJ|SL|DL|TB)\s?[A-Z]?\s?\d{1,5})\b", re.IGNORECASE)
_CLAUSE_RE = re.compile(r"\b\d{1,2}(?:\.\d{1,2}){1,3}\b")
# 泛化 token（2026-10-04 实测补：22 例真实追问里只有 4 例带显式规范号/条款号线索，
# 「DWT=40000 的满载吃水」「沉箱干舷高度应满足哪条规范」这类问法是多数派）：
# 拉丁词 / 长数字 / 中文词段都可作为匹配键，配合近邻兜底保证子图段不为空。
_TOKEN_RE = re.compile(r"[A-Za-z]{2,}|\d{3,}|[\u4e00-\u9fff]{2,}")
_STOPWORDS = {
    "什么", "怎么", "怎样", "如何", "多少", "哪些", "哪个", "可以", "是否", "需要",
    "一下", "具体", "分别", "我们", "你们", "现在", "已经", "这个", "那个", "告诉",
    "规范", "要求", "规定", "请问", "还有", "就是", "什么说", "什么样",
}


def _is_injected(content: Optional[str]) -> bool:
    """引擎注入的内部 user 提示——划 run 边界时必须跳过（口径同 agent_configs）。"""
    text = (content or "").strip()
    return bool(text) and text.startswith(_INJECTED_USER_PROMPTS)


def _strip_ext(title: str) -> str:
    return _DOC_EXT_RE.sub("", str(title or "")).strip()


def _last_segment(section_path: Any) -> str:
    parts = [p.strip() for p in str(section_path or "").split(" / ") if p.strip()]
    return parts[-1].rstrip("。. ") if parts else ""


def _items_of(message: AgentMessage) -> List[Dict[str, Any]]:
    """取 tool 消息的 items。

    ⚠️ 内存态在 ``message.meta``（= result_raw）；从 chat.sqlite 回读时 ``meta_json`` 已被裁成
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


@dataclass
class Node:
    """图节点（clause / value）。node_id 稳定可重建，是边的引用目标。"""

    node_id: str
    kind: str                 # clause | value
    key: str                  # 展示 key（自描述）
    doc_id: str = ""
    library_id: str = ""
    locator: str = ""         # clause_id 或 section_path 末段
    doc_title: str = ""
    value: str = ""
    unit: str = ""
    first_run: int = 0
    last_run: int = 0
    markers: List[str] = field(default_factory=list)   # 该节点被引用过的标记（保序去重）


@dataclass
class Edge:
    kind: str                 # cites | derives
    src: str                  # run 节点用 f"run:{n}"
    dst: str
    run: int
    marker: str = ""


@dataclass
class OfflineGraph:
    nodes: Dict[str, Node] = field(default_factory=dict)
    edges: List[Edge] = field(default_factory=list)
    runs: List[int] = field(default_factory=list)
    run_cites: Dict[int, List[str]] = field(default_factory=dict)

    def clause_nodes(self) -> List[Node]:
        return [n for n in self.nodes.values() if n.kind == "clause"]

    def value_nodes(self) -> List[Node]:
        return [n for n in self.nodes.values() if n.kind == "value"]


def _clause_node_id(library_id: str, doc_id: str, locator: str) -> str:
    return f"clause:{library_id or '-'}:{doc_id or '-'}:{locator or '-'}"


def build_graph(messages: Sequence[AgentMessage]) -> OfflineGraph:
    """按 run 顺序确定性重建图（cites 边 + value 节点）。"""
    graph = OfflineGraph()
    run_index = 0
    in_run = False
    run_tool_items: Dict[str, Dict[str, Any]] = {}   # marker cite → item
    run_cited_node_ids: List[str] = []

    def close_run() -> None:
        nonlocal in_run, run_tool_items, run_cited_node_ids
        if in_run:
            graph.run_cites[run_index] = list(dict.fromkeys(run_cited_node_ids))
        in_run = False
        run_tool_items = {}
        run_cited_node_ids = []

    for message in messages:
        if message.role == "user" and not _is_injected(message.content):
            close_run()
            run_index += 1
            graph.runs.append(run_index)
            in_run = True
            continue
        if not in_run:
            continue
        if message.role == "tool":
            for item in _items_of(message):
                md = item.get("metadata") if isinstance(item.get("metadata"), dict) else {}
                cite = str(md.get("cite") or "").strip()
                if cite:
                    run_tool_items.setdefault(cite, item)
            continue
        if message.role != "assistant":
            continue
        text = message.content or ""
        for prefix, number in MARKER_RE.findall(text):
            marker = f"{prefix}{number}"
            item = run_tool_items.get(marker)
            if item is None:
                continue
            md = item.get("metadata") if isinstance(item.get("metadata"), dict) else {}
            library_id = str(md.get("library_id") or "").strip()
            doc_id = str(item.get("doc_id") or "").strip()
            doc_title = _strip_ext(str(md.get("doc_title") or ""))
            locator = str(md.get("clause_id") or "") or _last_segment(md.get("section_path")) \
                or str(item.get("title") or "").strip()
            node_id = _clause_node_id(library_id, doc_id, locator)
            node = graph.nodes.get(node_id)
            display = "/".join(part for part in (doc_title or doc_id, locator) if part)
            if node is None:
                node = Node(node_id=node_id, kind="clause", key=display, doc_id=doc_id,
                            library_id=library_id, locator=locator, doc_title=doc_title,
                            first_run=run_index, last_run=run_index)
                graph.nodes[node_id] = node
            node.last_run = run_index
            if marker not in node.markers:
                node.markers.append(marker)
            graph.edges.append(Edge(kind="cites", src=f"run:{run_index}", dst=node_id,
                                    run=run_index, marker=marker))
            run_cited_node_ids.append(node_id)
        # value 节点：字母变量 + 数值 + 单位（BB §3.3），且数值必须在原文出现（原文回查）
        for name, number, unit in VALUE_RE.findall(text):
            literal = f"{name}={number}{unit}"
            if literal.replace(" ", "") not in re.sub(r"\s+", "", text) and number not in text:
                continue  # 原文回查失败 → 拒收（防幻觉）
            node_id = f"value:{name.strip()}:{number}{unit}"
            node = graph.nodes.get(node_id)
            if node is None:
                node = Node(node_id=node_id, kind="value", key=literal, value=number,
                            unit=unit, first_run=run_index, last_run=run_index)
                graph.nodes[node_id] = node
            node.last_run = run_index
            for clause_id in dict.fromkeys(run_cited_node_ids):
                graph.edges.append(Edge(kind="derives", src=node_id, dst=clause_id, run=run_index))
    close_run()
    return graph


def _ordinal_value(question: str) -> Optional[int]:
    """题面里的序号（「第2题」「第二条」）；无则 None（表示取全部）。"""
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
    """从问句抽匹配 token（拉丁词/长数字/中文词段），去停用词。"""
    tokens: List[str] = []
    for raw in _TOKEN_RE.findall(question or ""):
        token = raw.strip()
        if len(token) < 2 or token in _STOPWORDS:
            continue
        tokens.append(token)
    return tokens


def recall(graph: OfflineGraph, question: str, *, limit: int = 12) -> List[Node]:
    """子图召回（BB §4）：序数消解 → 编号/token 匹配 → **近邻兜底**。

    ⚠️ 兜底不是可选项（2026-10-04 实测）：22 例真实追问里，仅靠「规范号/条款号/序数」
    只能命中 **4 例**（18 例段为空——真实问法多是「DWT=40000 的满载吃水」这类无线索追问）。
    BB §4 首版明确不做向量召回，故这里必须给出确定性兜底：token 匹配 + 最近轮近邻，
    否则臂 3 在这些题上等于「丢了证据又没补上」，M0 会得出假的「收缩边界」结论。

    ⚠️ 序数/指示代词要指向**最近一个已产出引用的轮**——本轮提问自己会开一个新 run
    （build_graph 里 user 消息即开 run），直接取 ``runs[-1]`` 会命中空的当前轮。
    """
    picked: List[str] = []
    ordinal_hit = bool(REFERENCE_RE.search(question or "")) and bool(graph.runs)
    if ordinal_hit:
        cited_runs = [run for run in graph.runs if graph.run_cites.get(run)]
        if cited_runs:
            last_run = cited_runs[-1]
            cites = graph.run_cites.get(last_run) or []
            ordinal = _ordinal_value(question)
            if ordinal is not None and ordinal >= 1:
                sliced = cites[ordinal - 1: ordinal]
                # 序号超出该轮实际引用条数（含「同 doc+section 被引用两次 → 去重只剩 1 个节点」
                # 这种情形）→ 回退取该轮全部：宁可多给一条，也不要子图段整个空掉。
                cites = sliced or cites
            picked.extend(cites)

    codes = {m.group(1).replace(" ", "").upper() for m in _CODE_RE.finditer(question or "")}
    clauses = set(_CLAUSE_RE.findall(question or ""))
    tokens = _tokens(question)
    scored: List[tuple] = []
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
    picked.extend(node.node_id for _score, _run, node in scored)
    picked.extend(node.node_id for node in graph.value_nodes())

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
        # 近邻兜底：没有任何线索时，给最近轮产出过的节点（等价于「常驻段＋近邻」的最弱形态）
        by_recency = sorted(graph.nodes.values(), key=lambda n: -n.last_run)
        ordered = by_recency[: min(limit, 5)]
    return ordered


def render(nodes: Iterable[Node], *, max_chars: int = 4000) -> str:
    """固定版式渲染（BB §4）：按类型分节、每条一行、**自描述**（不带 [Kx]——跨 run 会撞号）。

    ``max_chars`` 默认 4000 = 2,000 est tokens，即 BB §7.2 闸 B 的硬上限（est = 字符数 ÷ 2）。
    """
    clauses = [n for n in nodes if n.kind == "clause"]
    values = [n for n in nodes if n.kind == "value"]
    if not clauses and not values:
        return ""
    lines: List[str] = ["【会话记忆·相关子图】"]
    for node in clauses:
        markers = f"；{'、'.join(node.markers)}" if node.markers else ""
        lines.append(f"- 条款｜{node.key}（第{node.last_run}轮引用{markers}）")
    for node in values:
        lines.append(f"- 数值｜{node.key}（第{node.last_run}轮算出）")
    text = "\n".join(lines)
    if len(text) > max_chars:
        text = text[: max(1, max_chars - 1)].rstrip() + "…"
    return text
