# -*- coding: utf-8 -*-
"""numeric 评测器单测：官方 vendored 判分器口径 / 金标与空答短路 / 形态闸 / 判分器异常防误伤。

全部用合成样例（含官方 README 示例），不依赖 gated 官方数据；
判分语义真相源 = officeqa_reward（逐字 vendored @ 7b9a3c154ef9）。
"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from evals_core.runner import numeric_eval  # noqa: E402
from evals_core.runner.base import get_evaluator, list_evaluator_names  # noqa: E402


def _ev():
    # evaluate 不依赖实例状态，__new__ 跳过 AnswerEvaluator 初始化的服务侧依赖
    return numeric_eval.NumericEvaluator.__new__(numeric_eval.NumericEvaluator)


def _q(gold=None, retrieval=False):
    question = {"question": "q", "numeric_gold": gold} if gold is not None else {"question": "q"}
    if retrieval:
        question["retrieval_gold"] = {"gold_doc_ids": ["doc-x"]}
    return question


def _eval(gold, answer):
    return _ev().evaluate(_q(gold), gold or {}, {"answer": answer})


class TestOfficialSemantics:
    """官方 score_answer/README 示例口径。"""

    def test_exact_number_pass(self):
        r = _eval({"answer": "123.45", "tolerance": 0.0}, "123.45")
        assert r["score"] == 1.0 and r["numeric_status"] == "PASS"

    def test_currency_pass(self):
        r = _eval({"answer": "$7,046,001.98", "tolerance": 0.0}, "$7,046,001.98")
        assert r["score"] == 1.0 and r["numeric_status"] == "PASS"

    def test_bracketed_label_value_pass(self):
        r = _eval({"answer": "[Massachusetts, 0.866]", "tolerance": 0.0},
                  "Massachusetts, with a ratio of 0.866")
        assert r["score"] == 1.0 and r["numeric_status"] == "PASS"

    def test_tolerance_boundary(self):
        assert _eval({"answer": "100.0", "tolerance": 0.0}, "100.5")["score"] == 0.0
        assert _eval({"answer": "100.0", "tolerance": 0.01}, "100.5")["score"] == 1.0

    def test_unit_context(self):
        assert _eval({"answer": "543 million", "tolerance": 0.0}, "about 543 million")["score"] == 1.0
        assert _eval({"answer": "543 million", "tolerance": 0.0}, "543")["score"] == 1.0
        assert _eval({"answer": "543 million", "tolerance": 0.0}, "543000000")["score"] == 0.0

    def test_incidental_year_filtered(self):
        r = _eval({"answer": "21.58", "tolerance": 0.0}, "The value, reported in 2023, is 21.58")
        assert r["score"] == 1.0

    def test_unable_to_determine_is_wrong(self):
        r = _eval({"answer": "21.58", "tolerance": 0.0}, "Unable to determine from the documents.")
        assert r["score"] == 0.0

    def test_text_answer_month_guard(self):
        assert _eval({"answer": "March 1977", "tolerance": 0.0}, "March 1977")["score"] == 1.0
        assert _eval({"answer": "March 1977", "tolerance": 0.0}, "April 1977")["score"] == 0.0


class TestGuards:
    """形态闸与短路：确定性判 0，不冒充未评估。"""

    def test_multiline_shape_fail(self):
        r = _eval({"answer": "123.45", "tolerance": 0.0}, "reasoning here\n123.45")
        assert r["score"] == 0.0 and r["numeric_status"] == "SHAPE_FAIL"

    def test_empty_answer_wrong_not_skipped(self):
        r = _eval({"answer": "123.45", "tolerance": 0.0}, "")
        assert r["score"] == 0.0 and r["numeric_status"] == "EMPTY"
        assert r["evaluated"] is True and r["refusal"] is True

    def test_no_gold_skipped(self):
        r = _ev().evaluate(_q(None), {}, {"answer": "whatever"})
        assert r["score"] is None and r["evaluated"] is False
        assert r["numeric_status"] == "NO_GOLD"

    def test_scorer_error_skipped_not_zero(self, monkeypatch):
        def _boom(*a, **k):
            raise RuntimeError("synthetic parse crash")
        monkeypatch.setattr(numeric_eval.officeqa_reward, "fuzzy_match_answer", _boom)
        r = _eval({"answer": "123.45", "tolerance": 0.0}, "123.45")
        assert r["score"] is None and r["evaluated"] is False
        assert r["numeric_status"] == "SCORER_ERROR"


class TestRegistration:
    def test_registered(self):
        assert "numeric" in list_evaluator_names()
        assert isinstance(get_evaluator("numeric"), numeric_eval.NumericEvaluator)

    def test_dispatch_selection(self):
        try:
            from evals_core.runner import suite_runner
        except Exception:  # angineer_core 依赖不在本测试环境时跳过接线断言
            pytest.skip("suite_runner import needs angineer_core on path")
        assert suite_runner._determine_evaluator_names(_q({"answer": "1", "tolerance": 0.0})) == ["numeric"]
        names = suite_runner._determine_evaluator_names(
            _q({"answer": "1", "tolerance": 0.0}, retrieval=True))
        assert names == ["numeric", "retrieval"]  # retrieval 殿后，防顶假绿


class TestBundleRoundTrip:
    """numeric 金标块随 bundle 进库/出库（eval.bundle.v2 → 行 → item）。"""

    def test_schema_and_row_mapping(self):
        from evals_core.dataset.schema import EvalQuestionItem
        from evals_core.dataset.manager import _item_to_question_row, _question_row_to_item

        item = EvalQuestionItem(
            question_id="oq_1", question="q", task_type="rag", difficulty="hard",
            numeric={"answer": "21.58", "tolerance": 0.01},
        )
        row = _item_to_question_row(item, "officeqa-pro-133-v1", sort_order=1)
        assert row["numeric_gold"] == {"answer": "21.58", "tolerance": 0.01}
        back = _question_row_to_item(row)
        assert back["numeric"] == {"answer": "21.58", "tolerance": 0.01}
