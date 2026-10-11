"""
SopApiClient（sop-api HTTP 客户端）单元测试：TTL / 快照兜底 / 双失败空池。
"""
import json
import os
import sys
import tempfile
import unittest
from unittest.mock import patch, MagicMock

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../../services/aichat-api")))
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../../services/sop-core/src")))
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../../services/angineer-core/src")))

from sop_api_client import SopApiClient


def _fake_response(items):
    resp = MagicMock()
    resp.json.return_value = {"sops": items}
    resp.raise_for_status.return_value = None
    return resp


def _one_sop(sop_id="sop-x"):
    return {
        "id": sop_id,
        "name_zh": "测试 SOP",
        "description": "测试",
        "status": "published",
        "steps": [{
            "id": "s1",
            "tool": "不存在的工具",
            "description": "测试步骤",
            "inputs": {},
            "outputs": {"result": "result"},
        }],
        "blackboard": {"required": [], "outputs": ["result"], "all": ["result"]},
    }


class TestSopApiClient(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.NamedTemporaryFile(suffix=".json", delete=False)
        self.tmp.close()
        os.unlink(self.tmp.name)
        self.client = SopApiClient(base_url="http://test", ttl=300.0)
        self.client.snapshot_path = self.tmp.name

    def _mock_session(self, response=None, error=None):
        """替换客户端 session 为 mock（客户端走 session.get，trust_env=False）。"""
        session = MagicMock()
        if error is not None:
            session.get.side_effect = error
        else:
            session.get.return_value = response
            session.get.return_value.raise_for_status.return_value = None
        self.client.session = session
        return session

    def tearDown(self):
        if os.path.exists(self.tmp.name):
            os.unlink(self.tmp.name)

    def test_fetch_success_builds_sops_with_tool_downgrade(self):
        """HTTP 成功 → 构造 SOP 对象，未注册工具降级 auto。"""
        self._mock_session(response=_fake_response([_one_sop()]))
        sops = self.client.load_published()
        self.assertEqual(len(sops), 1)
        self.assertEqual(sops[0].steps[0].tool, "auto")
        self.assertTrue(os.path.exists(self.tmp.name), "快照应写盘")

    def test_fetch_failure_falls_back_to_snapshot(self):
        """HTTP 失败 → 读末次快照。"""
        self._mock_session(response=_fake_response([_one_sop("sop-a")]))
        self.client.load_published()
        self.client.ttl = 0.0  # 打穿缓存
        self._mock_session(error=Exception("down"))
        sops = self.client.load_published()
        self.assertEqual([s.id for s in sops], ["sop-a"])

    def test_double_failure_returns_empty(self):
        """HTTP 失败且无快照 → 空池不抛异常。"""
        self._mock_session(error=Exception("down"))
        self.assertEqual(self.client.load_published(), [])

    def test_ttl_cache_hit_skips_http(self):
        """TTL 内二次调用不发 HTTP。"""
        session = self._mock_session(response=_fake_response([_one_sop()]))
        self.client.load_published()
        self.client.load_published()
        self.assertEqual(session.get.call_count, 1)

    def test_load_all_alias_matches_loader_signature(self):
        """load_all() 与 SopLoader 签名兼容（agent_policy/chat_agent 调用点零改动）。"""
        self._mock_session(response=_fake_response([_one_sop()]))
        self.assertEqual(len(self.client.load_all()), 1)


if __name__ == "__main__":
    unittest.main()
