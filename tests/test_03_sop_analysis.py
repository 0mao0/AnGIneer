
import sys
import os
import unittest
from unittest.mock import patch

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from backend.src.core.sop_loader import SopLoader

"""
SOP 混合分析测试脚本 (Test 03)
验证 SopLoader 是否能通过 LLM 将 Markdown 格式的 SOP 智能解析为结构化的执行步骤。
"""

@patch("src.core.llm.llm_client")
class TestSopAnalysis(unittest.TestCase):
    def test_analyze_sop(self, mock_llm):
        print("\n[测试 03] SOP 混合分析测试")
        sop_id = "航道边坡"
        mock_response = """
```json
{
  "steps": [
    {
      "id": "step1",
      "name": "匹配土质与状态",
      "description": "解析输入并标准化",
      "tool": "user_input",
      "inputs": {"soil_type": "土质名称", "condition": "状态描述"},
      "notes": "解析用户输入的土质名称与状态描述"
    },
    {
      "id": "step2",
      "name": "确定边坡坡度范围",
      "description": "查表获取范围",
      "tool": "table_lookup",
      "inputs": {"table_name": "海港水文规范-表6.4.9"},
      "notes": "若用户未提供具体状态，列出所有可能范围并提示补充"
    }
  ]
}
```
"""
        mock_llm.chat.return_value = mock_response

        sop_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "backend", "sops")
        loader = SopLoader(sop_dir)
        sops = loader.load_all()
        self.assertGreater(len(sops), 0)

        print("  -> 步骤 1: 执行分析")
        analyzed_sop = loader.analyze_sop(sop_id)
        self.assertGreater(len(analyzed_sop.steps), 0)
        self.assertTrue(all(step.analysis_status == "analyzed" for step in analyzed_sop.steps))
        self.assertTrue(any(step.notes for step in analyzed_sop.steps))
        print(f"     分析步骤数: {len(analyzed_sop.steps)}")

    def test_analyze_sop_fallback(self, mock_llm):
        print("\n[测试 03] SOP 分析失败回退测试")
        sop_id = "航道边坡"
        mock_llm.chat.return_value = "not-json"

        sop_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "backend", "sops")
        loader = SopLoader(sop_dir)

        print("  -> 步骤 1: 执行分析")
        sop = loader.analyze_sop(sop_id)
        self.assertGreater(len(sop.steps), 0)
        self.assertEqual(sop.steps[0].tool, "sop_run")

if __name__ == "__main__":
    unittest.main()
