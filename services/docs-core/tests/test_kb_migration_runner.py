import pytest
from docs_core.kb_migrator import KbMigrationRunner, MigrationBlocked


def test_single_flight(tmp_path):
    runner = KbMigrationRunner(migrator=None)
    runner._threads["t-live"] = type("T", (), {"is_alive": lambda self: True})()
    with pytest.raises(MigrationBlocked):
        runner.submit("t-new")


def test_submit_and_finish(tmp_path):
    class _Mig:
        def __init__(self):
            self.ran = []
        def run_task(self, task_id, *, operator="admin"):
            self.ran.append(task_id)
    mig = _Mig()
    runner = KbMigrationRunner(migrator=mig)
    worker = runner.submit("t-1")  # 用返回句柄 join：worker 收尾会自摘，按下标回读有竞态
    worker.join(timeout=5)
    assert mig.ran == ["t-1"]


def test_cancel_sets_store_flag(tmp_path):
    class _Store:
        def __init__(self): self.cancelled = []
        def request_cancel(self, tid): self.cancelled.append(tid)
        def get_task(self, tid): return {"status": "running"}
    class _Mig:
        store = _Store()
        def run_task(self, task_id, *, operator="admin"): pass
    mig = _Mig()
    runner = KbMigrationRunner(migrator=mig)
    runner.request_cancel("t-9")
    assert mig.store.cancelled == ["t-9"]
