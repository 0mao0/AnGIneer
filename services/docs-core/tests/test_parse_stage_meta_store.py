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


def test_run_raw_parse_sets_page_meta_on_context(tmp_path) -> None:
    from docs_core.parse_pipeline import StageContext, _run_raw_parse

    class FakeParser:
        backend = "hybrid-engine"

        def parse_to_raw_artifacts(self, input_path, output_dir=None, *, library_id=None, doc_id=None, on_step=None, **kwargs):
            return {
                "success": True,
                "persisted": {
                    "output_summary": "content.md",
                    "has_images": True,
                    "page_count": 36,
                    "ocr_retried": True,
                },
            }

    ctx = StageContext(
        task_id="task-1",
        library_id="lib1", doc_id="doc1", file_path="/tmp/x.pdf",
        source_path="/tmp/x.pdf", task_parser=FakeParser(),
    )
    message = _run_raw_parse(ctx)
    assert "MinerU解析完成" in message
    assert ctx.page_count == 36
    assert ctx.is_scanned is True
