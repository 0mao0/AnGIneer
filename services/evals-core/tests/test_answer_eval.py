"""AnswerEvaluator：有标准答案/要点时整体拒答必须确定性判失败，不再依赖 LLM 判分兜底。"""
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock


EVALS_CORE_SRC = Path(__file__).resolve().parents[1] / "src"
if str(EVALS_CORE_SRC) not in sys.path:
    sys.path.insert(0, str(EVALS_CORE_SRC))

from evals_core.runner.answer_eval import AnswerEvaluator  # noqa: E402
from evals_core.runner.suite_runner import _compute_summary  # noqa: E402


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


class RefusalMissSupportCheckTests(unittest.TestCase):
    """该拒题未拒时的二段判定：答案被检索证据支持与否拆「有据未拒 / 真幻觉」。

    口径不变：score 仍 0、refusal_correct 仍 False；支持度只进观测字段。
    """

    def setUp(self):
        self.evaluator = AnswerEvaluator()
        self.gold = {"refusal_expected": True}
        self.prediction = {
            "answer": "世界上最大的湖泊是里海，位于亚洲西部。",
            "citations": [],
            "retrieved_items": [{"text": "位于亚洲西部的裏海是世界上最大的湖泊。"}],
        }

    def _run(self, prediction, judge_text=None, side_effect=None):
        with mock.patch("ai_inference.llm_client.get_llm_client", return_value=object()), \
             mock.patch("ai_inference.llm_client.chat_result_guarded",
                        return_value=SimpleNamespace(text=judge_text),
                        side_effect=side_effect) as guarded:
            result = self.evaluator.evaluate({}, self.gold, prediction)
        return result, guarded

    def test_grounded_miss_marked_supported(self):
        result, guarded = self._run(
            self.prediction, judge_text='{"supported": true, "reason": "证据原文含答案"}')
        self.assertEqual(result["score"], 0.0)
        self.assertFalse(result["refusal_correct"])
        self.assertTrue(result["support_evaluated"])
        self.assertTrue(result["evidence_supported"])
        self.assertEqual(guarded.call_count, 1)

    def test_unsupported_miss_marked_hallucination(self):
        result, _ = self._run(
            self.prediction, judge_text='{"supported": false, "reason": "证据不含该结论"}')
        self.assertEqual(result["score"], 0.0)
        self.assertTrue(result["support_evaluated"])
        self.assertFalse(result["evidence_supported"])

    def test_no_context_skips_llm(self):
        result, guarded = self._run({"answer": "里海。", "citations": []})
        self.assertEqual(result["score"], 0.0)
        self.assertFalse(result["support_evaluated"])
        self.assertIsNone(result["evidence_supported"])
        self.assertEqual(guarded.call_count, 0)

    def test_judge_failure_keeps_score_and_marks_unevaluated(self):
        result, _ = self._run(self.prediction, side_effect=RuntimeError("boom"))
        self.assertEqual(result["score"], 0.0)
        self.assertFalse(result["support_evaluated"])
        self.assertIsNone(result["evidence_supported"])


class RefusalMissSummaryTests(unittest.TestCase):
    """suite_runner 聚合：有据未拒与真幻觉分别计数，不改 refusal_accuracy 口径。"""

    _QID_SEQ = 0

    def _detail(self, answer_scores):
        RefusalMissSummaryTests._QID_SEQ += 1
        return {"question_id": f"q{RefusalMissSummaryTests._QID_SEQ}",
                "all_scores": {"answer": {"evaluated": True, "refusal_expected": True,
                                          **answer_scores}}}

    def test_summary_splits_grounded_and_unsupported(self):
        summary = _compute_summary([
            self._detail({"refusal_correct": True}),
            self._detail({"refusal_correct": False, "evidence_supported": True}),
            self._detail({"refusal_correct": False, "evidence_supported": False}),
            self._detail({"refusal_correct": False, "evidence_supported": None}),
        ])
        self.assertEqual(summary["refusal_total"], 4)
        self.assertEqual(summary["refusal_correct"], 1)
        self.assertEqual(summary["refusal_miss_grounded"], 1)
        self.assertEqual(summary["refusal_miss_unsupported"], 1)




class RefusalContentJudgeTests(unittest.TestCase):
    """该拒题未拒时的内容判分（vs 公开 gold）：三档 verdict 只进观测字段，口径不变。"""

    def setUp(self):
        self.evaluator = AnswerEvaluator()
        self.gold = {"refusal_expected": True, "content_gold": "Yes."}
        self.question = {"question": "Does the evaluation process involve multiple-choice questions?"}
        self.prediction = {
            "answer": "是的，该评估过程涉及多项选择题。",
            "citations": [],
            "retrieved_items": [{"text": "评估使用多项选择题作答。"}],
        }

    def _run(self, gold=None, prediction=None, texts=None, side_effect=None):
        gold = self.gold if gold is None else gold
        prediction = self.prediction if prediction is None else prediction
        if side_effect is None:
            side_effect = [SimpleNamespace(text=t) for t in (texts or [])]
        with mock.patch("ai_inference.llm_client.get_llm_client", return_value=object()),              mock.patch("ai_inference.llm_client.chat_result_guarded",
                        side_effect=side_effect) as guarded:
            result = self.evaluator.evaluate(self.question, gold, prediction)
        return result, guarded

    def test_content_verdict_recorded(self):
        result, guarded = self._run(texts=[
            '{"supported": true, "reason": "证据含答案"}',
            '{"verdict": "correct", "reason": "结论与 gold 一致"}',
        ])
        self.assertEqual(result["score"], 0.0)
        self.assertTrue(result["content_evaluated"])
        self.assertEqual(result["content_verdict"], "correct")
        self.assertEqual(guarded.call_count, 2)

    def test_wrong_verdict_recorded(self):
        result, _ = self._run(texts=[
            '{"supported": true, "reason": "证据含答案"}',
            '{"verdict": "wrong", "reason": "与 gold 相反"}',
        ])
        self.assertEqual(result["score"], 0.0)
        self.assertEqual(result["content_verdict"], "wrong")

    def test_missing_content_gold_skips(self):
        result, guarded = self._run(
            gold={"refusal_expected": True},
            texts=['{"supported": true, "reason": "x"}'])
        self.assertFalse(result["content_evaluated"])
        self.assertIsNone(result["content_verdict"])
        self.assertEqual(guarded.call_count, 1)

    def test_judge_failure_not_fatal(self):
        result, _ = self._run(side_effect=RuntimeError("boom"))
        self.assertEqual(result["score"], 0.0)
        self.assertFalse(result["content_evaluated"])
        self.assertFalse(result["support_evaluated"])


class RefusalContentSummaryTests(unittest.TestCase):
    """suite_runner 聚合：内容三档计数与内容口径失守率；旧 run 无字段保持 None/0。"""

    _QID_SEQ = 0

    def _detail(self, answer_scores):
        RefusalContentSummaryTests._QID_SEQ += 1
        return {"question_id": f"cq{RefusalContentSummaryTests._QID_SEQ}",
                "all_scores": {"answer": {"evaluated": True, "refusal_expected": True,
                                          **answer_scores}}}

    def test_counts_and_rates(self):
        summary = _compute_summary([
            self._detail({"refusal_correct": True}),
            self._detail({"refusal_correct": False, "content_evaluated": True,
                          "content_verdict": "correct"}),
            self._detail({"refusal_correct": False, "content_evaluated": True,
                          "content_verdict": "wrong"}),
            self._detail({"refusal_correct": False, "content_evaluated": True,
                          "content_verdict": "uncertain"}),
        ])
        self.assertEqual(summary["refusal_total"], 4)
        self.assertEqual(summary["refusal_miss_content_correct"], 1)
        self.assertEqual(summary["refusal_miss_content_wrong"], 1)
        self.assertEqual(summary["refusal_miss_content_uncertain"], 1)
        self.assertEqual(summary["refusal_content_miss_rate"], 0.25)
        self.assertEqual(summary["refusal_content_miss_rate_upper"], 0.5)

    def test_old_run_keeps_none(self):
        summary = _compute_summary([
            self._detail({"refusal_correct": False, "evidence_supported": True}),
        ])
        self.assertEqual(summary["refusal_miss_content_correct"], 0)
        self.assertIsNone(summary["refusal_content_miss_rate"])
        self.assertIsNone(summary["refusal_content_miss_rate_upper"])


if __name__ == "__main__":
    unittest.main()
