"""WAL 写锁韧性（2026-10-02 实踩回归钉）。

事故：nightly 1040 题跑完后，主线程 finally 的保留策略把 5 个过期 run 的数千行
UPDATE 攒成一笔写事务独占 WAL 写锁 ~7.5 分钟；同期补判 resume 线程 complete_run
撞锁（Python connect 默认 busy timeout 仅 5s）抛 database is locked，except 里
fail_run 同败，线程裸死 → run 永卡 running(1040/1040)，nightly 主循环空等到
420 分钟超时线。

三层修复各钉一条：
- result_store._get_conn timeout=30 → 瞬时锁在 sqlite busy 处理器里排队即过；
- _write_run_state → 撞 locked/busy 退避重试、真错误不重试；
- retention._compact_run → 每 COMMIT_BATCH_ROWS 行提交一次（写锁分段持有）；
- pipeline._await_terminal → 进度停滞超 STALL_WARN_S 打点名告警。
"""
import asyncio
import logging
import os
import shutil
import sqlite3
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "src")))

from evals_core.nightly import pipeline  # noqa: E402
from evals_core.storage import result_store, retention  # noqa: E402


class _FlakyConn:
    """假连接：前 fail_times 次 execute 抛 database is locked，之后放行。"""

    def __init__(self, fail_times):
        self.fail_times = fail_times
        self.executed = 0
        self.commits = 0
        self.rollbacks = 0

    def execute(self, sql, params=()):
        self.executed += 1
        if self.executed <= self.fail_times:
            raise sqlite3.OperationalError("database is locked")

    def commit(self):
        self.commits += 1

    def rollback(self):
        self.rollbacks += 1


class WriteRunStateRetry(unittest.TestCase):
    def setUp(self):
        self._patch = mock.patch.object(result_store, "_LOCK_RETRY_BASE_WAIT_S", 0.01)
        self._patch.start()

    def tearDown(self):
        self._patch.stop()

    def test_retries_locked_then_succeeds(self):
        conn = _FlakyConn(fail_times=3)
        result_store._write_run_state(conn, [("UPDATE eval_run SET status='completed' WHERE run_id=?", ("r",))],
                                      what="complete_run", run_id="r")
        self.assertEqual(conn.executed, 4)  # 3 败 1 成
        self.assertEqual(conn.commits, 1)
        self.assertEqual(conn.rollbacks, 3)  # 每次重试前必须回滚，防空事务钉住 WAL 读快照

    def test_exhausts_and_raises(self):
        conn = _FlakyConn(fail_times=result_store._LOCK_RETRY_ATTEMPTS + 5)
        with self.assertRaises(sqlite3.OperationalError):
            result_store._write_run_state(conn, [("UPDATE x", ())], what="complete_run", run_id="r")
        self.assertEqual(conn.executed, result_store._LOCK_RETRY_ATTEMPTS)

    def test_real_error_no_retry(self):
        class _BadConn(_FlakyConn):
            def execute(self, sql, params=()):
                self.executed += 1
                raise sqlite3.OperationalError("no such table: nope")

        conn = _BadConn(0)
        with self.assertRaises(sqlite3.OperationalError):
            result_store._write_run_state(conn, [("UPDATE x", ())], what="fail_run", run_id="r")
        self.assertEqual(conn.executed, 1, "非 locked/busy 的 OperationalError 必须照抛不重试")


class TransientLockSurvives(unittest.TestCase):
    """真实并发：另一连接持未提交写事务 0.6s，complete_run 应排队等过而不是死。"""

    def setUp(self):
        self._tmp = tempfile.mkdtemp()
        self._orig_db = result_store._DB_PATH
        self._reset_conn()
        result_store._DB_PATH = str(Path(self._tmp) / "evals.sqlite")
        result_store.init_db()
        conn = result_store._get_conn()
        conn.execute(
            "INSERT INTO eval_run (run_id, dataset_id, status, total_questions, completed_questions,"
            " started_at, run_name, is_full_run, owner_pid) VALUES ('r-lock','ds','running',1,1,'t','',1,0)")
        conn.commit()

    def tearDown(self):
        self._reset_conn()
        result_store._DB_PATH = self._orig_db
        shutil.rmtree(self._tmp, ignore_errors=True)

    def _reset_conn(self):
        local = result_store._get_thread_local()
        conn = getattr(local, "conn", None)
        if conn is not None:
            try:
                conn.close()
            except Exception:
                pass
            del local.conn

    def test_complete_run_waits_out_holder(self):
        # holder 连接与 commit 必须同线程（sqlite 同线程限制），建连也放进释放线程；
        # 否则线程炸掉锁永不释放，complete_run 白撞满 busy_timeout+重试（≈150s）。
        released = threading.Event()
        holder_err: list = []

        def hold_and_release():
            holder = sqlite3.connect(result_store._DB_PATH, timeout=5)
            try:
                holder.execute("BEGIN IMMEDIATE")
                holder.execute("UPDATE eval_run SET run_name='held' WHERE run_id='r-lock'")
                time.sleep(0.6)
                holder.commit()
            except Exception as exc:  # noqa: BLE001
                holder_err.append(exc)
            finally:
                holder.close()
                released.set()

        threading.Thread(target=hold_and_release, daemon=True).start()
        t0 = time.monotonic()
        result_store.complete_run("r-lock", {"overall_score": 0.9})  # 不抛错 = busy_timeout 生效
        self.assertEqual(holder_err, [], "holder 线程自身异常会让本测试假象成立")
        self.assertTrue(released.wait(2))
        self.assertLess(time.monotonic() - t0, 5, "应在对方放锁后立即通过，而不是耗满重试")
        self.assertEqual(result_store.get_run("r-lock")["status"], "completed")


class BatchedCompaction(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.mkdtemp()
        self._orig_db = result_store._DB_PATH
        self._reset_conn()
        result_store._DB_PATH = str(Path(self._tmp) / "evals.sqlite")
        result_store.init_db()

    def tearDown(self):
        self._reset_conn()
        result_store._DB_PATH = self._orig_db
        shutil.rmtree(self._tmp, ignore_errors=True)

    def _reset_conn(self):
        local = result_store._get_thread_local()
        conn = getattr(local, "conn", None)
        if conn is not None:
            try:
                conn.close()
            except Exception:
                pass
            del local.conn

    def test_compact_run_commits_per_batch(self):
        conn = result_store._get_conn()
        conn.execute(
            "INSERT INTO eval_run (run_id, dataset_id, status, total_questions, completed_questions,"
            " started_at, completed_at, run_name, is_full_run, owner_pid)"
            " VALUES ('r-old','ds','completed',6,6,'2026-01-01T04:00:00','2026-01-01T04:00:00','',1,0)")
        payload = {"answer": "42", "retrieval_debug": {"x": "y" * 100}}
        for i in range(6):
            result_store.insert_run_detail({
                "run_id": "r-old", "question_id": f"q{i}", "status": "ok", "quality": "",
                "prediction": payload, "scores": {}, "all_scores": {},
                "all_predictions": {}, "error": "", "latency_ms": 1,
            })
        conn.commit()

        class _CommitSpy:  # sqlite3.Connection 实例不支持 setattr 换 commit，用代理计数
            def __init__(self, real):
                self._real = real
                self.commits = 0

            def execute(self, sql, params=()):
                return self._real.execute(sql, params)

            def commit(self):
                self.commits += 1
                self._real.commit()

        with mock.patch.object(retention, "COMMIT_BATCH_ROWS", 2):
            spy = _CommitSpy(conn)
            changed = retention._compact_run(spy, "r-old")
        self.assertEqual(changed, 6)
        # 6 行、批大小 2 → 循环内至少 3 次提交；一笔攒到底（回归）只有末尾 enforce 那一次
        self.assertGreaterEqual(spy.commits, 3,
                                "_compact_run 必须分批提交，禁止把整 run 攒成一笔写事务")


class StallWarning(unittest.TestCase):
    def _drive(self, progress_sequence, stall_s, deadline_s):
        """跑 _await_terminal 到超时，收集期间产生的 WARNING 记录。

        不用 assertLogs——它在 0 条记录时直接 fail，而「无告警」正是用例 2 的预期。"""
        it = iter(progress_sequence)
        current = {"p": next(it, 500)}

        def fake_get_run(run_id):
            cur = current["p"]
            nxt = next(it, None)
            if nxt is not None:
                current["p"] = nxt
            return {"status": "running", "completed_questions": cur, "total_questions": 1040}

        records = []

        class _Collector(logging.Handler):
            def emit(self, record):
                records.append(record)

        collector = _Collector(level=logging.WARNING)
        pipeline.logger.addHandler(collector)
        try:
            with mock.patch.object(result_store, "get_run", fake_get_run), \
                 mock.patch.object(pipeline, "POLL_INTERVAL_S", 0.01), \
                 mock.patch.object(pipeline, "STALL_WARN_S", stall_s):
                loop = asyncio.new_event_loop()
                try:
                    with self.assertRaises(pipeline.PipelineError):
                        loop.run_until_complete(
                            pipeline._await_terminal("r-stall", time.monotonic() + deadline_s))
                finally:
                    loop.close()
        finally:
            pipeline.logger.removeHandler(collector)
        return records

    def test_stall_logs_warning(self):
        records = self._drive([500] * 100, stall_s=0.05, deadline_s=0.4)
        self.assertTrue(any("无进度" in r.getMessage() and "1040" in r.getMessage() for r in records),
                        "进度停滞必须点名告警（含完成数/总数），否则又只剩 7 小时后的假超时")

    def test_moving_progress_no_warning(self):
        seq = list(range(100, 400)) + [400] * 3  # 持续前进后短暂平，但从未超停滞阈值
        records = self._drive(seq, stall_s=0.2, deadline_s=0.05)
        # deadline 极短：正常超时 PipelineError，且未及触发告警
        self.assertTrue(all("无进度" not in r.getMessage() for r in records))


class EnforceAfterRunCheckpoint(unittest.TestCase):
    def test_wal_checkpoint_after_compaction_is_best_effort(self):
        # 非 WAL 库上 pragma wal_checkpoint 返回空而非抛错；真 WAL 库走 smoke 路径即可
        tmp = tempfile.mkdtemp()
        orig = result_store._DB_PATH
        try:
            result_store._DB_PATH = str(Path(tmp) / "evals.sqlite")
            local = result_store._get_thread_local()
            if getattr(local, "conn", None) is not None:
                local.conn.close()
                del local.conn
            result_store.init_db()
            stats = retention.enforce_after_run()
            self.assertIn("compacted_runs", stats)
        finally:
            local = result_store._get_thread_local()
            if getattr(local, "conn", None) is not None:
                local.conn.close()
                del local.conn
            result_store._DB_PATH = orig
            shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
