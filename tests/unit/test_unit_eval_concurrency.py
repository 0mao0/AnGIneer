"""并发占用确认 + run 明细按题集顺序返回（2026-09-27 用户实踩两条）。

① 明细行 id 是建行顺序（题目开跑时删行重建，重建行 id 更大），直接按 id 返回会让
   右栏题号与题目列表整体错位——中栏第 3 题在右栏显示成第 20 格。
② 「已有评测在跑」旧实现是后端硬拦（400 + toast），用户只能放弃；现在返 409 + 在跑
   清单，用户点「仍然开始」带 allow_concurrent 重发即可并发。
"""
import os
import sys
import unittest
from unittest import mock

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "../.."))
for sub in ("evals-core", "angineer-core", "ai-inference", "sop-core"):
    p = os.path.join(ROOT, "services", sub, "src")
    if p not in sys.path:
        sys.path.insert(0, p)

from evals_core.runner import suite_runner  # noqa: E402

QUESTIONS = [{"question_id": f"q{i:02d}"} for i in range(1, 6)]


class RunDetailOrderTests(unittest.TestCase):
    """明细顺序必须跟题集顺序一致，而不是明细行的建行顺序。"""

    def test_details_sorted_by_dataset_order(self):
        # 建行顺序：先落 q03（没跑到，保留低位 id），后落 q01/q02（删行重建过，id 更大）
        details = [
            {"question_id": "q03", "status": "pending"},
            {"question_id": "q01", "status": "completed"},
            {"question_id": "q02", "status": "completed"},
        ]
        with mock.patch.object(suite_runner.result_store, "list_questions", return_value=QUESTIONS):
            enriched = suite_runner._enrich_run_details(details, "ds")

        self.assertEqual(["q01", "q02", "q03"], [d["question_id"] for d in enriched])

    def test_unknown_question_kept_at_tail(self):
        # 题集里已删除的题（历史 run）排在末尾，不挤占正常题号
        details = [
            {"question_id": "q-deleted", "status": "completed"},
            {"question_id": "q02", "status": "completed"},
            {"question_id": "q01", "status": "completed"},
        ]
        with mock.patch.object(suite_runner.result_store, "list_questions", return_value=QUESTIONS):
            enriched = suite_runner._enrich_run_details(details, "ds")

        self.assertEqual(["q01", "q02", "q-deleted"], [d["question_id"] for d in enriched])


class BusyGateTests(unittest.TestCase):
    """已有评测在跑：默认拦下并带清单，用户确认后放行。"""

    BUSY = [{
        "run_id": "run-live", "dataset_id": "ds-a", "dataset_title": "海港水文30问",
        "model": "Qwen3.6-35B-A3B", "completed_questions": 10, "total_questions": 30,
        "started_at": "2026-09-27T20:05:51",
    }]

    def test_busy_raises_with_running_list(self):
        with mock.patch.object(suite_runner, "list_running_runs", return_value=self.BUSY):
            with self.assertRaises(suite_runner.EvalBusyError) as ctx:
                suite_runner.start_eval_run("ds-b")
        self.assertEqual("run-live", ctx.exception.running[0]["run_id"])
        self.assertIn("海港水文30问", str(ctx.exception))

    def test_allow_concurrent_proceeds(self):
        captured = {}

        class FakeThread:
            def __init__(self, target=None, args=(), daemon=None):
                captured["args"] = args

            def start(self):
                pass

        with mock.patch.object(suite_runner, "list_running_runs", return_value=self.BUSY), \
             mock.patch.object(suite_runner.result_store, "list_questions", return_value=QUESTIONS), \
             mock.patch.object(suite_runner.result_store, "create_run",
                               return_value={"run_id": "run-new", "status": "running"}), \
             mock.patch.object(suite_runner.threading, "Thread", FakeThread):
            run = suite_runner.start_eval_run("ds-b", allow_concurrent=True)

        self.assertEqual("run-new", run["run_id"])
        self.assertTrue(captured["args"], "并发确认后必须真的起线程，而不是只跳过拦截")

    def test_restart_of_self_is_not_busy(self):
        """重来的目标 run 自己仍是 running（刚点重来）：不该被自己拦住。"""
        captured = {}

        class FakeThread:
            def __init__(self, target=None, args=(), daemon=None):
                captured["args"] = args

            def start(self):
                pass

        busy = [dict(self.BUSY[0], run_id="run-self")]
        with mock.patch.object(suite_runner, "list_running_runs", return_value=busy), \
             mock.patch.object(suite_runner.result_store, "list_questions", return_value=QUESTIONS), \
             mock.patch.object(suite_runner.result_store, "get_run",
                               return_value={"run_id": "run-self", "dataset_id": "ds-b", "run_name": "r"}), \
             mock.patch.object(suite_runner.result_store, "restart_run_for_retry"), \
             mock.patch.object(suite_runner.threading, "Thread", FakeThread):
            suite_runner.start_eval_run("ds-b", restart_run_id="run-self")

        self.assertTrue(captured["args"])


class RunningListTests(unittest.TestCase):
    def test_only_running_runs_with_titles(self):
        runs = [
            {"run_id": "run-1", "dataset_id": "ds-a", "status": "running",
             "completed_questions": 3, "total_questions": 10, "started_at": "t",
             "config_snapshot": {"model": "m1"}},
            {"run_id": "run-2", "dataset_id": "ds-b", "status": "completed",
             "completed_questions": 10, "total_questions": 10},
        ]
        with mock.patch.object(suite_runner.result_store, "list_runs", return_value=runs), \
             mock.patch.object(suite_runner.result_store, "get_dataset",
                               return_value={"dataset_id": "ds-a", "title": "精筛50题"}):
            out = suite_runner.list_running_runs()

        self.assertEqual(["run-1"], [r["run_id"] for r in out])
        self.assertEqual("精筛50题", out[0]["dataset_title"])
        self.assertEqual("m1", out[0]["model"])


class StopTargetTests(unittest.TestCase):
    """并发下停止必须打到指定 run，不能串台。"""

    def test_stop_sets_only_target_event(self):
        import threading
        ev_a, ev_b = threading.Event(), threading.Event()
        with mock.patch.dict(suite_runner._stop_events, {"run-a": ev_a, "run-b": ev_b}, clear=True):
            self.assertTrue(suite_runner.stop_eval_run("run-b"))

        self.assertFalse(ev_a.is_set())
        self.assertTrue(ev_b.is_set())

    def test_stop_unknown_run_falls_back_to_zombie_cleanup(self):
        with mock.patch.dict(suite_runner._stop_events, {}, clear=True), \
             mock.patch.object(suite_runner.result_store, "get_run",
                               return_value={"run_id": "run-z", "status": "completed"}):
            self.assertFalse(suite_runner.stop_eval_run("run-z"))


if __name__ == "__main__":
    unittest.main()
