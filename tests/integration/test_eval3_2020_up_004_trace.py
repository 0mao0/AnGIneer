"""单题严格追踪测试：定位 eval3_2020_up_004 的实际失败点。"""
from __future__ import annotations

import os
import sys
import unittest


ROOT_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "../.."))
EVALS_SRC = os.path.join(ROOT_DIR, "services", "evals-core", "src")

if EVALS_SRC not in sys.path:
    sys.path.insert(0, EVALS_SRC)

from evals_core.runner.case_trace import (  # noqa: E402
    run_eval_case_trace,
    write_case_trace_report,
)


class TestEval32020Up004Trace(unittest.TestCase):
    """验证该题已进入 L3 + SOP 主链，并产出与 gold 一致的结果。"""

    def test_trace_runs_through_l3_sop_and_matches_gold_answer(self) -> None:
        """运行严格追踪并断言已稳定命中 SOP 且答案选项与 gold 一致。"""
        trace_payload = run_eval_case_trace(
            dataset_id="eval_3",
            question_id="eval3_2020_up_004",
        )

        artifact_path = os.path.join(
            ROOT_DIR,
            "tests",
            "artifacts",
            "eval3_2020_up_004_trace.json",
        )
        write_case_trace_report(trace_payload, artifact_path)

        issue_codes = {issue["code"] for issue in trace_payload["issues"]}

        self.assertEqual(trace_payload["case"]["expected_intent_level"], "L3")
        self.assertEqual(
            trace_payload["classifier"]["intent"].get("intent_level"),
            "L3",
        )
        self.assertEqual(
            trace_payload["classifier"]["intent"].get("service_mode"),
            "standard_sop",
        )
        self.assertEqual(
            trace_payload["classifier"]["route"].get("matched_sop_id"),
            "海港码头前沿顶高程计算",
        )
        self.assertFalse(trace_payload["dispatch"]["fallback_used"])
        self.assertTrue(trace_payload["dispatch"]["sop_trace"])
        self.assertEqual(trace_payload["answer_check"].get("extracted_option"), "B")
        self.assertTrue(trace_payload["answer_check"].get("passed"))
        self.assertNotIn("calculator_input_contract_mismatch", issue_codes)
        self.assertNotIn("step_error_hidden_by_success_status", issue_codes)


if __name__ == "__main__":
    unittest.main()
