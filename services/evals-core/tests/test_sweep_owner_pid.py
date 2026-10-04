"""启动清扫所有权判定表（req-nightly-interrupt-resume §2-B1 / 验收 A1）。

回归 2026-09-06 事故：多实例共用 evals.sqlite 时，后启动实例的清扫把前一个
还活着的实例正在跑的 run（53/487）误标为 cancelled。
回归 2026-10-04 事故：docker 容器主进程恒 PID 1，旧判定 `_pid_alive(owner_pid)`
对 owner_pid=1 恒真 → 回收分支成死代码，被部署砸掉的 run 永久 status=running。
判定表：本实例内存活体不动；owner==self 且不在内存 = pid 复用幽灵 → 回收；
owner 为另一活进程 → 不动；owner 已死 / owner_pid=0 → 回收。
"""

import os
import subprocess
import sys
import tempfile
import threading
import unittest
from pathlib import Path

TESTS_DIR = Path(__file__).resolve().parent
SRC = TESTS_DIR.parent / "src"
for p in (str(SRC), str(TESTS_DIR)):
    if p not in sys.path:
        sys.path.insert(0, p)

from evals_core.runner import suite_runner
from evals_core.runner.suite_runner import _pid_alive, sweep_interrupted_runs
from evals_core.storage import result_store

DEAD_PID = 99999999


class EvalsDbCase(unittest.TestCase):
    """临时库切换；Windows 上必须先关连接再删临时目录。"""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self._orig_db = result_store._DB_PATH
        self._orig_local = result_store._LOCAL
        result_store._DB_PATH = str(Path(self._tmp.name) / "evals.sqlite")
        result_store._LOCAL = None
        result_store.init_db()

    def tearDown(self):
        try:
            conn = result_store._get_conn()
        except Exception:
            conn = None
        if conn is not None:
            try:
                conn.close()
            except Exception:
                pass
        result_store._LOCAL = None
        result_store._DB_PATH = self._orig_db
        self._tmp.cleanup()

    def insert_run(self, run_id: str, owner_pid: int) -> None:
        conn = result_store._get_conn()
        conn.execute(
            "INSERT INTO eval_run (run_id, dataset_id, status, total_questions, completed_questions, started_at, owner_pid) "
            "VALUES (?, 'ds-x', 'running', 10, 3, '2026-09-06T20:00:00', ?)",
            (run_id, owner_pid),
        )
        conn.commit()


class TestPidAlive(unittest.TestCase):
    def test_self_is_alive(self):
        self.assertTrue(_pid_alive(os.getpid()))

    def test_dead_and_invalid_pids(self):
        self.assertFalse(_pid_alive(DEAD_PID))
        self.assertFalse(_pid_alive(0))
        self.assertFalse(_pid_alive(-1))


class TestSweepOwnerGuard(EvalsDbCase):
    def tearDown(self):
        # 内存登记表是模块级状态，用例间必须清干净
        suite_runner._stop_events.clear()
        super().tearDown()

    def insert_detail(self, run_id: str, qid: str, status: str, quality=None) -> None:
        result_store.insert_run_detail({
            "run_id": run_id, "question_id": qid, "status": status, "quality": quality,
        })

    def test_container_form_pid_reuse_is_swept(self):
        """A1①容器形态：owner_pid==self（上一容器 PID 1 被本进程复用）且不在本实例
        内存 → 幽灵，盖章回收；correct/wrong 与明细一致（部署砸 run 实踩形态）。"""
        self.insert_run("run-ghost", os.getpid())
        self.insert_detail("run-ghost", "q1", "completed", "correct")
        self.insert_detail("run-ghost", "q2", "completed", "correct")
        self.insert_detail("run-ghost", "q3", "completed", "wrong")
        self.insert_detail("run-ghost", "q4", "pending")
        self.assertEqual(sweep_interrupted_runs(), 1)
        run = result_store.get_run("run-ghost")
        self.assertEqual(run["status"], "cancelled")
        self.assertTrue(run["summary_scores"]["interrupted_by_startup_sweep"])
        self.assertEqual(
            (run["summary_scores"]["correct"], run["summary_scores"]["wrong"],
             run["summary_scores"]["skipped"]), (2, 1, 7))
        # B4 回归锁：盖章后日常测试列表不再有永久「评测中」幽灵行
        self.assertEqual(suite_runner.list_running_runs(), [])

    def test_running_here_is_never_swept(self):
        """A1②本实例内存活体（登记了停止信号）→ 不动，即使 owner==self。"""
        self.insert_run("run-here", os.getpid())
        suite_runner._stop_events["run-here"] = threading.Event()
        self.assertEqual(sweep_interrupted_runs(), 0)
        self.assertEqual(result_store.get_run("run-here")["status"], "running")

    def test_other_live_instance_is_never_swept(self):
        """A1③他实例活体（pid 活着且≠self）→ 不动：53/487 误杀事故的守卫。
        用真实子进程拿一个「活着的他 pid」，不 mock _pid_alive。"""
        child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"])
        try:
            self.insert_run("run-other", child.pid)
            self.assertEqual(sweep_interrupted_runs(), 0)
            self.assertEqual(result_store.get_run("run-other")["status"], "running")
        finally:
            child.terminate()
            child.wait(timeout=10)

    def test_dead_owner_run_is_swept(self):
        """A1③ 对偶：owner 已死（pid 不存在）→ 回收。"""
        self.insert_run("run-dead-owner", DEAD_PID)
        self.assertEqual(sweep_interrupted_runs(), 1)
        run = result_store.get_run("run-dead-owner")
        self.assertEqual(run["status"], "cancelled")
        # 部分汇总按已完成明细真实统计（明细为空 → correct/wrong 均 0，skipped=10）
        self.assertEqual(run["summary_scores"]["skipped"], 10)

    def test_legacy_zero_pid_run_is_swept(self):
        """A1④历史行 owner_pid=0 无法判属主，照旧回收（不改变旧行为）。"""
        self.insert_run("run-legacy", 0)
        self.assertEqual(sweep_interrupted_runs(), 1)
        self.assertEqual(result_store.get_run("run-legacy")["status"], "cancelled")


class TestCreateRunRecordsOwner(EvalsDbCase):
    def test_create_run_and_resume_stamp_owner_pid(self):
        created = result_store.create_run("ds-x", 5)
        conn = result_store._get_conn()
        pid = conn.execute(
            "SELECT owner_pid FROM eval_run WHERE run_id = ?", (created["run_id"],)
        ).fetchone()[0]
        self.assertEqual(pid, os.getpid())
        result_store.cancel_run(created["run_id"], {})
        result_store.reset_run_for_resume(created["run_id"], {"answer_model": "m"})
        pid2 = conn.execute(
            "SELECT owner_pid FROM eval_run WHERE run_id = ?", (created["run_id"],)
        ).fetchone()[0]
        self.assertEqual(pid2, os.getpid())


if __name__ == "__main__":
    unittest.main()
