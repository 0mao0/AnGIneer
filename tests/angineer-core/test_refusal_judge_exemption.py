"""拒答题判分豁免口径（2026-09-27，report-refusal-attribution-20260927 §4 拍板两项）。

两类「模型其实已拒、标记对判分不可见」不再判错，且只对 refusal_expected=True 生效：
  ① 剥头毁标记：guard 半拒答剥头删掉拒答开头 → 按 answer_pre_strip 原文判；
  ② 实质拒答措辞：无任何标记、开头即「证据中未包含…」缺失声明 → is_substantive_refusal。
用例文本取 28/39 实测 run（run-f531b7a447fc）的真实回答原文。
"""
import os
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../../services/angineer-core/src")))
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../../services/evals-core/src")))

from angineer_core.agent_messages import is_substantive_refusal  # noqa: E402

# run-f531b7a447fc 实测：无标记实质拒答（final_outcome=model_answer，原判错）
REAL_SUBSTANTIVE_REFUSAL = (
    "检索结果中未包含关于“withdrawal fee”（提款费/撤资费）在一般金融头寸或特定区块链协议中"
    "的具体收费标准或计算公式。检索到的文档主要涉及流动性提供（LP）在恒定产品做市商（CPMM）中"
    "的费用收取机制，并未提及针对 $1 million 头寸的固定百分比提款费或费率上限（fee cap）的标准定义。"
)

# 同 run 实测：诱导作答（该题知识库无答案，模型借相邻证据强答）——不得被豁免翻成拒答
REAL_INDUCED_ANSWERS = (
    "不是。  根据检索证据，轨迹并非全部表示为多项式函数：\n- 在训练过程中，轨迹确实被定义为"
    "分段多项式（piecewise polynomial）[K2][K7]。",
    "是的，安全对齐的大语言模型（LLMs）在训练过程中会使用预训练数据过滤。  根据检索到的证据，"
    "具体的数据过滤实践包括语言识别与去重 [K1]，此外相关章节未提及的部分见后续。",
)


class IsSubstantiveRefusalTests(unittest.TestCase):
    def test_real_substantive_refusal(self):
        self.assertTrue(is_substantive_refusal(REAL_SUBSTANTIVE_REFUSAL))

    def test_gap_statement_after_citation_is_not_refusal(self):
        """合法部分覆盖：先给实质内容（引用在前），缺口句在引用之后——不是拒答。"""
        self.assertFalse(is_substantive_refusal(
            "规范第 4.2 条规定混凝土强度等级按立方体抗压强度标准值划分 [K1]；"
            "但对本工程未给出的养护条件，材料未提及具体取值。"
        ))

    def test_affirmative_lead_is_not_refusal(self):
        for text in REAL_INDUCED_ANSWERS:
            self.assertFalse(is_substantive_refusal(text), text[:30])

    def test_plain_answer_and_empty(self):
        self.assertFalse(is_substantive_refusal("混凝土强度等级为 C30。"))
        self.assertFalse(is_substantive_refusal(""))
        self.assertFalse(is_substantive_refusal(None))  # type: ignore[arg-type]


class RefusalJudgeExemptionTests(unittest.TestCase):
    """AnswerEvaluator.evaluate 对 refusal_expected=True 的豁免口径。"""

    def _eval(self, answer, gold, prediction=None):
        from evals_core.runner.answer_eval import AnswerEvaluator

        return AnswerEvaluator().evaluate(
            {"question": "q", "question_id": "q1"},
            gold,
            {"answer": answer, **(prediction or {})},
        )

    def test_pre_strip_original_counts_as_refusal(self):
        """①：剥头后正文无标记，但 answer_pre_strip 带硬拒答开头 → 判拒答（1 分）。"""
        stripped = (
            "已检索到的证据主要讨论了投资者情绪（以 VIX 指数衡量）对 BRICS 股票市场的影响 [K3]。"
            "证据中并未包含关于特斯拉（Tesla）股票价格或投资者信心对其具体影响的相关数据或分析。"
        )
        pre_strip = (
            "没有检索到足够证据支持最终结论。" + stripped
        )
        scores = self._eval(stripped, {"refusal_expected": True},
                            {"answer_pre_strip": pre_strip})
        self.assertEqual(scores["score"], 1.0)
        self.assertEqual(scores["refusal_recognized_by"], "pre_strip")

    def test_substantive_wording_counts_as_refusal(self):
        """②：无标记、开头缺失声明 → 判拒答（1 分）。"""
        scores = self._eval(REAL_SUBSTANTIVE_REFUSAL, {"refusal_expected": True})
        self.assertEqual(scores["score"], 1.0)
        self.assertEqual(scores["refusal_recognized_by"], "substantive_wording")

    def test_marker_refusal_flag_stays_none(self):
        scores = self._eval(
            "没有检索到足够证据支持最终结论。", {"refusal_expected": True})
        self.assertEqual(scores["score"], 1.0)
        self.assertIsNone(scores["refusal_recognized_by"])

    def test_induced_answer_still_zero(self):
        """诱导作答（借相邻证据强答）不因豁免口径翻绿。"""
        for text in REAL_INDUCED_ANSWERS:
            scores = self._eval(text, {"refusal_expected": True})
            self.assertEqual(scores["score"], 0.0, text[:30])
            self.assertIsNone(scores.get("refusal_recognized_by"))

    def test_answerable_question_unaffected_by_wording(self):
        """refusal_expected=False 的题即便回答含「未提及」也走正常判分，不整体判拒。"""
        from evals_core.runner import answer_eval as ae

        with patch.object(ae, "_llm_semantic_evaluate",
                          return_value={"semantic_score": 0.9, "semantic_reason": "ok",
                                        "semantic_evaluated": True, "semantic_fallback": False,
                                        "semantic_passed": True}) as sem:
            scores = self._eval(
                "规范第 4.2 条规定了划分标准 [K1]；对本工程未给出的养护条件，材料未提及具体取值。",
                {"gold_answer": "按立方体抗压强度标准值划分"},
            )
        sem.assert_called_once()
        self.assertEqual(scores["score"], 1.0)

    def test_substantive_refusal_with_llm_error_flagged(self):
        """实质拒答 + 被吞 LLM 失败 → refusal_via_error 识破（故障吞错式拒答不是校准拒答）。"""
        scores = self._eval(REAL_SUBSTANTIVE_REFUSAL, {"refusal_expected": True},
                            {"llm_error_count": 1})
        self.assertEqual(scores["score"], 1.0)
        self.assertTrue(scores.get("refusal_via_error"))


class PredictionCarriesPreStripTests(unittest.TestCase):
    def test_prediction_round_trip(self):
        from evals_core.runner.answer_eval import AnswerEvaluator

        evaluator = AnswerEvaluator()
        data = {"answer": "剥头后正文", "answer_pre_strip": "没有检索到足够证据支持最终结论。剥头后正文"}
        with patch("evals_core.runner.answer_eval.run_eval_query", return_value=data):
            result = evaluator.run_prediction({"question_id": "q1", "question": "测试"})
        prediction = result.get("prediction") or result
        self.assertIn("剥头", prediction["answer_pre_strip"])


if __name__ == "__main__":
    unittest.main()
