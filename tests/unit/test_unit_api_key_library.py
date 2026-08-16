"""P1 测试：API key 绑定 library_id + 中间件服务端强制 scope（防串库）。

语义：library_id='' 为未绑定（向后兼容，行为不变）；绑定后 query 缺失自动注入、
显式传不一致直接 403。
"""
import os
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../../services/docs-api")))
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../../services/docs-core/src")))
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../../services/angineer-core/src")))
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../../services/tree-core/src")))

import models.api_key as api_key_model  # noqa: E402
from models.api_key import APIKey  # noqa: E402


class ApiKeyLibraryBindingTests(unittest.TestCase):
    def setUp(self):
        import tempfile

        self.tmp_dir = tempfile.mkdtemp()
        self.addCleanup(lambda: __import__("shutil").rmtree(self.tmp_dir, ignore_errors=True))
        self.db_patch = patch.object(
            api_key_model, "DB_PATH", os.path.join(self.tmp_dir, "api_keys.sqlite")
        )
        self.db_patch.start()
        self.addCleanup(self.db_patch.stop)

    def test_generate_key_with_library_binding(self):
        raw, key = api_key_model.generate_key("alice", library_id="lib-alice")
        self.assertEqual(key.library_id, "lib-alice")
        loaded = api_key_model.lookup_key(raw)
        self.assertEqual(loaded.library_id, "lib-alice")

    def test_generate_key_auto_binds_library_when_empty(self):
        """P2 起：新 key 空 library_id = 自动生成租户库（lib-xxx），不再产生未绑定 key。"""
        raw, key = api_key_model.generate_key("legacy")
        self.assertTrue(key.library_id.startswith("lib-"))
        loaded = api_key_model.lookup_key(raw)
        self.assertEqual(loaded.library_id, key.library_id)

    def test_legacy_table_migrates_with_empty_library_id(self):
        import sqlite3

        conn = sqlite3.connect(api_key_model.DB_PATH)
        conn.execute(
            """CREATE TABLE api_keys (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                key_hash TEXT NOT NULL UNIQUE, key_prefix TEXT NOT NULL,
                user_name TEXT NOT NULL DEFAULT '', email TEXT NOT NULL DEFAULT '',
                is_active INTEGER NOT NULL DEFAULT 1, rate_limit_per_minute INTEGER NOT NULL DEFAULT 60,
                created_at TEXT NOT NULL, last_used_at TEXT, scope TEXT NOT NULL DEFAULT 'both'
            )"""
        )
        conn.commit()
        conn.close()

        api_key_model.init_db()
        raw, key = api_key_model.generate_key("bob")
        # 旧表迁移后新 key 同样自动绑定租户库
        self.assertTrue(key.library_id.startswith("lib-"))


class MiddlewareEnforcementTests(unittest.TestCase):
    def _make_client(self):
        from fastapi import FastAPI, Request
        from fastapi.testclient import TestClient

        from middleware.api_key_auth import APIKeyAuthMiddleware

        app = FastAPI()
        app.add_middleware(APIKeyAuthMiddleware, scope="doc")

        @app.get("/api/v1/ping")
        def ping(request: Request):
            return {"library_id": request.query_params.get("library_id", "")}

        return TestClient(app)

    def _bound_key(self, library_id="lib-alice"):
        return APIKey(id=1, user_name="alice", scope="doc", library_id=library_id)

    def test_bound_key_injects_missing_library_id(self):
        client = self._make_client()
        with patch("middleware.api_key_auth.lookup_key", return_value=self._bound_key()):
            resp = client.get("/api/v1/ping", headers={"X-API-Key": "k"})
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["library_id"], "lib-alice")

    def test_bound_key_rejects_mismatched_library_id(self):
        client = self._make_client()
        with patch("middleware.api_key_auth.lookup_key", return_value=self._bound_key()):
            resp = client.get(
                "/api/v1/ping?library_id=lib-eve", headers={"X-API-Key": "k"}
            )
        self.assertEqual(resp.status_code, 403)

    def test_bound_key_accepts_matching_library_id(self):
        client = self._make_client()
        with patch("middleware.api_key_auth.lookup_key", return_value=self._bound_key()):
            resp = client.get(
                "/api/v1/ping?library_id=lib-alice", headers={"X-API-Key": "k"}
            )
        self.assertEqual(resp.status_code, 200)

    def test_unbound_key_rejected(self):
        """开发期收紧：未绑定库的旧 key 直接拒绝，不再兼容放行。"""
        client = self._make_client()
        with patch(
            "middleware.api_key_auth.lookup_key",
            return_value=APIKey(id=2, user_name="legacy", scope="both", library_id=""),
        ):
            resp = client.get(
                "/api/v1/ping?library_id=lib-anything", headers={"X-API-Key": "k"}
            )
        self.assertEqual(resp.status_code, 403)


if __name__ == "__main__":
    unittest.main()
