import pytest
from docs_core.kb_migration_store import KbMigrationStore


@pytest.fixture
def store(tmp_path):
    return KbMigrationStore(db_path=tmp_path / "meta.sqlite")


def test_create_get_update_roundtrip(store):
    store.create_task("mig-1", op="split", params={"source": "a"}, total=3)
    task = store.get_task("mig-1")
    assert task["status"] == "running" and task["progress_total"] == 3
    store.update_task("mig-1", progress_done=2, stage="execute")
    task = store.get_task("mig-1")
    assert task["progress_done"] == 2 and task["stage"] == "execute"


def test_cancel_flag(store):
    store.create_task("mig-2", op="merge", params={}, total=1)
    assert store.is_cancel_requested("mig-2") is False
    store.request_cancel("mig-2")
    assert store.is_cancel_requested("mig-2") is True


def test_append_step_and_migrated_docs(store):
    store.create_task("mig-3", op="split", params={}, total=2)
    store.append_step("mig-3", "execute", "doc-1 迁移完成")
    store.mark_doc_migrated("mig-3", "doc-1")
    task = store.get_task("mig-1".replace("1", "3"))
    assert task["steps"][0]["step"] == "doc-1 迁移完成"  # 键名以计划 Task 14 前端类型 step 为准（计划测试原写 message，笔误）
    assert task["migrated_doc_ids"] == ["doc-1"]
    # 幂等：重复标记不翻倍
    store.mark_doc_migrated("mig-3", "doc-1")
    assert store.get_task("mig-3")["migrated_doc_ids"] == ["doc-1"]


def test_list_tasks_order(store):
    store.create_task("mig-a", op="split", params={}, total=1)
    store.create_task("mig-b", op="merge", params={}, total=1)
    ids = [t["id"] for t in store.list_tasks()]
    assert ids == ["mig-b", "mig-a"]  # 新的在前
