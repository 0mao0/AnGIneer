"""条款号直达解析：问题中显式条款编号按 clause_id 精确命中，跳过模糊召回。

设计原则：能确定的就别交给概率。
- 抽取阶段采用"上下文门控"：单点分编号（如 5.4）必须有 第/条/款/表/图/附录
  等上下文才采信，避免把 "1.5m" 这类测量值误当条款号；
- 「式/公式X」的编号是公式号、不是条款号（q_028：与条款号跨规范撞车），
  抽取前经 mask_formula_number_spans 整体屏蔽，交公式路处理；
- 匹配阶段走 canonical_blocks.clause_id 的双向层级精确查询，不再依赖模糊打分。
"""
import re
from typing import List, Optional

from docs_core.step09_query.protocols.contracts import KnowledgeNode, KnowledgeQueryRequest, RetrievedItem
from docs_core.step09_query.protocols.data_port import QueryDataPort, default_query_data_port
from docs_core.step09_query.retrieval.query_normalizer import (
    extract_topic_terms,
    mask_formula_number_spans,
    normalize_clause_ref_text,
    normalize_match_text,
    token_scoring_weight,
)

# 直达候选的基础分，确保精确命中排在稀疏召回（条款加成最高 +8）之前
_CLAUSE_DIRECT_BASE_SCORE = 12.0

# 主题重合加成上限（P0-2）：同号条款跨规范撞车时主题词决定排序，
# 必须大于「精确一致 +2」——父级命中的主题相关条款应能压过无关文档的精确同号条款。
_CLAUSE_TOPIC_WEIGHT = 6.0

_ASCII_TERM = re.compile(r"[a-z0-9_]+")

# 题面点名规范（P1-1）：《规范名》或 JTS/JTG/GB… 编号出现时，条款直达限域到该文档
_SPEC_BOOK_PATTERN = re.compile(r"《([^》]+)》")
_SPEC_CODE_PATTERN = re.compile(
    r"(?:JTS|JTG|JTJ|CJJ|GBJ|TB|DB\d{2}|GB)[A-Z]{0,3}[\s/]*[-—]?\s*\d+(?:\s*[-—]\s*\d{4})?",
    re.IGNORECASE,
)


def _compact_spec_text(text: str) -> str:
    return re.sub(r"[\s/—\-]+", "", str(text or "")).lower()


def _restrict_nodes_by_spec_hint(query: str, doc_nodes: List[KnowledgeNode]) -> List[KnowledgeNode]:
    """题面点名某本规范时只保留该文档的条款命中（同号撞车的文档侧解法）。

    点名的规范在候选里对不上任何文档时**回退不限域**——点名失败不得清空正常召回。
    """
    raw = str(query or "")
    books = _SPEC_BOOK_PATTERN.findall(raw)
    codes = [_compact_spec_text(code) for code in _SPEC_CODE_PATTERN.findall(raw)]
    if not books and not codes:
        return list(doc_nodes)
    matched = [
        node
        for node in doc_nodes
        if any(book in str(node.title) for book in books)
        or any(code and code in _compact_spec_text(node.title) for code in codes)
    ]
    return matched or list(doc_nodes)


def _topic_core_terms(topic_terms: List[str]) -> List[str]:
    """具体主题词子集：4–8 字 n-gram 或 ASCII 标识符。

    词长上限防跨虚词长串（整段 CJK 连串不是词，块文本永远对不上）；
    下限 4 字滤掉跨文档通用的短 n-gram。
    """
    return [t for t in topic_terms if 4 <= len(t) <= 8 or _ASCII_TERM.fullmatch(t)]


def _topic_overlap(text: str, topic_terms: List[str]) -> float:
    """题干主题词与块文本的加权重合度 ∈ [0,1]。

    优先用 _topic_core_terms 具体主题词；题干没有此类词则退回全量主题词。
    """
    if not topic_terms:
        return 0.0
    pool = _topic_core_terms(topic_terms) or topic_terms
    total = sum(token_scoring_weight(t) for t in pool)
    if total <= 0:
        return 0.0
    norm = normalize_match_text(text)
    matched = sum(token_scoring_weight(t) for t in pool if t and t in norm)
    return matched / total

# 需要上下文佐证的编号形态：第X条 / 第X款 / 表X / 图X / 附录X
# （式/公式号已踢出——公式号走公式路，见 mask_formula_number_spans）
_CLAUSE_CONTEXT_PATTERNS = [
    re.compile(r"第\s*([0-9]+(?:[.\s\-][0-9]+){0,4})\s*条"),
    re.compile(r"第\s*([0-9]+(?:[.\s\-][0-9]+){0,4})\s*款"),
    re.compile(r"(?:表|图)\s*([0-9]+(?:[.\s\-][0-9]+){0,4})"),
    re.compile(r"([0-9]+\.[0-9]+(?:\.[0-9]+){0,3})\s*条"),
    re.compile(r"附录\s*([A-Z](?:\.[0-9]+){0,3})"),
]

# 无上下文也可采信的形态：≥3 段点分编号（如 5.4.12，测量值极少出现该形态）
_CLAUSE_BARE_DOTTED_PATTERN = re.compile(r"(?<![\d.])(\d+\.\d+\.\d+(?:\.\d+){0,2})(?![\d.\-])")

# 附录字母编号（如 A.0.1），形态本身有区分度
_CLAUSE_APPENDIX_PATTERN = re.compile(r"(?<![\dA-Za-z.])([A-Z]\.\d+(?:\.\d+){0,3})(?![\d.])")


def extract_clause_refs_strict(query: str) -> List[str]:
    """上下文门控的条款号抽取：宁缺毋滥，避免测量值误判为条款编号。

    公式号先屏蔽——否则「公式6.2.8」的 6.2.8 会经裸号三段点分路（_CLAUSE_BARE_DOTTED_PATTERN）漏回。
    """
    raw = mask_formula_number_spans(query)
    refs: List[str] = []
    seen = set()

    def _add(candidate: str) -> None:
        normalized = normalize_clause_ref_text(candidate)
        # 至少两段（含字母前缀的点分），过滤单数字噪音
        if not normalized or "." not in normalized:
            return
        if normalized in seen:
            return
        seen.add(normalized)
        refs.append(normalized)

    for pattern in _CLAUSE_CONTEXT_PATTERNS:
        for match in pattern.finditer(raw):
            _add(match.group(1))
    for match in _CLAUSE_BARE_DOTTED_PATTERN.finditer(raw):
        _add(match.group(1))
    for match in _CLAUSE_APPENDIX_PATTERN.finditer(raw):
        _add(match.group(1))
    return refs


class ClauseResolver:
    """从 canonical blocks 中按 clause_id 精确召回条款候选。"""

    def __init__(self, port: Optional[QueryDataPort] = None) -> None:
        self._port = port

    def retrieve(
        self,
        request: KnowledgeQueryRequest,
        doc_nodes: List[KnowledgeNode],
        task_type: str,
    ) -> List[RetrievedItem]:
        port = self._port or default_query_data_port()
        clause_refs = extract_clause_refs_strict(request.query)
        if not clause_refs:
            return []
        doc_nodes = _restrict_nodes_by_spec_hint(request.query, doc_nodes)
        topic_terms = extract_topic_terms(request.query)
        core_terms = _topic_core_terms(topic_terms)
        candidates: List[RetrievedItem] = []
        for node in doc_nodes:
            blocks = port.list_blocks_by_clause_refs(
                doc_id=node.id,
                clause_refs=clause_refs,
                limit=max(6, request.top_k * 2),
            )
            for block in blocks:
                clause_id = str(block.get("clause_id") or "")
                text = str(block.get("text_clean") or block.get("text") or "")
                overlap = _topic_overlap(text, topic_terms)
                # 与问题条款号完全一致（而非父子层级）的命中给予加分；
                # 主题重合参与排序（P0-2）——跨规范同号撞车不再靠遍历顺序随缘
                score = (
                    _CLAUSE_DIRECT_BASE_SCORE
                    + (2.0 if clause_id in clause_refs else 0.0)
                    + _CLAUSE_TOPIC_WEIGHT * overlap
                )
                section = str(block.get("section_path") or "").strip()
                # P1-3：证据必须带规范名——否则生成器与用户无法分辨同号条款出自哪本规范
                doc_name = str(node.title or "")
                candidates.append(
                    RetrievedItem(
                        item_id=str(block.get("block_id") or ""),
                        entity_type=str(block.get("block_type") or "content"),
                        doc_id=node.id,
                        title=f"{doc_name}｜{section}" if section else doc_name,
                        text=text,
                        score=score,
                        citation_target_id=str(block.get("block_id") or ""),
                        retrieval_policy="clause_direct",
                        metadata={
                            "page_idx": block.get("page_idx"),
                            "section_path": block.get("section_path"),
                            "doc_title": doc_name,
                            "topic_overlap": round(overlap, 3),
                            "source_kind": "clause_direct",
                            "chunk_type": str(block.get("block_type") or "content"),
                            "strategy": "clause_direct_v1",
                            "citation_target_id": block.get("block_id"),
                            "clause_id": clause_id,
                        },
                    )
                )
        # P1-2：题干有具体主题信号而全部命中主题零重合 → 同号噪声条款判无效证据，
        # 返回空让主题词走 dense/sparse（现状噪声以 12~14 分上呈会把模型逼向拒答）。
        # 裸条款号引用（无核心主题词）不触发，避免误杀正常直达。
        if core_terms and all(
            float(item.metadata.get("topic_overlap") or 0.0) == 0.0 for item in candidates
        ):
            return []
        # 撞车候选按分数降序返回（主题加权的结果直接体现在返回顺序上）
        candidates.sort(key=lambda item: -item.score)
        return candidates


clause_resolver = ClauseResolver()
