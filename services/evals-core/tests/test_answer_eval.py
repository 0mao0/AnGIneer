"""AnswerEvaluator：有标准答案/要点时整体拒答必须确定性判失败，不再依赖 LLM 判分兜底。"""
import sys
import unittest
from pathlib import Path


EVALS_CORE_SRC = Path(__file__).resolve().parents[1] / "src"
if str(EVALS_CORE_SRC) not in sys.path:
    sys.path.insert(0, str(EVALS_CORE_SRC))

from evals_core.runner.answer_eval import AnswerEvaluator  # noqa: E402


class AnswerRefusalTests(unittest.TestCase):
    def setUp(self):
        self.evaluator = AnswerEvaluator()

    def test_refusal_with_gold_answer_fails_deterministically(self):
        """部分覆盖场景：有标准答案/要点时整体拒答按 0 分，且不走 LLM 判分。"""
        gold = {
            "gold_answer": "原文提到集成 17 类算法、12 个模型，但未列出具体名称。",
            "correctness_checks": [{"type": "contains_all", "keywords": ["17 类算法"]}],
        }
        prediction = {
            "answer": "没有检索到足够证据支持最终结论，不要自行补全。",
            "citations": [],
        }
        result = self.evaluator.evaluate({}, gold, prediction)
        self.assertEqual(result["score"], 0.0)
        self.assertFalse(result["refusal_correct"])
        self.assertFalse(result["semantic_evaluated"])
        self.assertTrue(result["has_answer"])

    def test_refusal_without_gold_not_hard_failed(self):
        """无标准答案且无要点时，拒答不额外扣分（保持原有语义判分路径）。"""
        gold = {}
        prediction = {
            "answer": "没有检索到足够证据支持最终结论。",
            "citations": [],
        }
        result = self.evaluator.evaluate({}, gold, prediction)
        self.assertEqual(result["score"], 1.0)

    def test_refusal_expected_still_passes(self):
        gold = {"refusal_expected": True}
        prediction = {
            "answer": "没有检索到足够证据支持最终结论。",
            "citations": [],
        }
        result = self.evaluator.evaluate({}, gold, prediction)
        self.assertEqual(result["score"], 1.0)
        self.assertTrue(result["refusal_correct"])


if __name__ == "__main__":
    unittest.main()
