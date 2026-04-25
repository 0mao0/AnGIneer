"""
单元测试：canonical SQLite 真相源与模块化查询主链。
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
    CanonicalChunk,
    CanonicalDocument,
    CanonicalPage,
    CanonicalTable,
    CitationTarget,
    CanonicalBlock,
    CitationTarget,
)
from docs_core.ingest.store.canonical_sql_store import CanonicalSQLiteStore
from docs_core.knowledge_service import KnowledgeNode, KnowledgeService
from docs_core.query.contracts import KnowledgeQueryRequest
from docs_core.query.service import KnowledgeQueryService


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


class TestKnowledgeQueryService(unittest.TestCase):
    """测试模块化查询主链优先读canonical SQLite。"""

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
                                text="通航宽度由航迹带宽度、船舶间富裕宽度和底边富裕宽度共同组成",
                                text_clean="通航宽度由航迹带宽度船舶间富裕宽度和底边富裕宽度共同组成",
                                token_count=20,
                                section_path="6.4 航道尺度",
                                page_start=3,
                                page_end=3,
                                source_block_ids=["block-vector-formula-1"],
                                version="0.1.0",
                            )
                        ],
                        tables=[
                            CanonicalTable(
                                table_id="table-vector-1",
                                doc_id="doc-vector-1",
                                page_start=4,
                                page_end=4,
                                title=".4.1 参数",
                                caption=".4.1 参数",
                                table_type="numeric_dense",
                                header_rows=[["项目", "取"]],
                                body_rows=[["C(m)", "0.80"]],
                                row_count=1,
                                col_count=2,
                                source_block_ids=["block-vector-formula-1"],
                                summary="参数表包含项目和取值",
                                row_keys=["C(m)"],
                                text_chunks=[],
                                version="0.1.0",
                            )
                        ],
                    )
                )

                vector_stats = isolated_service.get_document_vector_stats("doc-vector-1")
                self.assertEqual(vector_stats["total_count"], 4)
                self.assertEqual(vector_stats["by_entity_type"]["chunk"]["count"], 1)
                self.assertEqual(vector_stats["by_entity_type"]["table_schema"]["count"], 1)
                self.assertEqual(vector_stats["by_entity_type"]["table_row_key"]["count"], 1)
                self.assertEqual(vector_stats["by_entity_type"]["formula"]["count"], 1)
            finally:
                del isolated_service
                gc.collect()

    # 测试查询服务会从 canonical SQLite 中召回并回答
    def test_query_reads_from_canonical_sqlite(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / "knowledge_meta.sqlite"
            isolated_service = IsolatedKnowledgeService(db_path)
            isolated_service.create_node(
                KnowledgeNode(
                    id="doc-query-1",
                    title="港口工程规范",
                    type="document",
                    library_id="default",
                    visible=True,
                    status="completed",
                )
            )
            isolated_service.save_canonical_document(
                CanonicalDocument(
                    doc_id="doc-query-1",
                    library_id="default",
                    title="港口工程规范",
                    source_file_name="demo.pdf",
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
                            chunk_id="chunk-doc-query-1-1",
                            doc_id="doc-query-1",
                            chunk_type="content",
                            text="航道通航宽度由航迹带宽度、船舶间富裕宽度和船舶与航道底边间的富裕宽度组成",
                            text_clean="航道通航宽度由航迹带宽度船舶间富裕宽度和船舶与航道底边间的富裕宽度组",
                            token_count=24,
                            section_path="6.4 航道尺度",
                            page_start=2,
                            page_end=2,
                            source_block_ids=["block-query-1"],
                            citation_targets=[
                                CitationTarget(
                                    target_id="block-query-1",
                                    target_type="content",
                                    doc_id="doc-query-1",
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
                service = KnowledgeQueryService(knowledge_service_impl=isolated_service)
                response = service.query(
                    KnowledgeQueryRequest(
                        query="航道通航宽度由哪些部分组成？",
                        library_id="default",
                        doc_ids=["doc-query-1"],
                        top_k=3,
                        include_debug=True,
                        include_retrieved=True,
                    )
                )

                self.assertEqual(response.strategy, "canonical_hybrid_v1")
                self.assertEqual(response.task_type, "content_qa")
                self.assertTrue(response.answer)
                self.assertEqual(len(response.retrieved_items), 1)
                self.assertEqual(response.retrieved_items[0].item_id, "chunk-doc-query-1-1")
                self.assertEqual(len(response.citations), 1)
                self.assertEqual(response.citations[0].doc_id, "doc-query-1")
            finally:
                knowledge_service_module.knowledge_service = previous_root_service
                dense_retriever_module.knowledge_service = previous_dense_service
                sparse_retriever_module.knowledge_service = previous_sparse_service
                table_retriever_module.knowledge_service = previous_table_service
                formula_retriever_module.knowledge_service = previous_formula_service
                del isolated_service
                gc.collect()

    # 测试 dense 检索主逻辑消费向量命中，而不是依token overlap 才能返回结果
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
                    metadata={
                        "chunk_type": "content",
                        "title": "附录A",
                        "text": "这里没有任何查询词重叠，但存在向量相似命中",
                        "section_path": "附录A",
                        "page_idx": 6,
                        "source_block_ids": ["block-1"],
                    },
                )
            ]
            results = retriever.retrieve(
                KnowledgeQueryRequest(
                    query="航道通航宽度由哪些部分组成？",
                    library_id="default",
                    doc_ids=["doc-1"],
                    top_k=3,
                ),
                [
                    KnowledgeNode(
                        id="doc-1",
                        title="测试文档",
                        type="document",
                        library_id="default",
                        visible=True,
                    )
                ],
                "content_qa",
            )
            self.assertEqual(len(results), 1)
            self.assertEqual(results[0].item_id, "chunk-1")
            self.assertGreater(results[0].score, 0.7)
            self.assertEqual(results[0].metadata.get("strategy"), "canonical_dense_vector_v1")
            self.assertEqual(results[0].metadata.get("vector_score"), 0.72)
        finally:
            dense_retriever_module.knowledge_service.search_document_vectors = original_search

    # 测试当前默认 vector store 至少可初始化，并且在缺少 chromadb 时回退SQLite
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

    # 测试 table_qa 会优先走 table-aware retrieval 命中行键schema 证据
    def test_table_query_prefers_table_aware_retrieval(self):
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
                service = KnowledgeQueryService(knowledge_service_impl=isolated_service)
                response = service.query(
                    KnowledgeQueryRequest(
                        query="C(m) 取值是多少",
                        library_id="default",
                        doc_ids=["doc-table-1"],
                        mode="auto",
                        top_k=3,
                        include_debug=True,
                        include_retrieved=True,
                    )
                )

                self.assertEqual(response.task_type, "table_qa")
                self.assertEqual(response.debug.get("retrieval_route"), "table_aware")
                self.assertFalse(response.debug.get("fallback_used"))
                self.assertTrue(response.retrieved_items)
                self.assertIn(
                    response.retrieved_items[0].metadata.get("chunk_type"),
                    {"table_row_key", "table_schema"},
                )
                self.assertIn("表格相关的证", response.answer)
            finally:
                knowledge_service_module.knowledge_service = previous_root_service
                dense_retriever_module.knowledge_service = previous_dense_service
                sparse_retriever_module.knowledge_service = previous_sparse_service
                table_retriever_module.knowledge_service = previous_table_service
                formula_retriever_module.knowledge_service = previous_formula_service
                del isolated_service
                gc.collect()

    # 测试公式编号问答不会被误判为默认拒答
    def test_formula_reference_query_returns_non_refusal_answer(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / "knowledge_meta.sqlite"
            isolated_service = IsolatedKnowledgeService(db_path)
            isolated_service.create_node(
                KnowledgeNode(
                    id="doc-formula-1",
                    title="海港规范",
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
                    title="海港规范",
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
                            page_idx=12,
                            block_type="formula",
                            text="公式(6.2.8) C = A / B",
                            text_clean="公式(6.2.8) C = A / B",
                            reading_order=1,
                            section_path="6.2 疏浚设计",
                            source="mineru",
                        )
                    ],
                    chunks=[
                        CanonicalChunk(
                            chunk_id="chunk-formula-1",
                            doc_id="doc-formula-1",
                            chunk_type="content",
                            text="公式(6.2.8) 表示通航富裕宽度系数 C 的计算关系",
                            text_clean="公式628表示通航富裕宽度系数c的计算关",
                            token_count=18,
                            section_path="6.2 疏浚设计",
                            page_start=12,
                            page_end=12,
                            source_block_ids=["block-formula-1"],
                            citation_targets=[
                                CitationTarget(
                                    target_id="block-formula-1",
                                    target_type="formula",
                                    doc_id="doc-formula-1",
                                    page_idx=12,
                                    section_path="6.2 疏浚设计",
                                    display_title="公式(6.2.8)",
                                    snippet="公式(6.2.8) 表示通航富裕宽度系数 C 的计算关系",
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
                service = KnowledgeQueryService(knowledge_service_impl=isolated_service)
                response = service.query(
                    KnowledgeQueryRequest(
                        query="公式6.2.8是什么？",
                        library_id="default",
                        doc_ids=["doc-formula-1"],
                        top_k=3,
                        include_debug=True,
                        include_retrieved=True,
                    )
                )

                self.assertEqual(response.task_type, "definition_qa")
                self.assertTrue(response.answer)
                self.assertNotIn("没有检索到足够证据", response.answer)
                self.assertTrue(response.citations)
                self.assertEqual(response.citations[0].target_id, "block-formula-1")
            finally:
                knowledge_service_module.knowledge_service = previous_root_service
                dense_retriever_module.knowledge_service = previous_dense_service
                sparse_retriever_module.knowledge_service = previous_sparse_service
                table_retriever_module.knowledge_service = previous_table_service
                formula_retriever_module.knowledge_service = previous_formula_service
                del isolated_service
                gc.collect()

    # 测试计算型问题会优先走公式专用检索并返回相邻计算依据
    def test_formula_calculation_query_prefers_formula_aware_retrieval(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / "knowledge_meta.sqlite"
            isolated_service = IsolatedKnowledgeService(db_path)
            isolated_service.create_node(
                KnowledgeNode(
                    id="doc-formula-calc-1",
                    title="海港规范",
                    type="document",
                    library_id="default",
                    visible=True,
                    status="completed",
                )
            )
            isolated_service.save_canonical_document(
                CanonicalDocument(
                    doc_id="doc-formula-calc-1",
                    library_id="default",
                    title="海港规范",
                    source_file_name="formula-calc.pdf",
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
                            block_id="block-formula-calc-1",
                            doc_id="doc-formula-calc-1",
                            page_idx=8,
                            block_type="paragraph",
                            text="6.2.8 乘潮水位应根据需要乘潮的船舶航行密度、航行持续时间合理确定",
                            text_clean="6.2.8 乘潮水位应根据需要乘潮的船舶航行密度航行持续时间合理确定",
                            reading_order=1,
                            section_path="6.2 航道建设规模及航行标",
                            source="mineru",
                        ),
                        CanonicalBlock(
                            block_id="block-formula-calc-2",
                            doc_id="doc-formula-calc-1",
                            page_idx=8,
                            block_type="paragraph",
                            text="6.2.8.1 每潮次船舶乘潮进出港所需的持续时间可按式(6.2.8)确定",
                            text_clean="6.2.8.1 每潮次船舶乘潮进出港所需的持续时间可按式628确定",
                            reading_order=2,
                            section_path="6.2 航道建设规模及航行标",
                            source="mineru",
                        ),
                        CanonicalBlock(
                            block_id="block-formula-calc-3",
                            doc_id="doc-formula-calc-1",
                            page_idx=8,
                            block_type="formula",
                            text="t_s = K_t (t_1 + t_2 + t_3) (6.2.8)",
                            text_clean="t_s = K_t (t_1 + t_2 + t_3) (6.2.8)",
                            reading_order=3,
                            section_path="6.2 航道建设规模及航行标",
                            source="mineru",
                        ),
                        CanonicalBlock(
                            block_id="block-formula-calc-4",
                            doc_id="doc-formula-calc-1",
                            page_idx=8,
                            block_type="paragraph",
                            text="6.2.8.2 单一潮位站的乘潮水位应按统计结果确定，可取与持续时间对应的乘潮累积频0%~95%的水位",
                            text_clean="6.2.8.2 单一潮位站的乘潮水位应按统计结果确定可取与持续时间对应的乘潮累积频率90%95%的水",
                            reading_order=4,
                            section_path="6.2 航道建设规模及航行标",
                            source="mineru",
                        ),
                    ],
                    chunks=[
                        CanonicalChunk(
                            chunk_id="chunk-formula-calc-1",
                            doc_id="doc-formula-calc-1",
                            chunk_type="content",
                            text="6.2.8.1 每潮次船舶乘潮进出港所需的持续时间可按式(6.2.8)确定",
                            text_clean="6.2.8.1 每潮次船舶乘潮进出港所需的持续时间可按式628确定",
                            token_count=24,
                            section_path="6.2 航道建设规模及航行标",
                            page_start=8,
                            page_end=8,
                            source_block_ids=["block-formula-calc-2", "block-formula-calc-3"],
                            citation_targets=[
                                CitationTarget(
                                    target_id="block-formula-calc-3",
                                    target_type="formula",
                                    doc_id="doc-formula-calc-1",
                                    page_idx=8,
                                    section_path="6.2 航道建设规模及航行标",
                                    display_title="6.2.8)",
                                    snippet="t_s = K_t (t_1 + t_2 + t_3) (6.2.8)",
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
                service = KnowledgeQueryService(knowledge_service_impl=isolated_service)
                response = service.query(
                    KnowledgeQueryRequest(
                        query="乘潮水位怎么计算",
                        library_id="default",
                        doc_ids=["doc-formula-calc-1"],
                        top_k=4,
                        include_debug=True,
                        include_retrieved=True,
                    )
                )

                self.assertEqual(response.debug.get("retrieval_route"), "formula_aware")
                self.assertTrue(response.retrieved_items)
                self.assertIn(
                    response.retrieved_items[0].metadata.get("source_kind"),
                    {"formula_context", "formula_clause", "formula_block"},
                )
                self.assertIn("公式或计算相关的证据", response.answer)
                self.assertTrue(
                    "按式" in response.answer or "统计" in response.answer or "K_t" in response.answer
                )
            finally:
                knowledge_service_module.knowledge_service = previous_root_service
                dense_retriever_module.knowledge_service = previous_dense_service
                sparse_retriever_module.knowledge_service = previous_sparse_service
                table_retriever_module.knowledge_service = previous_table_service
                formula_retriever_module.knowledge_service = previous_formula_service
                del isolated_service
                gc.collect()

    # 测试 analytic_sql 会走最Text-to-SQL 闭环并返回只读统计结果
    def test_analytic_sql_query_returns_sql_payload(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / "knowledge_meta.sqlite"
            isolated_service = IsolatedKnowledgeService(db_path)
            isolated_service.create_node(
                KnowledgeNode(
                    id="doc-sql-1",
                    title="文档一",
                    type="document",
                    library_id="default",
                    visible=True,
                    status="completed",
                )
            )
            isolated_service.create_node(
                KnowledgeNode(
                    id="doc-sql-2",
                    title="文档",
                    type="document",
                    library_id="default",
                    visible=True,
                    status="completed",
                )
            )
            isolated_service.save_canonical_document(
                CanonicalDocument(
                    doc_id="doc-sql-1",
                    library_id="default",
                    title="文档一",
                    source_file_name="doc-1.pdf",
                    source_file_type="pdf",
                    schema_version="1.0.0",
                    parse_version="0.1.0",
                    language="zh",
                    page_count=0,
                    status="completed",
                    created_at="2026-04-21T00:00:00",
                    updated_at="2026-04-21T00:00:00",
                )
            )
            isolated_service.save_canonical_document(
                CanonicalDocument(
                    doc_id="doc-sql-2",
                    library_id="default",
                    title="文档",
                    source_file_name="doc-2.pdf",
                    source_file_type="pdf",
                    schema_version="1.0.0",
                    parse_version="0.1.0",
                    language="zh",
                    page_count=0,
                    status="completed",
                    created_at="2026-04-21T00:00:00",
                    updated_at="2026-04-21T00:00:00",
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
                service = KnowledgeQueryService(knowledge_service_impl=isolated_service)
                response = service.query(
                    KnowledgeQueryRequest(
                        query="默认知识库里有多少篇文档",
                        library_id="default",
                        mode="sql",
                        include_debug=True,
                    )
                )

                self.assertEqual(response.task_type, "analytic_sql")
                self.assertEqual(response.strategy, "text2sql_canonical_v1")
                self.assertIsNotNone(response.sql)
                assert response.sql is not None
                self.assertEqual(response.sql.execution_status, "success")
                self.assertIn("SELECT COUNT(*) AS total_count FROM canonical_documents", response.sql.generated_sql)
                result_preview = response.sql.result_preview if isinstance(response.sql.result_preview, dict) else {}
                rows = list(result_preview.get("rows") or [])
                self.assertTrue(response.answer)
                self.assertEqual(response.debug.get("executor"), "sql")
                self.assertTrue(response.debug.get("sql_supported"))
                self.assertEqual(rows[0]["total_count"], 2)
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
