"""retrieval_pipeline 存活函数单测：rerank 入口与拒答校验。"""
import os
import sys
import unittest
from types import SimpleNamespace
from unittest import mock

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../../services/angineer-core/src")))
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../../services/docs-core/src")))
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../../services/ai-inference/src")))

from angineer_core.retrieval_pipeline import (  # noqa: E402
    has_unsupported_reference,
    llm_rerank_candidates,
    rerank_candidates,
)


class RetrievalPipelineSharedTests(unittest.TestCase):
    def test_has_unsupported_reference_shared(self):
        self.assertTrue(has_unsupported_reference("依据 JTS 999-2020 计算", "只有一段正文"))
        self.assertFalse(has_unsupported_reference("依据 JTS 999-2020 计算", "JTS 999-2020 规定"))

    def test_rerank_candidates_shared_is_callable(self):
        self.assertTrue(callable(rerank_candidates))

    @staticmethod
    def _make_item(item_id: str = "a", text: str = "候选内容") -> SimpleNamespace:
        return SimpleNamespace(
            item_id=item_id,
            title="条款",
            text=text,
            rerank_score=0.0,
            metadata={},
        )

    def test_llm_rerank_reorders_and_sets_scores(self):
        items = [self._make_item(str(i)) for i in range(4)]
        with mock.patch("angineer_core.retrieval_pipeline.chat_result_guarded") as guarded:
            guarded.return_value = SimpleNamespace(text='{"ranking": [3, 1, 0, 2]}')
            out = llm_rerank_candidates("查询", items, llm_client=object())
        self.assertEqual([item.item_id for item in out], ["3", "1", "0", "2"])
        scores = [item.rerank_score for item in out]
        self.assertEqual(scores, sorted(scores, reverse=True))

    def test_llm_rerank_bad_output_returns_none(self):
        items = [self._make_item(str(i)) for i in range(4)]
        with mock.patch("angineer_core.retrieval_pipeline.chat_result_guarded") as guarded:
            guarded.return_value = SimpleNamespace(text="not json")
            self.assertIsNone(llm_rerank_candidates("查询", items, llm_client=object()))

    def test_llm_rerank_invalid_indices_are_skipped(self):
        items = [self._make_item(str(i)) for i in range(4)]
        with mock.patch("angineer_core.retrieval_pipeline.chat_result_guarded") as guarded:
            guarded.return_value = SimpleNamespace(text='{"ranking": [99, 1, -3, 2, 1]}')
            out = llm_rerank_candidates("查询", items, llm_client=object())
        self.assertEqual([item.item_id for item in out], ["1", "2", "0", "3"])

    def test_rerank_candidates_dense_degraded_uses_llm(self):
        items = [self._make_item(str(i)) for i in range(6)]
        with mock.patch(
            "angineer_core.retrieval_pipeline.llm_rerank_candidates",
            return_value=items,
        ) as llm:
            out = rerank_candidates("查询", items, dense_degraded=True)
        llm.assert_called_once()
        self.assertIs(out, items)

    def test_rerank_candidates_not_degraded_uses_local(self):
        items = [self._make_item(str(i)) for i in range(6)]
        with mock.patch(
            "docs_core.step09_query.retrieval.reranker.rerank_candidates",
            return_value=items,
        ) as local:
            out = rerank_candidates("查询", items, dense_degraded=False)
        local.assert_called_once()
        self.assertIs(out, items)


if __name__ == "__main__":
    unittest.main()
