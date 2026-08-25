"""用户/会话模型测试（账号密码登录）。"""
import os
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../../services/docs-api")))
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../../services/docs-core/src")))

import models.user as user_model  # noqa: E402


class UserModelTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(lambda: __import__("shutil").rmtree(self.tmp, ignore_errors=True))
        patcher = patch.object(user_model, "DB_PATH", os.path.join(self.tmp, "users.sqlite"))
        patcher.start()
        self.addCleanup(patcher.stop)
        user_model.init_db()

    def test_create_and_lookup(self):
        user = user_model.create_user("alice", "Alice", "secret123", ["lib-a", "lib-b"])
        loaded = user_model.get_user_by_username("alice")
        self.assertEqual(loaded.id, user.id)
        self.assertEqual(loaded.library_ids, ["lib-a", "lib-b"])
        self.assertTrue(loaded.password_hash.startswith("pbkdf2$"))
        self.assertNotIn("secret123", loaded.password_hash)
        self.assertTrue(user_model.verify_password("secret123", loaded.password_hash))
        self.assertFalse(user_model.verify_password("wrong", loaded.password_hash))

    def test_duplicate_username_rejected(self):
        user_model.create_user("bob", "Bob", "secret123")
        with self.assertRaises(ValueError):
            user_model.create_user("bob", "Bob2", "secret456")

    def test_short_password_rejected(self):
        with self.assertRaises(ValueError):
            user_model.create_user("carol", "Carol", "12345")

    def test_list_users_includes_libraries(self):
        user_model.create_user("dave", "Dave", "secret123", ["lib-x"])
        users = user_model.list_users()
        self.assertEqual(len(users), 1)
        self.assertEqual(users[0].library_ids, ["lib-x"])

    def test_update_user(self):
        user = user_model.create_user("erin", "Erin", "secret123", ["lib-a"])
        ok = user_model.update_user(user.id, display_name="Erin2", library_ids=["lib-b", "lib-c"])
        self.assertTrue(ok)
        loaded = user_model.get_user_by_id(user.id)
        self.assertEqual(loaded.display_name, "Erin2")
        self.assertEqual(loaded.library_ids, ["lib-b", "lib-c"])

    def test_set_password_invalidates_sessions(self):
        user = user_model.create_user("frank", "Frank", "secret123")
        token = user_model.create_session(user.id)
        self.assertIsNotNone(user_model.get_session_user(token))
        user_model.set_password(user.id, "newsecret456")
        self.assertIsNone(user_model.get_session_user(token))
        self.assertTrue(user_model.verify_password("newsecret456", user_model.get_user_by_id(user.id).password_hash))

    def test_deactivate_invalidates_sessions(self):
        user = user_model.create_user("grace", "Grace", "secret123")
        token = user_model.create_session(user.id)
        user_model.set_user_active(user.id, False)
        self.assertIsNone(user_model.get_session_user(token))
        self.assertFalse(user_model.get_user_by_id(user.id).is_active)

    def test_delete_user_cascades(self):
        user = user_model.create_user("heidi", "Heidi", "secret123", ["lib-a"])
        token = user_model.create_session(user.id)
        user_model.delete_user(user.id)
        self.assertIsNone(user_model.get_user_by_id(user.id))
        self.assertIsNone(user_model.get_session_user(token))

    def test_session_expiry_and_logout(self):
        user = user_model.create_user("ivan", "Ivan", "secret123")
        token = user_model.create_session(user.id)
        conn = user_model._get_conn()
        conn.execute("UPDATE sessions SET expires_at = ?", ("2000-01-01T00:00:00+00:00",))
        conn.commit()
        conn.close()
        self.assertIsNone(user_model.get_session_user(token))
        token2 = user_model.create_session(user.id)
        self.assertIsNotNone(user_model.get_session_user(token2))
        user_model.delete_session(token2)
        self.assertIsNone(user_model.get_session_user(token2))

    def test_is_admin_default_false(self):
        user = user_model.create_user("ivan2", "Ivan", "secret123", ["lib-a"])
        self.assertFalse(user.is_admin)
        self.assertFalse(user_model.get_user_by_username("ivan2").is_admin)

    def test_create_user_with_is_admin(self):
        user = user_model.create_user("judy", "Judy", "secret123", ["lib-a"], is_admin=True)
        self.assertTrue(user.is_admin)
        self.assertTrue(user_model.get_user_by_username("judy").is_admin)

    def test_init_db_adds_is_admin_column_to_legacy_table(self):
        conn = user_model._get_conn()
        conn.execute("DROP TABLE sessions")
        conn.execute("DROP TABLE user_libraries")
        conn.execute("DROP TABLE users")
        conn.execute(
            """
            CREATE TABLE users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT NOT NULL UNIQUE,
                display_name TEXT NOT NULL DEFAULT '',
                password_hash TEXT NOT NULL,
                is_active INTEGER NOT NULL DEFAULT 1,
                created_at TEXT NOT NULL,
                last_login_at TEXT
            )
            """
        )
        conn.commit()
        conn.close()
        user_model.init_db()
        user = user_model.create_user("kate", "Kate", "secret123")
        self.assertFalse(user.is_admin)
        user_model.init_db()  # 幂等：重复迁移不报错

    def test_ensure_admin_creates_from_env(self):
        with patch.dict(os.environ, {"ADMIN_USER": "boss", "ADMIN_PASSWORD": "boss123456"}, clear=False):
            user = user_model.ensure_admin_user()
        self.assertIsNotNone(user)
        self.assertEqual(user.username, "boss")
        self.assertTrue(user.is_admin)
        self.assertEqual(user.library_ids, ["default"])

    def test_ensure_admin_promotes_existing(self):
        user = user_model.create_user("boss", "Boss", "secret123")
        self.assertFalse(user.is_admin)
        with patch.dict(os.environ, {"ADMIN_USER": "boss", "ADMIN_PASSWORD": "boss123456"}, clear=False):
            promoted = user_model.ensure_admin_user()
        self.assertTrue(promoted.is_admin)

    def test_ensure_admin_missing_password_no_crash(self):
        with patch.dict(os.environ, {"ADMIN_USER": "boss", "ADMIN_PASSWORD": ""}, clear=False):
            self.assertIsNone(user_model.ensure_admin_user())

    def test_ensure_admin_no_env_noop(self):
        with patch.dict(os.environ, {"ADMIN_USER": "", "ADMIN_PASSWORD": ""}, clear=False):
            self.assertIsNone(user_model.ensure_admin_user())


if __name__ == "__main__":
    unittest.main()
