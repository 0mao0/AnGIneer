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


def _register(lib_id: str, group: str = "g1") -> None:
    from docs_core import library_registry
    if library_registry.get_library(lib_id) is None:
        library_registry.register_library(lib_id, name=lib_id, group_name=group,
                                          sqlite_file="knowledge/groups/g1.sqlite", collection="g1")


def test_preview_blockers(migrator):
    with pytest.raises(MigrationBlocked):
        migrator.compute_preview(op="split", source_library_id="lib-a",
                                 new_library_id="lib-b", new_name="x", doc_ids=[])  # 空选择
    with pytest.raises(MigrationBlocked):
        migrator.compute_preview(op="split", source_library_id="lib-a",
                                 new_library_id="lib-b", new_name="x",
                                 doc_ids=["d1", "d2", "d3"])  # 全选=请用合并


def test_preview_split_into_existing_library(migrator):
    """拆出去并入已有库（第三种目的地形态）：目标库计数进 target_before/after，新库字段留空。"""
    _register("lib-t")
    p = migrator.compute_preview(op="split", source_library_id="lib-a",
                                 target_library_id="lib-t", doc_ids=["d1"])
    assert p.new_library_id == ""            # 目的地形态=已有库（回滚时目标库不退役的判据）
    assert p.target_library_id == "lib-t"
    assert p.counts["docs"] == {"source_before": 3, "source_after": 2,
                                "target_before": 0, "target_after": 1}


def test_preview_split_destination_rules(migrator):
    _register("lib-t")
    _register("default")
    with pytest.raises(MigrationBlocked, match="二选一"):  # 双给
        migrator.compute_preview(op="split", source_library_id="lib-a",
                                 target_library_id="lib-t", new_library_id="lib-b", doc_ids=["d1"])
    with pytest.raises(MigrationBlocked, match="目的地"):  # 双缺
        migrator.compute_preview(op="split", source_library_id="lib-a", doc_ids=["d1"])
    with pytest.raises(MigrationBlocked, match="自己"):    # 目的地=源库
        migrator.compute_preview(op="split", source_library_id="lib-a",
                                 target_library_id="lib-a", doc_ids=["d1"])
    with pytest.raises(MigrationBlocked, match="默认库"):  # 默认库只出不进
        migrator.compute_preview(op="split", source_library_id="lib-a",
                                 target_library_id="default", doc_ids=["d1"])
    with pytest.raises(MigrationBlocked, match="未知操作"):
        migrator.compute_preview(op="teleport", source_library_id="lib-a", doc_ids=["d1"])


def test_preview_default_source_split_allowed_merge_blocked(migrator):
    """默认库允许拆分（2026-10-07 业主口径）：拆到新库/拆入已有库放行；整体合并仍拦。"""
    _register("default")
    _register("lib-t")
    with sqlite3.connect(migrator.meta_db) as conn:
        conn.executemany("INSERT INTO nodes (id, type, library_id, file_path, updated_at) VALUES (?,?,?,?,?)",
                         [("d9", "document", "default", "/x/d9", ""),
                          ("d10", "document", "default", "/x/d10", "")])
    p1 = migrator.compute_preview(op="split", source_library_id="default",
                                  new_library_id="lib-new", new_name="分册", doc_ids=["d9"])
    assert p1.new_library_id == "lib-new" and p1.doc_ids == ["d9"]
    p2 = migrator.compute_preview(op="split", source_library_id="default",
                                  target_library_id="lib-t", doc_ids=["d9"])
    assert p2.target_library_id == "lib-t"
    with pytest.raises(MigrationBlocked, match="默认库不支持整体合并"):
        migrator.compute_preview(op="merge", source_library_id="default", target_library_id="lib-t")
    with pytest.raises(MigrationBlocked, match="至少保留"):  # 拆走全部文档仍按既有规则拦（默认库提示不给死路）
        migrator.compute_preview(op="split", source_library_id="default",
                                 new_library_id="lib-new2", new_name="x", doc_ids=["d9", "d10"])


def test_assert_preview_fresh_roundtrips_both_destinations(migrator):
    """提交前重算：目的地按形态回填（新库走 new_library_id、已有库走 target_library_id），两种都不误报过期。"""
    _register("lib-t")
    p_new = migrator.compute_preview(op="split", source_library_id="lib-a",
                                     new_library_id="lib-b9", new_name="分册", doc_ids=["d1"])
    migrator.assert_preview_fresh(p_new)
    p_ext = migrator.compute_preview(op="split", source_library_id="lib-a",
                                     target_library_id="lib-t", doc_ids=["d1"])
    migrator.assert_preview_fresh(p_ext)


def test_digest_stable(migrator):
    kw = dict(op="split", source_library_id="lib-a", new_library_id="lib-b",
              new_name="分册", doc_ids=["d1"])
    assert migrator.compute_preview(**kw).digest == migrator.compute_preview(**kw).digest
