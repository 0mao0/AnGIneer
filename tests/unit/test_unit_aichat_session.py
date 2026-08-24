"""aichat-api 会话通道与多库校验测试。"""
import os
import sys
import tempfile
import unittest
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../../services/aichat-api")))
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../../services/ai-inference/src")))
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../../services/angineer-core/src")))
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../../services/sop-core/src")))
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../../services/docs-core/src")))

import models.user as user_model  # noqa: E402
from fastapi import HTTPException  # noqa: E402


class AichatSessionTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(lambda: __import__("shutil").rmtree(self.tmp, ignore_errors=True))
        patcher = patch.object(user_model, "DB_PATH", os.path.join(self.tmp, "users.sqlite"))
        patcher.start()
        self.addCleanup(patcher.stop)
        user_model.init_db()
        self.user = user_model.create_user("alice", "Alice", "secret123", ["lib-a", "lib-b"])
        self.token = user_model.create_session(self.user.id)

    def _state(self):
        state = MagicMock()
        state.bound_library_ids = set(self.user.library_ids)
        state.bound_library_id = "lib-a"
        return state

    def test_enforce_session_library_set(self):
        from main import enforce_bound_library
        state = self._state()
        self.assertEqual(enforce_bound_library(state, "lib-b"), "lib-b")
        self.assertEqual(enforce_bound_library(state, "default"), "lib-a")
        self.assertEqual(enforce_bound_library(state, ""), "lib-a")
        with self.assertRaises(HTTPException) as ctx:
            enforce_bound_library(state, "lib-other")
        self.assertEqual(ctx.exception.status_code, 403)

    def test_enforce_key_library_still_works(self):
        from main import enforce_bound_library
        state = MagicMock()
        state.bound_library_ids = None
        state.bound_library_id = "lib-x"
        self.assertEqual(enforce_bound_library(state, "default"), "lib-x")
        self.assertEqual(enforce_bound_library(state, "lib-x"), "lib-x")
        with self.assertRaises(HTTPException):
            enforce_bound_library(state, "lib-y")

    def test_resolve_session_in_middleware(self):
        from middleware.api_key_auth import resolve_session_principal
        req = MagicMock()
        req.headers.get.return_value = f"Bearer {self.token}"
        self.assertTrue(resolve_session_principal(req))
        self.assertEqual(req.state.bound_library_id, "lib-a")
        self.assertEqual(req.state.bound_library_ids, {"lib-a", "lib-b"})


if __name__ == "__main__":
    unittest.main()
