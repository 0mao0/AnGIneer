"""Phase D2 测试：/api/chat/agent 端点的 library_ids 接线（端点级）。

覆盖：
1. 多库集合经 normalize→鉴权 后到达 get_agent_session（library_ids kwarg）；
2. 旧 body 只带 library_id → library_ids 收敛为单元素、library_id 逐位不变（兼容铁律 1）；
3. 匿名越权库 403（兼容铁律 2，任一库越权即拒）。
stub 深度按 main.py 端点真实结构：get_agent_session/route_request/赌博式预检/history store 四点。
"""
import importlib
import os
import sys
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

_AICHAT_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "../../services/aichat-api"))
sys.path.append(_AICHAT_DIR)
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../../services/angineer-core/src")))

from angineer_core.base_contracts import RouteDebug, ScopeContext  # noqa: E402


def _load_aichat_module(name):
    """按归属加载 aichat-api 顶层模块（main/middleware/models 同名包冲突防御，同 test_route_pre.py）。"""
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


class _FakeSession:
    """最小会话替身：端点消费面 = wait_for_idle / run / cancel / history / active_run_id。

    run() 向 history 追加 user/assistant 两行——触发端点 run_end 未达时的兜底 persist
    （落库断言用例需要真实消息；无 store 时该路径自然跳过）。
    """

    def __init__(self):
        self.history = []
        self.active_run_id = None

    def wait_for_idle(self, timeout=None):
        return True

    def run(self, query, emit, config_factory):
        self.history.append(SimpleNamespace(role="user", content=query))
        self.history.append(SimpleNamespace(role="assistant", content="ok"))
        return None

    def cancel(self):
        return None


class _CapturingStore:
    """捕获端点 persist 组装的 run_meta（chat-history append 的服务端权威入口）。"""

    def __init__(self):
        self.run_metas = []

    def append(self, owner, session_id, scope_hash, messages, run_meta):
        self.run_metas.append(run_meta)
        return [len(self.run_metas)]

    def guest_rounds(self, owner):
        return 0

    def guest_is_claimed(self, guest_id):
        return False


class AgentEndpointLibraryIdsTests(unittest.TestCase):
    def _post(self, payload, api_key=None, session_user=None, store=None):
        main = _load_aichat_module("main")
        self.addCleanup(_unload_aichat_modules)
        from fastapi.testclient import TestClient
        # 测试侧 scope 构造与端点同源：调生产归一化点（M4），不再手抄规则
        from docs_core.step09_query.protocols.contracts import normalize_library_ids

        captured = {}

        def fake_get_session(*args, **kwargs):
            captured["args"] = args
            captured.update(kwargs)
            return _FakeSession()

        def fake_fire(*args, **kwargs):
            captured["fire_args"] = args
            captured["fire_kwargs"] = kwargs
            return None

        decision = SimpleNamespace(
            intent_result=None,
            scene="qa",
            fallback=True,
            attempts=[],  # route_debug_event 读 decision.attempts（SSE 首帧）
            scope=ScopeContext(
                library_ids=normalize_library_ids(
                    payload.get("library_ids") or None, payload.get("library_id") or ""),
                doc_ids=list(payload.get("doc_ids") or [])),
            route_debug=RouteDebug(fallback=True),
        )
        patches = [
            patch.object(main, "get_agent_session", side_effect=fake_get_session),
            patch.object(main, "route_request", new=AsyncMock(return_value=decision)),
            patch.object(main, "fire_speculative_first_search", side_effect=fake_fire),
            patch.object(main, "route_pre_enabled", return_value=True),
            patch.object(main, "route_parallel_enabled", return_value=True),
            patch.object(main, "_get_history_store", return_value=store),
            patch.dict(os.environ, {}, clear=False),
        ]
        for p in patches:
            p.start()
        self.addCleanup(lambda: [p.stop() for p in reversed(patches)])
        os.environ.pop("ANGINEER_CHAT_AUTH_REQUIRED", None)

        headers = {}
        if api_key is not None:
            middleware = _load_aichat_module("middleware.api_key_auth")
            patches_mw = patch.object(middleware, "lookup_key", return_value=api_key)
            patches_mw.start()
            self.addCleanup(patches_mw.stop)
            headers["X-API-Key"] = "test-key"
        if session_user is not None:
            # 登录态注入：中间件 resolve_session_principal 经 chat_auth.get_session_user 查票
            chat_auth = _load_aichat_module("chat_auth")
            patches_user = patch.object(chat_auth, "get_session_user", return_value=session_user)
            patches_user.start()
            self.addCleanup(patches_user.stop)
            headers["Authorization"] = "Bearer fake-session-token"

        client = TestClient(main.app)
        resp = client.post("/api/chat/agent", json=payload, headers=headers)
        return resp, captured

    def test_multi_library_flows_to_session(self):
        resp, captured = self._post({
            "query": "混凝土抗压强度怎么算",
            "library_ids": ["default"],
            "session_id": "chat-test-multi",
        })
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(captured.get("library_ids"), ["default"])
        # 首库回填：单值消费点（旧字段）不变
        self.assertEqual(captured.get("library_id"), "default")

    def test_legacy_body_single_library_unchanged(self):
        """兼容铁律 1：旧 body 只带 library_id → 集合收敛为单元素，行为与现状一致。"""
        models = _load_aichat_module("models.api_key")
        key = models.APIKey(id=1, user_name="tester", scope="chat", library_id="lib-a")
        resp, captured = self._post(
            {"query": "q", "library_id": "lib-a", "session_id": "chat-test-legacy"},
            api_key=key,
        )
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(captured.get("library_ids"), ["lib-a"])
        self.assertEqual(captured.get("library_id"), "lib-a")

    def test_anonymous_unbound_library_403(self):
        """兼容铁律 2：匿名请求非默认库（哪怕集合里混着 default）→ 403。"""
        resp, _ = self._post({
            "query": "q",
            "library_ids": ["default", "lib-secret"],
            "session_id": "chat-test-403",
        })
        self.assertEqual(resp.status_code, 403)

    def test_key_bound_multi_library_converges_to_bound(self):
        """Key 仍单库：多库请求收敛为绑定库（越权成员在鉴权层拒，见 D1 用例）。"""
        models = _load_aichat_module("models.api_key")
        key = models.APIKey(id=2, user_name="tester", scope="chat", library_id="lib-a")
        resp, captured = self._post(
            {"query": "q", "library_ids": ["lib-a"], "session_id": "chat-test-key"},
            api_key=key,
        )
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(captured.get("library_ids"), ["lib-a"])

    def test_key_bound_unbound_member_403(self):
        from fastapi import HTTPException  # noqa: F401  （语义标注：越权即拒）
        models = _load_aichat_module("models.api_key")
        key = models.APIKey(id=3, user_name="tester", scope="chat", library_id="lib-a")
        resp, _ = self._post(
            {"query": "q", "library_ids": ["lib-a", "lib-eve"], "session_id": "chat-test-key403"},
            api_key=key,
        )
        self.assertEqual(resp.status_code, 403)

    # ---- run_meta 落库键（评审 MINOR-1：chat-history append 消费 run_meta["library_ids"]）----

    def test_run_meta_carries_library_ids_single(self):
        """单库：run_meta 同时带单值 library_id 与集合 library_ids，且首项=单值。"""
        store = _CapturingStore()
        resp, _ = self._post(
            {"query": "q", "library_id": "default", "session_id": "chat-test-meta1"},
            store=store,
        )
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(len(store.run_metas), 1)
        meta = store.run_metas[0]
        self.assertEqual(meta.get("library_ids"), ["default"])
        self.assertEqual(meta.get("library_id"), "default")
        self.assertEqual(meta["library_ids"][0], meta["library_id"])

    def test_run_meta_carries_library_ids_multi(self):
        """多库（登录用户授权集内）：集合全量落库，首项=主库=单值字段（D8 回填）。"""
        user = SimpleNamespace(id=9, username="multi-u", is_active=True, is_admin=False,
                               library_ids=["libA", "libB"])
        store = _CapturingStore()
        resp, captured = self._post(
            {"query": "q", "library_ids": ["libA", "libB"], "session_id": "chat-test-meta2"},
            session_user=user,
            store=store,
        )
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(captured.get("library_ids"), ["libA", "libB"])
        self.assertEqual(len(store.run_metas), 1)
        meta = store.run_metas[0]
        self.assertEqual(meta.get("library_ids"), ["libA", "libB"])
        self.assertEqual(meta["library_ids"][0], meta["library_id"])

    def test_fire_speculative_receives_normalized_set(self):
        """I1：赌博式预检收到的集合 = 端点归一+鉴权后结果（与 get_agent_session 同源）。

        预检内部（route_pre）再按 is_multi_scope 同口径决定 knowledge_search 上浮，
        端点侧只负责把唯一真相集合递到（memo 键对齐的上游前提）。"""
        user = SimpleNamespace(id=10, username="multi-fire", is_active=True, is_admin=False,
                               library_ids=["libA", "libB"])
        resp, captured = self._post(
            {"query": "混凝土外加剂相容性", "library_ids": ["libA", "libB"],
             "session_id": "chat-test-fire"},
            session_user=user,
        )
        self.assertEqual(resp.status_code, 200)
        fire_kw = captured.get("fire_kwargs") or {}
        self.assertEqual(fire_kw.get("library_ids"), ["libA", "libB"])
        self.assertEqual(fire_kw.get("library_ids"), captured.get("library_ids"))


if __name__ == "__main__":
    unittest.main()
