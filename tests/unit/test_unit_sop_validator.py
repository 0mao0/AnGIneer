"""P1.2 SOP 结构校验器单测（五条规则正反例）。"""
import os
import sys
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../../services/angineer-core/src")))
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../../services/sop-core/src")))

from sop_core.sop_validator import validate_sop_data  # noqa: E402


def valid_sop_dict(**overrides):
    data = {
        "id": "sop_test",
        "name_zh": "测试SOP",
        "description": "测试描述",
        "steps": [
            {
                "id": "step_1",
                "name": "查表获取L",
                "description": {"content": "依据表A.0.2-1获取L", "citations": []},
                "tool": "table_lookup",
                "inputs": {
                    "table_name": "表A.0.2-1",
                    "query_conditions": {"船型": "${船型}"},
                },
                "outputs": {"L": "result"},
                "analysis_status": "analyzed",
                "next_step_id": "step_2",
            },
            {
                "id": "step_2",
                "name": "计算面积",
                "description": {"content": "S=L*W", "citations": []},
                "tool": "calculator",
                "inputs": {"expression": "${L}*${W}"},
                "outputs": {"S": "result"},
                "analysis_status": "analyzed",
                "next_step_id": None,
            },
        ],
        "blackboard": {"required": ["船型", "W"], "outputs": ["L", "S"]},
    }
    data.update(overrides)
    return data


class SopValidatorTests(unittest.TestCase):
    """validate_sop_data 五条规则的正反例。"""

    def test_valid_sop_passes(self):
        self.assertEqual(validate_sop_data(valid_sop_dict()), [])

    def test_empty_steps_rejected(self):
        problems = validate_sop_data(valid_sop_dict(steps=[]))
        self.assertTrue(any("steps" in p and "空" in p for p in problems))

    def test_duplicate_step_id_rejected(self):
        data = valid_sop_dict()
        data["steps"][1]["id"] = "step_1"
        problems = validate_sop_data(data)
        self.assertTrue(any("重复" in p for p in problems))

    def test_next_step_id_missing_target_rejected(self):
        data = valid_sop_dict()
        data["steps"][0]["next_step_id"] = "step_999"
        problems = validate_sop_data(data)
        self.assertTrue(any("不存在" in p for p in problems))

    def test_next_step_id_cycle_rejected(self):
        data = valid_sop_dict()
        data["steps"][1]["next_step_id"] = "step_1"
        problems = validate_sop_data(data)
        self.assertTrue(any("环" in p for p in problems))

    def test_unknown_tool_rejected(self):
        data = valid_sop_dict()
        data["steps"][0]["tool"] = "magic_tool"
        problems = validate_sop_data(data)
        self.assertTrue(any("未注册" in p for p in problems))

    def test_auto_tool_only_allowed_before_analyzed(self):
        data = valid_sop_dict()
        data["steps"][0]["tool"] = "auto"
        data["steps"][0]["analysis_status"] = "analyzed"
        problems = validate_sop_data(data)
        self.assertTrue(any("auto" in p and "analyzed" in p for p in problems))

        data["steps"][0]["analysis_status"] = "pending"
        self.assertEqual(validate_sop_data(data), [])

    def test_non_dict_inputs_rejected(self):
        data = valid_sop_dict()
        data["steps"][0]["inputs"] = ["not", "dict"]
        problems = validate_sop_data(data)
        self.assertTrue(any("模型校验" in p for p in problems))

    def test_required_key_must_be_referenced_or_produced(self):
        data = valid_sop_dict()
        data["blackboard"] = {"required": ["完全无关的键"], "outputs": ["L", "S"]}
        problems = validate_sop_data(data)
        self.assertTrue(any("无法由初始上下文或任何步骤提供" in p for p in problems))

    def test_required_key_produced_by_step_outputs_passes(self):
        data = valid_sop_dict()
        # S 由 step_2 outputs 产出；L 由 step_1 产出
        data["blackboard"] = {"required": ["L", "S"], "outputs": ["L", "S"]}
        self.assertEqual(validate_sop_data(data), [])

    def test_empty_step_description_rejected(self):
        data = valid_sop_dict()
        data["steps"][0]["description"] = {"content": "", "citations": []}
        problems = validate_sop_data(data)
        self.assertTrue(any("description.content" in p for p in problems))


if __name__ == "__main__":
    unittest.main()
