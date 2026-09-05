"""异常检测 + judge 候选链 + summary judge_failed_count 单测。"""
import os
import sys
import unittest
from types import SimpleNamespace
from unittest import mock

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "../.."))
for sub in ("evals-core", "angineer-core", "ai-inference"):
    p = os.path.join(ROOT, "services", sub, "src")
    if p not in sys.path:
        sys.path.insert(0, p)

from evals_core.runner import anomaly  # noqa: E402
from evals_core.runner import answer_eval  # noqa: E402
from evals_core.runner import suite_runner  # noqa: E402


class AnomalyClassifyTests(unittest.TestCase):
    def test_judge_fail_detected(self):
        d = {"question_id": "q1", "status": "completed", "scores": {"semantic_fallback": True}}
        self.assertIn(anomaly.JUDGE_FAIL, anomaly.classify_detail(d))

    def test_judge_fail_in_all_scores_answer(self):
        d = {"question_id": "q1", "status": "completed",
             "all_scores": {"answer": {"semantic_fallback": True}}}
        self.assertIn(anomaly.JUDGE_FAIL, anomaly.classify_detail(d))

    def test_exec_error(self):
        d = {"question_id": "q1", "status": "error", "error": "timeout"}
        self.assertEqual(anomaly.classify_detail(d), [anomaly.EXEC_ERROR])

    def test_rule_refusal_zero_is_NOT_anomaly(self):
        """规则判零（该答却拒答）确定性 0 分不是异常：semantic_evaluated=False 但无 fallback。"""
        d = {"question_id": "q1", "status": "completed", "scores": {
            "semantic_evaluated": False, "semantic_fallback": False,
            "semantic_reason": "有标准答案/要点时整体拒答按失败计（refusal_expected=False）",
        }}
        self.assertEqual(anomaly.classify_detail(d, slow_ms=-1), [])

    def test_slow_watch_only(self):
        d = {"question_id": "q1", "status": "completed", "latency_ms": 130_000, "scores": {}}
        self.assertEqual(anomaly.classify_detail(d), [anomaly.SLOW])

    def test_json_string_scores(self):
        d = {"question_id": "q1", "status": "completed",
             "scores": '{"semantic_fallback": true}'}
        self.assertIn(anomaly.JUDGE_FAIL, anomaly.classify_detail(d))

    def test_judge_failed_count_dedupes(self):
        details = [
            {"question_id": "a", "scores": {"semantic_fallback": True}},
            {"question_id": "a", "scores": {"semantic_fallback": True}},
            {"question_id": "b", "scores": {"semantic_fallback": False}},
            {"question_id": "c", "status": "error", "error": "boom"},
        ]
        self.assertEqual(anomaly.judge_failed_count(details), 1)


class SummaryCountTests(unittest.TestCase):
    def test_summary_has_judge_failed_count(self):
        details = [
            {"question_id": "a", "status": "completed", "quality": "wrong",
             "all_scores": {"answer": {"semantic_fallback": True}}},
            {"question_id": "b", "status": "completed", "quality": "correct", "all_scores": {}},
            {"question_id": "c", "status": "error", "error": "x", "all_scores": {}},
        ]
        summary = suite_runner._compute_summary(details)
        self.assertEqual(summary["judge_failed_count"], 1)
        self.assertEqual(summary["anomaly_count"], 2)  # 1 judge_fail + 1 errored


class JudgeChainTests(unittest.TestCase):
    """EVAL_JUDGE_CONFIGS 候选链：顺序尝试、失败切下一项、全挂才 fallback、不静默降级被测。"""

    def _run_with(self, env, side_effects):
        with mock.patch.dict(os.environ, env, clear=False):
            with mock.patch("ai_inference.llm_client.get_llm_client", return_value=object()), \
                 mock.patch("ai_inference.llm_client.chat_result_guarded", side_effect=side_effects) as guarded:
                return answer_eval._llm_semantic_evaluate("答", "金标", [], 0.65), guarded

    def test_failover_to_second_candidate(self):
        def side(client, messages, mode=None, config_name=None, temperature=None):
            if config_name == "bad":
                raise RuntimeError("connection refused")
            return SimpleNamespace(text='{"score": 0.9, "reason": "好"}')
        result, guarded = self._run_with(
            {"EVAL_JUDGE_CONFIGS": '["bad", "good"]', "EVAL_JUDGE_MODEL": "should-be-ignored"},
            side,
        )
        self.assertTrue(result["semantic_evaluated"])
        self.assertEqual(result["judge_used"], "good")
        self.assertTrue(result["judge_failover"])

    def test_all_candidates_fail_sets_fallback(self):
        result, guarded = self._run_with(
            {"EVAL_JUDGE_CONFIGS": '["a", "b"]'},
            RuntimeError("down"),
        )
        self.assertFalse(result["semantic_evaluated"])
        self.assertTrue(result["semantic_fallback"])
        self.assertIn("2 个端点均失败", result["semantic_reason"])
        self.assertEqual(guarded.call_count, 2)
        names = [c.kwargs["config_name"] for c in guarded.call_args_list]
        self.assertEqual(names, ["a", "b"])

    def test_never_silently_falls_back_to_answer_model(self):
        """单候选挂了不许回退到 config_name=None（被测自判自评）。"""
        result, guarded = self._run_with({"EVAL_JUDGE_CONFIGS": '["only"]'}, RuntimeError("down"))
        self.assertTrue(result["semantic_fallback"])
        self.assertEqual(guarded.call_count, 1)  # 没有第二次 None 候选

    def test_single_env_legacy(self):
        result, guarded = self._run_with(
            {"EVAL_JUDGE_CONFIGS": "", "EVAL_JUDGE_MODEL": "LegacyJudge"},
            lambda *a, **k: SimpleNamespace(text='{"score": 1.0, "reason": "ok"}'),
        )
        self.assertEqual(result["judge_used"], "LegacyJudge")
        self.assertFalse(result["judge_failover"])

    def test_no_env_uses_default_model(self):
        result, _ = self._run_with(
            {"EVAL_JUDGE_CONFIGS": "", "EVAL_JUDGE_MODEL": ""},
            lambda *a, **k: SimpleNamespace(text='{"score": 1.0, "reason": "ok"}'),
        )
        self.assertEqual(result["judge_used"], "<被测默认>")


if __name__ == "__main__":
    unittest.main()
