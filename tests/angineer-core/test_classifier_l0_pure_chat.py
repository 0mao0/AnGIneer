"""L0 闲聊词表补强（2026-10-17）：

探针存量 FAIL ir-l0-pure-04（「给我讲个笑话？」L0→L1）：L0 判据是显式封闭词表，
「笑话」从未入表——该题在题集里 rule_hit=model，一直由 LLM 判；网关模型漂移后
LLM 改给 L1，三份基线（run3/run4/v2）复现同样失败。收口采用最小口径：只补「笑话」
一词（闲聊表演类收宽有 L0 误吞风险，按真实流量再扩）。本测试锁两件事：
1) 笑话类问句规则直达 L0（不再依赖 LLM 行为）；2) 带实质内容的「笑话」句不被吞。
"""
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../../services/angineer-core/src")))
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../../services/ai-inference/src")))

from angineer_core.classifier import (  # noqa: E402
    _check_l0_intent,
    IntentClassifier,
)

# 探针存量失败题 + 近义变体（原样回归）
JOKE_QUERIES = ["给我讲个笑话？", "讲个笑话", "来段笑话吧"]

# 「笑话」子串不得绕过 _has_substantive_content 闸门（实质内容/L1 词/超长句）
NOT_L0_QUERIES = [
    "什么是冷笑话的定义",  # 定义题（L1 词），不归闲聊
    "笑话在工程规范里能不能出现这种情况",  # 长句有实质内容
]


class L0JokeKeywordTests(unittest.TestCase):
    def test_joke_queries_hit_l0(self):
        for query in JOKE_QUERIES:
            result = _check_l0_intent(query)
            self.assertIsNotNone(result, query)
            self.assertEqual(result.intent_level, "L0", query)
            self.assertEqual(result.service_mode, "casual_chat", query)

    def test_substantive_joke_queries_not_l0(self):
        for query in NOT_L0_QUERIES:
            self.assertIsNone(_check_l0_intent(query), query)


class L0JokeEndToEndTests(unittest.TestCase):
    """探针原题经 classify_intent 直达 L0（规则前置，LLM 不会被调用——llm_client 传哨兵对象）。"""

    def setUp(self):
        # 观测落盘导入测试沙箱，不污染 data/ops/（conftest 全局 DISABLE，这里需显式恢复）
        self._tmp = tempfile.TemporaryDirectory()
        self._old_ops = {k: os.environ.get(k) for k in ("ANGINEER_OPS_DIR", "ANGINEER_OPS_DISABLE")}
        os.environ["ANGINEER_OPS_DIR"] = self._tmp.name
        os.environ.pop("ANGINEER_OPS_DISABLE", None)

    def tearDown(self):
        for k, v in self._old_ops.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        self._tmp.cleanup()

    def test_probe_item_routes_l0_without_llm(self):
        classifier = IntentClassifier([], llm_client=object())
        result = classifier.classify_intent("给我讲个笑话？")
        self.assertEqual(result.intent_level, "L0")
        self.assertEqual(result.service_mode, "casual_chat")
        self.assertIn("纯闲聊", result.reason or "")


if __name__ == "__main__":
    unittest.main()
