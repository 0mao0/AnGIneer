"""Embedding provider 稳定性回归测试。"""

import sys
import unittest
from pathlib import Path
from unittest.mock import patch

import requests


DOCS_CORE_SRC = Path(__file__).resolve().parents[1] / "src"
if str(DOCS_CORE_SRC) not in sys.path:
    sys.path.insert(0, str(DOCS_CORE_SRC))

from docs_core.indexing.embedding_provider import DashScopeEmbeddingProvider


class DashScopeEmbeddingProviderTests(unittest.TestCase):
    """验证 502 时走一次回退并暴露 runtime flag。"""

    def test_embed_texts_sets_runtime_flag_when_dashscope_502(self) -> None:
        """DashScope 失败时应回退到 hash embedding 并记录标志。"""
        provider = DashScopeEmbeddingProvider(
            model="text-embedding-v3",
            api_key="demo",
            api_url="https://example.com",
        )
        with patch("requests.post") as post:
            post.return_value.raise_for_status.side_effect = requests.HTTPError("502 Server Error")
            vectors = provider.embed_texts(["hello"])

        self.assertEqual(len(vectors), 1)
        self.assertIn("embedding_hash_fallback", provider.runtime_flags)


if __name__ == "__main__":
    unittest.main()
