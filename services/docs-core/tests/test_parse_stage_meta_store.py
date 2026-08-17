"""doc_parse_stages 页数/扫描件列迁移与透传契约。"""
from docs_core.step05_sqlite_fts.store.blocks_sql_store import KnowledgeMetaStore


def test_migration_idempotent(tmp_path) -> None:
    db = tmp_path / "meta.sqlite"
    KnowledgeMetaStore(db_path=db, schema_version="1.0.0")
    KnowledgeMetaStore(db_path=db, schema_version="1.0.0")  # 重复初始化不抛错


def test_upsert_and_list_carry_page_meta(tmp_path) -> None:
    store = KnowledgeMetaStore(db_path=tmp_path / "meta.sqlite", schema_version="1.0.0")
    store.upsert_parse_stage(
        "doc-x", "raw_parse", status="completed",
        page_count=42, is_scanned=True,
        started_at="2026-08-17T00:00:00", finished_at="2026-08-17T00:01:00",
    )
    rows = store.list_parse_stages("doc-x")
    assert len(rows) == 1
    assert rows[0]["page_count"] == 42
    assert rows[0]["is_scanned"] == 1


def test_upsert_defaults_page_meta_zero(tmp_path) -> None:
    store = KnowledgeMetaStore(db_path=tmp_path / "meta.sqlite", schema_version="1.0.0")
    store.upsert_parse_stage("doc-x", "convert", status="completed")
    row = store.list_parse_stages("doc-x")[0]
    assert row["page_count"] == 0
    assert row["is_scanned"] == 0
