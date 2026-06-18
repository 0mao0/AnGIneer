"""canonical 读模型从语义图重建的回归测试。"""

import gc
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

DOCS_CORE_SRC = Path(__file__).resolve().parents[1] / "src"
if str(DOCS_CORE_SRC) not in sys.path:
    sys.path.insert(0, str(DOCS_CORE_SRC))

from docs_core.ingest.organize.builder import rebuild_canonical_document_from_graph
from docs_core.ingest.store.canonical_sql_store import CanonicalSQLiteStore
from docs_core.knowledge_service import KnowledgeService


class CanonicalGraphProjectionTests(unittest.TestCase):
    """验证语义图到 canonical/citation 的单向投影。"""

    def test_rebuild_canonical_document_prefers_semantic_graph(self) -> None:
        """builder 应直接消费 graph nodes/edges 重建 blocks 与 citation targets。"""
        graph = {
            "nodes": [
                {"block_uid": "title-1", "block_type": "title", "plain_text": "1 总则", "page_idx": 0, "block_seq": 1, "derived_level": 1},
                {"block_uid": "figure-1", "block_type": "image", "plain_text": "系统架构图", "page_idx": 0, "block_seq": 2, "caption": "图 1 系统架构图"},
                {"block_uid": "formula-1", "block_type": "equation_interline", "plain_text": "E=mc^2", "page_idx": 0, "block_seq": 3, "content_json": {"formula_number": "(1)", "formula_summary": "能量守恒公式"}},
            ],
            "edges": [
                {"source": "title-1", "target": "figure-1", "relation": "contains"},
                {"source": "title-1", "target": "formula-1", "relation": "contains"},
            ],
        }

        document = rebuild_canonical_document_from_graph("default", "doc-1", graph, title="规范文档")

        self.assertEqual(document.blocks[1].block_type, "figure")
        self.assertTrue(document.chunks)
        target_types = {item.target_type for item in document.citation_targets}
        self.assertIn("figure", target_types)
        self.assertIn("formula", target_types)

    def test_store_lists_graph_level_citation_targets(self) -> None:
        """store 应能独立查询图级 citation targets。"""
        graph = {
            "nodes": [
                {"block_uid": "title-1", "block_type": "title", "plain_text": "1 总则", "page_idx": 0, "block_seq": 1, "derived_level": 1},
                {"block_uid": "figure-1", "block_type": "image", "plain_text": "系统架构图", "page_idx": 0, "block_seq": 2, "caption": "图 1 系统架构图"},
                {"block_uid": "formula-1", "block_type": "equation_interline", "plain_text": "E=mc^2", "page_idx": 0, "block_seq": 3, "content_json": {"formula_number": "(1)", "formula_summary": "能量守恒公式"}},
            ],
            "edges": [],
        }
        document = rebuild_canonical_document_from_graph("default", "doc-1", graph, title="规范文档")

        temp_dir = tempfile.mkdtemp()
        try:
            store = CanonicalSQLiteStore(db_path=Path(temp_dir) / "canonical.sqlite")
            stats = store.save_document(document)
            targets = store.list_citation_targets("doc-1")
            store = None
            gc.collect()
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)

        target_types = {item["target_type"] for item in targets}
        self.assertGreaterEqual(stats["citations"], 2)
        self.assertIn("figure", target_types)
        self.assertIn("formula", target_types)

    def test_save_semantic_graph_projection_rebuilds_vectors_from_graph(self) -> None:
        """KnowledgeService 应走 graph -> canonical -> vector 的单向流程。"""
        graph = {
            "nodes": [
                {"block_uid": "title-1", "block_type": "title", "plain_text": "1 总则", "page_idx": 0, "block_seq": 1, "derived_level": 1},
                {"block_uid": "figure-1", "block_type": "image", "plain_text": "系统架构图", "page_idx": 0, "block_seq": 2, "caption": "图 1 系统架构图"},
            ],
            "edges": [],
        }
        temp_dir = tempfile.mkdtemp()
        try:
            temp_root = Path(temp_dir)
            with (
                patch("docs_core.knowledge_service.resolve_knowledge_meta_db_path", return_value=temp_root / "meta.sqlite"),
                patch("docs_core.knowledge_service.resolve_knowledge_index_db_path", return_value=temp_root / "index.sqlite"),
                patch("docs_core.knowledge_service.get_vectorstore_provider_name", return_value="sqlite"),
            ):
                service = KnowledgeService()
            with (
                patch("docs_core.indexing.build_vector_records", return_value=[{"entity_id": "chunk-1"}]),
                patch.object(service.vector_store, "clear_document") as clear_vectors,
                patch.object(service.vector_store, "upsert_records") as upsert_records,
            ):
                stats = service.save_semantic_graph_projection("default", "doc-1", graph, title="规范文档")
            service = None
            gc.collect()
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)

        self.assertGreaterEqual(stats["citations"], 1)
        clear_vectors.assert_called_once_with("doc-1")
        upsert_records.assert_called_once()


if __name__ == "__main__":
    unittest.main()
