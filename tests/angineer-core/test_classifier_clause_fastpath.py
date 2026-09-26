"""条款号规则快路径（需求 §5.3 靶子）：

「应符合哪条规范」「在哪条规范里」类问句问的是条款出处，2026-09-26 三方对照实测
现役 LLM 分类器会把这类题漏成 L1（4 例），规则直达 L2。本测试锁两件事：
1) 窄口径 pattern 的判准（4 例生产漏题必须命中；概念题/取值题不得误伤）；
2) 快路径经 classify_intent 全链路直达 L2 structured_lookup（LLM 不参与）。
"""
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../../services/angineer-core/src")))
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../../services/ai-inference/src")))

from angineer_core.classifier import (  # noqa: E402
    _clause_fastpath_enabled,
    _is_clause_number_query,
    IntentClassifier,
)

# 2026-09-26 §8 对照中 35B 漏成 L1 的 4 道生产题（原样回归）
PRODUCTION_MISSES = [
    "重力式码头抗滑稳定性验算应符合哪条规范要求？",
    "沉箱干舷高度应满足哪条规范？",
    "土工织物的等效孔径要求在哪条规范里？",
    "营运中码头的船舶荷载应符合哪条规范规定？",
]

NOT_CLAUSE_QUERIES = [
    "什么是港口吞吐量？",
    "疏浚土的分类有哪些？",
    "依据《海港总体设计规范》确定5万吨级散货船的设计船型尺度",  # 取值题，归 L2 但不归本规则
    "某5万吨级散货船，试计算码头前沿水深。",  # L3 计算题
    "知识库里有多少篇文档？",  # meta 通道
    "条款的内容是什么",  # 条款概念题，无「哪条」
]


class ClauseFastPathPatternTests(unittest.TestCase):
    def test_production_misses_hit_pattern(self):
        for query in PRODUCTION_MISSES:
            self.assertTrue(_is_clause_number_query(query), query)

    def test_non_clause_queries_not_hit(self):
        for query in NOT_CLAUSE_QUERIES:
            self.assertFalse(_is_clause_number_query(query), query)

    def test_switch_default_on_and_off(self):
        old = os.environ.get("ANGINEER_CLAUSE_FASTPATH")
        try:
            os.environ.pop("ANGINEER_CLAUSE_FASTPATH", None)
            self.assertTrue(_clause_fastpath_enabled())
            os.environ["ANGINEER_CLAUSE_FASTPATH"] = "false"
            self.assertFalse(_clause_fastpath_enabled())
        finally:
            if old is None:
                os.environ.pop("ANGINEER_CLAUSE_FASTPATH", None)
            else:
                os.environ["ANGINEER_CLAUSE_FASTPATH"] = old


class ClauseFastPathEndToEndTests(unittest.TestCase):
    """快路径命中时 classify_intent 直达 L2（规则前置，LLM 不会被调用——llm_client 传哨兵对象）。"""

    def setUp(self):
        # 观测落盘导入测试沙箱，不污染 data/ops/
        self._tmp = tempfile.TemporaryDirectory()
        self._old_ops = os.environ.get("ANGINEER_OPS_DIR")
        os.environ["ANGINEER_OPS_DIR"] = self._tmp.name

    def tearDown(self):
        if self._old_ops is None:
            os.environ.pop("ANGINEER_OPS_DIR", None)
        else:
            os.environ["ANGINEER_OPS_DIR"] = self._old_ops
        self._tmp.cleanup()

    def test_clause_query_routes_l2_without_llm(self):
        classifier = IntentClassifier([], llm_client=object())
        for query in PRODUCTION_MISSES:
            result = classifier.classify_intent(query)
            self.assertEqual(result.intent_level, "L2", query)
            self.assertEqual(result.service_mode, "structured_lookup", query)

    def test_result_recorded_to_ops_jsonl(self):
        classifier = IntentClassifier([], llm_client=object())
        classifier.classify_intent(PRODUCTION_MISSES[0])
        files = os.listdir(self._tmp.name)
        self.assertTrue(any(f.startswith("classify-") and f.endswith(".jsonl") for f in files), files)
        import json

        path = os.path.join(self._tmp.name, [f for f in files if f.startswith("classify-")][0])
        with open(path, encoding="utf-8") as f:
            line = json.loads(f.readline())
        self.assertEqual(line["kind"], "classify")
        self.assertIn("dur_ms", line)
        self.assertEqual(line["level"], "L2")


if __name__ == "__main__":
    unittest.main()
