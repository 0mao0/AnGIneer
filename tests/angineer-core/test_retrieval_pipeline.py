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
    has_unsupported_claim,
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
            out = rerank_candidates(
                "查询",
                items,
                dense_degraded=True,
                config_name="cfg-x",
                mode="thinking",
            )
        llm.assert_called_once()
        self.assertEqual(llm.call_args.kwargs["config_name"], "cfg-x")
        self.assertEqual(llm.call_args.kwargs["mode"], "thinking")
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


class UnsupportedClaimGuardTests(unittest.TestCase):
    def test_numeric_present_ok(self):
        self.assertFalse(has_unsupported_claim("平均误差为 26.6 km [K1]。", "平均误差为26.6 km"))

    def test_numeric_missing_flagged(self):
        self.assertTrue(has_unsupported_claim("平均误差为 99.9 km [K1]。", "平均误差为26.6 km"))

    def test_numeric_cn_equivalent_ok(self):
        self.assertFalse(has_unsupported_claim("共一百二十五个样本 [K1]。", "共125个样本"))

    def test_numeric_cn_missing_flagged(self):
        self.assertTrue(has_unsupported_claim("共九百九十九个样本 [K1]。", "共125个样本"))

    def test_small_ordinals_exempt(self):
        self.assertFalse(has_unsupported_claim("第 1 步、第 2 步 [K1]。", "step 1 and 2"))

    def test_year_exempt(self):
        self.assertFalse(has_unsupported_claim("该研究发布于 2023 年 [K1]。", "published in 2024"))

    def test_entity_present_ok(self):
        self.assertFalse(has_unsupported_claim("DukeSeg 数据集用于评估 [K1]。", "DukeSeg and quality control module"))

    def test_entity_missing_flagged(self):
        self.assertTrue(has_unsupported_claim("FooBar 数据集用于评估 [K1]。", "DukeSeg dataset"))

    def test_common_words_exempt(self):
        self.assertFalse(has_unsupported_claim("Based on the results, the answer is Yes. [K1]", "Based on the results"))

    def test_cite_markers_not_treated_as_entity(self):
        self.assertFalse(has_unsupported_claim("该算法用于多模态交互 [K1][T2]。", "多模态交互用于视听提取"))

    def test_empty_answer_ok(self):
        self.assertFalse(has_unsupported_claim("", "任意证据"))


class HalfRefusalTests(unittest.TestCase):
    def test_half_refusal_flagged(self):
        from angineer_core.agent_messages import is_half_refusal_text

        half = (
            "证据不足，无法给出完整结论。但是根据检索到的内容，该算法的主要目的是利用多模态交互来增强视听目标说话人提取的性能 [K1]，"
            "具体包括对比学习引导时序交互、最大化目标语音与视觉特征同步性、联合训练损失函数设计等多个方面，"
            "这些内容在论文的第四章节中有详细说明，实验结果表明该方法在多个数据集上取得了显著提升。"
        )
        self.assertTrue(is_half_refusal_text(half))

    def test_plain_answer_ok(self):
        from angineer_core.agent_messages import is_half_refusal_text

        part = (
            "该算法的主要目的是利用多模态交互增强视听目标说话人提取性能 [K1]。"
            "证据中已支持对比学习引导与时序交互两部分内容，但证据未列出具体的损失函数设计细节。"
        )
        self.assertFalse(is_half_refusal_text(part))

    def test_declaration_without_cite_ok(self):
        from angineer_core.agent_messages import is_half_refusal_text

        decl = "证据不足，无法给出完整结论，当前检索到的片段仅能确认部分相关性，不足以安全地给出答案。"
        self.assertFalse(is_half_refusal_text(decl))


class PerDocBlockDedupTests(unittest.TestCase):
    def test_keep_per_doc_blocks_caps_and_dedups(self):
        from angineer_core.agent_tools import _keep_per_doc_blocks

        items = [
            SimpleNamespace(item_id="a1", doc_id="docA", text="", metadata={}),
            SimpleNamespace(item_id="a1", doc_id="docA", text="", metadata={}),
            SimpleNamespace(item_id="a2", doc_id="docA", text="", metadata={}),
            SimpleNamespace(item_id="a3", doc_id="docA", text="", metadata={}),
            SimpleNamespace(item_id="a4", doc_id="docA", text="", metadata={}),
            SimpleNamespace(item_id="b1", doc_id="docB", text="", metadata={}),
        ]
        kept = _keep_per_doc_blocks(items, total_cap=30)
        ids = [getattr(item, "item_id") for item in kept]
        self.assertEqual(ids, ["a1", "a2", "a3", "a4", "b1"])

    def test_keep_per_doc_blocks_total_cap(self):
        from angineer_core.agent_tools import _keep_per_doc_blocks

        items = [
            SimpleNamespace(item_id=f"d{i}x", doc_id=f"doc{i}", text="", metadata={})
            for i in range(40)
        ]
        kept = _keep_per_doc_blocks(items, total_cap=10)
        self.assertEqual(len(kept), 10)


if __name__ == "__main__":
    unittest.main()
