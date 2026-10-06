import sqlite3
import pytest
from docs_core.kb_migrator import KbMigrator, MigrationBlocked


@pytest.fixture
def migrator(tmp_path, monkeypatch):
    meta = tmp_path / "meta.sqlite"
    with sqlite3.connect(meta) as conn:
        # deleted 列必须建：统计 SQL 用 COALESCE(deleted,0)，列不存在直接报错（评审 P1-7①）
        conn.execute("CREATE TABLE nodes (id TEXT PRIMARY KEY, type TEXT, library_id TEXT, file_path TEXT, updated_at TEXT, deleted INTEGER NOT NULL DEFAULT 0)")
        conn.execute("CREATE TABLE tree_node (node_id TEXT PRIMARY KEY, tree_type TEXT, scope_id TEXT, updated_at TEXT)")
        conn.execute("CREATE TABLE parse_tasks (id TEXT PRIMARY KEY, library_id TEXT, doc_id TEXT, updated_at TEXT)")
        conn.executemany("INSERT INTO nodes (id, type, library_id, file_path, updated_at) VALUES (?,?,?,?,?)",
                         [("d1", "document", "lib-a", "/x/d1", ""), ("d2", "document", "lib-a", "/x/d2", ""),
                          ("d3", "document", "lib-a", "/x/d3", "")])
    group = tmp_path / "group.sqlite"
    with sqlite3.connect(group) as conn:
        conn.execute("CREATE TABLE canonical_documents (doc_id TEXT PRIMARY KEY, library_id TEXT, updated_at TEXT)")
        conn.execute("CREATE TABLE canonical_chunks (chunk_id TEXT PRIMARY KEY, doc_id TEXT, text TEXT)")
        conn.execute("CREATE TABLE document_segments (id TEXT PRIMARY KEY, doc_id TEXT, library_id TEXT, updated_at TEXT)")
        conn.executemany("INSERT INTO canonical_documents VALUES (?,?,?)",
                         [("d1", "lib-a", ""), ("d2", "lib-a", ""), ("d3", "lib-a", "")])
        conn.executemany("INSERT INTO canonical_chunks VALUES (?,?,?)",
                         [("c1", "d1", "x"), ("c2", "d1", "y"), ("c3", "d2", "z")])
    evals = tmp_path / "evals.sqlite"
    with sqlite3.connect(evals) as conn:
        conn.execute("CREATE TABLE eval_dataset (dataset_id TEXT PRIMARY KEY, title TEXT, library_id TEXT)")
        conn.execute("CREATE TABLE eval_question (question_id TEXT, dataset_id TEXT, library_id TEXT, doc_ids TEXT)")
        conn.execute("INSERT INTO eval_dataset VALUES ('ds1', '题集一', 'lib-a')")
        conn.execute("INSERT INTO eval_question VALUES ('q1', 'ds1', 'lib-a', '[\"d1\"]')")
    graph = tmp_path / "graph.sqlite"
    # AUDIT_PATH 在模块 import 期就绑死（conftest 的 env 隔离拦不住它），不临时挪走会直写
    # 真 data/ops/kb_migration_audit.jsonl —— 同 80fd815「测试单例串库直写真库」一类坑（施工补）
    from docs_core import kb_migration_audit
    monkeypatch.setattr(kb_migration_audit, "AUDIT_PATH", tmp_path / "audit.jsonl")
    # conftest 已把 ANGINEER_REGISTRY_DB 隔离到 tmp：直接注册，让 _check_blockers 通过（评审 P1-7①）
    from docs_core import library_registry
    library_registry.register_library("lib-a", name="a", group_name="g1",
                                      sqlite_file="knowledge/groups/g1.sqlite", collection="g1")
    mig = KbMigrator(meta_db=meta, group_db=group, graph_db=graph, evals_db=evals,
                     libraries_root=tmp_path / "libraries", vector_store=None)
    return mig


def test_preview_counts_and_eval_refs(migrator):
    p = migrator.compute_preview(op="split", source_library_id="lib-a",
                                 new_library_id="lib-b", new_name="分册", doc_ids=["d1"])
    assert p.counts["docs"] == {"source_before": 3, "source_after": 2, "target_before": 0, "target_after": 1}
    assert p.counts["chunks"] == {"moved": 2}
    assert p.eval_refs["datasets"] == [{"dataset_id": "ds1", "title": "题集一"}]
    assert p.eval_refs["question_count"] == 1
    assert p.blockers == []
    assert len(p.digest) == 64


def test_preview_blockers(migrator):
    with pytest.raises(MigrationBlocked):
        migrator.compute_preview(op="split", source_library_id="default",
                                 new_library_id="lib-b", new_name="x", doc_ids=["d1"])
    with pytest.raises(MigrationBlocked):
        migrator.compute_preview(op="split", source_library_id="lib-a",
                                 new_library_id="lib-b", new_name="x", doc_ids=[])  # 空选择
    with pytest.raises(MigrationBlocked):
        migrator.compute_preview(op="split", source_library_id="lib-a",
                                 new_library_id="lib-b", new_name="x",
                                 doc_ids=["d1", "d2", "d3"])  # 全选=请用合并


def test_digest_stable(migrator):
    kw = dict(op="split", source_library_id="lib-a", new_library_id="lib-b",
              new_name="分册", doc_ids=["d1"])
    assert migrator.compute_preview(**kw).digest == migrator.compute_preview(**kw).digest
