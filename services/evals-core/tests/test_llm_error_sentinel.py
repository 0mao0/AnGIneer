"""哨兵 b：被吞掉的 LLM 失败必须沿 prediction → scores → run 汇总可见。

回归 2026-09-06 双事故：
- 53 题全灭（流式 KeyError 被逐层吞成拒答模板，明细 error=None，事后无从分辨故障与真拒答）；
- 拒答题集"假满分 100"（故障吞错式拒答与校准拒答判分同分，run 级无任何提示）。
"""
import sys
import threading
import unittest
from pathlib import Path
from unittest import mock

EVALS_CORE_SRC = Path(__file__).resolve().parents[1] / "src"
if str(EVALS_CORE_SRC) not in sys.path:
    sys.path.insert(0, str(EVALS_CORE_SRC))

from evals_core.runner.answer_eval import AnswerEvaluator  # noqa: E402
from evals_core.runner.suite_runner import _compute_summary  # noqa: E402

from angineer_core.agent_loop import AgentLoopConfig, _run_llm_turn  # noqa: E402
from angineer_core.agent_messages import AgentMessage  # noqa: E402
from angineer_core.classifier import IntentClassifier  # noqa: E402
from angineer_core.tool_codec import TextToolCallCodec  # noqa: E402

REFUSAL = "没有检索到足够证据支持最终结论。当前仅能确认已有片段与问题相关，但不足以安全地给出完整答案。"


class TestScoresAnnotation(unittest.TestCase):
    def setUp(self):
        self.evaluator = AnswerEvaluator()
        self.gold_refusal = {"gold_answer": "", "correctness_checks": [], "refusal_expected": True}

    def test_refusal_with_swallowed_errors_flagged(self):
        """吞错式拒答：分数维持行为兼容（1.0），但必须带 refusal_via_error 标记。"""
        prediction = {"answer": REFUSAL, "llm_error_count": 2, "llm_errors": ["意图分类 LLM 空响应", "turn0 LLM 流式调用异常: 'text'"]}
        scores = self.evaluator.evaluate({}, self.gold_refusal, prediction)
        self.assertEqual(scores["score"], 1.0)
        self.assertEqual(scores["llm_error_count"], 2)
        self.assertTrue(scores.get("refusal_via_error"))

    def test_calibrated_refusal_not_flagged(self):
        scores = self.evaluator.evaluate({}, self.gold_refusal, {"answer": REFUSAL})
        self.assertEqual(scores["score"], 1.0)
        self.assertEqual(scores["llm_error_count"], 0)
        self.assertNotIn("refusal_via_error", scores)

    def test_empty_answer_carry_count_without_refusal_flag(self):
        """无答案早期返回路径同样要带计数（无答案不是拒答标记）。"""
        scores = self.evaluator.evaluate({}, self.gold_refusal, {"answer": "", "llm_error_count": 3})
        self.assertEqual(scores["has_answer"], False)
        self.assertEqual(scores["llm_error_count"], 3)
        self.assertNotIn("refusal_via_error", scores)


class TestRunSummary(unittest.TestCase):
    def test_summary_counts_error_swallowed_questions(self):
        details = [
            {"question_id": "q1", "status": "completed", "quality": "correct", "scores": {"llm_error_count": 2, "refusal_via_error": True}, "all_scores": {}},
            {"question_id": "q2", "status": "completed", "quality": "wrong", "scores": {"llm_error_count": 1}, "all_scores": {}},
            {"question_id": "q3", "status": "completed", "quality": "correct", "scores": {}, "all_scores": {}},
        ]
        summary = _compute_summary(details)
        self.assertEqual(summary["llm_error_questions"], 2)
        self.assertEqual(summary["refusal_via_error_questions"], 1)


class TestClassifierSink(unittest.TestCase):
    def _classify(self, side_effect):
        sink = []
        clf = IntentClassifier([])
        with mock.patch("angineer_core.classifier.chat_result_guarded", side_effect=side_effect):
            result = clf.classify_intent("码头结构设计中混凝土保护层厚度是多少？", error_sink=sink)
        return result, sink

    def test_llm_exception_recorded(self):
        result, sink = self._classify(RuntimeError("boom"))
        self.assertIsNotNone(result)  # 降级路径不变
        self.assertTrue(any("意图分类 LLM 异常" in s and "boom" in s for s in sink))

    def test_empty_response_recorded(self):
        result, sink = self._classify(lambda *a, **k: mock.Mock(text=""))
        self.assertIsNotNone(result)
        self.assertIn("意图分类 LLM 空响应", sink)

    def test_no_sink_no_side_effect(self):
        with mock.patch("angineer_core.classifier.chat_result_guarded", side_effect=RuntimeError("boom")):
            IntentClassifier([]).classify_intent("混凝土保护层厚度是多少？")  # 不传 sink 不得抛


class TestAgentLoopSink(unittest.TestCase):
    class _BoomLLM:
        def chat_stream_events(self, *a, **k):
            raise RuntimeError("stream boom")

    def test_turn_exception_recorded_and_loop_degrades(self):
        sink = []
        config = AgentLoopConfig(llm=self._BoomLLM(), system_prompt="s", error_sink=sink)
        answer, calls, direct, usage = _run_llm_turn(
            [AgentMessage(role="user", content="q")], [], config, TextToolCallCodec(),
            {}, None, "r1", threading.Event(), 0, False,
        )
        self.assertEqual(calls, [])
        self.assertEqual((answer.content or "").strip(), "")
        self.assertTrue(any("LLM 流式调用异常" in s and "stream boom" in s for s in sink))

    def test_no_sink_still_degrades(self):
        config = AgentLoopConfig(llm=self._BoomLLM(), system_prompt="s")
        answer, calls, _, _ = _run_llm_turn(
            [AgentMessage(role="user", content="q")], [], config, TextToolCallCodec(),
            {}, None, "r1", threading.Event(), 0, False,
        )
        self.assertEqual(calls, [])


if __name__ == "__main__":
    unittest.main()
