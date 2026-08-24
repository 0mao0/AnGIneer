"""管理端用户接口测试。"""
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


class UsersRoutesTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(lambda: __import__("shutil").rmtree(self.tmp, ignore_errors=True))
        patcher = patch.object(user_model, "DB_PATH", os.path.join(self.tmp, "users.sqlite"))
        patcher.start()
        self.addCleanup(patcher.stop)
        user_model.init_db()

    def _create(self, library_ids=("lib-a",)):
        from users_routes import create_user_route
        req = MagicMock()
        req.username = "alice"
        req.display_name = "Alice"
        req.password = "secret123"
        req.library_ids = list(library_ids)
        with patch("users_routes.get_docs_service") as mock_ks:
            mock_ks.return_value.get_library.return_value = MagicMock()
            return asyncio.run(create_user_route(req))

    def test_create_requires_existing_library(self):
        from users_routes import create_user_route
        req = MagicMock()
        req.username = "bob"
        req.display_name = "Bob"
        req.password = "secret123"
        req.library_ids = ["lib-nope"]
        with patch("users_routes.get_docs_service") as mock_ks:
            mock_ks.return_value.get_library.return_value = None
            with self.assertRaises(HTTPException) as ctx:
                asyncio.run(create_user_route(req))
        self.assertEqual(ctx.exception.status_code, 400)

    def test_create_and_list(self):
        from users_routes import list_users_route
        created = self._create()
        self.assertEqual(created.username, "alice")
        items = asyncio.run(list_users_route())
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0].library_ids, ["lib-a"])

    def test_reset_password_invalidates_sessions(self):
        user = user_model.create_user("carol", "Carol", "secret123", ["lib-a"])
        token = user_model.create_session(user.id)
        from users_routes import reset_password_route
        req = MagicMock()
        req.password = "newsecret456"
        asyncio.run(reset_password_route(user.id, req))
        self.assertIsNone(user_model.get_session_user(token))


if __name__ == "__main__":
    unittest.main()
