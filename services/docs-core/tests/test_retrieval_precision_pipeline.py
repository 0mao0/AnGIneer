"""规范文档检索精度主链的专项回归测试。"""

import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch


DOCS_CORE_SRC = Path(__file__).resolve().parents[1] / "src"
if str(DOCS_CORE_SRC) not in sys.path:
    sys.path.insert(0, str(DOCS_CORE_SRC))

from docs_core.ingest.organize.types import CanonicalBlock, CanonicalChunk, CanonicalDocument, CitationTarget
from docs_core.ingest.store.canonical_sql_store import CanonicalSQLiteStore
from docs_core.query_protocols.contracts import KnowledgeQueryRequest, RetrievedItem
from docs_core.retrieval.dense_retriever import score_text
from docs_core.retrieval.hybrid_retriever import fuse_candidates
from docs_core.retrieval.query_normalizer import extract_formula_identifiers, extract_query_signals
from docs_core.retrieval.sparse_retriever import sparse_retriever


class RetrievalPrecisionPipelineTests(unittest.TestCase):
    """覆盖 query signal 与 target recall。"""

    def test_extract_query_signals_for_clause_figure_and_formula(self) -> None:
        """应抽取条款、图号、公式相关的检索信号。"""
        clause_signals = extract_query_signals("4.2.3 条关于港口水位有什么要求？")
        self.assertEqual(clause_signals["question_type"], "locate_clause")
        self.assertEqual(clause_signals["clause_refs"], ["4.2.3"])

        figure_signals = extract_query_signals("海港2 中图 3 说明的是哪种布置形式？")
        self.assertEqual(figure_signals["question_type"], "locate_figure")
        self.assertEqual(figure_signals["figure_refs"], ["3"])

        formula_signals = extract_query_signals("弯矩设计值的公式在哪一节？")
        self.assertEqual(formula_signals["question_type"], "locate_formula")
        self.assertIn("公式", "".join(formula_signals["raw_tokens"]))

    def test_score_text_matches_formula_identifier_aliases(self) -> None:
        """公式符号查询应能命中 LaTeX 形式的同义表达。"""
        query_tokens = extract_query_signals("混凝土结构设计规范附录 C 中 ε_t,r 的公式在哪一节？")["keywords"]

        target_score = score_text(
            query_tokens,
            "附录 C / C.2 混凝土本构关系",
            r"\varepsilon_{t,r} = f_{t,r}^{0.54} \times 65 \times 10^{-6}",
        )
        distractor_score = score_text(
            query_tokens,
            "附录 C / C.2 混凝土本构关系",
            r"\varepsilon_{c,r} = (700 + 172 \sqrt{f_c}) \times 10^{-6}",
        )

        self.assertGreater(target_score, 0.0)
        self.assertGreater(target_score, distractor_score)

    def test_score_text_matches_formula_identifier_with_mathrm_wrapper(self) -> None:
        """公式符号查询应能命中带 `\\mathrm{}` 包装的 LaTeX 下标写法。"""
        query_tokens = extract_query_signals("混凝土结构设计规范附录 C 中 ε_t,r 的公式在哪一节？")["keywords"]

        target_score = score_text(
            query_tokens,
            "附录 C / C.2 混凝土本构关系",
            r"\varepsilon_ {\mathrm{t}, \mathrm{r}} = f _ {\mathrm{t}, \mathrm{r}} ^ {0.54}",
        )
        distractor_score = score_text(
            query_tokens,
            "附录 C / C.2 混凝土本构关系",
            r"\varepsilon_ {\mathrm{c}, \mathrm{r}} = (700 + 172 \sqrt{f _ {\mathrm{c}}})",
        )

        self.assertGreater(target_score, distractor_score)

    def test_extract_formula_identifiers_handles_mathrm_subscripts_with_spacing(self) -> None:
        """应识别带空格和 `\\mathrm{}` 包装的 LaTeX 下标公式符号。"""
        identifiers = extract_formula_identifiers(
            r"\varepsilon_ {\mathrm{t}, \mathrm{r}} = f _ {\mathrm{t}, \mathrm{r}} ^ {0.54}"
        )

        self.assertIn("varepsilon_tr", identifiers)

    def test_search_citation_targets_prefers_direct_figure_target_hits(self) -> None:
        """图查询应优先命中 figure 对象，而不是只返回正文 chunk。"""
        temp_dir = tempfile.mkdtemp()
        try:
            store = CanonicalSQLiteStore(db_path=Path(temp_dir) / "canonical.sqlite")
            document = CanonicalDocument(
                doc_id="harbor-2",
                library_id="default",
                title="海港2",
                blocks=[
                    CanonicalBlock(
                        block_id="figure:3",
                        doc_id="harbor-2",
                        block_type="figure",
                        text="图 3 港池布置形式",
                        page_idx=2,
                        section_path="第三章/图3",
                    ),
                    CanonicalBlock(
                        block_id="content:3",
                        doc_id="harbor-2",
                        block_type="paragraph",
                        text="正文对布置形式的说明",
                        page_idx=2,
                        section_path="第三章/正文说明",
                    ),
                ],
                citation_targets=[
                    CitationTarget(
                        target_id="figure:3",
                        target_type="figure",
                        doc_id="harbor-2",
                        page_idx=2,
                        section_path="第三章/图3",
                        display_title="图 3 港池布置形式",
                        snippet="图 3 港池布置形式",
                    ),
                ],
                chunks=[
                    CanonicalChunk(
                        chunk_id="chunk-body-3",
                        doc_id="harbor-2",
                        chunk_type="content",
                        text="正文对布置形式的说明",
                        text_clean="正文对布置形式的说明",
                        section_path="第三章/正文说明",
                        page_start=2,
                        page_end=2,
                    ),
                ],
            )
            store.save_document(document)

            target_hits = store.search_citation_targets("harbor-2", "图 3 布置形式", limit=5)

            self.assertEqual(target_hits[0]["target_id"], "figure:3")
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)

    def test_search_chunk_fts_supports_clause_query_with_dots(self) -> None:
        """条款类查询包含 4.2.3 这类编号时，不应触发 FTS 语法错误。"""
        temp_dir = tempfile.mkdtemp()
        try:
            store = CanonicalSQLiteStore(db_path=Path(temp_dir) / "canonical.sqlite")
            document = CanonicalDocument(
                doc_id="harbor-1",
                library_id="default",
                title="海港1",
                chunks=[
                    CanonicalChunk(
                        chunk_id="chunk-clause-423",
                        doc_id="harbor-1",
                        chunk_type="outline_anchor",
                        text="4.2.3 港口水位应满足设计要求",
                        text_clean="4.2.3 港口水位应满足设计要求",
                        section_path="第四章/4.2/4.2.3",
                        page_start=1,
                        page_end=1,
                    ),
                ],
            )
            store.save_document(document)

            chunk_hits = store.search_chunk_fts("harbor-1", "4.2.3 条关于港口水位有什么要求？", limit=5)

            self.assertEqual(chunk_hits[0]["chunk_id"], "chunk-clause-423")
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)

    def test_sparse_retriever_includes_target_sparse_hits_for_figure_query(self) -> None:
        """图类查询应把 citation target 直接加入候选。"""
        request = KnowledgeQueryRequest(query="海港2 中图 3 说明的是哪种布置形式？", top_k=5)
        doc_node = SimpleNamespace(id="harbor-2", title="海港2")

        with patch(
            "docs_core.retrieval.sparse_retriever.knowledge_service.canonical_store.search_citation_targets",
            return_value=[{
                "target_id": "figure:3",
                "target_type": "figure",
                "page_idx": 2,
                "section_path": "第三章/图3",
                "display_title": "图 3 港池布置形式",
                "snippet": "图 3 港池布置形式",
            }],
        ), patch(
            "docs_core.retrieval.sparse_retriever.knowledge_service.canonical_store.search_chunk_fts",
            return_value=[],
        ), patch(
            "docs_core.retrieval.sparse_retriever.knowledge_service.list_canonical_chunks",
            return_value=[],
        ), patch(
            "docs_core.retrieval.sparse_retriever.knowledge_service.list_canonical_blocks",
            return_value=[],
        ):
            items = sparse_retriever.retrieve(request, [doc_node], task_type="locate_figure")

        self.assertEqual(items[0].citation_target_id, "figure:3")
        self.assertEqual(items[0].retrieval_policy, "target_sparse")

    def test_fuse_candidates_merges_chunk_and_target_for_same_figure(self) -> None:
        """相同 citation target 的 chunk 与 target 候选应在融合后归并。"""
        figure_chunk = RetrievedItem(
            item_id="chunk-figure-3",
            entity_type="content",
            doc_id="harbor-2",
            title="第三章/图3",
            text="图 3 港池布置形式说明",
            score=0.8,
            citation_target_id="figure:3",
            metadata={
                "source_kind": "canonical_sparse",
                "chunk_type": "content",
                "citation_target_id": "figure:3",
                "target_type": "figure",
            },
        )
        figure_target = RetrievedItem(
            item_id="figure:3",
            entity_type="figure",
            doc_id="harbor-2",
            title="图 3 港池布置形式",
            text="图 3 港池布置形式",
            score=1.0,
            citation_target_id="figure:3",
            metadata={
                "source_kind": "target_sparse",
                "chunk_type": "figure",
                "citation_target_id": "figure:3",
                "target_type": "figure",
            },
        )

        fused, debug = fuse_candidates(
            {"canonical_sparse": [figure_chunk], "target_sparse": [figure_target]},
            task_type="locate_figure",
            top_k=5,
        )

        self.assertEqual(len(fused), 1)
        self.assertEqual(fused[0].citation_target_id, "figure:3")
        self.assertIn("target_sparse", fused[0].metadata["fusion_sources"])
        self.assertEqual(debug["returned_hits"], 1)

    def test_fuse_candidates_prefers_formula_context_for_locate_formula(self) -> None:
        """公式定位题在混排时应优先保留公式候选，而不是被正文 chunk 挤掉。"""
        content_item = RetrievedItem(
            item_id="chunk-content-1",
            entity_type="content",
            doc_id="doc-8474a7fe",
            title="附录 C / C.2 混凝土本构关系",
            text="附录 C 中关于混凝土本构关系的正文说明。",
            score=1.0,
            citation_target_id="doc-8474a7fe:content-1",
            metadata={
                "source_kind": "canonical_dense",
                "chunk_type": "content",
                "citation_target_id": "doc-8474a7fe:content-1",
                "target_type": "content",
            },
        )
        formula_item = RetrievedItem(
            item_id="doc-8474a7fe:19:1:context",
            entity_type="formula_context",
            doc_id="doc-8474a7fe",
            title="附录 C / C.2 混凝土本构关系",
            text=r"\varepsilon_ {\mathrm{t}, \mathrm{r}} = f _ {\mathrm{t}, \mathrm{r}} ^ {0.54}",
            score=20.0,
            citation_target_id="doc-8474a7fe:19:1",
            metadata={
                "source_kind": "formula_context",
                "chunk_type": "formula_context",
                "citation_target_id": "doc-8474a7fe:19:1",
                "target_type": "formula",
            },
        )
        stronger_formula_peer = RetrievedItem(
            item_id="doc-8474a7fe:20:8:context",
            entity_type="formula_context",
            doc_id="doc-8474a7fe",
            title="附录 C / C.4 混凝土强度准则",
            text=r"\frac{-f_1}{f_{c,r}} = 1.2 + 33 \left(\frac{\sigma_1}{\sigma_3}\right)^{1.8}",
            score=29.0,
            citation_target_id="doc-8474a7fe:20:8",
            metadata={
                "source_kind": "formula_context",
                "chunk_type": "formula_context",
                "citation_target_id": "doc-8474a7fe:20:8",
                "target_type": "formula",
            },
        )

        fused, _debug = fuse_candidates(
            {
                "canonical_dense": [content_item],
                "formula_context": [stronger_formula_peer, formula_item],
            },
            task_type="locate_formula",
            top_k=5,
        )

        ranked_targets = [item.citation_target_id for item in fused]
        self.assertLess(
            ranked_targets.index("doc-8474a7fe:19:1"),
            ranked_targets.index("doc-8474a7fe:content-1"),
        )

    def test_fuse_candidates_keeps_high_formula_score_when_merging_formula_sources(self) -> None:
        """同一公式来自多个公式源时，融合后不应因分数截断被正文候选反超。"""
        content_item = RetrievedItem(
            item_id="chunk-content-1",
            entity_type="content",
            doc_id="doc-8474a7fe",
            title="附录 C / C.2 混凝土本构关系",
            text="附录 C 中关于混凝土本构关系的正文说明。",
            score=1.0,
            citation_target_id="doc-8474a7fe:content-1",
            metadata={
                "source_kind": "canonical_dense",
                "chunk_type": "content",
                "citation_target_id": "doc-8474a7fe:content-1",
                "target_type": "content",
            },
        )
        formula_context_item = RetrievedItem(
            item_id="doc-8474a7fe:19:1:context",
            entity_type="formula_context",
            doc_id="doc-8474a7fe",
            title="附录 C / C.2 混凝土本构关系",
            text=r"\varepsilon_ {\mathrm{t}, \mathrm{r}} = f _ {\mathrm{t}, \mathrm{r}} ^ {0.54}",
            score=24.0,
            citation_target_id="doc-8474a7fe:19:1",
            metadata={
                "source_kind": "formula_context",
                "chunk_type": "formula_context",
                "citation_target_id": "doc-8474a7fe:19:1",
                "target_type": "formula",
            },
        )
        formula_block_item = RetrievedItem(
            item_id="doc-8474a7fe:19:1",
            entity_type="formula",
            doc_id="doc-8474a7fe",
            title="附录 C / C.2 混凝土本构关系",
            text=r"\varepsilon_ {\mathrm{t}, \mathrm{r}} = f _ {\mathrm{t}, \mathrm{r}} ^ {0.54}",
            score=18.0,
            citation_target_id="doc-8474a7fe:19:1",
            metadata={
                "source_kind": "formula_block",
                "chunk_type": "formula",
                "citation_target_id": "doc-8474a7fe:19:1",
                "target_type": "formula",
            },
        )

        fused, _debug = fuse_candidates(
            {
                "canonical_dense": [content_item],
                "formula_context": [formula_context_item],
                "formula_block": [formula_block_item],
            },
            task_type="locate_formula",
            top_k=5,
        )

        self.assertEqual(fused[0].citation_target_id, "doc-8474a7fe:19:1")
        self.assertGreater(float(fused[0].rerank_score or 0.0), 1.3)


if __name__ == "__main__":
    unittest.main()
