import sqlite3
import pytest
from docs_core import library_registry
from docs_core.kb_migrator import KbMigrator, PreviewStaleError
from test_kb_migrator_preview import migrator as _base  # noqa: F401  doc_env 的父 fixture 须在本模块命名空间可见（pytest 在请求模块解析 fixture 参数）
from test_kb_migrator_doc_unit import doc_env  # noqa: F401


def _register(libs=("lib-a",)):
    for lib in libs:
        if library_registry.get_library(lib) is None:
            library_registry.register_library(lib, name=lib, group_name="g1",
                                              sqlite_file="knowledge/groups/g1.sqlite", collection="g1")


def test_run_task_split_happy_path(doc_env, tmp_path):
    mig = doc_env
    _register()
    mig.store.create_task("t-1", op="split",
                          params={"op": "split", "source_library_id": "lib-a",
                                  "new_library_id": "lib-b", "new_name": "分册",
                                  "doc_ids": ["d1"]}, total=1)
    mig.run_task("t-1", operator="admin")
    task = mig.store.get_task("t-1")
    assert task["status"] == "completed" and task["stage"] == "switch"
    assert task["rollback_deadline"]
    rec = library_registry.get_library("lib-b")
    assert rec is not None and rec.status == "active" and rec.group_name == "g1"
    assert library_registry.get_library("lib-a").status == "active"  # 切换后源库恢复
    assert task["verify"]["ok"] is True


def test_run_task_cancel_compensates(doc_env):
    mig = doc_env
    _register()
    mig.store.create_task("t-2", op="split",
                          params={"op": "split", "source_library_id": "lib-a",
                                  "new_library_id": "lib-b2", "new_name": "x", "doc_ids": ["d1"]},
                          total=1)
    mig.store.request_cancel("t-2")  # 执行前即取消 → 直接收敛
    mig.run_task("t-2", operator="admin")
    task = mig.store.get_task("t-2")
    assert task["status"] == "cancelled"
    # 未迁任何 doc，源库原样
    with sqlite3.connect(mig.meta_db) as conn:
        assert conn.execute("SELECT library_id FROM nodes WHERE id='d1'").fetchone()[0] == "lib-a"


def test_verify_catches_count_mismatch(doc_env):
    mig = doc_env
    _register()
    mig.store.create_task("t-3", op="split",
                          params={"op": "split", "source_library_id": "lib-a",
                                  "new_library_id": "lib-b3", "new_name": "x", "doc_ids": ["d1"]},
                          total=1, preview={"counts": {"docs": {"target_after": 99}}})
    # 对账失败 run_task 标 failed 后必上抛（runner 侧才能看见），计划测试漏包 raises（施工补）
    with pytest.raises(RuntimeError, match="对账"):
        mig.run_task("t-3", operator="admin")
    task = mig.store.get_task("t-3")
    assert task["status"] == "failed" and "对账" in (task["error"] or "")


def test_merge_doc_ids_fallback_to_preview(doc_env):
    """评审 P0-1：merge 提交体无 doc_ids，run_task 必须从任务行 preview 兜底取全集。"""
    mig = doc_env
    _register(("lib-a", "lib-t"))
    preview = mig.compute_preview(op="merge", source_library_id="lib-a", target_library_id="lib-t")
    mig.store.create_task("t-4", op="merge",
                          params={"op": "merge", "source_library_id": "lib-a",
                                  "target_library_id": "lib-t"},  # 无 doc_ids
                          total=3, preview={"counts": preview.counts, "doc_ids": preview.doc_ids})
    mig.run_task("t-4", operator="admin")
    task = mig.store.get_task("t-4")
    assert task["status"] == "completed"
    assert len(task["migrated_doc_ids"]) == 3
    assert library_registry.get_library("lib-a").status == "retired"


def test_run_task_split_into_existing_library(doc_env):
    """拆出去并入已有库：无新库注册、目标库计数增长、切换后两端回 active（业主 2026-10-07 新增形态）。"""
    mig = doc_env
    _register(("lib-a", "lib-t"))
    preview = mig.compute_preview(op="split", source_library_id="lib-a",
                                  target_library_id="lib-t", doc_ids=["d1"])
    mig.store.create_task("t-6", op="split",
                          params={"op": "split", "source_library_id": "lib-a",
                                  "target_library_id": "lib-t", "gate_second": True,
                                  "doc_ids": ["d1"]},
                          total=1, preview={"counts": preview.counts, "doc_ids": preview.doc_ids})
    mig.run_task("t-6", operator="admin")
    task = mig.store.get_task("t-6")
    assert task["status"] == "completed" and task["verify"]["ok"] is True
    # 两端都回 active（目标库是别人的库，只放行门禁，绝不退役）
    assert library_registry.get_library("lib-t").status == "active"
    assert library_registry.get_library("lib-a").status == "active"
    with sqlite3.connect(mig.meta_db) as conn:
        assert conn.execute("SELECT library_id FROM nodes WHERE id='d1'").fetchone()[0] == "lib-t"


def test_rollback_into_existing_library_keeps_target_active(doc_env):
    """拆入已有库的回滚：doc_ids=原任务 migrated_doc_ids，撤回后目标库不退役、源库回 active。"""
    mig = doc_env
    _register(("lib-a", "lib-t"))
    preview = mig.compute_preview(op="split", source_library_id="lib-a",
                                  target_library_id="lib-t", doc_ids=["d1"])
    mig.store.create_task("t-7", op="split",
                          params={"op": "split", "source_library_id": "lib-a",
                                  "target_library_id": "lib-t", "gate_second": True,
                                  "doc_ids": ["d1"]},
                          total=1, preview={"counts": preview.counts, "doc_ids": preview.doc_ids})
    mig.run_task("t-7", operator="admin")
    assert mig.store.get_task("t-7")["status"] == "completed"
    mig.store.create_task("t-7r", op="rollback",
                          params={"rollback_kind": "split", "rollback_of": "t-7",
                                  "original_source_library_id": "lib-a", "library_id": "lib-t",
                                  "collection": "g1", "doc_ids": ["d1"],
                                  "destination_is_new": False, "gate_second": True},
                          total=1)
    mig.run_task("t-7r", operator="admin")
    assert mig.store.get_task("t-7r")["status"] == "completed"
    assert library_registry.get_library("lib-t").status == "active"   # 既有库绝不能被退役
    assert library_registry.get_library("lib-a").status == "active"
    with sqlite3.connect(mig.meta_db) as conn:
        assert conn.execute("SELECT library_id FROM nodes WHERE id='d1'").fetchone()[0] == "lib-a"


def test_verify_tolerates_doc_without_canonical_rows(doc_env):
    """无 canonical 行的文档（未解析/解析失败）不算对账缺口（2026-10-07 假失败实踩）。

    预期数取预览 fingerprint.canonical_documents.count；拿 len(doc_ids) 比会把「迁对了」判成失败。
    """
    mig = doc_env
    _register(("lib-a", "lib-t"))
    with sqlite3.connect(mig.group_db_for("lib-a")) as conn:
        conn.execute("DELETE FROM canonical_documents WHERE doc_id='d2'")
    preview = mig.compute_preview(op="split", source_library_id="lib-a",
                                  target_library_id="lib-t", doc_ids=["d1", "d2"])
    assert preview.counts["fingerprint"]["canonical_documents"]["count"] == 1
    mig.store.create_task("t-8", op="split",
                          params={"op": "split", "source_library_id": "lib-a",
                                  "target_library_id": "lib-t", "gate_second": True,
                                  "doc_ids": ["d1", "d2"]},
                          total=2, preview={"counts": preview.counts, "doc_ids": preview.doc_ids})
    mig.run_task("t-8", operator="admin")
    task = mig.store.get_task("t-8")
    assert task["status"] == "completed" and task["verify"]["ok"] is True
    with sqlite3.connect(mig.group_db_for("lib-a")) as conn:
        assert conn.execute("SELECT library_id FROM canonical_documents WHERE doc_id='d1'").fetchone()[0] == "lib-t"


def test_rollback_branch_relabels_back_and_retires_new_lib(doc_env):
    """评审 P0-3：回滚走显式分支，禁止 register_library；拆分回滚后新库 retired。"""
    mig = doc_env
    _register()
    mig.store.create_task("t-5", op="split",
                          params={"op": "split", "source_library_id": "lib-a",
                                  "new_library_id": "lib-b5", "new_name": "分册", "doc_ids": ["d1"]},
                          total=1)
    mig.run_task("t-5", operator="admin")
    assert mig.store.get_task("t-5")["status"] == "completed"
    # 回滚：拆分回滚 = 新库当前全部文档（提交时由端点解析落入 params）
    mig.store.create_task("t-5r", op="rollback",
                          params={"rollback_kind": "split", "rollback_of": "t-5",
                                  "original_source_library_id": "lib-a", "library_id": "lib-b5",
                                  "collection": "g1", "doc_ids": ["d1"]},
                          total=1)
    mig.run_task("t-5r", operator="admin")
    assert mig.store.get_task("t-5r")["status"] == "completed"
    assert library_registry.get_library("lib-b5").status == "retired"
    with sqlite3.connect(mig.meta_db) as conn:
        assert conn.execute("SELECT library_id FROM nodes WHERE id='d1'").fetchone()[0] == "lib-a"
