"""docs-api 中间件会话通道测试。"""
import importlib.util
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


def _load_docs_middleware():
    path = os.path.abspath(os.path.join(
        os.path.dirname(__file__), "../../services/docs-api/middleware/api_key_auth.py"
    ))
    spec = importlib.util.spec_from_file_location("docs_api_middleware", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


middleware_mod = _load_docs_middleware()


class SessionMiddlewareTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(lambda: __import__("shutil").rmtree(self.tmp, ignore_errors=True))
        patcher = patch.object(user_model, "DB_PATH", os.path.join(self.tmp, "users.sqlite"))
        patcher.start()
        self.addCleanup(patcher.stop)
        user_model.init_db()
        self.user = user_model.create_user("alice", "Alice", "secret123", ["lib-a", "lib-b"])
        self.token = user_model.create_session(self.user.id)

    def _req(self, raw_token):
        req = MagicMock()
        req.headers.get.return_value = f"Bearer {raw_token}"
        req.query_params = {}
        return req

    def test_resolve_session_sets_user_and_token(self):
        req = self._req(self.token)
        result = middleware_mod.resolve_session_principal(req)
        self.assertTrue(result)
        self.assertEqual(req.state.session_user.id, self.user.id)
        self.assertEqual(req.state.session_token_raw, self.token)

    def test_resolve_session_invalid_token_fails(self):
        req = self._req("bad-token")
        self.assertFalse(middleware_mod.resolve_session_principal(req))

    def test_library_membership_checked(self):
        req = self._req(self.token)
        middleware_mod.resolve_session_principal(req)
        self.assertEqual(middleware_mod.authorize_library(req, "lib-b"), "lib-b")
        self.assertEqual(middleware_mod.authorize_library(req, ""), "lib-a")
        self.assertIsNone(middleware_mod.authorize_library(req, "lib-other"))


if __name__ == "__main__":
    unittest.main()
