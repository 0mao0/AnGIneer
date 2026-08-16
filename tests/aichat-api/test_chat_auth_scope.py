"""P1.5 测试：aichat-api /api/chat/* 的 API key 鉴权与绑定 library_id 服务端强制。

兼容语义：未提供 X-API-Key 时放行（存量单租户部署不受影响）；
ANGINEER_CHAT_AUTH_REQUIRED=true 时无 key 直接 401；绑定 key 的请求体 library_id 被强制。
"""
import importlib
import os
import sys
import unittest
from unittest.mock import patch

_AICHAT_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "../../services/aichat-api"))
sys.path.append(_AICHAT_DIR)
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../../services/angineer-core/src")))


def _load_aichat_module(name):
    """按归属加载 aichat-api 顶层模块：强制目录置顶 + 逐级弹出非 aichat 归属的父包。

    混跑时 docs-api 的 models/middleware/main 同名包可能顶占 sys.path 或 sys.modules，
    仅在 path 中不够，必须保证在 0 位且父包归属正确。
    """
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
    # 防御：清掉 sys.modules 中的 None 占位（导入中断标记），避免同名单元测试绑定到幽灵对象
    for name, mod in list(sys.modules.items()):
        if mod is None:
            sys.modules.pop(name, None)


def _make_client(middleware_module):
    from fastapi import FastAPI, Request
    from fastapi.testclient import TestClient

    app = FastAPI()
    app.add_middleware(middleware_module.APIKeyAuthMiddleware, scope="chat")

    @app.post("/api/chat/agent")
    def chat(request: Request):
        return {"bound": getattr(request.state, "bound_library_id", "")}

    return TestClient(app)


class ChatMiddlewareTests(unittest.TestCase):
    def tearDown(self):
        _unload_aichat_modules()

    def test_no_key_passes_through_by_default(self):
        mw = _load_aichat_module("middleware.api_key_auth")
        client = _make_client(mw)
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("ANGINEER_CHAT_AUTH_REQUIRED", None)
            resp = client.post("/api/chat/agent", json={"query": "q"})
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["bound"], "")

    def test_auth_required_env_rejects_missing_key(self):
        mw = _load_aichat_module("middleware.api_key_auth")
        client = _make_client(mw)
        with patch.dict(os.environ, {"ANGINEER_CHAT_AUTH_REQUIRED": "true"}):
            resp = client.post("/api/chat/agent", json={"query": "q"})
        self.assertEqual(resp.status_code, 401)

    def test_invalid_key_rejected(self):
        mw = _load_aichat_module("middleware.api_key_auth")
        client = _make_client(mw)
        with patch.object(mw, "lookup_key", return_value=None):
            resp = client.post("/api/chat/agent", json={"query": "q"}, headers={"X-API-Key": "bad"})
        self.assertEqual(resp.status_code, 403)

    def test_bound_key_sets_state(self):
        mw = _load_aichat_module("middleware.api_key_auth")
        models = _load_aichat_module("models.api_key")
        key = models.APIKey(id=1, user_name="alice", scope="chat", library_id="lib-alice")
        client = _make_client(mw)
        with patch.object(mw, "lookup_key", return_value=key):
            resp = client.post("/api/chat/agent", json={"query": "q"}, headers={"X-API-Key": "k"})
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["bound"], "lib-alice")

    def test_lookup_key_survives_migrated_db(self):
        """DB 已有 library_id 列时，aichat 旧 dataclass 不得 TypeError。"""
        import tempfile

        models = _load_aichat_module("models.api_key")
        tmp_dir = tempfile.mkdtemp()
        self.addCleanup(lambda: __import__("shutil").rmtree(tmp_dir, ignore_errors=True))
        with patch.object(models, "DB_PATH", os.path.join(tmp_dir, "api_keys.sqlite")):
            raw, _ = models.generate_key("alice", library_id="lib-alice")
            loaded = models.lookup_key(raw)
        self.assertEqual(loaded.library_id, "lib-alice")


class EnforceBoundLibraryTests(unittest.TestCase):
    def tearDown(self):
        _unload_aichat_modules()

    def _enforce(self, bound, requested):
        main = _load_aichat_module("main")
        return main.enforce_bound_library(bound, requested)

    def test_unbound_passes_requested(self):
        self.assertEqual(self._enforce("", "lib-any"), "lib-any")
        self.assertEqual(self._enforce("", ""), "default")

    def test_bound_overrides_default_or_empty(self):
        self.assertEqual(self._enforce("lib-alice", "default"), "lib-alice")
        self.assertEqual(self._enforce("lib-alice", ""), "lib-alice")

    def test_bound_matching_passes(self):
        self.assertEqual(self._enforce("lib-alice", "lib-alice"), "lib-alice")

    def test_bound_conflict_raises_403(self):
        from fastapi import HTTPException

        with self.assertRaises(HTTPException) as ctx:
            self._enforce("lib-alice", "lib-eve")
        self.assertEqual(ctx.exception.status_code, 403)


if __name__ == "__main__":
    unittest.main()
