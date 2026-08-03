"""Phase 0 展示层契约测试：印刷页码贯穿 引用目标查询 → 检索元数据。"""

from docs_core.ingest.structure.popo_mapper import po_po_blocks_to_canonical
from docs_core.ingest.canonical.builder import build_canonical_document_from_popoblocks
from fixtures.popo_fixtures import EMPTY_TREE, build_noise_fixture


def _build_store(tmp_path):
    from docs_core.write.store.canonical_sql_store import CanonicalSQLiteStore

    blocks, outlines, _, pages = po_po_blocks_to_canonical(
        "doc-1", build_noise_fixture(), EMPTY_TREE
    )
    document = build_canonical_document_from_popoblocks(
        library_id="lib-1", doc_id="doc-1", title="",
        blocks=blocks, outlines=outlines, pages=pages,
    )
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


def test_sparse_retriever_carries_page_label(tmp_path, monkeypatch) -> None:
    import importlib

    sparse_module = importlib.import_module("docs_core.query.retrieval.sparse_retriever")
    from docs_core.knowledge_service import KnowledgeNode
    from docs_core.query.protocols.contracts import KnowledgeQueryRequest
    from docs_core.query.retrieval.sparse_retriever import sparse_retriever

    store = _build_store(tmp_path)

    class _FakeKS:
        def __init__(self) -> None:
            self.canonical_store = store

        def list_canonical_chunks(self, **kwargs):
            return []

        def list_canonical_blocks(self, **kwargs):
            return []

        def search_chunk_fts(self, **kwargs):
            return []

    monkeypatch.setattr(sparse_module, "knowledge_service", _FakeKS())
    request = KnowledgeQueryRequest(query="第一章", library_id="default")
    doc_nodes = [
        KnowledgeNode(id="doc-1", title="示例文档", type="document", library_id="default"),
    ]
    candidates = sparse_retriever.retrieve(request, doc_nodes, task_type="content_qa")
    assert candidates, "应命中标题引用目标"
    labeled = [c for c in candidates if c.metadata.get("page_label")]
    assert labeled, "检索元数据应携带印刷页码"
    assert labeled[0].metadata["page_label"] == "12"
