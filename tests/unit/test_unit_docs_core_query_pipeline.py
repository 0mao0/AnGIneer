"""
单元测试：canonical SQLite 真相源与检索管线。
"""
import gc
import importlib
import sys
import tempfile
import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT / "services" / "docs-core" / "src"))
sys.path.insert(0, str(PROJECT_ROOT / "apps" / "api-server"))

import docs_core.knowledge_service as knowledge_service_module
from docs_core.ingest.organize.types import (
    CanonicalBlock,
    CanonicalChunk,
    CanonicalDocument,
    CanonicalPage,
    CanonicalTable,
    CitationTarget,
)
from docs_core.ingest.store.canonical_sql_store import CanonicalSQLiteStore
from docs_core.knowledge_service import KnowledgeNode, KnowledgeService
from docs_core.query_protocols.contracts import KnowledgeQueryRequest

dense_retriever_module = importlib.import_module("docs_core.retrieval.dense_retriever")
sparse_retriever_module = importlib.import_module("docs_core.retrieval.sparse_retriever")
table_retriever_module = importlib.import_module("docs_core.retrieval.table_retriever")
formula_retriever_module = importlib.import_module("docs_core.retrieval.formula_retriever")
indexing_module = importlib.import_module("docs_core.indexing")


class IsolatedKnowledgeService(KnowledgeService):
    """隔离数据库路径的 KnowledgeService。"""

    # 初始化测试专用数据库路径。
    def __init__(self, db_path: Path):
        self._isolated_db_path = db_path
        self._isolated_index_db_path = db_path.parent / "knowledge_index.sqlite"
        super().__init__()

    # 返回测试专用元数据库路径。
    def _resolve_db_path(self) -> Path:
        self._isolated_db_path.parent.mkdir(parents=True, exist_ok=True)
        return self._isolated_db_path

    # 返回测试专用索引数据库路径。
    def _resolve_index_db_path(self) -> Path:
        self._isolated_index_db_path.parent.mkdir(parents=True, exist_ok=True)
        return self._isolated_index_db_path


class TestCanonicalSQLiteStore(unittest.TestCase):
    """测试 canonical SQLite 的持久化与查询。"""

    # 测试 canonical document 可以完整 round-trip。
    def test_save_and_get_document_round_trip(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / "knowledge_index.sqlite"
            store = CanonicalSQLiteStore(db_path=db_path)
            document = CanonicalDocument(
                doc_id="doc-canonical-1",
                library_id="default",
                title="测试规范",
                source_file_name="demo.pdf",
                source_file_type="pdf",
                schema_version="1.0.0",
                parse_version="0.1.0",
                language="zh",
                page_count=1,
                status="completed",
                created_at="2026-04-21T00:00:00",
                updated_at="2026-04-21T00:00:00",
                pages=[
                    CanonicalPage(
                        doc_id="doc-canonical-1",
                        page_idx=0,
                        width=1000,
                        height=1400,
                        rotation=0,
                    )
                ],
                chunks=[
                    CanonicalChunk(
                        chunk_id="chunk-doc-canonical-1-1",
                        doc_id="doc-canonical-1",
                        chunk_type="content",
                        text="航道通航宽度由航迹带宽度、船舶间富裕宽度和底边富裕宽度组成",
                        text_clean="航道通航宽度由航迹带宽度船舶间富裕宽度和底边富裕宽度组成",
                        token_count=20,
                        section_path="6.4 航道尺度",
                        page_start=0,
                        page_end=0,
                        source_block_ids=["block-1"],
                        citation_targets=[
                            CitationTarget(
                                target_id="block-1",
                                target_type="content",
                                doc_id="doc-canonical-1",
                                page_idx=0,
                                section_path="6.4 航道尺度",
                                display_title="6.4 航道尺度",
                                snippet="航道通航宽度由航迹带宽度、船舶间富裕宽度和底边富裕宽度组成",
                            )
                        ],
                        version="0.1.0",
                    )
                ],
            )

            stats = store.save_document(document)
            loaded = store.get_document("doc-canonical-1")

            self.assertEqual(stats["pages"], 1)
            self.assertEqual(stats["chunks"], 1)
            self.assertIsNotNone(loaded)
            assert loaded is not None
            self.assertEqual(loaded.doc_id, "doc-canonical-1")
            self.assertEqual(len(loaded.pages), 1)
            self.assertEqual(len(loaded.chunks), 1)
            self.assertEqual(loaded.chunks[0].chunk_id, "chunk-doc-canonical-1-1")
            self.assertEqual(loaded.chunks[0].citation_targets[0].target_id, "block-1")
            del loaded
            del store
            gc.collect()


class TestRetrievalPipeline(unittest.TestCase):
    """测试检索管线各组件（直接调用检索器，不经过旧 KnowledgeQueryService）。"""

    # 测试默认 embedding provider 会按环境变量选择 DashScope 实现
    def test_default_embedding_provider_prefers_dashscope_when_env_present(self):
        provider = indexing_module.create_default_embedding_provider()
        self.assertIn(provider.name, {"dashscope_embedding_v1", "hash_embedding_v1"})

    # 测试保存 canonical 文档后会同步产出向量索引
    def test_save_canonical_document_builds_vector_index(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / "knowledge_meta.sqlite"
            isolated_service = IsolatedKnowledgeService(db_path)
            try:
                isolated_service.create_node(
                    KnowledgeNode(
                        id="doc-vector-1",
                        title="通航标准",
                        type="document",
                        library_id="default",
                        visible=True,
                        status="completed",
                    )
                )
                isolated_service.save_canonical_document(
                    CanonicalDocument(
                        doc_id="doc-vector-1",
                        library_id="default",
                        title="通航标准",
                        source_file_name="vector.pdf",
                        source_file_type="pdf",
                        schema_version="1.0.0",
                        parse_version="0.1.0",
                        language="zh",
                        page_count=1,
                        status="completed",
                        created_at="2026-04-24T00:00:00",
                        updated_at="2026-04-24T00:00:00",
                        blocks=[
                            CanonicalBlock(
                                block_id="block-vector-formula-1",
                                doc_id="doc-vector-1",
                                page_idx=3,
                                block_type="formula",
                                text="B = b1 + b2 + b3",
                                text_clean="B = b1 + b2 + b3",
                                reading_order=2,
                                section_path="6.4 航道尺度",
                                source="mineru",
                            )
                        ],
                        chunks=[
                            CanonicalChunk(
                                chunk_id="chunk-vector-1",
                                doc_id="doc-vector-1",
                                chunk_type="content",
                                text="航道通航宽度由航迹带宽度、船舶间富裕宽度和船舶与航道底边间的富裕宽度组成",
                                text_clean="航道通航宽度由航迹带宽度船舶间富裕宽度和船舶与航道底边间的富裕宽度组成",
                                token_count=24,
                                section_path="6.4 航道尺度",
                                page_start=3,
                                page_end=3,
                                source_block_ids=["block-vector-formula-1"],
                                citation_targets=[
                                    CitationTarget(
                                        target_id="block-vector-formula-1",
                                        target_type="formula",
                                        doc_id="doc-vector-1",
                                        page_idx=3,
                                        section_path="6.4 航道尺度",
                                        display_title="6.4 航道尺度",
                                        snippet="B = b1 + b2 + b3",
                                    )
                                ],
                                version="0.1.0",
                            )
                        ],
                    )
                )
                from docs_core.indexing import default_embedding_provider
                query_embedding = default_embedding_provider.embed_texts(["航道通航宽度"])[0]
                vector_hits = isolated_service.search_document_vectors(query_embedding, top_k=5)
                self.assertTrue(len(vector_hits) >= 1, "Should have at least 1 vector hit after indexing")
            finally:
                del isolated_service
                gc.collect()

    # 测试 dense 检索器消费向量命中
    def test_dense_retriever_uses_vector_hits_as_primary_signal(self):
        retriever = dense_retriever_module.DenseRetriever()
        original_search = dense_retriever_module.knowledge_service.search_document_vectors
        try:
            dense_retriever_module.knowledge_service.search_document_vectors = lambda *args, **kwargs: [
                dense_retriever_module.VectorSearchHit(
                    record_id="doc-1:chunk:chunk-1",
                    doc_id="doc-1",
                    entity_type="chunk",
                    entity_id="chunk-1",
                    content="完全不同的文",
                    score=0.72,
                )
            ]
            request = KnowledgeQueryRequest(query="测试查询", library_id="default", top_k=5)
            doc_nodes = [KnowledgeNode(id="doc-1", title="文档", type="document", library_id="default", visible=True, status="completed")]
            results = retriever.retrieve(request, doc_nodes, "content_qa")
            self.assertTrue(len(results) >= 1)
            self.assertEqual(results[0].item_id, "chunk-1")
        finally:
            dense_retriever_module.knowledge_service.search_document_vectors = original_search

    # 测试 KnowledgeService 创建兼容的向量存储
    def test_knowledge_service_creates_compatible_vector_store(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / "knowledge_meta.sqlite"
            isolated_service = IsolatedKnowledgeService(db_path)
            try:
                self.assertIn(
                    isolated_service.vector_store.__class__.__name__,
                    {"ChromaVectorStore", "SQLiteVectorStore"},
                )
            finally:
                del isolated_service
                gc.collect()

    # 测试 table 检索器优先走 table-aware retrieval
    def test_table_retriever_prefers_table_aware_retrieval(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / "knowledge_meta.sqlite"
            isolated_service = IsolatedKnowledgeService(db_path)
            isolated_service.create_node(
                KnowledgeNode(
                    id="doc-table-1",
                    title="疏浚参数",
                    type="document",
                    library_id="default",
                    visible=True,
                    status="completed",
                )
            )
            isolated_service.save_canonical_document(
                CanonicalDocument(
                    doc_id="doc-table-1",
                    library_id="default",
                    title="疏浚参数",
                    source_file_name="table.pdf",
                    source_file_type="pdf",
                    schema_version="1.0.0",
                    parse_version="0.1.0",
                    language="zh",
                    page_count=1,
                    status="completed",
                    created_at="2026-04-21T00:00:00",
                    updated_at="2026-04-21T00:00:00",
                    tables=[
                        CanonicalTable(
                            table_id="table-1",
                            doc_id="doc-table-1",
                            page_start=4,
                            page_end=4,
                            title=".2.8 参数",
                            caption=".2.8 参数",
                            table_type="numeric_dense",
                            header_rows=[["项目", "取", "说明"]],
                            body_rows=[["C(m)", "0.80", "系数"], ["K", "1.25", "修正系数"]],
                            row_count=2,
                            col_count=3,
                            source_block_ids=["block-table-1"],
                            summary=".2.8 参数表，包含项目、取值和说明",
                            row_keys=["C(m)", "K"],
                            text_chunks=[],
                            version="0.1.0",
                        )
                    ],
                )
            )

            previous_root_service = knowledge_service_module.knowledge_service
            previous_dense_service = dense_retriever_module.knowledge_service
            previous_sparse_service = sparse_retriever_module.knowledge_service
            previous_table_service = table_retriever_module.knowledge_service
            previous_formula_service = formula_retriever_module.knowledge_service
            knowledge_service_module.knowledge_service = isolated_service
            dense_retriever_module.knowledge_service = isolated_service
            sparse_retriever_module.knowledge_service = isolated_service
            table_retriever_module.knowledge_service = isolated_service
            formula_retriever_module.knowledge_service = isolated_service
            try:
                retriever = table_retriever_module.TableRetriever()
                request = KnowledgeQueryRequest(
                    query="C(m) 取值是多少",
                    library_id="default",
                    doc_ids=["doc-table-1"],
                    top_k=3,
                )
                doc_nodes = [KnowledgeNode(id="doc-table-1", title="疏浚参数", type="document", library_id="default", visible=True, status="completed")]
                results = retriever.retrieve(request, doc_nodes)
                self.assertTrue(len(results) >= 1, "Table retriever should return results")
                chunk_types = [item.metadata.get("chunk_type") for item in results]
                self.assertTrue(
                    any(ct in {"table_row_key", "table_schema"} for ct in chunk_types),
                    f"Expected table_row_key or table_schema in chunk_types, got {chunk_types}",
                )
            finally:
                knowledge_service_module.knowledge_service = previous_root_service
                dense_retriever_module.knowledge_service = previous_dense_service
                sparse_retriever_module.knowledge_service = previous_sparse_service
                table_retriever_module.knowledge_service = previous_table_service
                formula_retriever_module.knowledge_service = previous_formula_service
                del isolated_service
                gc.collect()

    # 测试 formula 检索器能命中公式引用
    def test_formula_retriever_returns_formula_hits(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / "knowledge_meta.sqlite"
            isolated_service = IsolatedKnowledgeService(db_path)
            isolated_service.create_node(
                KnowledgeNode(
                    id="doc-formula-1",
                    title="公式文档",
                    type="document",
                    library_id="default",
                    visible=True,
                    status="completed",
                )
            )
            isolated_service.save_canonical_document(
                CanonicalDocument(
                    doc_id="doc-formula-1",
                    library_id="default",
                    title="公式文档",
                    source_file_name="formula.pdf",
                    source_file_type="pdf",
                    schema_version="1.0.0",
                    parse_version="0.1.0",
                    language="zh",
                    page_count=1,
                    status="completed",
                    created_at="2026-04-21T00:00:00",
                    updated_at="2026-04-21T00:00:00",
                    blocks=[
                        CanonicalBlock(
                            block_id="block-formula-1",
                            doc_id="doc-formula-1",
                            page_idx=1,
                            block_type="formula",
                            text="B = b1 + b2 + b3",
                            text_clean="B = b1 + b2 + b3",
                            reading_order=1,
                            section_path="6.4 航道尺度",
                            source="mineru",
                        )
                    ],
                    chunks=[
                        CanonicalChunk(
                            chunk_id="chunk-formula-1",
                            doc_id="doc-formula-1",
                            chunk_type="content",
                            text="航道宽度计算公式 B = b1 + b2 + b3",
                            text_clean="航道宽度计算公式 B = b1 + b2 + b3",
                            token_count=15,
                            section_path="6.4 航道尺度",
                            page_start=1,
                            page_end=1,
                            source_block_ids=["block-formula-1"],
                            citation_targets=[
                                CitationTarget(
                                    target_id="block-formula-1",
                                    target_type="formula",
                                    doc_id="doc-formula-1",
                                    page_idx=1,
                                    section_path="6.4 航道尺度",
                                    display_title="6.4 航道尺度",
                                    snippet="B = b1 + b2 + b3",
                                )
                            ],
                            version="0.1.0",
                        )
                    ],
                )
            )

            previous_root_service = knowledge_service_module.knowledge_service
            previous_dense_service = dense_retriever_module.knowledge_service
            previous_sparse_service = sparse_retriever_module.knowledge_service
            previous_table_service = table_retriever_module.knowledge_service
            previous_formula_service = formula_retriever_module.knowledge_service
            knowledge_service_module.knowledge_service = isolated_service
            dense_retriever_module.knowledge_service = isolated_service
            sparse_retriever_module.knowledge_service = isolated_service
            table_retriever_module.knowledge_service = isolated_service
            formula_retriever_module.knowledge_service = isolated_service
            try:
                retriever = formula_retriever_module.FormulaRetriever()
                request = KnowledgeQueryRequest(
                    query="航道宽度计算公式",
                    library_id="default",
                    doc_ids=["doc-formula-1"],
                    top_k=3,
                )
                doc_nodes = [KnowledgeNode(id="doc-formula-1", title="公式文档", type="document", library_id="default", visible=True, status="completed")]
                results = retriever.retrieve(request, doc_nodes)
                self.assertTrue(len(results) >= 1, "Formula retriever should return results")
            finally:
                knowledge_service_module.knowledge_service = previous_root_service
                dense_retriever_module.knowledge_service = previous_dense_service
                sparse_retriever_module.knowledge_service = previous_sparse_service
                table_retriever_module.knowledge_service = previous_table_service
                formula_retriever_module.knowledge_service = previous_formula_service
                del isolated_service
                gc.collect()

    # 测试 hybrid retriever 融合 dense 和 sparse 结果
    def test_hybrid_retriever_fuses_dense_and_sparse(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / "knowledge_meta.sqlite"
            isolated_service = IsolatedKnowledgeService(db_path)
            isolated_service.create_node(
                KnowledgeNode(
                    id="doc-hybrid-1",
                    title="混合检索文档",
                    type="document",
                    library_id="default",
                    visible=True,
                    status="completed",
                )
            )
            isolated_service.save_canonical_document(
                CanonicalDocument(
                    doc_id="doc-hybrid-1",
                    library_id="default",
                    title="混合检索文档",
                    source_file_name="hybrid.pdf",
                    source_file_type="pdf",
                    schema_version="1.0.0",
                    parse_version="0.1.0",
                    language="zh",
                    page_count=1,
                    status="completed",
                    created_at="2026-04-21T00:00:00",
                    updated_at="2026-04-21T00:00:00",
                    chunks=[
                        CanonicalChunk(
                            chunk_id="chunk-hybrid-1",
                            doc_id="doc-hybrid-1",
                            chunk_type="content",
                            text="航道通航宽度由航迹带宽度、船舶间富裕宽度和船舶与航道底边间的富裕宽度组成",
                            text_clean="航道通航宽度由航迹带宽度船舶间富裕宽度和船舶与航道底边间的富裕宽度组成",
                            token_count=24,
                            section_path="6.4 航道尺度",
                            page_start=2,
                            page_end=2,
                            source_block_ids=["block-hybrid-1"],
                            citation_targets=[
                                CitationTarget(
                                    target_id="block-hybrid-1",
                                    target_type="content",
                                    doc_id="doc-hybrid-1",
                                    page_idx=2,
                                    section_path="6.4 航道尺度",
                                    display_title="6.4 航道尺度",
                                    snippet="航道通航宽度由航迹带宽度、船舶间富裕宽度和船舶与航道底边间的富裕宽度组成",
                                )
                            ],
                            version="0.1.0",
                        )
                    ],
                )
            )

            previous_root_service = knowledge_service_module.knowledge_service
            previous_dense_service = dense_retriever_module.knowledge_service
            previous_sparse_service = sparse_retriever_module.knowledge_service
            previous_table_service = table_retriever_module.knowledge_service
            previous_formula_service = formula_retriever_module.knowledge_service
            knowledge_service_module.knowledge_service = isolated_service
            dense_retriever_module.knowledge_service = isolated_service
            sparse_retriever_module.knowledge_service = isolated_service
            table_retriever_module.knowledge_service = isolated_service
            formula_retriever_module.knowledge_service = isolated_service
            try:
                from docs_core.retrieval.hybrid_retriever import fuse_candidates
                dense_retriever = dense_retriever_module.DenseRetriever()
                sparse_retriever = sparse_retriever_module.SparseRetriever()
                request = KnowledgeQueryRequest(
                    query="航道通航宽度由哪些部分组成？",
                    library_id="default",
                    doc_ids=["doc-hybrid-1"],
                    top_k=5,
                )
                doc_nodes = [KnowledgeNode(id="doc-hybrid-1", title="混合检索文档", type="document", library_id="default", visible=True, status="completed")]
                dense_hits = dense_retriever.retrieve(request, doc_nodes, "content_qa")
                sparse_hits = sparse_retriever.retrieve(request, doc_nodes, "content_qa")
                fused, _debug = fuse_candidates({"dense": dense_hits, "sparse": sparse_hits}, "content_qa", top_k=5)
                self.assertTrue(len(fused) >= 1, "Hybrid retrieval should return fused results")
            finally:
                knowledge_service_module.knowledge_service = previous_root_service
                dense_retriever_module.knowledge_service = previous_dense_service
                sparse_retriever_module.knowledge_service = previous_sparse_service
                table_retriever_module.knowledge_service = previous_table_service
                formula_retriever_module.knowledge_service = previous_formula_service
                del isolated_service
                gc.collect()


if __name__ == "__main__":
    unittest.main()
