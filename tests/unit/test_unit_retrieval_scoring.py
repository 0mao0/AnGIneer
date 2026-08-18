# -*- coding: utf-8 -*-
"""检索打分的 n-gram 权重单测：通用词降权，避免无关文档靠"计算/方法/要求"刷分。"""
import os
import sys
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../../services/docs-core/src")))

from docs_core.step09_query.retrieval.query_normalizer import (  # noqa: E402
    GENERIC_NGRAM_STOPLIST,
    token_scoring_weight,
)
from docs_core.step09_query.retrieval.sparse_retriever import score_sparse_match  # noqa: E402


class TokenScoringWeightTests(unittest.TestCase):
    def test_topic_ngrams_outweigh_generic_ones(self):
        self.assertGreater(token_scoring_weight("斜坡堤稳定"), token_scoring_weight("计算方法"))
        self.assertGreater(token_scoring_weight("斜坡堤"), token_scoring_weight("计算"))

    def test_generic_grams_are_suppressed(self):
        self.assertLess(token_scoring_weight("计算"), 0.2)
        self.assertLess(token_scoring_weight("方法"), 0.2)
        self.assertLess(token_scoring_weight("要求"), 0.2)
        self.assertLess(token_scoring_weight("计算方法"), 0.2)

    def test_length_progression(self):
        self.assertGreater(token_scoring_weight("斜坡堤稳定"), token_scoring_weight("稳定计算"))
        self.assertGreater(token_scoring_weight("斜坡堤稳定"), token_scoring_weight("斜坡堤"))
        self.assertGreater(token_scoring_weight("斜坡堤"), token_scoring_weight("斜坡"))
        self.assertGreaterEqual(token_scoring_weight("斜坡堤稳定计算"), token_scoring_weight("斜坡堤稳定"))

    def test_formula_identifier_gets_premium_weight(self):
        self.assertEqual(token_scoring_weight("eps_tr"), 1.5)

    def test_stoplist_contains_observed_offenders(self):
        self.assertTrue({"计算", "方法", "要求", "计算方法"} <= GENERIC_NGRAM_STOPLIST)


class SparseScoreRegressionTests(unittest.TestCase):
    """回归：内河通航标准的公式上下文不该靠通用词压过防波堤规范的斜坡堤条文。"""

    QUERY = "斜坡堤稳定计算方法和要求"

    def test_relevant_slope_embankment_outranks_navigation_channel(self):
        navigation = (
            "附录 A 天然和渠化河流航道水深和宽度的计算方法 / A.0.1 航道水深可按下式计算：\n"
            "H = T + ΔH\n式中：H——航道水深(m)；T——船舶吃水(m)，根据航道条件和运输要求可取船舶、"
            "船队设计吃水或枯水期减载时的吃水"
        )
        slope = (
            "4 斜坡式防波堤设计 / 4.3 斜坡堤计算\n"
            "(5) 地震状况, 在进行斜坡式防波堤整体稳定性计算时, 考虑地震作用的组合, 不考虑波浪的作用;\n"
            "4.3.6 计算堤顶胸墙抗滑和抗倾稳定性应符合下列规定"
        )
        slope_score = score_sparse_match(self.QUERY, slope, "")
        navigation_score = score_sparse_match(self.QUERY, navigation, "")
        self.assertGreater(slope_score, navigation_score)


if __name__ == "__main__":
    unittest.main()
