"""P2 测试：租户身份闭环——/me 返回绑定库并自动建库，建 key 空库自动生成。"""
import asyncio
import os
import sys
import unittest
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../../services/docs-api")))
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../../services/docs-core/src")))
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../../services/angineer-core/src")))
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../../services/tree-core/src")))

import models.api_key as api_key_model  # noqa: E402
from models.api_key import APIKey  # noqa: E402
from models.v1_responses import MeResponse  # noqa: E402


class MeEndpointTests(unittest.TestCase):
    def _me(self, key_info):
        from routes.v1 import auth

        req = MagicMock()
        req.state.api_key_info = key_info
        return asyncio.run(auth.auth_me(req))

    def test_bound_key_returns_library_and_ensures_it(self):
        from routes.v1 import auth

        key = APIKey(id=1, user_name="alice", scope="doc", library_id="lib-alice",
                     key_prefix="ag_****", email="", created_at="now")
        with patch.object(auth, "get_docs_service") as mock_ks:
            mock_ks.return_value.get_library.return_value = None
            resp = self._me(key)

        self.assertEqual(resp.library_id, "lib-alice")
        self.assertTrue(resp.library_exists)
        mock_ks.return_value.create_library.assert_called_once()
        args = mock_ks.return_value.create_library.call_args.args
        self.assertEqual(args[0], "lib-alice")

    def test_bound_key_existing_library_no_create(self):
        from routes.v1 import auth

        key = APIKey(id=1, user_name="alice", scope="doc", library_id="lib-alice",
                     key_prefix="ag_****", email="", created_at="now")
        with patch.object(auth, "get_docs_service") as mock_ks:
            mock_ks.return_value.get_library.return_value = MagicMock()
            resp = self._me(key)

        self.assertTrue(resp.library_exists)
        mock_ks.return_value.create_library.assert_not_called()

    def test_unbound_key_rejected(self):
        """开发期收紧：未绑定库的旧 key 调 /me 直接 403。"""
        from fastapi import HTTPException

        key = APIKey(id=2, user_name="legacy", scope="both", library_id="",
                     key_prefix="ag_****", email="", created_at="now")
        with self.assertRaises(HTTPException) as ctx:
            self._me(key)
        self.assertEqual(ctx.exception.status_code, 403)


class AutoBindKeyTests(unittest.TestCase):
    def test_create_key_with_empty_library_generates_one(self):
        import tempfile

        tmp_dir = tempfile.mkdtemp()
        self.addCleanup(lambda: __import__("shutil").rmtree(tmp_dir, ignore_errors=True))
        with patch.object(api_key_model, "DB_PATH", os.path.join(tmp_dir, "k.sqlite")):
            raw, key = api_key_model.generate_key("alice", library_id="")
            loaded = api_key_model.lookup_key(raw)
        self.assertTrue(key.library_id.startswith("lib-"))
        self.assertEqual(loaded.library_id, key.library_id)

    def test_create_key_with_explicit_library_keeps_it(self):
        import tempfile

        tmp_dir = tempfile.mkdtemp()
        self.addCleanup(lambda: __import__("shutil").rmtree(tmp_dir, ignore_errors=True))
        with patch.object(api_key_model, "DB_PATH", os.path.join(tmp_dir, "k.sqlite")):
            raw, key = api_key_model.generate_key("bob", library_id="lib-bob")
        self.assertEqual(key.library_id, "lib-bob")


if __name__ == "__main__":
    unittest.main()
