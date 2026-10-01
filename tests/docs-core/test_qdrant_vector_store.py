"""QdrantVectorStore 客户端构造单测：trust_env=False 必须透传给 httpx（防系统代理劫持本地流量）。"""
import os
import sys
import types
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../../services/docs-core/src")))

from docs_core.step06_vectors.qdrant_vector_store import QdrantVectorStore  # noqa: E402


class QdrantClientKwargsTests(unittest.TestCase):
    def test_client_disables_trust_env(self):
        captured = {}

        class FakeClient:
            def __init__(self, **kwargs):
                captured.update(kwargs)

        fake = types.ModuleType("qdrant_client")
        fake.QdrantClient = FakeClient
        with patch.dict(sys.modules, {"qdrant_client": fake}):
            QdrantVectorStore(url="http://localhost:6333")._get_client()
        self.assertIs(captured.get("trust_env"), False)
        self.assertEqual(captured.get("url"), "http://localhost:6333")


if __name__ == "__main__":
    unittest.main()
