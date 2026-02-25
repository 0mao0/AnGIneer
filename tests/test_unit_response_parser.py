"""
单元测试：LLM 响应解析模块。
"""
import unittest
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../services/angineer-core/src")))

from angineer_core.infra.response_parser import (
    ParseError,
    IntentResponse,
    ActionResponse,
    StepParseResponse,
    ArgsExtractResponse,
    extract_json_from_text,
    parse_and_validate,
    safe_extract_string,
    safe_extract_dict,
)


class TestExtractJsonFromText(unittest.TestCase):
    """测试 JSON 提取功能。"""
    
    def test_extract_simple_json(self):
        """测试提取简单 JSON。"""
        text = '{"name": "test", "value": 123}'
        result = extract_json_from_text(text)
        self.assertEqual(result["name"], "test")
        self.assertEqual(result["value"], 123)
    
    def test_extract_json_with_markdown_block(self):
        """测试提取 Markdown 代码块中的 JSON。"""
        text = '''
这是一些文本
```json
{"sop_id": "math_sop", "reason": "数学计算"}
```
更多文本
'''
        result = extract_json_from_text(text)
        self.assertEqual(result["sop_id"], "math_sop")
        self.assertEqual(result["reason"], "数学计算")
    
    def test_extract_json_with_generic_block(self):
        """测试提取通用代码块中的 JSON。"""
        text = '''
```
{"action": "execute", "tool": "calculator"}
```
'''
        result = extract_json_from_text(text)
        self.assertEqual(result["action"], "execute")
        self.assertEqual(result["tool"], "calculator")
    
    def test_extract_json_embedded_in_text(self):
        """测试提取嵌入在文本中的 JSON。"""
        text = '响应结果: {"status": "ok"} 结束'
        result = extract_json_from_text(text)
        self.assertEqual(result["status"], "ok")
    
    def test_extract_nested_json(self):
        """测试提取嵌套 JSON。"""
        text = '{"outer": {"inner": {"value": 42}}}'
        result = extract_json_from_text(text)
        self.assertEqual(result["outer"]["inner"]["value"], 42)
    
    def test_empty_text_raises_error(self):
        """测试空文本抛出错误。"""
        with self.assertRaises(ParseError):
            extract_json_from_text("")
    
    def test_invalid_json_raises_error(self):
        """测试无效 JSON 抛出错误。"""
        with self.assertRaises(ParseError):
            extract_json_from_text("这不是 JSON")


class TestParseAndValidate(unittest.TestCase):
    """测试解析和校验功能。"""
    
    def test_validate_intent_response(self):
        """测试校验意图响应。"""
        text = '{"sop_id": "test_sop", "reason": "测试原因"}'
        result = parse_and_validate(text, IntentResponse)
        self.assertEqual(result.sop_id, "test_sop")
        self.assertEqual(result.reason, "测试原因")
    
    def test_validate_action_response(self):
        """测试校验动作响应。"""
        text = '{"action": "execute_tool", "tool": "calculator", "inputs": {"expr": "1+1"}}'
        result = parse_and_validate(text, ActionResponse)
        self.assertEqual(result.action, "execute_tool")
        self.assertEqual(result.tool, "calculator")
        self.assertEqual(result.inputs["expr"], "1+1")
    
    def test_validate_with_missing_optional_fields(self):
        """测试缺少可选字段时使用默认值。"""
        text = '{"action": "skip"}'
        result = parse_and_validate(text, ActionResponse)
        self.assertEqual(result.action, "skip")
        self.assertIsNone(result.tool)
        self.assertIsNone(result.inputs)
    
    def test_strict_mode_raises_error(self):
        """测试严格模式下校验失败抛出错误。"""
        text = 'this is not valid json at all'
        with self.assertRaises(ParseError):
            parse_and_validate(text, IntentResponse, strict=True)
    
    def test_strict_mode_with_invalid_json_structure(self):
        """测试严格模式下无效 JSON 结构抛出错误。"""
        text = '{"action": "test"}'
        from angineer_core.infra.response_parser import StepParseResponse
        with self.assertRaises(ParseError):
            parse_and_validate(text, StepParseResponse, strict=True)
    
    def test_non_strict_mode_uses_defaults(self):
        """测试非严格模式使用默认值。"""
        text = '{"invalid_field": "value"}'
        result = parse_and_validate(text, IntentResponse, strict=False)
        self.assertIsNone(result.sop_id)
        self.assertIsNone(result.reason)


class TestSafeExtract(unittest.TestCase):
    """测试安全提取功能。"""
    
    def test_safe_extract_string_found(self):
        """测试安全提取字符串 - 找到。"""
        text = '{"name": "test_value"}'
        result = safe_extract_string(text, "name")
        self.assertEqual(result, "test_value")
    
    def test_safe_extract_string_not_found(self):
        """测试安全提取字符串 - 未找到。"""
        text = '{"other": "value"}'
        result = safe_extract_string(text, "name", default="default")
        self.assertEqual(result, "default")
    
    def test_safe_extract_dict_found(self):
        """测试安全提取字典 - 找到。"""
        text = '{"args": {"key1": "value1", "key2": "value2"}}'
        result = safe_extract_dict(text, "args")
        self.assertEqual(result["key1"], "value1")
    
    def test_safe_extract_dict_not_found(self):
        """测试安全提取字典 - 未找到。"""
        text = '{"other": "value"}'
        result = safe_extract_dict(text, "args", default={})
        self.assertEqual(result, {})


class TestParseError(unittest.TestCase):
    """测试 ParseError 异常。"""
    
    def test_error_message(self):
        """测试错误消息格式。"""
        error = ParseError("解析失败", raw_response="原始响应", details="详细信息")
        self.assertIn("解析失败", str(error))
        self.assertIn("详细信息", str(error))
        self.assertEqual(error.raw_response, "原始响应")
    
    def test_error_without_details(self):
        """测试没有详情的错误消息。"""
        error = ParseError("简单错误")
        self.assertIn("简单错误", str(error))


class TestResponseModels(unittest.TestCase):
    """测试响应模型。"""
    
    def test_intent_response_model(self):
        """测试意图响应模型。"""
        response = IntentResponse(sop_id="test", reason="测试")
        self.assertEqual(response.sop_id, "test")
        self.assertEqual(response.reason, "测试")
    
    def test_action_response_model(self):
        """测试动作响应模型。"""
        response = ActionResponse(
            action="ask_user",
            question="请输入参数"
        )
        self.assertEqual(response.action, "ask_user")
        self.assertEqual(response.question, "请输入参数")
    
    def test_args_extract_response_model(self):
        """测试参数提取响应模型。"""
        response = ArgsExtractResponse(args={"key": "value"})
        self.assertEqual(response.args["key"], "value")
    
    def test_step_parse_response_model(self):
        """测试步骤解析响应模型。"""
        response = StepParseResponse(
            id="step_1",
            tool="calculator",
            inputs={"expr": "1+1"},
            outputs={"result": "output"}
        )
        self.assertEqual(response.id, "step_1")
        self.assertEqual(response.tool, "calculator")


if __name__ == "__main__":
    unittest.main()
