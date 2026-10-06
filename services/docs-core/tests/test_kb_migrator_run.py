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
