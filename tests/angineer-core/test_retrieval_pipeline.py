"""retrieval_pipeline 存活函数单测：rerank 入口与拒答校验。"""
import os
import sys
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../../services/angineer-core/src")))
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../../services/docs-core/src")))
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../../services/ai-inference/src")))

from angineer_core.retrieval_pipeline import (  # noqa: E402
    has_unsupported_reference,
    rerank_candidates,
)


class RetrievalPipelineSharedTests(unittest.TestCase):
    def test_has_unsupported_reference_shared(self):
        self.assertTrue(has_unsupported_reference("依据 JTS 999-2020 计算", "只有一段正文"))
        self.assertFalse(has_unsupported_reference("依据 JTS 999-2020 计算", "JTS 999-2020 规定"))

    def test_rerank_candidates_shared_is_callable(self):
        self.assertTrue(callable(rerank_candidates))


if __name__ == "__main__":
    unittest.main()
