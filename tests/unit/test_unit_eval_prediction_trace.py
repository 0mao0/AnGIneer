"""
评测 prediction trace 归一化单元测试。
"""
import os
import sys
import unittest


ROOT_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "../.."))
EVALS_SRC = os.path.join(ROOT_DIR, "services", "evals-core", "src")

if EVALS_SRC not in sys.path:
    sys.path.insert(0, EVALS_SRC)

from evals_core.runner._prediction_trace import enrich_prediction_trace  # noqa: E402


class TestEvalPredictionTrace(unittest.TestCase):
    """验证评测 trace 字段能被稳定归一化。"""

    def test_standard_sop_trace_fields_are_normalized(self) -> None:
        """L3 + SOP 场景下应生成标准流程 trace 结构。"""
        question = {
            "intent_level": "L3",
        }
        raw_data = {
            "intent": {
                "intent_level": "L3",
                "intent_type": "exam_case",
                "service_mode": "standard_sop",
                "reason": "命中标准计算题",
            },
            "strategy": "SOP 执行 (海港码头前沿顶高程计算, confidence=1.00)",
            "fallback_used": False,
            "route_debug": {
                "route_kind": "standard_sop",
                "matched_sop_id": "海港码头前沿顶高程计算",
                "matched_sop_name": "海港码头前沿顶高程计算",
                "confidence": 1.0,
                "args": {"DWL": 4.3},
                "missing_args": [],
                "reason": "匹配成功",
            },
            "flow_debug": {
                "flow_type": "standard_sop",
                "sop_id": "海港码头前沿顶高程计算",
                "sop_name": "海港码头前沿顶高程计算",
                "final_context": {"E": 7.94},
                "summary": "命中标准 SOP 并完成执行。",
            },
            "sop_trace": [
                {
                    "step_id": "step_1",
                    "step_name": "参数提取",
                    "status": "success",
                    "tool": "llm_generate",
                    "outputs": {"DWL": 4.3},
                }
            ],
        }
        prediction = {
            "answer": "对应选项：(B) 7.9m",
        }

        enriched = enrich_prediction_trace(question, raw_data, prediction)

        self.assertEqual(enriched["trace_meta"]["level"], "L3")
        self.assertEqual(enriched["trace_meta"]["trace_mode"], "flow")
        self.assertEqual(enriched["trace_meta"]["title"], "标准 SOP 执行")
        self.assertEqual(enriched["route_debug"]["matched_sop_id"], "海港码头前沿顶高程计算")
        self.assertEqual(enriched["flow_debug"]["flow_type"], "standard_sop")
        self.assertEqual(enriched["issues"], [])
        self.assertIn("海港码头前沿顶高程计算", enriched["trace_summary"])

    def test_step_error_is_exposed_in_trace_issues(self) -> None:
        """步骤显式报错时应生成问题列表而不是静默吞掉。"""
        question = {
            "intent_level": "L3",
        }
        raw_data = {
            "intent": {
                "intent_level": "L3",
                "intent_type": "exam_case",
                "service_mode": "standard_sop",
            },
            "fallback_used": True,
            "route_debug": {
                "route_kind": "standard_sop",
                "matched_sop_id": "",
                "matched_sop_name": "",
                "missing_args": ["DWL"],
            },
            "sop_trace": [
                {
                    "step_id": "step_2",
                    "step_name": "计算",
                    "status": "success",
                    "tool": "calculator",
                    "error": "",
                    "outputs": {"error": "表达式不能为空"},
                }
            ],
        }

        enriched = enrich_prediction_trace(question, raw_data, {"answer": ""})
        issue_codes = {item["code"] for item in enriched["issues"]}

        self.assertIn("dispatch_fallback_used", issue_codes)
        self.assertIn("route_no_match", issue_codes)
        self.assertIn("route_missing_args", issue_codes)
        self.assertIn("sop_step_error", issue_codes)
        self.assertIn("step_error_hidden_by_success_status", issue_codes)


if __name__ == "__main__":
    unittest.main()
