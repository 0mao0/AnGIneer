"""展示层契约测试：印刷页码贯穿 引用目标查询 → 检索元数据。"""

from fixtures.popo_fixtures import build_document_with_printed_labels


def _build_store(tmp_path):
    from docs_core.step05_sqlite_fts.store.canonical_sql_store import CanonicalSQLiteStore

    document = build_document_with_printed_labels("doc-1")
    store = CanonicalSQLiteStore(db_path=tmp_path / "index.sqlite")
    store.save_document(document)
    return store


def test_list_pages_returns_printed_labels(tmp_path) -> None:
    store = _build_store(tmp_path)
    pages = store.list_pages("doc-1")
    by_idx = {p.page_idx: p for p in pages}
    assert by_idx[0].printed_page_label == "12"
    assert by_idx[1].printed_page_label == "13"


def test_citation_target_queries_include_page_label(tmp_path) -> None:
    store = _build_store(tmp_path)
    target = store.get_citation_target("doc-1", "doc-1:b1")
    assert target is not None
    assert target["page_label"] == "12"

    hits = store.search_citation_targets("doc-1", "第一章")
    assert hits
    assert all("page_label" in hit for hit in hits)
    assert any(hit["page_label"] for hit in hits)

    listed = store.list_citation_targets("doc-1")
    assert listed
    assert all("page_label" in hit for hit in listed)


def test_sparse_retriever_carries_page_label(tmp_path) -> None:
    from docs_core.step09_query.protocols.contracts import KnowledgeNode, KnowledgeQueryRequest
    from docs_core.step09_query.retrieval.sparse_retriever import SparseRetriever

    store = _build_store(tmp_path)

    class _FakePort:
        def list_canonical_pages(self, doc_id):
            return store.list_pages(doc_id)

        def search_citation_targets(self, doc_id, query, limit=20):
            return store.search_citation_targets(doc_id, query, limit)

        def search_chunk_fts(self, doc_id, query, limit=20):
            return []

        def list_canonical_chunks(self, **kwargs):
            return []

        def list_canonical_blocks(self, **kwargs):
            return []

    retriever = SparseRetriever(port=_FakePort())
    request = KnowledgeQueryRequest(query="第一章", library_id="default")
    doc_nodes = [
        KnowledgeNode(id="doc-1", title="示例文档", type="document", library_id="default"),
    ]
    candidates = retriever.retrieve(request, doc_nodes, task_type="content_qa")
    assert candidates, "应命中标题引用目标"
    labeled = [c for c in candidates if c.metadata.get("page_label")]
    assert labeled, "检索元数据应携带印刷页码"
    assert labeled[0].metadata["page_label"] == "12"
