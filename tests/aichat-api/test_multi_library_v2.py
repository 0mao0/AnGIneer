"""V2 订阅派生制鉴权测试——设计稿 docs/design-user-kb-access-scope.md §9-4/§9-5（设计稿已完结清理、git 历史可查）。

对照 test_multi_library_auth.py（V2=0 旧语义基线）：本文件钉 V2=1 侧——
会话用户改走 _enforce_bound_v2 派生制成员校验：
- 隐式（空/["default"]）= 派生集全选，无上限、无 [:5] 截断（业主口径「选 M 库 = M 库检索」）；
- 显式 @ 任一非成员（未订阅/未登记）→ 403 可见报错，不静默剔除；全成员 → 整集返回；
- 派生集为空（零订阅/空快照）→ 回退 [bound_library_id or default]，不锁死（§8-4）；
- V2=0 回滚保险：旧平铺 5 库截断逐位保留。

模块加载与卸载克隆 test_multi_library_auth.py 惯例（混跑时同名包冲突防御）。
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
    """按归属加载 aichat-api 顶层模块（同 test_multi_library_auth.py 惯例）。"""
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


from fastapi import HTTPException  # noqa: E402

ALL21 = [f"kb-{i:02d}" for i in range(21)]


class TestEnforceBoundV2(unittest.TestCase):
    def setUp(self):
        self.chat_auth = _load_aichat_module("chat_auth")
        self.addCleanup(_unload_aichat_modules)
        env_patch = patch.dict(os.environ, {}, clear=False)
        env_patch.start()
        self.addCleanup(env_patch.stop)
        os.environ.pop("ANGINEER_MAX_CHAT_LIBRARIES", None)
        os.environ.pop("ANGINEER_KB_SUBSCRIPTION_V2", None)

    def _state(self, *, user=None, bound_id="", bound_ids=None):
        return SimpleNamespace(session_user=user, bound_library_id=bound_id, bound_library_ids=bound_ids)

    def _user(self, is_admin=False, library_ids=None):
        return SimpleNamespace(
            is_admin=is_admin,
            library_ids=list(library_ids or []),
            group_subscriptions=[],
            library_direct=[],
        )

    def _v2_on(self):
        return patch.object(self.chat_auth, "subscription_v2_enabled", return_value=True)

    # ---- 派生集注入路径（state.bound_library_ids 已含派生结果） ----

    def test_explicit_subset_all_members_returns_full_set(self):
        """显式勾选 7 成员（>旧 5 上限）→ 整集 7 库返回，无截断。"""
        state = self._state(user=self._user(), bound_id=ALL21[0], bound_ids=list(ALL21))
        req = ALL21[:7]
        with self._v2_on():
            got = self.chat_auth.enforce_bound_libraries(state, req)
        self.assertEqual(got, req)

    def test_implicit_empty_returns_full_derived(self):
        """隐式（空列表）= 派生集全选：21 库全部返回（无上限）。"""
        state = self._state(user=self._user(), bound_id=ALL21[0], bound_ids=list(ALL21))
        with self._v2_on():
            got = self.chat_auth.enforce_bound_libraries(state, [])
        self.assertEqual(got, list(ALL21))

    def test_implicit_default_marker_returns_full_derived(self):
        """["default"] 视同隐式全选（旧兼容：default 标记不进成员校验）。"""
        state = self._state(user=self._user(), bound_id=ALL21[0], bound_ids=list(ALL21))
        with self._v2_on():
            got = self.chat_auth.enforce_bound_libraries(state, ["default"])
        self.assertEqual(got, list(ALL21))

    def test_non_member_403_visible_error(self):
        """显式 @ 含非成员 → 403，不静默剔除（静默截断移除）。"""
        state = self._state(user=self._user(), bound_id="kb-00", bound_ids=list(ALL21))
        with self._v2_on():
            with self.assertRaises(HTTPException) as ctx:
                self.chat_auth.enforce_bound_libraries(state, ["kb-01", "kb-99"])
        self.assertEqual(ctx.exception.status_code, 403)
        self.assertIn("kb-99", ctx.exception.detail)

    def test_all_members_under_threshold_no_warning(self):
        """21 库全成员请求：只记 warning 不拦截（FANOUT_WARN_THRESHOLD 观测口径）。"""
        state = self._state(user=self._user(), bound_id=ALL21[0], bound_ids=list(ALL21))
        with self._v2_on():
            got = self.chat_auth.enforce_bound_libraries(state, list(ALL21))
        self.assertEqual(got, list(ALL21))

    # ---- 派生现算路径（state 未注入成员集 → 现场 derive_libraries_for_user） ----

    def test_derive_ran_when_no_bound_injection(self):
        """旁路 state（无 bound_library_ids）→ 现场跑派生，成员集单一真相源。"""
        state = self._state(user=self._user(), bound_id="", bound_ids=None)
        with self._v2_on(), patch.object(self.chat_auth, "derive_libraries_for_user", return_value=list(ALL21)):
            got = self.chat_auth.enforce_bound_libraries(state, ALL21[:7])
        self.assertEqual(got, ALL21[:7])

    def test_zero_subscription_empty_derive_falls_back_default(self):
        """§8-4：派生为空（零订阅）→ 回退默认库，不锁死。"""
        state = self._state(user=self._user(), bound_id="", bound_ids=None)
        with self._v2_on(), patch.object(self.chat_auth, "derive_libraries_for_user", return_value=[]):
            got = self.chat_auth.enforce_bound_libraries(state, [])
        self.assertEqual(got, ["default"])

    def test_zero_subscription_derive_falls_back_bound_id(self):
        """派生为空且绑定过单库（API key 形 state 不在此列）→ 回退 bound_library_id。"""
        state = self._state(user=self._user(), bound_id="kb-07", bound_ids=None)
        with self._v2_on(), patch.object(self.chat_auth, "derive_libraries_for_user", return_value=[]):
            got = self.chat_auth.enforce_bound_libraries(state, [])
        self.assertEqual(got, ["kb-07"])

    def test_admin_full_active_minus_evals_via_derive(self):
        """管理员同闸：V2 开时派生集=全部 active−evals，由 derive 现算（本测试注入替身）。"""
        active_no_evals = [f"kb-{i:02d}" for i in range(25)]
        state = self._state(user=self._user(is_admin=True), bound_id=active_no_evals[0], bound_ids=None)
        with self._v2_on(), patch.object(self.chat_auth, "derive_libraries_for_user", return_value=list(active_no_evals)):
            got = self.chat_auth.enforce_bound_libraries(state, [])
        self.assertEqual(got, active_no_evals)

    def test_admin_unknown_lib_still_403(self):
        """管理员派生集外的未登记 id → 仍 403（管理员视野=active−evals，不是无限放行）。"""
        state = self._state(user=self._user(is_admin=True), bound_id=ALL21[0], bound_ids=list(ALL21))
        with self._v2_on():
            with self.assertRaises(HTTPException) as ctx:
                self.chat_auth.enforce_bound_libraries(state, ["kb-20", "ghost-lib"])
        self.assertEqual(ctx.exception.status_code, 403)

    # ---- V2=0 回滚保险：旧平铺语义逐位保留 ----

    def test_v2_off_truncates_to_cap(self):
        """开关关 = 旧 5 库截断：7 成员请求 → 前 5 + 显式非成员照旧 403。"""
        state = self._state(user=self._user(library_ids=list(ALL21)), bound_id=ALL21[0], bound_ids=set(ALL21))
        got = self.chat_auth.enforce_bound_libraries(state, ALL21[:7])
        self.assertEqual(got, ALL21[:5])
        with self.assertRaises(HTTPException) as ctx:
            self.chat_auth.enforce_bound_libraries(state, ALL21[:6] + ["ghost"])
        self.assertEqual(ctx.exception.status_code, 403)

    # ---- 非会话用户主体不受 V2 影响（§8-C2） ----

    def test_api_key_single_library_convergence_unchanged(self):
        """API key 单库绑定收敛保留：绑 kb-01 请求含 kb-02 → 403。"""
        state = self._state(user=None, bound_id="kb-01", bound_ids=None)
        with self.assertRaises(HTTPException):
            self.chat_auth.enforce_bound_libraries(state, ["kb-01", "kb-02"])
        self.assertEqual(self.chat_auth.enforce_bound_libraries(state, ["kb-01"]), ["kb-01"])

    def test_anonymous_default_only_unchanged(self):
        """匿名（无用户无绑定）仅默认库；显式 @ 其它库 403。"""
        state = self._state(user=None, bound_id="", bound_ids=None)
        self.assertEqual(self.chat_auth.enforce_bound_libraries(state, []), ["default"])
        self.assertEqual(self.chat_auth.enforce_bound_libraries(state, ["default"]), ["default"])
        with self.assertRaises(HTTPException):
            self.chat_auth.enforce_bound_libraries(state, ["kb-01"])


if __name__ == "__main__":
    unittest.main()
