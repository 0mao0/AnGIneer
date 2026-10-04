"""SparseRetriever：doc_id=None 的 FTS 召回携带库集合（求交前移）。"""
from docs_core.step09_query.protocols.contracts import KnowledgeNode, KnowledgeQueryRequest
from docs_core.step09_query.retrieval.sparse_retriever import SparseRetriever


class _FakePort:
    def __init__(self):
        self.fts_calls: list[dict] = []

    def search_chunk_fts(self, doc_id, query, limit=20, library_ids=None):
        self.fts_calls.append({"doc_id": doc_id, "library_ids": library_ids})
        return []

    # 其余端口：FTS 无命中 → 退化为前 20 节点路径，批量取数全返回空
    def list_pages_for_docs(self, doc_ids): return []
    def search_citation_targets_for_docs(self, doc_ids, query, per_doc_limit=20): return []
    def list_chunks_by_ids(self, chunk_ids): return []
    def list_chunks_for_docs(self, doc_ids, keyword=None, per_doc_limit=40): return []
    def list_blocks_for_docs(self, doc_ids, keyword=None, per_doc_limit=20): return []


class TestSparseLibraryScoping:
    def test_multi_library_ids_passed_to_fts(self):
        port = _FakePort()
        req = KnowledgeQueryRequest(
            query="混凝土抗压强度", library_id="libA", library_ids=["libA", "libB"], top_k=20,
        )
        SparseRetriever(port=port).retrieve(req, [], "content_qa")
        assert port.fts_calls[0]["library_ids"] == ["libA", "libB"]

    def test_single_library_falls_back_to_library_id(self):
        port = _FakePort()
        req = KnowledgeQueryRequest(query="混凝土抗压强度", library_id="libA", top_k=20)
        SparseRetriever(port=port).retrieve(req, [], "content_qa")
        assert port.fts_calls[0]["library_ids"] == ["libA"]
