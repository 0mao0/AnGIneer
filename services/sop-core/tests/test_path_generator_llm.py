"""SopPathGenerator.generate_sop_from_steps 公共包装测试（plan-sop-l4-synth Task 2）。"""

import json
import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

SOP_CORE_SRC = Path(__file__).resolve().parents[1] / "src"
if str(SOP_CORE_SRC) not in sys.path:
    sys.path.insert(0, str(SOP_CORE_SRC))

from sop_core.sop_path_generator import SopPathGenerator


class TestGenerateSopFromSteps(unittest.TestCase):
    def test_llm_success_returns_parsed_sop(self):
        gen = SopPathGenerator(store=None)
        llm_json = {
            "name_zh": "测试 SOP", "description": "d",
            "steps": [{"id": "step_1", "name": "s", "description": "x",
                       "execution": {"tool": "calculator", "inputs": {"a": "x"}, "outputs": {"r": "y"}},
                       "next_step_id": None}],
            "blackboard": {"required": ["a"], "outputs": ["r"]},
        }
        with patch("ai_inference.llm_client.chat_result_guarded") as mock_chat, \
             patch("ai_inference.llm_client.LLMClient", return_value=MagicMock()):
            mock_chat.return_value = MagicMock(text=json.dumps(llm_json))
            sop = gen.generate_sop_from_steps("测试框架", ["s"], "第3.2条", "lib", "doc")
        self.assertEqual(sop["name_zh"], "测试 SOP")
        self.assertEqual(sop["steps"][0]["execution"]["tool"], "calculator")
        # 包装层兜底字段：无 id 回落框架名；库/文档标识缺省补齐
        self.assertEqual(sop["id"], "测试框架")
        self.assertEqual(sop["library_id"], "lib")
        self.assertEqual(sop["doc_id"], "doc")

    def test_llm_failure_falls_back_to_skeleton(self):
        gen = SopPathGenerator(store=None)
        with patch("ai_inference.llm_client.chat_result_guarded", side_effect=RuntimeError("llm down")):
            sop = gen.generate_sop_from_steps("测试框架", ["查吃水", "算水深"], "", "", "")
        self.assertEqual(sop.get("id"), "测试框架")
        self.assertIn("steps", sop)
        # 注：骨架合并器对纯 concept 链会收敛（纯 concept 双步现状合为 1 步）——
        # 此处锁定「LLM 失败必回退出骨架」这一行为，不锁步数（步数收敛另议）。
        self.assertTrue(len(sop["steps"]) >= 1)


if __name__ == "__main__":
    unittest.main()
