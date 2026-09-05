"""rescore 补判路径单测：prediction_override 跳过问答链路；start_eval_run 透传与 pre_done 排除。"""
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


class ExplodingEvaluator:
    """run_prediction 被调用即失败——证明 rescore 路径没有重新作答。"""

    def run_prediction(self, question, stage_callback=None):
        raise AssertionError("rescore 不应触发 run_prediction")

    def evaluate(self, question, gold, prediction):
        return {"score": 1.0 if prediction.get("answer") else 0.0, "evaluated": True}


class PredictionOverrideTests(unittest.TestCase):
    def test_override_skips_run_prediction(self):
        result = suite_runner._run_single_question(
            {"question_id": "q1", "answer_gold": {"gold_answer": "x"}},
            ["answer"],
            {"answer": ExplodingEvaluator()},
            prediction_override={"answer": "存量答案", "citations": []},
        )
        self.assertEqual(result["status"], "completed")
        self.assertEqual(result["quality"], "correct")
        self.assertEqual(result["prediction"]["answer"], "存量答案")

    def test_override_with_error_falls_through_to_full_run(self):
        class Runner:
            def run_prediction(self, question, stage_callback=None):
                return {"answer": "重答"}

            def evaluate(self, question, gold, prediction):
                return {"score": 1.0, "evaluated": True}

        result = suite_runner._run_single_question(
            {"question_id": "q1"}, ["answer"], {"answer": Runner()},
            prediction_override={"error": "存量 prediction 不完整"},
        )
        self.assertEqual(result["prediction"]["answer"], "重答")


class StartEvalRunRescoreTests(unittest.TestCase):
    """start_eval_run(rescore_question_ids)：pre_done 排除补判题 + rescore_map 构造并传给线程。"""

    QUESTIONS = [{"question_id": f"q{i}"} for i in range(3)]

    def _details(self, light=True):
        rows = [
            {"question_id": "q0", "status": "completed", "scores": {"s": 1}},
            {"question_id": "q1", "status": "completed", "scores": {"s": 0},
             "prediction": None if light else {"answer": "存量答案"}},
            {"question_id": "q2", "status": "completed", "scores": {"s": 1}},
        ]
        return rows if not light else [{k: v for k, v in r.items() if k != "prediction"} for r in rows]

    def test_rescore_map_and_pre_done_exclusion(self):
        captured = {}

        class FakeThread:
            def __init__(self, target=None, args=(), daemon=None):
                captured["args"] = args

            def start(self):
                pass

        with mock.patch.object(suite_runner, "_current_run_id", None), \
             mock.patch.object(suite_runner.result_store, "list_questions", return_value=self.QUESTIONS), \
             mock.patch.object(suite_runner.result_store, "get_run", return_value={"dataset_id": "ds", "run_name": "r"}), \
             mock.patch.object(suite_runner.result_store, "reset_run_for_resume"), \
             mock.patch.object(suite_runner.result_store, "list_run_details",
                               side_effect=lambda rid, light=False: self._details(light)), \
             mock.patch.object(suite_runner.threading, "Thread", FakeThread):
            suite_runner.start_eval_run("ds", resume_run_id="run-x", rescore_question_ids=["q1"])

        args = captured["args"]
        pre_done, in_place, rescore_map = args[4], args[5], args[7]
        self.assertNotIn("q1", pre_done, "补判题必须从 pre_done 排除才会被重新处理")
        self.assertEqual({"q0", "q2"}, set(pre_done))
        self.assertTrue(in_place)
        self.assertEqual(rescore_map, {"q1": {"answer": "存量答案"}})

    def test_rescore_without_resume_rejected(self):
        with mock.patch.object(suite_runner, "_current_run_id", None):
            with self.assertRaises(ValueError):
                suite_runner.start_eval_run("ds", rescore_question_ids=["q1"])


if __name__ == "__main__":
    unittest.main()
