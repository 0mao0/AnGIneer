"""synthesize/crystallize 端点测试。"""
import importlib.util
import os, sys, json, unittest
from pathlib import Path
from unittest.mock import patch
from fastapi.testclient import TestClient

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../../services/sop-core/src")))
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../../services/angineer-core/src")))

# 坑：不要裸 `import main`，也不要把 services/sop-api 常驻 sys.path——全量套跑 collection
# 阶段即导入本模块，该目录会遮蔽 docs-api 侧按裸名 import main 的用例（health_identity
# 曾套内必红、单跑必绿）。做法：临时入 path 完成加载（path_selector / docs_graph_client
# 进 sys.modules 供端点 lazy import），随后移除；main.py 按唯一模块名加载，互不遮蔽。
_SOP_API_DIR = str(Path(__file__).resolve().parents[2] / "services" / "sop-api")
sys.path.insert(0, _SOP_API_DIR)
try:
    import docs_graph_client  # noqa: F401
    from path_selector import SynthUnavailable
    _spec = importlib.util.spec_from_file_location(
        "sop_api_main_under_test", os.path.join(_SOP_API_DIR, "main.py"))
    assert _spec and _spec.loader
    _sop_main = importlib.util.module_from_spec(_spec)
    _spec.loader.exec_module(_sop_main)
finally:
    sys.path.remove(_SOP_API_DIR)

client = TestClient(_sop_main.app)

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
