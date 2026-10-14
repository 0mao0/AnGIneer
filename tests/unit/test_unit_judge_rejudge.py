# -*- coding: utf-8 -*-
"""判官双判一致制（judge_audit + answer_eval 接入）单测。

覆盖：开关解析、中位/合并规则、legacy 路径四种收口（单判/双一致/三票多数/票失败兜底）。
deepeval 路径由离线探针（data/scratch/t7_judge_rejudge_probe.py）在真实判官上验证。
"""
import json
import os
import sys
import types
import unittest
from unittest import mock

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../../services/evals-core/src")))

from evals_core.runner import judge_audit  # noqa: E402


class HelperTests(unittest.TestCase):
    def test_switch_parsing(self):
        with mock.patch.dict(os.environ, {"ANGINEER_JUDGE_REJUDGE": ""}):
            self.assertFalse(judge_audit.rejudge_enabled())
        for v in ("1", "true", "ON"):
            with mock.patch.dict(os.environ, {"ANGINEER_JUDGE_REJUDGE": v}):
                self.assertTrue(judge_audit.rejudge_enabled(), v)

    def test_median_score(self):
        self.assertEqual(judge_audit.median_score([0.9, 0.2, 0.8]), 0.8)
        self.assertEqual(judge_audit.median_score([0.9, 0.8]), 0.85)

    def test_combine_votes(self):
        thr = 0.65
        self.assertEqual(judge_audit.combine_votes([True, True], [0.9, 0.8], thr),
                         {"passed": True, "mode": "double_agree"})
        self.assertEqual(judge_audit.combine_votes([True, False, True], [0.9, 0.2, 0.8], thr),
                         {"passed": True, "mode": "majority"})
        self.assertEqual(judge_audit.combine_votes([True, False, False], [0.9, 0.2, 0.1], thr),
                         {"passed": False, "mode": "majority"})
        self.assertEqual(judge_audit.combine_votes([True, False], [0.9, 0.2], thr),
                         {"passed": False, "mode": "split_fallback"})  # 均值 0.55 < 0.65


def _judge_text(score, reason="ok"):
    return types.SimpleNamespace(text=json.dumps({"score": score, "reason": reason}, ensure_ascii=False))


class LegacyRejudgeTests(unittest.TestCase):
    """legacy 判分路径（EVAL_ENGINE=legacy）的双判协议接入。"""

    def _run(self, side_effect, rejudge):
        from evals_core.runner import answer_eval
        env = {"EVAL_ENGINE": "legacy", "ANGINEER_JUDGE_REJUDGE": "1" if rejudge else "0"}
        with mock.patch.dict(os.environ, env):
            with mock.patch("ai_inference.llm_client.get_llm_client", return_value=mock.Mock()), \
                 mock.patch("ai_inference.llm_client.chat_result_guarded", side_effect=side_effect) as judge_mock:
                result = answer_eval._llm_semantic_evaluate(
                    answer="候选答案", gold_answer="标准答案", checks=[],
                    semantic_threshold=0.65, question_text="题干",
                )
        return result, judge_mock.call_count

    def test_switch_off_single_call_legacy_shape(self):
        result, calls = self._run([_judge_text(0.9)], rejudge=False)
        self.assertEqual(calls, 1)
        self.assertTrue(result["semantic_passed"])
        self.assertNotIn("semantic_rejudge", result)

    def test_double_agree_two_calls(self):
        result, calls = self._run([_judge_text(0.9), _judge_text(0.8)], rejudge=True)
        self.assertEqual(calls, 2)
        self.assertTrue(result["semantic_passed"])
        self.assertEqual(result["semantic_score"], 0.85)
        self.assertEqual(result["semantic_rejudge"]["mode"], "double_agree")
        self.assertEqual(result["semantic_rejudge"]["scores"], [0.9, 0.8])

    def test_disagree_third_vote_majority(self):
        result, calls = self._run([_judge_text(0.9), _judge_text(0.2), _judge_text(0.8)], rejudge=True)
        self.assertEqual(calls, 3)
        self.assertTrue(result["semantic_passed"])
        self.assertEqual(result["semantic_score"], 0.8)
        self.assertEqual(result["semantic_rejudge"]["mode"], "majority")
        self.assertEqual(result["semantic_rejudge"]["votes"], [True, False, True])

    def test_second_vote_failure_keeps_single(self):
        result, calls = self._run([_judge_text(0.9), RuntimeError("judge down")], rejudge=True)
        self.assertEqual(calls, 2)
        self.assertTrue(result["semantic_passed"])
        self.assertEqual(result["semantic_score"], 0.9)
        self.assertEqual(result["semantic_rejudge"]["mode"], "second_failed")

    def test_third_vote_failure_split_fallback(self):
        result, calls = self._run([_judge_text(0.9), _judge_text(0.2), RuntimeError("judge down")], rejudge=True)
        self.assertEqual(calls, 3)
        self.assertFalse(result["semantic_passed"])  # 前两票均值 0.55 < 0.65
        self.assertEqual(result["semantic_rejudge"]["mode"], "split_fallback")


if __name__ == "__main__":
    unittest.main()
