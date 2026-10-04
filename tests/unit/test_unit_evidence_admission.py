"""证据上桌留痕上浮链单测（plan-evidence-admission 变更 E）。

覆盖：policy_query._aggregate_admission 聚合（求和/None 跳过/fallback 取或/judge_ms 求和）；
RetrievalEvaluator.evaluate 把 prediction.admission 写入 all_scores.retrieval.admission。
"""
import os
import sys
import unittest

ROOT_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "../.."))
for sub in (
    os.path.join("services", "evals-core", "src"),
    os.path.join("services", "angineer-core", "src"),
    os.path.join("services", "ai-inference", "src"),
):
    path = os.path.join(ROOT_DIR, sub)
    if path not in sys.path:
        sys.path.insert(0, path)

from angineer_core.policy_query import _aggregate_admission  # noqa: E402
from evals_core.runner.retrieval_eval import RetrievalEvaluator  # noqa: E402


class AggregateAdmissionTests(unittest.TestCase):
    def test_none_when_no_blocks(self):
        self.assertIsNone(_aggregate_admission([]))

    def test_counts_sum_and_fallback_or(self):
        merged = _aggregate_admission([
            {"kept": 3, "dropped": 5, "quarreled": 1, "exempted": 2, "fallback": False,
             "judge_config": "Qwen3.8-Flash-Next", "judge_ms": 1200, "cap_dropped": 2},
            {"kept": None, "dropped": None, "quarreled": None, "exempted": None, "fallback": True,
             "judge_config": "Qwen3.8-Flash-Next", "judge_ms": None, "cap_dropped": 0},
        ])
        self.assertEqual(merged["kept"], 3)  # None 计数跳过、有数就加
        self.assertEqual(merged["dropped"], 5)
        self.assertEqual(merged["cap_dropped"], 2)
        self.assertTrue(merged["fallback"])  # 任一块 fail-open 即 True
        self.assertEqual(merged["judge_ms"], 1200)
        self.assertEqual(merged["judge_config"], "Qwen3.8-Flash-Next")

    def test_partial_entity_cap_block(self):
        """entity_search 只带 cap_dropped 的部分块：其余键补 None、不炸聚合。"""
        merged = _aggregate_admission([{"cap_dropped": 4}])
        self.assertEqual(merged["cap_dropped"], 4)
        self.assertIsNone(merged["kept"])
        self.assertFalse(merged["fallback"])


class RetrievalEvalAdmissionPassthroughTests(unittest.TestCase):
    def test_evaluate_carries_admission_into_all_scores(self):
        evaluator = RetrievalEvaluator()
        question = {"question_id": "q1", "question": "q"}
        gold = {"gold_doc_ids": ["d1"]}
        prediction = {
            "retrieved_items": [{"item_id": "i1", "doc_id": "d1", "metadata": {}}],
            "citations": [],
            "admission": {"kept": 9, "dropped": 4, "quarreled": 2, "exempted": 1,
                          "fallback": False, "judge_config": "Qwen3.8-Flash-Next",
                          "judge_ms": 1500, "cap_dropped": 1},
        }
        scores = evaluator.evaluate(question, gold, prediction)
        self.assertEqual(scores["admission"]["kept"], 9)
        self.assertEqual(scores["admission"]["cap_dropped"], 1)

    def test_no_admission_key_when_absent(self):
        evaluator = RetrievalEvaluator()
        scores = evaluator.evaluate(
            {"question_id": "q2", "question": "q"},
            {"gold_doc_ids": ["d1"]},
            {"retrieved_items": [], "citations": []},
        )
        self.assertNotIn("admission", scores)  # 未触发的题不带键


if __name__ == "__main__":
    unittest.main()
