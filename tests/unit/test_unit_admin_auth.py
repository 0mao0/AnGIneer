"""管理端 require_admin 守卫测试。"""
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
from admin_auth import resolve_admin_session  # noqa: E402
from fastapi import HTTPException  # noqa: E402


class AdminAuthTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(lambda: __import__("shutil").rmtree(self.tmp, ignore_errors=True))
        patcher = patch.object(user_model, "DB_PATH", os.path.join(self.tmp, "users.sqlite"))
        patcher.start()
        self.addCleanup(patcher.stop)
        user_model.init_db()

    def _req(self, token=""):
        req = MagicMock()
        req.headers = {"Authorization": f"Bearer {token}"} if token else {}
        return req

    def test_no_token_401(self):
        with self.assertRaises(HTTPException) as ctx:
            resolve_admin_session(self._req())
        self.assertEqual(ctx.exception.status_code, 401)

    def test_normal_user_403(self):
        user = user_model.create_user("alice", "Alice", "secret123", ["lib-a"])
        token = user_model.create_session(user.id)
        with self.assertRaises(HTTPException) as ctx:
            resolve_admin_session(self._req(token))
        self.assertEqual(ctx.exception.status_code, 403)

    def test_admin_ok(self):
        user = user_model.create_user("boss", "Boss", "secret123", ["lib-a"], is_admin=True)
        token = user_model.create_session(user.id)
        resolved = resolve_admin_session(self._req(token))
        self.assertEqual(resolved.username, "boss")

    def test_admin_routers_have_dependency(self):
        from users_routes import router as users_router
        from api_key_routes import router as api_key_router
        self.assertTrue(users_router.dependencies)
        self.assertTrue(api_key_router.dependencies)


if __name__ == "__main__":
    unittest.main()
