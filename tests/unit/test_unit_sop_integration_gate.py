"""P1 集成闸门：未审核 SOP 对分类器/路由不可见；生成落盘为 draft 且校验不通过被拒收。"""
import json
import os
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../../services/ai-inference/src")))
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../../services/angineer-core/src")))
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../../services/sop-core/src")))
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../../services/docs-core/src")))

from sop_core.sop_loader import SopLoader  # noqa: E402


def write_sop(sop_dir, sop_id, payload):
    os.makedirs(sop_dir, exist_ok=True)
    with open(os.path.join(sop_dir, f"{sop_id}.json"), "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)


class SopExecutionGateTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.sop_base = os.path.join(self._tmp.name, "sops")
        self.json_dir = os.path.join(self.sop_base, "json")

    def tearDown(self):
        self._tmp.cleanup()

    def test_unreviewed_sop_invisible_to_classifier_until_published(self):
        write_sop(self.json_dir, "legacy", {"id": "legacy", "name_zh": "旧SOP", "steps": []})
        write_sop(
            self.json_dir,
            "draft_sop",
            {
                "id": "draft_sop",
                "name_zh": "新SOP",
                "status": "draft",
                "steps": [
                    {
                        "id": "step_1",
                        "description": {"content": "执行", "citations": []},
                        "tool": "auto",
                    }
                ],
            },
        )

        loader = SopLoader(self.sop_base)
        from angineer_core.classifier import IntentClassifier

        classifier = IntentClassifier(loader.load_all())
        self.assertEqual([s.id for s in classifier.sops], ["legacy"])

        loader.update_status("draft_sop", "published")
        classifier = IntentClassifier(loader.load_all())
        self.assertEqual({s.id for s in classifier.sops}, {"legacy", "draft_sop"})

    def test_generated_sops_written_as_draft_and_invalid_rejected(self):
        from sop_core.sop_path_generator import SopPathGenerator

        valid = {
            "id": "gen_valid",
            "name_zh": "有效生成",
            "description": "desc",
            "steps": [
                {
                    "id": "step_1",
                    "name": "计算",
                    "description": "计算 ${a}+${b}",
                    "execution": {"tool": "calculator", "inputs": {"expression": "${a}+${b}"}, "outputs": {"S": "result"}},
                    "next_step_id": None,
                }
            ],
            "blackboard": {"required": ["a", "b"], "outputs": ["S"]},
        }
        invalid = {"id": "gen_invalid", "name_zh": "无效生成", "description": "desc", "steps": []}

        with patch.dict(os.environ, {"DATA_DIR": self._tmp.name}):
            written, rejected = SopPathGenerator()._write_sops_to_disk([valid, invalid], library_id="lib1")

        self.assertEqual([s["id"] for s in written], ["gen_valid"])
        self.assertEqual(rejected[0]["id"], "gen_invalid")
        self.assertTrue(rejected[0]["problems"])

        with open(os.path.join(self.json_dir, "gen_valid.json"), "r", encoding="utf-8") as f:
            data = json.load(f)
        self.assertEqual(data["status"], "draft")
        self.assertEqual(data["source"]["kind"], "graph")
        self.assertEqual(data["source"]["library_id"], "lib1")
        self.assertFalse(os.path.exists(os.path.join(self.json_dir, "gen_invalid.json")))


if __name__ == "__main__":
    unittest.main()
