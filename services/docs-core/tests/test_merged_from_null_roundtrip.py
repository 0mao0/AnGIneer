"""merged_from=None 落库/读回契约：JSON null 不得让 get_document 抛 TypeError。

回归场景：commit 5999dce 后，save_document 将 merged_from=None 写成 JSON 字面量
"null"，而 get_document 执行 list(_load_json(..., [])) 时对 None 迭代抛
"'NoneType' object is not iterable"，导致 vectors 阶段（rebuild_document_vectors）
对任何含未合并块的文档全部失败。
"""

from pathlib import Path

from docs_core.models.types import CanonicalBlock, CanonicalDocument
from docs_core.step05_sqlite_fts.store.canonical_sql_store import CanonicalSQLiteStore


def _make_document(doc_id: str) -> CanonicalDocument:
    return CanonicalDocument(
        doc_id=doc_id,
        library_id="default",
        title="merged_from null 契约",
        blocks=[
            CanonicalBlock(
                block_id=f"{doc_id}:0:1",
                doc_id=doc_id,
                page_idx=0,
                block_type="paragraph",
                text="未合并块",
                text_clean="未合并块",
                reading_order=1,
                merged_from=None,
            ),
            CanonicalBlock(
                block_id=f"{doc_id}:0:2",
                doc_id=doc_id,
                page_idx=0,
                block_type="paragraph",
                text="合并块",
                text_clean="合并块",
                reading_order=2,
                merged_from=[f"{doc_id}:0:1"],
            ),
        ],
    )


def test_get_document_roundtrip_with_merged_from_none(tmp_path: Path) -> None:
    store = CanonicalSQLiteStore(db_path=tmp_path / "index.sqlite")
    doc = _make_document("doc-null-merge")
    store.save_document(doc)

    restored = store.get_document("doc-null-merge")
    assert restored is not None
    by_id = {block.block_id: block for block in restored.blocks}
    assert by_id["doc-null-merge:0:1"].merged_from == []
    assert by_id["doc-null-merge:0:2"].merged_from == ["doc-null-merge:0:1"]


def test_merged_from_none_stored_as_sql_null(tmp_path: Path) -> None:
    store = CanonicalSQLiteStore(db_path=tmp_path / "index.sqlite")
    store.save_document(_make_document("doc-null-merge"))

    with store.connect() as conn:
        rows = conn.execute(
            "SELECT block_id, merged_from_json FROM canonical_blocks WHERE doc_id = ?",
            ("doc-null-merge",),
        ).fetchall()
    stored = dict(rows)
    assert stored["doc-null-merge:0:1"] is None
    assert stored["doc-null-merge:0:2"] == '["doc-null-merge:0:1"]'
