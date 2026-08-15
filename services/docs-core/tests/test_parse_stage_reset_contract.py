"""全量重跑时阶段记录与子阶段步骤一并清空契约测试。"""
from docs_core.step05_sqlite_fts.store.blocks_sql_store import KnowledgeMetaStore
from docs_core.parse_pipeline import reset_parse_stage_records


def test_full_reparse_clears_stages_and_steps(tmp_path) -> None:
    store = KnowledgeMetaStore(db_path=tmp_path / "meta.sqlite", schema_version="1.0.0")
    store.upsert_parse_stage("doc-x", "structure", status="completed")
    store.insert_parse_stage_step("doc-x", "structure", "建块", "done", "")
    store.insert_parse_stage_step("doc-x", "raw_parse", "解析", "done", "")
    assert len(store.list_parse_stages("doc-x")) == 1
    assert len(store.list_parse_stage_steps("doc-x")) == 2

    reset_parse_stage_records(store, "doc-x")

    assert store.list_parse_stages("doc-x") == []
    assert store.list_parse_stage_steps("doc-x") == []
