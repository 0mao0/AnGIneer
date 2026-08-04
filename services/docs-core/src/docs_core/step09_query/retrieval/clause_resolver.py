"""条款号直达解析：问题中显式条款编号按 clause_id 精确命中，跳过模糊召回。

设计原则：能确定的就别交给概率。
- 抽取阶段采用"上下文门控"：单点分编号（如 5.4）必须有 第/条/款/表/图/式/附录
  等上下文才采信，避免把 "1.5m" 这类测量值误当条款号；
- 匹配阶段走 canonical_blocks.clause_id 的双向层级精确查询，不再依赖模糊打分。
"""
import re
from typing import List, Optional

from docs_core.step09_query.protocols.contracts import KnowledgeNode, KnowledgeQueryRequest, RetrievedItem
from docs_core.step09_query.protocols.data_port import QueryDataPort, default_query_data_port
from docs_core.step09_query.retrieval.query_normalizer import normalize_clause_ref_text

# 直达候选的基础分，确保精确命中排在稀疏召回（条款加成最高 +8）之前
_CLAUSE_DIRECT_BASE_SCORE = 12.0

# 需要上下文佐证的编号形态：第X条 / 第X款 / 表X / 图X / 式X / 附录X
_CLAUSE_CONTEXT_PATTERNS = [
    re.compile(r"第\s*([0-9]+(?:[.\s\-][0-9]+){0,4})\s*条"),
    re.compile(r"第\s*([0-9]+(?:[.\s\-][0-9]+){0,4})\s*款"),
    re.compile(r"(?:表|图|式|公式)\s*([0-9]+(?:[.\s\-][0-9]+){0,4})"),
    re.compile(r"([0-9]+\.[0-9]+(?:\.[0-9]+){0,3})\s*条"),
    re.compile(r"附录\s*([A-Z](?:\.[0-9]+){0,3})"),
]

# 无上下文也可采信的形态：≥3 段点分编号（如 5.4.12，测量值极少出现该形态）
_CLAUSE_BARE_DOTTED_PATTERN = re.compile(r"(?<![\d.])(\d+\.\d+\.\d+(?:\.\d+){0,2})(?![\d.\-])")

# 附录字母编号（如 A.0.1），形态本身有区分度
_CLAUSE_APPENDIX_PATTERN = re.compile(r"(?<![\dA-Za-z.])([A-Z]\.\d+(?:\.\d+){0,3})(?![\d.])")


def extract_clause_refs_strict(query: str) -> List[str]:
    """上下文门控的条款号抽取：宁缺毋滥，避免测量值误判为条款编号。"""
    raw = str(query or "")
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
        candidates: List[RetrievedItem] = []
        for node in doc_nodes:
            blocks = port.list_blocks_by_clause_refs(
                doc_id=node.id,
                clause_refs=clause_refs,
                limit=max(6, request.top_k * 2),
            )
            for block in blocks:
                clause_id = str(block.get("clause_id") or "")
                # 与问题条款号完全一致（而非父子层级）的命中给予加分
                score = _CLAUSE_DIRECT_BASE_SCORE + (2.0 if clause_id in clause_refs else 0.0)
                candidates.append(
                    RetrievedItem(
                        item_id=str(block.get("block_id") or ""),
                        entity_type=str(block.get("block_type") or "content"),
                        doc_id=node.id,
                        title=str(block.get("section_path") or node.title),
                        text=str(block.get("text_clean") or block.get("text") or ""),
                        score=score,
                        citation_target_id=str(block.get("block_id") or ""),
                        retrieval_policy="clause_direct",
                        metadata={
                            "page_idx": block.get("page_idx"),
                            "section_path": block.get("section_path"),
                            "source_kind": "clause_direct",
                            "chunk_type": str(block.get("block_type") or "content"),
                            "strategy": "clause_direct_v1",
                            "citation_target_id": block.get("block_id"),
                            "clause_id": clause_id,
                        },
                    )
                )
        return candidates


clause_resolver = ClauseResolver()
