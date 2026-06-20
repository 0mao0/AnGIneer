"""Embedding provider 单元测试。"""
import sys
import unittest
from pathlib import Path


DOCS_CORE_SRC = Path(__file__).resolve().parents[1] / "src"
if str(DOCS_CORE_SRC) not in sys.path:
    sys.path.insert(0, str(DOCS_CORE_SRC))


class EmbeddingProviderTests(unittest.TestCase):
    """验证 embedding provider 的 strict 与 fallback 行为。"""

    def test_dashscope_embeds_raises_when_strict_fallback_enabled_and_fails(self):
        """strict 模式下 DashScope 失败应抛出异常，不回退 hash。"""
        from docs_core.indexing.embedding_provider import (
            DashScopeEmbeddingProvider,
            HashEmbeddingProvider,
        )

        provider = DashScopeEmbeddingProvider(
            model="",
            api_key="",
            api_url="",
            fallback_provider=HashEmbeddingProvider(dimension=256),
        )
        provider._strict_fallback = True
        with self.assertRaises(RuntimeError):
            provider.embed_texts(["hello"])
