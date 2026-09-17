"""游客身份与 30 轮闸测试（计划 §5 步 3，D2/D6/D12）。

覆盖：resolve_pool_owner 的 g: cookie 优先级（登录/key > cookie > ip:）、
guest_gate_blocked 边界（29/30/31）、存储降级 fail-open、env 阈值注入。
"""
import os
import sys
import unittest
from types import SimpleNamespace
from unittest.mock import patch

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "../../services/aichat-api")))
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../../services/angineer-core/src")))

import importlib

_AICHAT_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "../../services/aichat-api"))


def _load_chat_auth():
    while _AICHAT_DIR in sys.path:
        sys.path.remove(_AICHAT_DIR)
    sys.path.insert(0, _AICHAT_DIR)
    loaded = sys.modules.get("chat_auth")
    if loaded is not None:
        owner = os.path.abspath(getattr(loaded, "__file__", "") or "")
        if not owner.lower().startswith(_AICHAT_DIR.lower()):
            sys.modules.pop("chat_auth", None)
    return importlib.import_module("chat_auth")


def _request(cookies=None, user=None, key_info=None, xff="1.2.3.4"):
    state = SimpleNamespace(
        session_user=user,
        api_key_info=key_info,
    )
    return SimpleNamespace(state=state, cookies=cookies or {},
                           headers={"x-forwarded-for": xff},
                           client=SimpleNamespace(host=""))


class _FakeStore:
    def __init__(self, count):
        self._count = count

    def count_user_messages(self, owner):
        return self._count


class ResolveGuestOwnerTests(unittest.TestCase):
    def setUp(self):
        self.chat_auth = _load_chat_auth()
        self.addCleanup(self._unload)

    @staticmethod
    def _unload():
        sys.modules.pop("chat_auth", None)

    def test_cookie_resolves_to_g_owner(self):
        req = _request(cookies={"ag_guest_id": "abc123"})
        self.assertEqual(self.chat_auth.resolve_pool_owner(req), "g:abc123")

    def test_login_beats_cookie(self):
        req = _request(cookies={"ag_guest_id": "abc123"}, user=SimpleNamespace(id=7))
        self.assertEqual(self.chat_auth.resolve_pool_owner(req), "u:7")

    def test_api_key_beats_cookie(self):
        req = _request(cookies={"ag_guest_id": "abc123"}, key_info=SimpleNamespace(id=3))
        self.assertEqual(self.chat_auth.resolve_pool_owner(req), "k:3")

    def test_no_cookie_falls_back_to_ip(self):
        req = _request()
        owner = self.chat_auth.resolve_pool_owner(req)
        self.assertTrue(owner.startswith("ip:"))

    def test_different_cookies_different_buckets(self):
        # D6：同 NAT 两个游客不再撞池
        o1 = self.chat_auth.resolve_pool_owner(_request(cookies={"ag_guest_id": "g1"}))
        o2 = self.chat_auth.resolve_pool_owner(_request(cookies={"ag_guest_id": "g2"}))
        self.assertNotEqual(o1, o2)


class GuestGateTests(unittest.TestCase):
    def setUp(self):
        self.chat_auth = _load_chat_auth()
        self.addCleanup(lambda: sys.modules.pop("chat_auth", None))

    def test_non_guest_never_blocked(self):
        self.assertFalse(self.chat_auth.guest_gate_blocked("u:1", _FakeStore(999)))
        self.assertFalse(self.chat_auth.guest_gate_blocked("ip:abc", _FakeStore(999)))
        self.assertFalse(self.chat_auth.guest_gate_blocked("k:1", _FakeStore(999)))

    def test_store_none_fail_open(self):
        self.assertFalse(self.chat_auth.guest_gate_blocked("g:x", None))

    def test_boundary_29_30_31(self):
        # 29 轮放行，30 轮是最后一轮（放行），31 轮拦（D2：满 30 硬拦 = 已有 30 时拒第 31 条）
        self.assertFalse(self.chat_auth.guest_gate_blocked("g:x", _FakeStore(29)))
        self.assertFalse(self.chat_auth.guest_gate_blocked("g:x", _FakeStore(30 - 1)))
        self.assertTrue(self.chat_auth.guest_gate_blocked("g:x", _FakeStore(30)))

    def test_rounds_limit_env_override(self):
        with patch.dict(os.environ, {"ANGINEER_GUEST_ROUNDS": "5"}):
            self.assertEqual(self.chat_auth.guest_rounds_limit(), 5)
            self.assertTrue(self.chat_auth.guest_gate_blocked("g:x", _FakeStore(5)))
            self.assertFalse(self.chat_auth.guest_gate_blocked("g:x", _FakeStore(4)))


if __name__ == "__main__":
    unittest.main()
