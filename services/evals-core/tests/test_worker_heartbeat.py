"""worker 挂死回收（2026-10-24 事故回归）。

实踩形态：aichat 死后评测 worker 悬死（在途请求无超时挂起），run 行永远 running；
owner_pid 被复用后 _pid_alive 恒真，连启动清扫的属主守卫都被骗过。三件套修复的
回归锁：①心跳往返 ②「owner 活着但心跳超时」回收 + pid 复用守卫不误杀 ③新鲜/空
心跳保持 53/487 误杀守卫原语义 ④worker 进程入口无条件退出（P0，防线程 join 卡死）。
"""

import json
import os
import subprocess
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

TESTS_DIR = Path(__file__).resolve().parent
SRC = TESTS_DIR.parent / "src"
for p in (str(SRC), str(TESTS_DIR)):
    if p not in sys.path:
        sys.path.insert(0, p)

from evals_core.runner import suite_runner
from evals_core.runner.suite_runner import (
    _heartbeat_stale,
    _worker_cmdline,
    sweep_interrupted_runs,
)
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

    def insert_run(self, run_id: str, owner_pid: int, heartbeat=None) -> None:
        conn = result_store._get_conn()
        conn.execute(
            "INSERT INTO eval_run (run_id, dataset_id, status, total_questions, completed_questions,"
            " started_at, owner_pid, owner_heartbeat) "
            "VALUES (?, 'ds-x', 'running', 10, 3, '2026-10-24T12:00:00', ?, ?)",
            (run_id, owner_pid, heartbeat),
        )
        conn.commit()


class TestTouchHeartbeat(EvalsDbCase):
    def test_roundtrip_writes_fresh_utc_iso(self):
        created = result_store.create_run("ds-x", 5)
        result_store.touch_owner_heartbeat(created["run_id"])
        conn = result_store._get_conn()
        raw = conn.execute(
            "SELECT owner_heartbeat FROM eval_run WHERE run_id = ?", (created["run_id"],)
        ).fetchone()[0]
        ts = datetime.fromisoformat(raw)
        self.assertIsNotNone(ts.tzinfo)
        self.assertLess(datetime.now(timezone.utc) - ts, timedelta(minutes=1))

    def test_heartbeat_stale_predicate(self):
        stale = (datetime.now(timezone.utc) - timedelta(minutes=30)).isoformat()
        fresh = datetime.now(timezone.utc).isoformat()
        self.assertTrue(_heartbeat_stale({"owner_heartbeat": stale}))
        self.assertFalse(_heartbeat_stale({"owner_heartbeat": fresh}))
        self.assertFalse(_heartbeat_stale({"owner_heartbeat": None}))
        self.assertFalse(_heartbeat_stale({}))
        self.assertFalse(_heartbeat_stale({"owner_heartbeat": "not-a-time"}))


class TestSweepStaleHeartbeat(EvalsDbCase):
    """挂死回收判定表：心跳超时才是「owner 活着也回收」的唯一入口。"""

    def tearDown(self):
        suite_runner._stop_events.clear()
        super().tearDown()

    def test_stale_heartbeat_live_owner_is_swept_without_killing_unrelated_pid(self):
        """owner 活着但心跳超时 30 分钟 → 行回收；pid 复用守卫：命令行不含
        run_worker/run_id 的活进程（无辜复用者）不杀。"""
        child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"])
        try:
            stale = (datetime.now(timezone.utc) - timedelta(minutes=30)).isoformat()
            self.insert_run("run-wedged", child.pid, stale)
            self.assertEqual(sweep_interrupted_runs(), 1)
            run = result_store.get_run("run-wedged")
            self.assertEqual(run["status"], "cancelled")
            self.assertTrue(run["summary_scores"]["interrupted_by_startup_sweep"])
            self.assertIsNone(child.poll())  # 守卫拒杀，无辜进程仍活
        finally:
            child.terminate()
            child.wait(timeout=10)

    def test_fresh_heartbeat_live_owner_is_kept(self):
        child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"])
        try:
            self.insert_run("run-alive", child.pid, datetime.now(timezone.utc).isoformat())
            self.assertEqual(sweep_interrupted_runs(), 0)
            self.assertEqual(result_store.get_run("run-alive")["status"], "running")
        finally:
            child.terminate()
            child.wait(timeout=10)

    def test_null_heartbeat_live_owner_is_kept(self):
        """旧版 worker 不写心跳：53/487 误杀守卫原语义不回退。"""
        child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"])
        try:
            self.insert_run("run-legacy-hb", child.pid, None)
            self.assertEqual(sweep_interrupted_runs(), 0)
            self.assertEqual(result_store.get_run("run-legacy-hb")["status"], "running")
        finally:
            child.terminate()
            child.wait(timeout=10)

    def test_worker_cmdline_readable_on_this_platform(self):
        """本进程命令行可读（Linux /proc 或 psutil），供 pid 复用守卫用。"""
        cmdline = _worker_cmdline(os.getpid())
        if cmdline is None:
            self.skipTest("psutil 不可用且非 Linux，cmdline 不可读")
        self.assertTrue(cmdline.strip())


class TestWorkerEntryExits(unittest.TestCase):
    """P0：进程入口必须无条件退出，不得被线程 join/atexit 卡死（10-24 实测
    跑完 1040 题的 worker 存活 18h）。缺 run_id 的快速失败路径走 os._exit(2)。"""

    def test_missing_run_id_exits_fast_with_code_2(self):
        with tempfile.NamedTemporaryFile(
            "w", suffix=".json", delete=False, encoding="utf-8"
        ) as f:
            json.dump({"dataset_id": "x"}, f)
            path = f.name
        try:
            env = dict(os.environ)
            env["PYTHONPATH"] = os.pathsep.join([str(SRC), env.get("PYTHONPATH", "")])
            proc = subprocess.run(
                [sys.executable, "-m", "evals_core.runner.run_worker", "--params", path],
                capture_output=True, timeout=30, env=env,
            )
            self.assertEqual(proc.returncode, 2)
        finally:
            # worker 读完即删参数文件（防泄漏双保险），这里容忍已删
            os.unlink(path) if os.path.exists(path) else None


if __name__ == "__main__":
    unittest.main()
