"""synthesize/crystallize 端点测试。"""
import os, sys, json, unittest
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../../services/sop-api")))
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../../services/sop-core/src")))
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../../services/angineer-core/src")))

from unittest.mock import patch
from fastapi.testclient import TestClient
import main
from path_selector import SynthUnavailable

client = TestClient(main.app)

_SOP = {
    "id": "synthtest1", "name_zh": "合成测试", "description": "d",
    "steps": [{"id": "s1", "name": "s", "description": {"content": "x", "citations": []},
               "tool": "auto", "inputs": {}, "outputs": {"result": "result"}}],
    "blackboard": {"required": [], "outputs": ["result"], "all": ["result"]},
}


class TestSynthesizeEndpoint(unittest.TestCase):
    def test_200_shape(self):
        # 端点函数内 from path_selector import ...（lazy），patch 必须打 path_selector 命名空间
        with patch("path_selector.synthesize_sop", return_value={"sop": _SOP, "path": ["s"]}):
            r = client.post("/api/sops/synthesize", json={"query": "测试", "library_id": "lib"})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()["sop"]["steps"][0]["tool"], "auto")  # 已归一化

    def test_412_when_unavailable(self):
        with patch("path_selector.synthesize_sop", side_effect=SynthUnavailable("无实体")):
            r = client.post("/api/sops/synthesize", json={"query": "测试"})
        self.assertEqual(r.status_code, 412)
        self.assertEqual(r.json()["detail"]["error"], "no_path")


class TestCrystallizeEndpoint(unittest.TestCase):
    def test_saves_draft(self):
        with patch("sop_routes._sop_loader.save_generated_sop", return_value="synthtest1") as mock_save:
            r = client.post("/api/sops/crystallize",
                            json={"sop": _SOP, "source_query": "测试问题", "review_note": "自动结晶"})
        self.assertEqual(r.status_code, 200)
        payload = mock_save.call_args.args[1]
        self.assertEqual(payload["status"], "draft")
        self.assertEqual(payload["source"]["kind"], "l4_synth")
        self.assertEqual(payload["review"]["note"], "自动结晶")


if __name__ == "__main__":
    unittest.main()
