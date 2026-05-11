"""
意图分类器单元测试。
"""
import unittest
from unittest.mock import Mock, patch, MagicMock
import json

import sys
import os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../../services/ai-inference/src")))
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../../services/angineer-core/src")))

from angineer_core.classifier import IntentClassifier, _char_bigrams, _build_sop_corpus, _keyword_recall
from angineer_core.base_contracts import SOP, Step, RouteResult
from angineer_core.base_contracts import IntentResponse, ArgsExtractResponse


class TestCharBigrams(unittest.TestCase):
    """测试字符级 bigram 分词。"""

    def test_basic_chinese(self):
        result = _char_bigrams("航道通航底高程")
        self.assertEqual(result, ["航道", "道通", "通航", "航底", "底高", "高程"])

    def test_english(self):
        result = _char_bigrams("hello")
        self.assertEqual(result, ["he", "el", "ll", "lo"])

    def test_empty_string(self):
        result = _char_bigrams("")
        self.assertEqual(result, [])

    def test_single_char(self):
        result = _char_bigrams("a")
        self.assertEqual(result, ["a"])

    def test_whitespace_removed(self):
        result = _char_bigrams("航 道")
        self.assertEqual(result, ["航道"])


class TestBuildSopCorpus(unittest.TestCase):
    """测试 SOP 语料构建。"""

    def test_basic_corpus(self):
        sops = [
            SOP(id="sop1", name_zh="航道底高程", description="计算航道底高程", steps=[]),
            SOP(id="sop2", name_zh="码头宽度", description="计算码头设计宽度", steps=[]),
        ]
        doc_ids, documents = _build_sop_corpus(sops)
        self.assertEqual(doc_ids, ["sop1", "sop2"])
        self.assertEqual(len(documents), 2)
        self.assertIn("航道底高程", documents[0])
        self.assertIn("码头宽度", documents[1])

    def test_corpus_with_blackboard(self):
        sops = [
            SOP(
                id="sop1",
                name_zh="航道底高程",
                steps=[],
                blackboard={"required": ["dwt", "water_level"], "outputs": ["D0", "E_nav"]},
            ),
        ]
        doc_ids, documents = _build_sop_corpus(sops)
        self.assertIn("dwt", documents[0])
        self.assertIn("E_nav", documents[0])


class TestKeywordRecall(unittest.TestCase):
    """测试关键词粗筛。"""

    def test_basic_recall(self):
        doc_ids = ["sop1", "sop2"]
        documents = ["航道通航底高程计算", "码头设计宽度计算"]
        results = _keyword_recall("航道底高程", doc_ids, documents)
        self.assertTrue(len(results) > 0)
        self.assertEqual(results[0][0], "sop1")

    def test_no_match(self):
        doc_ids = ["sop1"]
        documents = ["码头设计宽度计算"]
        results = _keyword_recall("天气预报", doc_ids, documents, min_score=0.5)
        self.assertEqual(len(results), 0)

    def test_empty_documents(self):
        results = _keyword_recall("测试", [], [])
        self.assertEqual(len(results), 0)

    def test_top_k_limit(self):
        doc_ids = ["sop1", "sop2", "sop3"]
        documents = ["航道底高程", "航道宽度", "航道水深"]
        results = _keyword_recall("航道底高程", doc_ids, documents, top_k=2)
        self.assertTrue(len(results) <= 2)


class TestIntentClassifierInit(unittest.TestCase):
    """测试 IntentClassifier 初始化。"""

    def test_init_with_sops(self):
        sops = [
            SOP(id="test_sop", steps=[]),
            SOP(id="math_sop", steps=[]),
        ]
        classifier = IntentClassifier(sops)
        self.assertEqual(len(classifier.sops), 2)

    def test_init_empty_sops(self):
        classifier = IntentClassifier([])
        self.assertEqual(len(classifier.sops), 0)

    def test_init_with_custom_llm_client(self):
        mock_client = Mock()
        sops = [SOP(id="test", steps=[])]
        classifier = IntentClassifier(sops, llm_client=mock_client)
        self.assertEqual(classifier._llm_client, mock_client)


class TestRouteWithMockLLM(unittest.TestCase):
    """测试 route 方法（使用 Mock LLM，模拟两阶段匹配）。"""

    def setUp(self):
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

    def _make_rerank_response(self, sop_id=None, confidence=0.9, reason="匹配"):
        """构造 LLM 精排的返回值。"""
        return json.dumps({
            "sop_id": sop_id,
            "confidence": confidence,
            "reason": reason,
        })

    def test_route_match_success(self):
        """测试成功匹配 SOP。"""
        mock_client = Mock()
        mock_client.chat.return_value = self._make_rerank_response(
            sop_id="math_sop", confidence=0.9, reason="用户想要进行数学计算"
        )

        classifier = IntentClassifier(self.sops, llm_client=mock_client)
        result = classifier.route("计算 25 * 4")

        self.assertIsNotNone(result.sop)
        self.assertEqual(result.sop.id, "math_sop")
        self.assertGreaterEqual(result.confidence, 0.6)

    def test_route_no_match_null_sop(self):
        """测试 LLM 返回 null sop_id。"""
        mock_client = Mock()
        mock_client.chat.return_value = self._make_rerank_response(
            sop_id=None, confidence=0.2, reason="无法识别用户意图"
        )

        classifier = IntentClassifier(self.sops, llm_client=mock_client)
        result = classifier.route("今天天气怎么样")

        self.assertIsNone(result.sop)

    def test_route_low_confidence_rejection(self):
        """测试低置信度拒绝。"""
        mock_client = Mock()
        mock_client.chat.return_value = self._make_rerank_response(
            sop_id="math_sop", confidence=0.4, reason="部分相关"
        )

        classifier = IntentClassifier(self.sops, llm_client=mock_client)
        result = classifier.route("计算相关的话题")

        self.assertIsNone(result.sop)
        self.assertLess(result.confidence, 0.6)

    def test_route_with_unknown_sop_id(self):
        """测试 LLM 返回未知 SOP ID。"""
        mock_client = Mock()
        mock_client.chat.return_value = self._make_rerank_response(
            sop_id="unknown_sop", confidence=0.9, reason="匹配未知 SOP"
        )

        classifier = IntentClassifier(self.sops, llm_client=mock_client)
        result = classifier.route("测试未知 SOP")

        self.assertIsNone(result.sop)

    def test_route_with_markdown_json(self):
        """测试 LLM 返回 Markdown 包裹的 JSON。"""
        mock_client = Mock()
        mock_client.chat.return_value = '''```json
{
    "sop_id": "code_review",
    "confidence": 0.85,
    "reason": "用户想要审查代码"
}
```'''

        classifier = IntentClassifier(self.sops, llm_client=mock_client)
        result = classifier.route("审查这段代码")

        self.assertIsNotNone(result.sop)
        self.assertEqual(result.sop.id, "code_review")

    def test_route_with_malformed_json(self):
        """测试 LLM 返回格式错误的 JSON。"""
        mock_client = Mock()
        mock_client.chat.return_value = "这不是一个有效的 JSON"

        classifier = IntentClassifier(self.sops, llm_client=mock_client)
        result = classifier.route("测试格式错误")

        self.assertIsNone(result.sop)

    def test_route_llm_error(self):
        """测试 LLM 调用失败。"""
        mock_client = Mock()
        mock_client.chat.side_effect = Exception("API 连接失败")

        classifier = IntentClassifier(self.sops, llm_client=mock_client)
        result = classifier.route("测试 LLM 错误")

        self.assertIsNone(result.sop)
        self.assertEqual(result.args, {})

    def test_route_empty_response(self):
        """测试 LLM 返回空响应。"""
        mock_client = Mock()
        mock_client.chat.return_value = ""

        classifier = IntentClassifier(self.sops, llm_client=mock_client)
        result = classifier.route("测试空响应")

        self.assertIsNone(result.sop)

    def test_route_empty_sops_list(self):
        """测试空 SOP 列表时的路由。"""
        mock_client = Mock()
        classifier = IntentClassifier([], llm_client=mock_client)
        result = classifier.route("测试空列表")

        self.assertIsNone(result.sop)
        mock_client.chat.assert_not_called()

    def test_route_returns_candidates(self):
        """测试 route 返回候选列表。"""
        mock_client = Mock()
        mock_client.chat.return_value = self._make_rerank_response(
            sop_id="math_sop", confidence=0.9, reason="匹配"
        )

        classifier = IntentClassifier(self.sops, llm_client=mock_client)
        result = classifier.route("计算 25 * 4")

        self.assertIsInstance(result.candidates, list)
        self.assertTrue(len(result.candidates) > 0)


class TestArgsExtraction(unittest.TestCase):
    """测试参数提取功能。"""

    def setUp(self):
        self.sops = [
            SOP(
                id="math_sop",
                name_zh="数学计算",
                steps=[Step(id="step1", tool="calculator", inputs={})],
                blackboard={"required": ["expression", "precision"]}
            ),
        ]

    def _make_rerank_response(self, sop_id, confidence=0.9, reason="匹配"):
        return json.dumps({
            "sop_id": sop_id,
            "confidence": confidence,
            "reason": reason,
        })

    def test_extract_args_success(self):
        """测试成功提取参数。"""
        mock_client = Mock()
        mock_client.chat.side_effect = [
            self._make_rerank_response("math_sop"),
            json.dumps({"args": {"expression": "25 * 4", "precision": 2}}),
        ]

        classifier = IntentClassifier(self.sops, llm_client=mock_client)
        result = classifier.route("计算 25 * 4，保留两位小数")

        self.assertIsNotNone(result.sop)
        self.assertIn("expression", result.args)

    def test_extract_args_partial(self):
        """测试部分参数提取。"""
        mock_client = Mock()
        mock_client.chat.side_effect = [
            self._make_rerank_response("math_sop"),
            json.dumps({"args": {"expression": "25 * 4"}}),
        ]

        classifier = IntentClassifier(self.sops, llm_client=mock_client)
        result = classifier.route("计算 25 * 4")

        self.assertIsNotNone(result.sop)
        self.assertIn("expression", result.args)

    def test_extract_args_with_null_values(self):
        """测试参数提取时过滤 null 值。"""
        mock_client = Mock()
        mock_client.chat.side_effect = [
            self._make_rerank_response("math_sop"),
            json.dumps({"args": {"expression": "25 * 4", "precision": None}}),
        ]

        classifier = IntentClassifier(self.sops, llm_client=mock_client)
        result = classifier.route("计算 25 * 4")

        self.assertIsNotNone(result.sop)
        self.assertIn("expression", result.args)
        self.assertNotIn("precision", result.args)


class TestSOPMatching(unittest.TestCase):
    """测试 SOP 匹配逻辑。"""

    def _make_rerank_response(self, sop_id, confidence=0.9, reason="匹配"):
        return json.dumps({
            "sop_id": sop_id,
            "confidence": confidence,
            "reason": reason,
        })

    def test_match_by_id(self):
        """测试通过 ID 匹配 SOP。"""
        sops = [
            SOP(id="math_sop", name_zh="数学计算", steps=[]),
            SOP(id="code_review", name_zh="代码审查", steps=[]),
        ]
        mock_client = Mock()
        mock_client.chat.return_value = self._make_rerank_response("math_sop")

        classifier = IntentClassifier(sops, llm_client=mock_client)
        result = classifier.route("测试")

        self.assertEqual(result.sop.id, "math_sop")

    def test_match_by_id_case_insensitive(self):
        """测试 ID 匹配忽略大小写。"""
        sops = [
            SOP(id="Math_SOP", name_zh="数学计算", steps=[]),
        ]
        mock_client = Mock()
        mock_client.chat.return_value = self._make_rerank_response("math_sop")

        classifier = IntentClassifier(sops, llm_client=mock_client)
        result = classifier.route("测试")

        self.assertIsNotNone(result.sop)

    def test_match_by_name_zh(self):
        """测试通过中文名称匹配 SOP。"""
        sops = [
            SOP(id="sop_001", name_zh="数学计算", steps=[]),
        ]
        mock_client = Mock()
        mock_client.chat.return_value = self._make_rerank_response("数学计算")

        classifier = IntentClassifier(sops, llm_client=mock_client)
        result = classifier.route("测试")

        self.assertIsNotNone(result.sop)
        self.assertEqual(result.sop.id, "sop_001")


if __name__ == "__main__":
    unittest.main()
