"""evals 时间戳口径迁移回归（2026-10-07）。

旧问题：result_store 用 datetime.now().isoformat() 写库＝裸串（生产容器=UTC），
前端 new Date 把无偏移串当本地时间解析 → 生产历史时间整体早 8 小时（业主实锤）。
迁移后契约：
- 新写行一律带偏移（...+00:00）；
- 历史裸行仍按 UTC 读：_bjt_date / fmt_span / _find_resume_candidate 三种口径
  （带偏移、裸串 UTC）都换算正确；
- cleanup_individual_runs 的 cutoff 与两种口径行同场比较不炸。
"""
import os
import shutil
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "src")))

from evals_core.nightly import notify  # noqa: E402
from evals_core.nightly.pipeline import _find_resume_candidate  # noqa: E402
from evals_core.runner import suite_runner  # noqa: E402
from evals_core.storage import result_store, retention  # noqa: E402

BJT = timezone(timedelta(hours=8))


class TimestampStoreSuite(unittest.TestCase):
    def _reset_conn(self):
        local = result_store._get_thread_local()
        conn = getattr(local, "conn", None)
        if conn is not None:
            try:
                conn.close()
            except Exception:
                pass
            del local.conn

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

    def _insert_dataset(self, dataset_id):
        conn = result_store._get_conn()
        conn.execute("INSERT INTO eval_dataset (dataset_id, title) VALUES (?, ?)", (dataset_id, "ds"))
        conn.commit()

    def _mk_run(self, run_id, dataset_id, completed_at, is_full_run=0):
        conn = result_store._get_conn()
        conn.execute(
            "INSERT INTO eval_run (run_id, dataset_id, status, total_questions,"
            " completed_questions, started_at, completed_at, is_full_run) VALUES (?, ?,"
            " 'completed', 1, 1, ?, ?, ?)",
            (run_id, dataset_id, completed_at or "", completed_at, is_full_run),
        )
        conn.commit()

    def test_new_run_writes_offset_timestamp(self):
        run = result_store.create_run("ds-new", 1)
        self.assertTrue(run["started_at"].endswith("+00:00"),
                        f"新行必须带偏移，实际 {run['started_at']}")

    def test_cleanup_mixed_naive_and_aware(self):
        """1 小时闸：裸串（UTC 两小时前）删、带偏移新串（刚写）留；混场比较不抛 TypeError。"""
        self._insert_dataset("ds-cl")
        naive_old = (datetime.now(timezone.utc) - timedelta(hours=2)).replace(tzinfo=None).isoformat()
        self._mk_run("r-naive-old", "ds-cl", naive_old)
        # 带偏移、确在窗口内（1 分钟前）的单题 run 作参照：它绝不该被删
        recent = (datetime.now(timezone.utc) - timedelta(minutes=1)).isoformat(timespec="seconds")
        self._mk_run("r-aware-recent", "ds-cl", recent)
        removed = result_store.cleanup_individual_runs("ds-cl")
        self.assertEqual(removed, 1)
        conn = result_store._get_conn()
        left = {r["run_id"] for r in conn.execute(
            "SELECT run_id FROM eval_run WHERE dataset_id='ds-cl'")}
        self.assertEqual(left, {"r-aware-recent"})

    def test_bjt_date_both_conventions(self):
        utc = datetime(2026, 10, 7, 20, 0)  # UTC 20:00 = 北京 10-08 04:00
        aware = utc.replace(tzinfo=timezone.utc).isoformat()
        naive = utc.isoformat()
        self.assertEqual(retention._bjt_date(aware), "2026-10-08")
        self.assertEqual(retention._bjt_date(naive), "2026-10-08")

    def test_fmt_span_both_conventions(self):
        start = datetime(2026, 10, 7, 3, 42, tzinfo=timezone.utc)
        end = start + timedelta(hours=8)
        span, duration = notify.fmt_span(start.isoformat(), end.isoformat())
        self.assertEqual(span, "10-07 11:42 – 19:42")
        self.assertEqual(duration, "8h00m")
        span2, duration2 = notify.fmt_span(
            start.replace(tzinfo=None).isoformat(), end.replace(tzinfo=None).isoformat())
        self.assertEqual(span2, span)
        self.assertEqual(duration2, duration)


class ResumeWindowSuite(unittest.TestCase):
    """断点续跑窗口：aware 新行与 naive cutoff 混比是 TypeError 高危点。"""

    FP = {"eval_engine": "deepeval", "deepval_extra": "0", "judge_model": "J", "steps_fp": "abc"}

    def _mk_row(self, completed_at_ago_min):
        summary = {"total": 10, "correct": 5, "interrupted_by_startup_sweep": True}
        return {
            "run_id": "run-x", "status": "cancelled", "completed_questions": 5,
            "completed_at": (datetime.now(timezone.utc) - timedelta(
                minutes=completed_at_ago_min)).isoformat(timespec="seconds"),
            "summary_scores": summary, "config_snapshot": {"caliber_fp": self.FP},
        }

    def _find(self, completed_at, within_hours=6):
        row = self._mk_row(0)
        row["completed_at"] = completed_at
        orig_list = result_store.list_runs
        orig_fp = suite_runner.caliber_fingerprint
        result_store.list_runs = lambda ds: [row]
        suite_runner.caliber_fingerprint = lambda: dict(self.FP)
        try:
            return _find_resume_candidate("ds", within_hours=within_hours)
        finally:
            result_store.list_runs = orig_list
            suite_runner.caliber_fingerprint = orig_fp

    def test_aware_recent_is_candidate(self):
        self.assertEqual(self._find(self._mk_row(30)["completed_at"]), "run-x")

    def test_naive_legacy_recent_is_candidate(self):
        naive = (datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(minutes=30)).isoformat(timespec="seconds")
        self.assertEqual(self._find(naive), "run-x")

    def test_both_conventions_outside_window_rejected(self):
        aware_old = (datetime.now(timezone.utc) - timedelta(hours=7)).isoformat(timespec="seconds")
        naive_old = (datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(hours=7)).isoformat(timespec="seconds")
        self.assertEqual(self._find(aware_old), "")
        self.assertEqual(self._find(naive_old), "")
