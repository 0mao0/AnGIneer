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
        # 钉住 V1：宿主 .env 设了 ANGINEER_KB_SUBSCRIPTION_V2=1 时 create/update 走 v2 分支，
        # MagicMock 的 direct_library_ids 真值但迭代为空 → set_user_access(id, [], []) 抹掉镜像。
        # v2 形态另有专测显式开开关验形状（test_create_writes_v2_access）。
        v2 = patch("users_routes.subscription_v2_enabled", return_value=False)
        v2.start()
        self.addCleanup(v2.stop)

    def test_create_writes_v2_access(self):
        """v2 开关打开时的形状：组订阅+直选按原样透传 set_user_access（镜像由其统一回写）。"""
        from users_routes import create_user_route
        req = MagicMock()
        req.username = "dave"
        req.display_name = "Dave"
        req.password = "secret123"
        req.library_ids = ["lib-a"]
        req.is_admin = False
        req.group_subscriptions = [{"group": "g1"}]
        req.direct_library_ids = ["lib-a"]
        with patch("users_routes.subscription_v2_enabled", return_value=True), \
                patch("users_routes.get_docs_service") as mock_ks, \
                patch("users_routes.set_user_access") as mock_set:
            mock_ks.return_value._known_group.return_value = True
            mock_ks.return_value.get_library.return_value = MagicMock()
            asyncio.run(create_user_route(req))
        _user_id, subs, direct = mock_set.call_args[0]
        self.assertEqual(subs, [{"group": "g1"}])
        self.assertEqual(direct, ["lib-a"])

    def _create(self, library_ids=("lib-a",), is_admin=False):
        from users_routes import create_user_route
        req = MagicMock()
        req.username = "alice"
        req.display_name = "Alice"
        req.password = "secret123"
        req.library_ids = list(library_ids)
        req.is_admin = is_admin
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

    def test_create_with_is_admin_flag(self):
        created = self._create(is_admin=True)
        self.assertTrue(created.is_admin)

    def test_update_is_admin_flag(self):
        from users_routes import update_user_route
        created = self._create()
        req = MagicMock()
        req.display_name = "Alice2"
        req.library_ids = ["lib-a"]
        req.is_admin = True
        with patch("users_routes.get_docs_service") as mock_ks:
            mock_ks.return_value.get_library.return_value = MagicMock()
            asyncio.run(update_user_route(created.id, req))
        loaded = user_model.get_user_by_id(created.id)
        self.assertTrue(loaded.is_admin)


if __name__ == "__main__":
    unittest.main()
