"""
意图分类器单元测试。
"""
import unittest
from unittest.mock import Mock, patch, MagicMock
import json

import sys
import os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../services/angineer-core/src")))

from angineer_core.core.classifier import IntentClassifier
from angineer_core.standard.context_models import SOP, Step
from angineer_core.infra.response_parser import IntentResponse, ArgsExtractResponse


class TestIntentClassifierInit(unittest.TestCase):
    """测试 IntentClassifier 初始化。"""
    
    def test_init_with_sops(self):
        """测试使用 SOP 列表初始化。"""
        sops = [
            SOP(id="test_sop", steps=[]),
            SOP(id="math_sop", steps=[]),
        ]
        classifier = IntentClassifier(sops)
        self.assertEqual(len(classifier.sops), 2)
    
    def test_init_empty_sops(self):
        """测试空 SOP 列表初始化。"""
        classifier = IntentClassifier([])
        self.assertEqual(len(classifier.sops), 0)
    
    def test_init_with_custom_llm_client(self):
        """测试使用自定义 LLM 客户端初始化。"""
        mock_client = Mock()
        sops = [SOP(id="test", steps=[])]
        classifier = IntentClassifier(sops, llm_client=mock_client)
        self.assertEqual(classifier._llm_client, mock_client)


class TestRouteWithMockLLM(unittest.TestCase):
    """测试 route 方法（使用 Mock LLM）。"""
    
    def setUp(self):
        """设置测试环境。"""
        self.sops = [
            SOP(
                id="math_sop",
                name_zh="数学计算",
                description="执行数学运算",
                steps=[Step(id="step1", tool="calculator", inputs={})],
                blackboard={"required": ["expression"]}
            ),
            SOP(
                id="code_review",
                name_zh="代码审查",
                description="审查代码质量",
                steps=[Step(id="step1", tool="reviewer", inputs={})]
            ),
            SOP(
                id="search",
                name_zh="知识搜索",
                description="搜索知识库",
                steps=[Step(id="step1", tool="search", inputs={})]
            ),
        ]
    
    def test_route_match_success(self):
        """测试成功匹配 SOP。"""
        mock_client = Mock()
        mock_client.chat.return_value = json.dumps({
            "sop_id": "math_sop",
            "reason": "用户想要进行数学计算"
        })
        
        classifier = IntentClassifier(self.sops, llm_client=mock_client)
        sop, args, reason = classifier.route("计算 25 * 4")
        
        self.assertIsNotNone(sop)
        self.assertEqual(sop.id, "math_sop")
        self.assertEqual(reason, "用户想要进行数学计算")
    
    def test_route_no_match(self):
        """测试未匹配到 SOP。"""
        mock_client = Mock()
        mock_client.chat.return_value = json.dumps({
            "sop_id": None,
            "reason": "无法识别用户意图"
        })
        
        classifier = IntentClassifier(self.sops, llm_client=mock_client)
        sop, args, reason = classifier.route("今天天气怎么样")
        
        self.assertIsNone(sop)
        self.assertEqual(reason, "无法识别用户意图")
    
    def test_route_with_unknown_sop_id(self):
        """测试 LLM 返回未知 SOP ID。"""
        mock_client = Mock()
        mock_client.chat.return_value = json.dumps({
            "sop_id": "unknown_sop",
            "reason": "匹配未知 SOP"
        })
        
        classifier = IntentClassifier(self.sops, llm_client=mock_client)
        sop, args, reason = classifier.route("测试未知 SOP")
        
        self.assertIsNone(sop)
    
    def test_route_with_markdown_json(self):
        """测试 LLM 返回 Markdown 包裹的 JSON。"""
        mock_client = Mock()
        mock_client.chat.return_value = '''```json
{
    "sop_id": "code_review",
    "reason": "用户想要审查代码"
}
```'''
        
        classifier = IntentClassifier(self.sops, llm_client=mock_client)
        sop, args, reason = classifier.route("审查这段代码")
        
        self.assertIsNotNone(sop)
        self.assertEqual(sop.id, "code_review")
    
    def test_route_with_malformed_json(self):
        """测试 LLM 返回格式错误的 JSON。"""
        mock_client = Mock()
        mock_client.chat.return_value = "这不是一个有效的 JSON"
        
        classifier = IntentClassifier(self.sops, llm_client=mock_client)
        sop, args, reason = classifier.route("测试格式错误")
        
        self.assertIsNone(sop)
    
    def test_route_llm_error(self):
        """测试 LLM 调用失败。"""
        mock_client = Mock()
        mock_client.chat.side_effect = Exception("API 连接失败")
        
        classifier = IntentClassifier(self.sops, llm_client=mock_client)
        sop, args, reason = classifier.route("测试 LLM 错误")
        
        self.assertIsNone(sop)
        self.assertEqual(args, {})
    
    def test_route_empty_response(self):
        """测试 LLM 返回空响应。"""
        mock_client = Mock()
        mock_client.chat.return_value = ""
        
        classifier = IntentClassifier(self.sops, llm_client=mock_client)
        sop, args, reason = classifier.route("测试空响应")
        
        self.assertIsNone(sop)
    
    def test_route_empty_sops_list(self):
        """测试空 SOP 列表时的路由。"""
        mock_client = Mock()
        classifier = IntentClassifier([], llm_client=mock_client)
        sop, args, reason = classifier.route("测试空列表")
        
        self.assertIsNone(sop)
        mock_client.chat.assert_not_called()


class TestArgsExtraction(unittest.TestCase):
    """测试参数提取功能。"""
    
    def setUp(self):
        """设置测试环境。"""
        self.sops = [
            SOP(
                id="math_sop",
                name_zh="数学计算",
                steps=[Step(id="step1", tool="calculator", inputs={})],
                blackboard={"required": ["expression", "precision"]}
            ),
        ]
    
    def test_extract_args_success(self):
        """测试成功提取参数。"""
        mock_client = Mock()
        mock_client.chat.side_effect = [
            json.dumps({"sop_id": "math_sop", "reason": "数学计算"}),
            json.dumps({"args": {"expression": "25 * 4", "precision": 2}}),
        ]
        
        classifier = IntentClassifier(self.sops, llm_client=mock_client)
        sop, args, reason = classifier.route("计算 25 * 4，保留两位小数")
        
        self.assertIsNotNone(sop)
        self.assertIn("expression", args)
    
    def test_extract_args_partial(self):
        """测试部分参数提取。"""
        mock_client = Mock()
        mock_client.chat.side_effect = [
            json.dumps({"sop_id": "math_sop", "reason": "数学计算"}),
            json.dumps({"args": {"expression": "25 * 4"}}),
        ]
        
        classifier = IntentClassifier(self.sops, llm_client=mock_client)
        sop, args, reason = classifier.route("计算 25 * 4")
        
        self.assertIsNotNone(sop)
        self.assertIn("expression", args)
    
    def test_extract_args_with_null_values(self):
        """测试参数提取时过滤 null 值。"""
        mock_client = Mock()
        mock_client.chat.side_effect = [
            json.dumps({"sop_id": "math_sop", "reason": "数学计算"}),
            json.dumps({"args": {"expression": "25 * 4", "precision": None}}),
        ]
        
        classifier = IntentClassifier(self.sops, llm_client=mock_client)
        sop, args, reason = classifier.route("计算 25 * 4")
        
        self.assertIsNotNone(sop)
        self.assertIn("expression", args)
        self.assertNotIn("precision", args)


class TestSOPMatching(unittest.TestCase):
    """测试 SOP 匹配逻辑。"""
    
    def test_match_by_id(self):
        """测试通过 ID 匹配 SOP。"""
        sops = [
            SOP(id="math_sop", steps=[]),
            SOP(id="code_review", steps=[]),
        ]
        mock_client = Mock()
        mock_client.chat.return_value = json.dumps({
            "sop_id": "math_sop",
            "reason": "匹配"
        })
        
        classifier = IntentClassifier(sops, llm_client=mock_client)
        sop, _, _ = classifier.route("测试")
        
        self.assertEqual(sop.id, "math_sop")
    
    def test_match_by_id_case_insensitive(self):
        """测试 ID 匹配忽略大小写。"""
        sops = [
            SOP(id="Math_SOP", steps=[]),
        ]
        mock_client = Mock()
        mock_client.chat.return_value = json.dumps({
            "sop_id": "math_sop",
            "reason": "匹配"
        })
        
        classifier = IntentClassifier(sops, llm_client=mock_client)
        sop, _, _ = classifier.route("测试")
        
        self.assertIsNotNone(sop)
    
    def test_match_by_name_zh(self):
        """测试通过中文名称匹配 SOP。"""
        sops = [
            SOP(id="sop_001", name_zh="数学计算", steps=[]),
        ]
        mock_client = Mock()
        mock_client.chat.return_value = json.dumps({
            "sop_id": "数学计算",
            "reason": "匹配"
        })
        
        classifier = IntentClassifier(sops, llm_client=mock_client)
        sop, _, _ = classifier.route("测试")
        
        self.assertIsNotNone(sop)
        self.assertEqual(sop.id, "sop_001")


if __name__ == "__main__":
    unittest.main()
