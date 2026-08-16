"""意图分类：强 L1 定位信号优先于 LLM，避免同一查询被分到 L2 后表格问答不稳定。"""
import json
import os
import sys
import unittest
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../../services/angineer-core/src")))
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../../services/ai-inference/src")))

from angineer_core.classifier import IntentClassifier  # noqa: E402


def _llm_response(intent_level, service_mode, intent_type):
    payload = {
        "intent_level": intent_level,
        "intent_type": intent_type,
        "confidence": 0.95,
        "service_mode": service_mode,
        "reason": "llm",
    }
    return SimpleNamespace(text=json.dumps(payload, ensure_ascii=False))


class L1LocationPrecedenceTests(unittest.TestCase):
    def test_location_keyword_wins_over_llm_l2(self):
        classifier = IntentClassifier(sops=[], llm_client=object())
        with patch(
            "angineer_core.classifier.chat_result_guarded",
            return_value=_llm_response("L2", "structured_lookup", "条款查表"),
        ) as mocked:
            result = classifier.classify_intent("杂货船设计船型尺度表 在哪里")
        mocked.assert_not_called()
        self.assertEqual(result.intent_level, "L1")
        self.assertEqual(result.intent_type, "locate_navigation")
        self.assertEqual(result.service_mode, "semantic_retrieval")

    def test_non_location_query_still_uses_llm(self):
        classifier = IntentClassifier(sops=[], llm_client=object())
        with patch(
            "angineer_core.classifier.chat_result_guarded",
            return_value=_llm_response("L2", "structured_lookup", "条款查表"),
        ) as mocked:
            result = classifier.classify_intent("2300t的杂货船船型尺度该怎么设计")
        mocked.assert_called_once()
        self.assertEqual(result.intent_level, "L2")
        self.assertEqual(result.service_mode, "structured_lookup")


if __name__ == "__main__":
    unittest.main()
