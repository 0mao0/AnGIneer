# 组文件桶解析（2026-10-07 生产实踩 mig-cd0e1350f7fe）：
# 拆到新库=切换时刻才注册（_switch），执行全程目的地在注册表缺席；
# 组面改标若按 to_lib 现查 resolve_index_db_path，未注册新库会回退 knowledge_index 默认桶——
# UPDATE 落在陈年副本上，组文件纹丝不动，对账「组文件改标 0/5」必败。
# 本文件不复用 migrator 父夹具（它注入 _group_db_override，恰好遮蔽此 bug），
# 按生产形态装：源库注册在真组文件 + 目的地未注册 + 回退桶里放陈年副本。
import sqlite3

import pytest

from docs_core import library_registry, paths
from docs_core.kb_migrator import KbMigrator


@pytest.fixture
def prod_shape(tmp_path, monkeypatch):
    from docs_core import kb_migration_audit, paths
    monkeypatch.setattr(kb_migration_audit, "audit_path", lambda: tmp_path / "audit.jsonl")
    # conftest 已隔离 ANGINEER_DATA_ROOT/REGISTRY_DB 到 tmp；回退桶（KNOWLEDGE_BASE_DIR 口径）同指 tmp
    monkeypatch.setenv("KNOWLEDGE_BASE_DIR", str(tmp_path / "data" / "knowledge"))
    group_db = tmp_path / "data" / "knowledge" / "groups" / "g1.sqlite"
    group_db.parent.mkdir(parents=True)
    fallback_db = paths.resolve_knowledge_index_db_path()
    fallback_db.parent.mkdir(parents=True, exist_ok=True)
    meta = tmp_path / "meta.sqlite"
    with sqlite3.connect(meta) as conn:
        conn.execute("CREATE TABLE nodes (id TEXT PRIMARY KEY, type TEXT, library_id TEXT, file_path TEXT, updated_at TEXT, deleted INTEGER NOT NULL DEFAULT 0)")
        conn.execute("CREATE TABLE tree_node (node_id TEXT PRIMARY KEY, tree_type TEXT, scope_id TEXT, updated_at TEXT)")
        conn.execute("CREATE TABLE parse_tasks (id TEXT PRIMARY KEY, library_id TEXT, doc_id TEXT, updated_at TEXT)")
    schema = [("CREATE TABLE canonical_documents (doc_id TEXT PRIMARY KEY, library_id TEXT, updated_at TEXT)",
               ("d1", "lib-a", "")),
              ("CREATE TABLE document_segments (id TEXT PRIMARY KEY, doc_id TEXT, library_id TEXT, updated_at TEXT)",
               ("s1", "d1", "lib-a", ""))]
    # 权威桶：组文件持有 d1 的 canonical 行；回退桶：迁移前就存在的陈年副本（default 拆库前 knowledge_index 残留形态）
    for db in (group_db, fallback_db):
        with sqlite3.connect(db) as conn:
            for ddl, row in schema:
                conn.execute(ddl)
                conn.execute("INSERT INTO canonical_documents VALUES (?,?,?)" if "canonical" in ddl
                             else "INSERT INTO document_segments VALUES (?,?,?,?)", row)
    library_registry.register_library("lib-a", name="a", group_name="g1",
                                      sqlite_file="knowledge/groups/g1.sqlite", collection="g1")
    graph = tmp_path / "graph.sqlite"
    from docs_core.step07_graph.graph_store import GraphStore
    GraphStore(str(graph))  # 真 graph 库恒有 schema（对账图面直接 SELECT，无建表豁免）
    # 切换收尾的 reload_scope_cache 属宿主进程行为，与本文件主题（组桶写位）无关；
    # 本夹具改了 KNOWLEDGE_BASE_DIR，真服务构造不了 tmp 环境，stub 掉。
    # 必须打 sys.modules 真模块：包级重导出是 __getattr__ 代理壳，碰属性名就触发建服务（conftest 同款坑）
    class _FakeKs:
        """_switch 收尾只用到 meta_store.upsert_library + reload_scope_cache 两个端口。"""

        def __init__(self) -> None:
            self.meta_store = self
            self.libraries: list = []

        def upsert_library(self, lib) -> None:
            self.libraries.append(lib)

        def reload_scope_cache(self) -> None:
            return None

    fake_ks = _FakeKs()
    import sys
    monkeypatch.setattr(sys.modules["docs_core.docs_service"], "get_docs_service", lambda: fake_ks)
    evals = tmp_path / "evals.sqlite"
    with sqlite3.connect(evals) as conn:
        conn.execute("CREATE TABLE eval_dataset (dataset_id TEXT PRIMARY KEY, title TEXT, library_id TEXT)")
        conn.execute("CREATE TABLE eval_question (question_id TEXT, dataset_id TEXT, library_id TEXT, doc_ids TEXT)")
    mig = KbMigrator(meta_db=meta, graph_db=graph, evals_db=evals,
                     libraries_root=tmp_path / "libraries", vector_store=None)  # 关键：不注 group_db，走真解析
    src_dir = mig.libraries_root_for("lib-a") / "documents" / "d1"
    src_dir.mkdir(parents=True)
    (src_dir / "source.txt").write_text("hello", encoding="utf-8")
    with sqlite3.connect(meta) as conn:
        conn.execute("INSERT INTO nodes (id, type, library_id, file_path, updated_at) VALUES (?,?,?,?,?)",
                     ("d1", "document", "lib-a", str(src_dir / "source.txt"), ""))
    return mig


def _rows(db, sql, args=()):
    with sqlite3.connect(db) as conn:
        return conn.execute(sql, args).fetchall()


def test_split_to_new_library_group_relabel_lands_in_group_file(prod_shape):
    """执行期目的地未注册：组面改标必须落组文件，不许漏进回退桶；对账须过、任务须完成。"""
    mig = prod_shape
    group_db = library_registry.resolve_index_db_path("lib-a")
    fallback_db = paths.resolve_knowledge_index_db_path()
    mig.store.create_task("t-g1", op="split",
                          params={"op": "split", "source_library_id": "lib-a",
                                  "new_library_id": "lib-b", "new_name": "分册", "doc_ids": ["d1"]},
                          total=1)
    mig.run_task("t-g1", operator="admin")  # 修复前：RuntimeError 对账不一致 ['group: 组文件改标 0/1']
    assert mig.store.get_task("t-g1")["status"] == "completed"
    assert _rows(group_db, "SELECT library_id FROM canonical_documents WHERE doc_id='d1'") == [("lib-b",)]
    assert _rows(group_db, "SELECT library_id FROM document_segments WHERE doc_id='d1'") == [("lib-b",)]
    # 回退桶的陈年副本保持原库：零写入（它不在任何库的读路径上，被写脏就是 mig-cd0e1350f7fe 现场）
    assert _rows(fallback_db, "SELECT library_id FROM canonical_documents WHERE doc_id='d1'") == [("lib-a",)]


def test_rollback_of_never_registered_new_library(prod_shape):
    """拆到新库但没走到 _switch 就失败：新库在注册表缺席，「全部回滚」不许 KeyError，数据回源库。"""
    mig = prod_shape
    # 手工摆出生产卡死形态：meta/文件面已指向未注册新库，组文件仍挂源库（bug 的错写位）
    with sqlite3.connect(mig.meta_db) as conn:
        conn.execute("UPDATE nodes SET library_id='lib-b' WHERE id='d1'")
    assert library_registry.get_library("lib-b") is None
    mig.store.create_task("t-r", op="rollback",
                          params={"rollback_kind": "split", "rollback_of": "t-x",
                                  "original_source_library_id": "lib-a", "library_id": "lib-b",
                                  "collection": "g1", "doc_ids": ["d1"], "destination_is_new": True},
                          total=1)
    mig.run_task("t-r", operator="admin")  # 修复前：_gate_libraries→set_status KeyError 注册表无此库
    assert mig.store.get_task("t-r")["status"] == "completed"
    with sqlite3.connect(mig.meta_db) as conn:
        assert conn.execute("SELECT library_id FROM nodes WHERE id='d1'").fetchone()[0] == "lib-a"
    assert (mig.libraries_root_for("lib-a") / "documents" / "d1" / "source.txt").exists()
    group_db = library_registry.resolve_index_db_path("lib-a")
    assert _rows(group_db, "SELECT library_id FROM canonical_documents WHERE doc_id='d1'") == [("lib-a",)]
    # 新库从未注册=从未对外可见，回滚收尾无需（也不许）retire 一条不存在的注册行
    assert library_registry.get_library("lib-b") is None
    assert library_registry.get_library("lib-a").status == "active"
