"""Phase D1 测试：chat_auth.enforce_bound_libraries 集合鉴权（先鉴权后截断，spec §P1-5）。

语义：会话用户按 bound_library_ids 集合校验（任一库越权即 403，不做静默剔除）；
管理员任意集合；API Key 维持单库绑定（集合强制收敛为 [bound]）；匿名仅默认库；
上限截断（ANGINEER_MAX_CHAT_LIBRARIES 默认 5，夹 1..10）永远发生在鉴权之后。
"""
import importlib
import os
import sys
import unittest
from types import SimpleNamespace
from unittest.mock import patch

_AICHAT_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "../../services/aichat-api"))
sys.path.append(_AICHAT_DIR)
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../../services/angineer-core/src")))


def _load_aichat_module(name):
    """按归属加载 aichat-api 顶层模块（同 test_chat_auth_scope.py 惯例：混跑时同名包冲突防御）。"""
    while _AICHAT_DIR in sys.path:
        sys.path.remove(_AICHAT_DIR)
    sys.path.insert(0, _AICHAT_DIR)
    parts = name.split(".")
    for i in range(1, len(parts) + 1):
        mod_name = ".".join(parts[:i])
        loaded = sys.modules.get(mod_name)
        if loaded is not None:
            owner = os.path.abspath(getattr(loaded, "__file__", "") or "")
            if not owner.lower().startswith(_AICHAT_DIR.lower()):
                sys.modules.pop(mod_name, None)
    return importlib.import_module(name)


def _unload_aichat_modules():
    for name, mod in list(sys.modules.items()):
        path = getattr(mod, "__file__", None)
        if path and os.path.abspath(path).lower().startswith(_AICHAT_DIR.lower()):
            sys.modules.pop(name, None)
    while _AICHAT_DIR in sys.path:
        sys.path.remove(_AICHAT_DIR)
    for name, mod in list(sys.modules.items()):
        if mod is None:
            sys.modules.pop(name, None)


class TestEnforceBoundLibraries(unittest.TestCase):
    def setUp(self):
        self.chat_auth = _load_aichat_module("chat_auth")
        self.addCleanup(_unload_aichat_modules)
        # 隔离外部 env：默认上限 5 的用例不能被调试值污染（同 guest_gate 用例的 env 隔离惯例）
        env_patch = patch.dict(os.environ, {}, clear=False)
        env_patch.start()
        self.addCleanup(env_patch.stop)
        os.environ.pop("ANGINEER_MAX_CHAT_LIBRARIES", None)

    def _state(self, **kw):
        base = dict(session_user=None, bound_library_id="", bound_library_ids=None)
        base.update(kw)  # 计划片段原形用 **kw 直传 SimpleNamespace，重复关键字会 TypeError，改为 dict 合并
        return SimpleNamespace(**base)

    def test_session_user_set_validation_pass(self):
        state = self._state(bound_library_ids={"libA", "libB"}, bound_library_id="libA")
        self.assertEqual(self.chat_auth.enforce_bound_libraries(state, ["libA", "libB"]), ["libA", "libB"])

    def test_session_user_rejects_unbound_before_truncate(self):
        from fastapi import HTTPException

        # 真竞态钉法（M1）：cap=5 下前 5 个全部授权、第 6 个越权——
        # 若实现先截断 [:5] 再把截断后的集合送去鉴权，越权项恰好在截断窗口外被丢弃，
        # 整个请求会静默放行；必须对未截断的整集鉴权 → 403。
        authed = [f"l{i}" for i in range(1, 6)]
        state = self._state(bound_library_ids=set(authed), bound_library_id=authed[0])
        with patch.dict(os.environ, {"ANGINEER_MAX_CHAT_LIBRARIES": "5"}):
            self.assertEqual(self.chat_auth.max_chat_libraries(), 5)
            with self.assertRaises(HTTPException) as ctx:
                self.chat_auth.enforce_bound_libraries(state, authed + ["lX"])
        self.assertEqual(ctx.exception.status_code, 403)
        # 非竞态基线：小集合混越权库同样 403（截断不参与时也不得放行）
        state2 = self._state(bound_library_ids={"libA"}, bound_library_id="libA")
        with self.assertRaises(HTTPException):
            self.chat_auth.enforce_bound_libraries(state2, ["libA", "libX"])

    def test_admin_any_set(self):
        state = self._state(session_user=SimpleNamespace(is_admin=True))
        self.assertEqual(
            self.chat_auth.enforce_bound_libraries(state, ["libA", "libZ"]), ["libA", "libZ"]
        )

    def test_anonymous_default_only(self):
        state = self._state()
        self.assertEqual(self.chat_auth.enforce_bound_libraries(state, []), ["default"])
        from fastapi import HTTPException

        with self.assertRaises(HTTPException):
            self.chat_auth.enforce_bound_libraries(state, ["libA"])

    def test_cap_truncates_after_auth(self):
        state = self._state(session_user=SimpleNamespace(is_admin=True))
        out = self.chat_auth.enforce_bound_libraries(state, ["a", "b", "c", "d", "e", "f", "g"])
        self.assertEqual(len(out), 5)  # ANGINEER_MAX_CHAT_LIBRARIES 默认 5

    # ---- 兼容铁律补充用例 ----

    def test_session_user_default_set_falls_back_to_first_bound_library(self):
        state = self._state(bound_library_ids={"libA", "libB"}, bound_library_id="libA")
        self.assertEqual(self.chat_auth.enforce_bound_libraries(state, ["default"]), ["libA"])
        self.assertEqual(self.chat_auth.enforce_bound_libraries(state, []), ["libA"])

    def test_zero_bound_session_user_legacy_body_passes(self):
        """评审 blocking 回归钉：零绑库登录用户（ids=set() 非 None、bound=""）旧 body
        （空/["default"]）必须照常放行——旧 enforce_bound_library 回退 bound→""→"default"，
        新集合版若在回退分支仍过成员校验即 403，破兼容铁律 1。"""
        state = self._state(bound_library_ids=set(), bound_library_id="")
        self.assertEqual(self.chat_auth.enforce_bound_libraries(state, []), ["default"])
        self.assertEqual(self.chat_auth.enforce_bound_libraries(state, ["default"]), ["default"])

    def test_zero_bound_session_user_explicit_library_still_403(self):
        """同一零绑库用户显式请求具名库：非回退路径，成员校验照旧 403。"""
        from fastapi import HTTPException

        state = self._state(bound_library_ids=set(), bound_library_id="")
        with self.assertRaises(HTTPException) as ctx:
            self.chat_auth.enforce_bound_libraries(state, ["libX"])
        self.assertEqual(ctx.exception.status_code, 403)

    def test_api_key_set_converges_to_single_bound_library(self):
        """Key 维持单库绑定：授权集内多库请求也收敛为 [bound]。"""
        state = SimpleNamespace(bound_library_id="lib-alice")
        self.assertEqual(self.chat_auth.enforce_bound_libraries(state, ["lib-alice", "lib-alice"]), ["lib-alice"])
        self.assertEqual(self.chat_auth.enforce_bound_libraries(state, ["default"]), ["lib-alice"])
        self.assertEqual(self.chat_auth.enforce_bound_libraries(state, []), ["lib-alice"])

    def test_api_key_unbound_member_raises_403(self):
        """越权库不进集合：单库冲突（旧契约）与多库混入越权库都必须 403，不静默收敛。"""
        from fastapi import HTTPException

        state = SimpleNamespace(bound_library_id="lib-alice")
        with self.assertRaises(HTTPException) as ctx:
            self.chat_auth.enforce_bound_libraries(state, ["lib-eve"])
        self.assertEqual(ctx.exception.status_code, 403)
        with self.assertRaises(HTTPException):
            self.chat_auth.enforce_bound_libraries(state, ["lib-alice", "lib-eve"])

    def test_max_chat_libraries_env_clamp(self):
        with patch.dict(os.environ, {"ANGINEER_MAX_CHAT_LIBRARIES": "100"}):
            self.assertEqual(self.chat_auth.max_chat_libraries(), 10)
        with patch.dict(os.environ, {"ANGINEER_MAX_CHAT_LIBRARIES": "0"}):
            self.assertEqual(self.chat_auth.max_chat_libraries(), 1)
        with patch.dict(os.environ, {"ANGINEER_MAX_CHAT_LIBRARIES": "abc"}):
            self.assertEqual(self.chat_auth.max_chat_libraries(), 5)


if __name__ == "__main__":
    unittest.main()
