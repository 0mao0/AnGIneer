"""suite_runner 并发路径单测：验证 _run_questions_concurrent 并行执行与计数。

不触网：mock _run_one_worker 与 result_store 写库路径。
"""
import os
import sys
import threading
import time
import unittest
from unittest import mock

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../../services/evals-core/src")))
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../../services/angineer-core/src")))
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../../services/ai-inference/src")))
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../../services/sop-core/src")))

from evals_core.runner import suite_runner  # noqa: E402


class ConcurrencyTests(unittest.TestCase):
    def test_eval_concurrency_default(self):
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop("EVAL_CONCURRENCY", None)
            self.assertEqual(suite_runner._eval_concurrency(), 3)

    def test_eval_concurrency_env_override(self):
        with mock.patch.dict(os.environ, {"EVAL_CONCURRENCY": "1"}, clear=False):
            self.assertEqual(suite_runner._eval_concurrency(), 1)

    def test_eval_concurrency_invalid_falls_back(self):
        with mock.patch.dict(os.environ, {"EVAL_CONCURRENCY": "abc"}, clear=False):
            self.assertEqual(suite_runner._eval_concurrency(), 1)

    def test_run_questions_concurrent_parallel_and_counts(self):
        questions = [{"question_id": f"q{i}", "question": f"题{i}"} for i in range(8)]
        active = []
        lock = threading.Lock()

        def fake_worker(question, evaluator_names, stage_callback=None):
            with lock:
                active.append(question["question_id"])
            time.sleep(0.15)
            return question["question_id"], {
                "status": "completed",
                "scores": {"answer": {"score": 1.0}},
                "prediction": {"answer": "x"},
                "all_scores": {"answer": {"score": 1.0}},
                "all_predictions": {"answer": {"answer": "x"}},
            }

        with mock.patch.object(suite_runner, "_run_one_worker", side_effect=fake_worker):
            with mock.patch.object(suite_runner.result_store, "delete_run_detail"):
                with mock.patch.object(suite_runner.result_store, "insert_run_detail"):
                    with mock.patch.object(suite_runner.result_store, "update_run_detail"):
                        with mock.patch.object(suite_runner.result_store, "update_run_progress") as progress:
                            executed = suite_runner._run_questions_concurrent(
                                run_id="run-x",
                                questions=questions,
                                pre_done={},
                                in_place=False,
                                pre_done_count=0,
                                workers=4,
                                stop_event=threading.Event(),
                                override_doc_ids=None,
                                config_name=None,
                            )
        self.assertEqual(executed, 8)
        self.assertEqual(progress.call_count, 8)
        # 并发证据：任一时刻 active 超过 1
        self.assertGreaterEqual(len(set(active)), 2)

    def test_run_questions_concurrent_respects_stop(self):
        questions = [{"question_id": f"q{i}"} for i in range(10)]
        stop = threading.Event()
        stop.set()
        with mock.patch.object(suite_runner, "_run_one_worker") as worker:
            with mock.patch.object(suite_runner.result_store, "delete_run_detail"):
                with mock.patch.object(suite_runner.result_store, "insert_run_detail"):
                    with mock.patch.object(suite_runner.result_store, "update_run_detail"):
                        with mock.patch.object(suite_runner.result_store, "update_run_progress"):
                            executed = suite_runner._run_questions_concurrent(
                                run_id="run-x",
                                questions=questions,
                                pre_done={},
                                in_place=False,
                                pre_done_count=0,
                                workers=4,
                                stop_event=stop,
                                override_doc_ids=None,
                                config_name=None,
                            )
        self.assertEqual(executed, 0)
        worker.assert_not_called()


if __name__ == "__main__":
    unittest.main()
