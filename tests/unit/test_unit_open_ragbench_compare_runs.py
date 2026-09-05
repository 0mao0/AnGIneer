"""compare_runs 单测：过渡矩阵、配对 CI、归因桶、门禁判定、基线 pin。"""
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../../scripts")))

from open_ragbench import compare_runs  # noqa: E402


def _d(qid, quality, hit5=1, sem=0.9, refusal=False, intent="L1", anomaly=False):
    reason = "有标准答案/要点时整体拒答按失败计" if refusal else "正常评判"
    return {
        "question_id": qid, "status": "completed", "quality": quality, "latency_ms": 30_000,
        "scores": {"semantic_fallback": anomaly},
        "prediction": {"intent": intent},
        "all_scores": {
            "retrieval": {"hit@5_doc": hit5},
            "answer": {"semantic_score": sem, "semantic_fallback": anomaly,
                       "has_answer": not refusal, "semantic_reason": reason},
        },
    }


def _run(run_id, details):
    return {"run_id": run_id, "dataset_id": "ds", "status": "completed", "details": details}


class MatrixTests(unittest.TestCase):
    def test_matrix_and_ci_green(self):
        base, new = [], []
        for i in range(15):  # pp
            base.append(_d(f"p{i}", "correct")); new.append(_d(f"p{i}", "correct"))
        for i in range(3):   # pf 新修复
            base.append(_d(f"f{i}", "wrong")); new.append(_d(f"f{i}", "correct"))
        for i in range(2):   # fp 新回退
            base.append(_d(f"r{i}", "correct")); new.append(_d(f"r{i}", "wrong", sem=0.3))
        for i in range(2):   # ff
            base.append(_d(f"w{i}", "wrong")); new.append(_d(f"w{i}", "wrong", sem=0.2))
        matrix, _, anomalies = compare_runs.transition_matrix(
            compare_runs.question_map(_run("b", base)), compare_runs.question_map(_run("n", new)))
        self.assertEqual(len(matrix["pp"]), 15)
        self.assertEqual(len(matrix["pf"]), 3)
        self.assertEqual(len(matrix["fp"]), 2)
        lo, hi = compare_runs.paired_delta_ci(matrix)
        self.assertGreaterEqual(hi, 0)  # 正向修复居多，CI 上界不为负 → 门禁不会红
        self.assertFalse(compare_runs.evaluate_gate(
            matrix, {k: v for k, v in anomalies.items() if v}, (lo, hi), 0.05, {}))

    def test_anomaly_forces_red(self):
        base = {"q": _d("q", "correct")}
        new = {"q": _d("q", "wrong", anomaly=True)}
        matrix, _, anomalies = compare_runs.transition_matrix(base, new)
        reasons = compare_runs.evaluate_gate(
            matrix, {k: v for k, v in anomalies.items() if v}, (None, None), None, {})
        self.assertTrue(any("未清零异常" in r for r in reasons))


class AttributionTests(unittest.TestCase):
    def test_buckets(self):
        base = _d("q", "correct", hit5=1, sem=1.0, intent="L1")
        cases = {
            "retrieval": (dict(_d("q", "wrong", hit5=0)), "retrieval_regression"),
            "refusal": (dict(_d("q", "wrong", refusal=True)), "refusal"),
            "route": (dict(_d("q", "wrong", intent="L3")), "route_change"),
            "partial": (dict(_d("q", "wrong", sem=0.55)), "partial_coverage"),
            "severe": (dict(_d("q", "wrong", sem=0.1)), "severe_miss"),
            "infra": (dict(_d("q", "wrong", anomaly=True)), "infra_anomaly"),
        }
        for label, (new, expect) in cases.items():
            with self.subTest(label):
                self.assertTrue(compare_runs.attribute("q", base, new).startswith(expect))


class PinTests(unittest.TestCase):
    def test_pin_prunes_prediction_and_writes_pointer(self):
        with tempfile.TemporaryDirectory() as tmp:
            raw = _run("run-x", [_d("q1", "correct")])
            raw["details"][0]["prediction"]["retrieved_items"] = ["巨量大字段"] * 100
            raw_path = Path(tmp) / "raw.json"
            raw_path.write_text(json.dumps(raw), encoding="utf-8")
            with mock.patch.object(compare_runs, "BASELINE_DIR", Path(tmp) / "baseline"), \
                 mock.patch.object(compare_runs, "BASELINE_POINTER", Path(tmp) / "baseline" / "baseline_run.json"), \
                 mock.patch.object(compare_runs.common, "REPO_ROOT", Path(tmp)):
                args = mock.Mock(raw=str(raw_path), label="v2基线-2026-09")
                self.assertEqual(compare_runs.cmd_pin(args), 0)
                pointer = json.loads((Path(tmp) / "baseline" / "baseline_run.json").read_text(encoding="utf-8"))
                snap = json.loads((Path(tmp) / pointer["raw"]).read_text(encoding="utf-8"))
        self.assertEqual(pointer["label"], "v2基线-2026-09")
        pred = snap["details"][0]["prediction"]
        self.assertNotIn("retrieved_items", pred)  # 大字段已裁剪
        self.assertEqual(pred.get("intent"), "L1")   # 归因需要的小字段保留


if __name__ == "__main__":
    unittest.main()
