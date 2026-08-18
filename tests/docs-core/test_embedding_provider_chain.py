# -*- coding: utf-8 -*-
"""embedding 多 provider 自动降级链单测：顺序降级、维度校验、严格模式、hash 标记。"""
import os
import sys
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../../services/docs-core/src")))

from docs_core.step06_vectors.embedding_provider import (  # noqa: E402
    ChainedEmbeddingProvider,
    HashEmbeddingProvider,
    create_default_embedding_provider,
)


class _FakeProvider:
    def __init__(self, name, embeddings=None, flags=None, error=None):
        self.name = name
        self.embeddings = embeddings or []
        self.flags = flags or []
        self.error = error
        self.runtime_flags = []
        self.calls = 0

    def embed_texts(self, texts):
        self.calls += 1
        self.runtime_flags = list(self.flags)
        if self.error:
            raise self.error
        return [list(item) for item in self.embeddings]


class ChainedEmbeddingProviderTests(unittest.TestCase):
    def test_falls_through_failing_tiers_and_propagates_flags(self):
        ok = _FakeProvider("ok", embeddings=[[0.1, 0.2]], flags=["embedding_hash_fallback"])
        chain = ChainedEmbeddingProvider(
            [_FakeProvider("bad", error=RuntimeError("boom")), ok],
            expected_dimension=2,
        )
        out = chain.embed_texts(["文本"])
        self.assertEqual(out, [[0.1, 0.2]])
        self.assertEqual(chain.runtime_flags, ["embedding_hash_fallback"])
        self.assertEqual(chain.dimension, 2)

    def test_skips_dimension_mismatch_tier(self):
        wrong_dim = _FakeProvider("wrong-dim", embeddings=[[0.1, 0.2, 0.3]])
        ok = _FakeProvider("ok", embeddings=[[0.4, 0.5]])
        chain = ChainedEmbeddingProvider([wrong_dim, ok], expected_dimension=2)
        out = chain.embed_texts(["文本"])
        self.assertEqual(len(out[0]), 2)
        self.assertEqual(wrong_dim.calls, 1)
        self.assertEqual(ok.calls, 1)

    def test_all_fail_raises(self):
        chain = ChainedEmbeddingProvider(
            [_FakeProvider("a", error=RuntimeError("x")), _FakeProvider("b", error=RuntimeError("y"))]
        )
        with self.assertRaises(RuntimeError):
            chain.embed_texts(["文本"])

    def test_strict_mode_raises_before_secondary(self):
        ok = _FakeProvider("ok", embeddings=[[0.1, 0.2]])
        chain = ChainedEmbeddingProvider(
            [_FakeProvider("bad", error=RuntimeError("x")), ok],
            strict_fallback=True,
        )
        with self.assertRaises(RuntimeError):
            chain.embed_texts(["文本"])
        self.assertEqual(ok.calls, 0)

    def test_hash_provider_marks_fallback(self):
        provider = HashEmbeddingProvider(dimension=4)
        provider.embed_texts(["斜坡堤"])
        self.assertEqual(provider.runtime_flags, ["embedding_hash_fallback"])

    def test_default_provider_name_compat(self):
        provider = create_default_embedding_provider()
        self.assertIn(provider.name, {"dashscope_embedding_v1", "hash_embedding_v1"})


if __name__ == "__main__":
    unittest.main()
