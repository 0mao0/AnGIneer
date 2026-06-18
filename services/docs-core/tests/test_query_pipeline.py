"""检索主链、引用协议与评测指标的回归测试。"""

import gc
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

DOCS_CORE_SRC = Path(__file__).resolve().parents[1] / "src"
ANGINEER_CORE_SRC = Path(__file__).resolve().parents[2] / "angineer-core" / "src"
EVALS_CORE_SRC = Path(__file__).resolve().parents[2] / "evals-core" / "src"
if str(DOCS_CORE_SRC) not in sys.path:
    sys.path.insert(0, str(DOCS_CORE_SRC))
if str(ANGINEER_CORE_SRC) not in sys.path:
    sys.path.insert(0, str(ANGINEER_CORE_SRC))
if str(EVALS_CORE_SRC) not in sys.path:
    sys.path.insert(0, str(EVALS_CORE_SRC))

from angineer_core.dispatcher import Dispatcher
from docs_core.ingest.organize.types import CanonicalChunk, CanonicalDocument, CitationTarget
from docs_core.ingest.store.canonical_sql_store import CanonicalSQLiteStore
from docs_core.knowledge_service import KnowledgeService
from docs_core.query_protocols.contracts import RetrievedItem
from docs_core.retrieval.hybrid_retriever import get_source_weight
from evals_core.runner.retrieval_eval import compute_citation_hit


class QueryPipelineTests(unittest.TestCase):
    """覆盖 FTS、增量索引、稳定引用与评测指标。"""

    def test_search_chunk_fts_matches_title_and_figure_caption(self) -> None:
        """FTS 应能按 OR 语义命中标题块与图注块。"""
        temp_dir = tempfile.mkdtemp()
        try:
            store = CanonicalSQLiteStore(db_path=Path(temp_dir) / "canonical.sqlite")
            document = CanonicalDocument(
                doc_id="doc-1",
                library_id="default",
                title="规范文档",
                chunks=[
                    CanonicalChunk(
                        chunk_id="chunk-title",
                        doc_id="doc-1",
                        chunk_type="content",
                        text="1 总则",
                        text_clean="1 总则",
                        section_path="第一章/总则",
                        page_start=0,
                        page_end=0,
                        citation_targets=[
                            CitationTarget(
                                target_id="title-1",
                                target_type="title",
                                doc_id="doc-1",
                                page_idx=0,
                                section_path="第一章/总则",
                                display_title="1 总则",
                                snippet="1 总则",
                            )
                        ],
                    ),
                    CanonicalChunk(
                        chunk_id="chunk-figure",
                        doc_id="doc-1",
                        chunk_type="content",
                        text="图 1 系统架构图",
                        text_clean="图 1 系统架构图",
                        section_path="第一章/总则",
                        page_start=0,
                        page_end=0,
                        citation_targets=[
                            CitationTarget(
                                target_id="figure-1",
                                target_type="figure",
                                doc_id="doc-1",
                                page_idx=0,
                                section_path="第一章/总则",
                                display_title="图 1 系统架构图",
                                snippet="图 1 系统架构图",
                            )
                        ],
                    ),
                ],
                citation_targets=[
                    CitationTarget(
                        target_id="title-1",
                        target_type="title",
                        doc_id="doc-1",
                        page_idx=0,
                        section_path="第一章/总则",
                        display_title="1 总则",
                        snippet="1 总则",
                    ),
                    CitationTarget(
                        target_id="figure-1",
                        target_type="figure",
                        doc_id="doc-1",
                        page_idx=0,
                        section_path="第一章/总则",
                        display_title="图 1 系统架构图",
                        snippet="图 1 系统架构图",
                    ),
                ],
            )
            store.save_document(document)

            results = store.search_chunk_fts("doc-1", "总则 架构图")
            store = None
            gc.collect()
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)

        chunk_ids = {item["chunk_id"] for item in results}
        self.assertIn("chunk-title", chunk_ids)
        self.assertIn("chunk-figure", chunk_ids)

    def test_rebuild_document_indexes_only_replaces_changed_chunks(self) -> None:
        """增量刷新时应只删除变更 chunk，而不是整篇清空。"""
        temp_dir = tempfile.mkdtemp()
        try:
            temp_root = Path(temp_dir)
            with (
                patch("docs_core.knowledge_service.resolve_knowledge_meta_db_path", return_value=temp_root / "meta.sqlite"),
                patch("docs_core.knowledge_service.resolve_knowledge_index_db_path", return_value=temp_root / "index.sqlite"),
                patch("docs_core.knowledge_service.get_vectorstore_provider_name", return_value="sqlite"),
            ):
                service = KnowledgeService()

            document = CanonicalDocument(
                doc_id="doc-1",
                library_id="default",
                title="规范文档",
                chunks=[
                    CanonicalChunk(
                        chunk_id="chunk-2",
                        doc_id="doc-1",
                        chunk_type="content",
                        text="增量刷新内容",
                        text_clean="增量刷新内容",
                        section_path="第一章/总则",
                        page_start=0,
                        page_end=0,
                    )
                ],
            )
            service.canonical_store.save_document(document)

            with (
                patch("docs_core.indexing.build_vector_records", return_value=[{"entity_id": "chunk-2"}]),
                patch.object(service.vector_store, "delete_records", return_value=1) as delete_records,
                patch.object(service.vector_store, "clear_document") as clear_document,
                patch.object(service.vector_store, "upsert_records") as upsert_records,
            ):
                service.rebuild_document_indexes("doc-1", document, changed_chunk_ids=["chunk-2"])

            service = None
            gc.collect()
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)

        delete_records.assert_called_once_with(doc_id="doc-1", entity_ids=["chunk-2"])
        clear_document.assert_not_called()
        upsert_records.assert_called_once()

    def test_dispatcher_builds_citations_from_citation_targets(self) -> None:
        """dispatcher 应优先基于稳定 citation target 构建引用。"""
        item = RetrievedItem(
            item_id="chunk-1",
            entity_type="content",
            doc_id="doc-1",
            title="总则",
            text="引用正文片段",
            score=0.93,
            citation_target_id="figure-1",
            metadata={"fusion_sources": ["canonical_sparse"]},
        )
        doc_nodes = [SimpleNamespace(id="doc-1", title="规范文档")]
        mock_service = Mock()
        mock_service.get_citation_target.return_value = {
            "target_id": "figure-1",
            "target_type": "figure",
            "page_idx": 2,
            "section_path": "第一章/总则",
            "display_title": "图 1 系统架构图",
            "snippet": "图 1 系统架构图",
        }

        with patch("docs_core.knowledge_service.get_knowledge_service", return_value=mock_service):
            citations = Dispatcher._build_citations_from_retrieved([item], doc_nodes)

        self.assertEqual(citations[0]["reference"]["targetId"], "figure-1")
        self.assertEqual(citations[0]["reference"]["targetType"], "figure")
        self.assertEqual(citations[0]["reference"]["pageIdx"], 2)
        self.assertEqual(citations[0]["reference"]["sectionPath"], "第一章/总则")

    def test_retrieval_evaluator_reports_citation_hit(self) -> None:
        """评测器应识别 reference 协议中的稳定 targetId。"""
        predicted = [{
            "label": "图 1 系统架构图",
            "reference": {
                "targetId": "figure-1",
                "targetType": "figure",
                "docId": "doc-1",
            },
        }]

        self.assertEqual(compute_citation_hit(predicted, ["figure-1"]), 1.0)
        self.assertEqual(compute_citation_hit(predicted, ["formula-1"]), 0.0)

    def test_get_source_weight_supports_policy_override(self) -> None:
        """hybrid 权重应支持按任务类型覆写。"""
        policy = {"definition_qa": {"canonical_sparse": 2.5}}
        self.assertEqual(get_source_weight("canonical_sparse", "definition_qa", policy=policy), 2.5)


if __name__ == "__main__":
    unittest.main()
