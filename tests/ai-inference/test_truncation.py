"""
单元测试：截断守卫（P0.2）。

覆盖：
- extract_json_from_text(strict=True) 拒绝截断 JSON（不 salvage）；
- 非 strict 保留尽力修复的兜底行为；
- _try_fix_json 不破坏字符串内撇号；
- LLMTruncatedError 携带 partial_text。
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../../services/ai-inference/src")))
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../../services/angineer-core/src")))

from ai_inference.llm_response_parser import ParseError, extract_json_from_text
from ai_inference.llm_client import LLMTruncatedError


class TestStrictExtract(unittest.TestCase):
    """strict=True 时截断 JSON 不得被静默 salvage。"""

    def test_strict_rejects_truncated_json(self):
        truncated = '{"name": "test", "value": 12'  # 未闭合
        with self.assertRaises(ParseError):
            extract_json_from_text(truncated, strict=True)

    def test_strict_rejects_trailing_comma_json(self):
        """strict 模式同样拒绝需要修复的 JSON（即使可修复）。"""
        with self.assertRaises(ParseError):
            extract_json_from_text('{"a": 1,}', strict=True)

    def test_non_strict_keeps_salvage_fallback(self):
        """非 strict 保留现有尽力修复行为。"""
        result = extract_json_from_text('{"a": 1,}')
        self.assertEqual(result, {"a": 1})


class TestTryFixJsonPreservesApostrophes(unittest.TestCase):
    """Q1：_try_fix_json 不得用全局 replace("'", '"') 破坏字符串内撇号。"""

    def test_apostrophe_inside_double_quoted_string_preserved(self):
        text = '{"name": "it\'s ok", "value": 1,}'
        result = extract_json_from_text(text)
        self.assertEqual(result["name"], "it's ok")
        self.assertEqual(result["value"], 1)

    def test_python_style_single_quoted_keys_still_fixed(self):
        """键名/裸值的单引号仍需修复（保留原能力）。"""
        result = extract_json_from_text("{'name': 'test', 'value': 1,}")
        self.assertEqual(result["name"], "test")
        self.assertEqual(result["value"], 1)


class TestLLMTruncatedError(unittest.TestCase):
    """LLMTruncatedError 异常携带 partial_text。"""

    def test_error_carries_partial_text(self):
        err = LLMTruncatedError("输出被截断", partial_text='{"a":')
        self.assertIn("输出被截断", str(err))
        self.assertEqual(err.partial_text, '{"a":')


class TestClassifierCallSiteTruncation(unittest.TestCase):
    """调用点级：classifier 路由遇到截断输出时不得静默接受半截 JSON。"""

    def test_route_rejects_truncated_rerank_output(self):
        from unittest.mock import Mock

        from angineer_core.base_contracts import SOP, Step
        from angineer_core.classifier import IntentClassifier
        from ai_inference.llm_client import ChatResult

        sops = [
            SOP(
                id="math_sop",
                name_zh="数学计算",
                steps=[Step(id="s1", tool="calculator", inputs={})],
            )
        ]
        mock_client = Mock()
        mock_client.chat_result.return_value = ChatResult(
            text='{"sop_id": "math_sop", "confidence": 0.9',
            finish_reason="length",
        )
        classifier = IntentClassifier(sops, llm_client=mock_client)

        result = classifier.route("计算 25 * 4")

        self.assertIsNone(result.sop)
        self.assertIn("截断", result.reason)


if __name__ == "__main__":
    unittest.main()
