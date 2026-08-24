"""账号登录/登出/me 测试。"""
import asyncio
import os
import sys
import tempfile
import unittest
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../../services/docs-api")))
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../../services/docs-core/src")))
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../../services/angineer-core/src")))
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../../services/tree-core/src")))

import models.user as user_model  # noqa: E402
from fastapi import HTTPException  # noqa: E402


class LoginTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(lambda: __import__("shutil").rmtree(self.tmp, ignore_errors=True))
        patcher = patch.object(user_model, "DB_PATH", os.path.join(self.tmp, "users.sqlite"))
        patcher.start()
        self.addCleanup(patcher.stop)
        user_model.init_db()
        self.user = user_model.create_user("alice", "Alice", "secret123", ["lib-a"])

    def _login(self, username="alice", password="secret123"):
        from routes.v1 import auth
        req = MagicMock()
        req.username = username
        req.password = password
        return asyncio.run(auth.auth_login(req))

    def test_login_success_returns_token_and_libraries(self):
        resp = self._login()
        self.assertTrue(resp.token)
        self.assertEqual(resp.user.username, "alice")
        self.assertEqual(resp.user.libraries, ["lib-a"])
        self.assertIsNotNone(user_model.get_session_user(resp.token))

    def test_login_wrong_password_rejected(self):
        with self.assertRaises(HTTPException) as ctx:
            self._login(password="wrongpass")
        self.assertEqual(ctx.exception.status_code, 401)

    def test_login_unknown_user_rejected(self):
        with self.assertRaises(HTTPException) as ctx:
            self._login(username="nobody")
        self.assertEqual(ctx.exception.status_code, 401)

    def test_login_disabled_user_rejected(self):
        user_model.set_user_active(self.user.id, False)
        with self.assertRaises(HTTPException) as ctx:
            self._login()
        self.assertEqual(ctx.exception.status_code, 401)

    def test_logout_invalidates_session(self):
        resp = self._login()
        from routes.v1 import auth
        req = MagicMock()
        req.state.session_token_raw = resp.token
        asyncio.run(auth.auth_logout(req))
        self.assertIsNone(user_model.get_session_user(resp.token))

    def test_me_session_identity_filters_missing_libraries(self):
        from routes.v1 import auth
        req = MagicMock()
        req.state.session_user = self.user
        with patch.object(auth, "get_docs_service") as mock_ks:
            def fake_get_library(lid):
                return MagicMock() if lid == "lib-a" else None
            mock_ks.return_value.get_library.side_effect = fake_get_library
            resp = asyncio.run(auth.auth_me(req))
        self.assertEqual(resp.username, "alice")
        self.assertEqual(resp.libraries, ["lib-a"])
        self.assertEqual(resp.default_library, "lib-a")


if __name__ == "__main__":
    unittest.main()
