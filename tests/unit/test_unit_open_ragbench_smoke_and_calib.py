import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../../scripts")))

from open_ragbench import build_smoke_set, common, judge_calibration, run_smoke  # noqa: E402


class BuildSmokeSetTests(unittest.TestCase):
    def test_smoke_bundle_mixes_positive_and_refusal(self):
        subset = {
            "dataset": {"dataset_id": "open-ragbench-subset-v1", "library_id": "lib-1"},
            "items": [
                {"question_id": f"q{i}", "tags": ["text" if i % 2 else "text-table"],
                 "answer": {"refusal_expected": False}}
                for i in range(40)
            ],
        }
        refusal = {
            "dataset": {"dataset_id": "open-ragbench-refusal-v1"},
            "items": [
                {"question_id": f"refusal-{i}", "tags": ["text"], "answer": {"refusal_expected": True}}
                for i in range(10)
            ],
        }
        with patch.object(common, "EVAL_DATASET_FILE", "x"), \
                patch.object(common, "REFUSAL_DATASET_FILE", "y"), \
                patch.object(common, "load_json", side_effect=lambda p: subset if p == "x" else refusal):
            bundle = build_smoke_set.build_smoke_bundle(positive_count=20, refusal_count=5, seed=42)
        items = bundle["items"]
        self.assertEqual(len(items), 25)
        refusal_items = [i for i in items if i["answer"]["refusal_expected"]]
        self.assertEqual(len(refusal_items), 5)
        self.assertEqual(bundle["dataset"]["dataset_id"], "open-ragbench-smoke-v1")
        self.assertEqual(bundle["dataset"]["library_id"], "lib-1")


class RunSmokeRegressionTests(unittest.TestCase):
    def test_check_regression_flags_score_drop(self):
        baseline = {"overall_score": 0.9, "refusal_accuracy": 0.9}
        ok = run_smoke.check_regression({"overall_score": 0.88, "refusal_accuracy": 0.95}, baseline)
        self.assertEqual(ok, [])
        bad = run_smoke.check_regression({"overall_score": 0.80, "refusal_accuracy": 0.95}, baseline)
        self.assertEqual(len(bad), 1)
        self.assertIn("overall_score", bad[0])
        bad_refusal = run_smoke.check_regression({"overall_score": 0.95, "refusal_accuracy": 0.5}, baseline)
        self.assertEqual(len(bad_refusal), 1)
        self.assertIn("refusal_accuracy", bad_refusal[0])

    def test_check_regression_skips_missing_metrics(self):
        baseline = {"overall_score": 0.9, "refusal_accuracy": None}
        problems = run_smoke.check_regression({"overall_score": 0.92}, baseline)
        self.assertEqual(problems, [])

    def test_extract_metrics(self):
        run = {"run_id": "r1", "status": "completed", "summary": {
            "overall_score": 0.9, "retrieval_score": 0.8, "answer_score": 0.9,
            "refusal_accuracy": 1.0, "hallucination_on_unanswerable": 0,
        }}
        metrics = run_smoke.extract_metrics(run)
        self.assertEqual(metrics["overall_score"], 0.9)
        self.assertEqual(metrics["refusal_accuracy"], 1.0)


class JudgeCalibrationTests(unittest.TestCase):
    def test_cohens_kappa_perfect_and_chance(self):
        perfect = [(True, True), (False, False)] * 5
        self.assertEqual(judge_calibration._cohens_kappa(perfect), 1.0)
        self.assertIsNone(judge_calibration._cohens_kappa([]))

    def test_check_worksheet_computes_agreement(self):
        sheet = {
            "run_id": "r1",
            "items": [
                {"question_id": "q1", "judge_passed": True, "human_verdict": "correct"},
                {"question_id": "q2", "judge_passed": True, "human_verdict": "wrong"},
                {"question_id": "q3", "judge_passed": False, "human_verdict": "wrong"},
                {"question_id": "q4", "judge_passed": False, "human_verdict": "correct"},
                {"question_id": "q5", "judge_passed": True, "human_verdict": "correct"},
                {"question_id": "q6", "judge_passed": True, "human_verdict": ""},
            ],
        }
        with tempfile.TemporaryDirectory() as tmp:
            worksheet = Path(tmp) / "worksheet.json"
            result = Path(tmp) / "result.json"
            worksheet.write_text(json.dumps(sheet), encoding="utf-8")
            with patch.object(judge_calibration, "WORKSHEET", worksheet), \
                    patch.object(judge_calibration, "RESULT", result):
                rc = judge_calibration.check_worksheet()
            saved = json.loads(result.read_text(encoding="utf-8"))
        self.assertEqual(rc, 0)
        self.assertEqual(saved["labeled"], 5)
        self.assertEqual(saved["confusion"]["judge_pass_human_wrong"], 1)
        self.assertEqual(saved["confusion"]["judge_wrong_human_pass"], 1)
        self.assertAlmostEqual(saved["agreement_accuracy"], 0.6)


if __name__ == "__main__":
    unittest.main()
