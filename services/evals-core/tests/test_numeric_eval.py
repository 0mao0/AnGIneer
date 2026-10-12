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


class TestTailLinePairing:
    """尾行提取与「答案收尾协议」成对（2026-10-11 P0-1）：
    输出侧注入 answer_format 才有资格判分侧取尾行；否则维持官方全文口径。"""

    MULTILINE = "根据检索证据计算如下：\n第一步取数 123.44\n第二步求和\n123.45\n您是否想了解其他年份的数据？"

    def test_answer_format_enables_tail_line(self):
        # 尾行是反问句 → 剥掉取倒数第二行的纯答案；全文口径下这题必 SHAPE_FAIL
        q = _q({"answer": "123.45", "tolerance": 0.0})
        q["answer_format"] = "最后必须另起一行，只写最终答案本身"
        r = _ev().evaluate(q, q["numeric_gold"], {"answer": self.MULTILINE})
        assert r["score"] == 1.0 and r["numeric_status"] == "PASS"

    def test_no_answer_format_keeps_full_text(self):
        # 不带协议 → 官方全文口径（多行判 0），与历史可比性不动
        r = _eval({"answer": "123.45", "tolerance": 0.0}, self.MULTILINE)
        assert r["score"] == 0.0 and r["numeric_status"] == "SHAPE_FAIL"

    def test_env_forces_tail_line_without_protocol(self, monkeypatch):
        monkeypatch.setenv("ANGINEER_NUMERIC_TAIL_LINE", "1")
        r = _eval({"answer": "123.45", "tolerance": 0.0}, self.MULTILINE)
        assert r["score"] == 1.0 and r["numeric_status"] == "PASS"

    def test_blank_answer_format_is_not_protocol(self):
        # 空白文本不算注入（与 start_eval_run 的 strip 口径一致）
        q = _q({"answer": "123.45", "tolerance": 0.0})
        q["answer_format"] = "   "
        r = _ev().evaluate(q, q["numeric_gold"], {"answer": self.MULTILINE})
        assert r["score"] == 0.0 and r["numeric_status"] == "SHAPE_FAIL"


class TestDatasetMetaFallback:
    """start_eval_run 的数据集 meta 回退（_answer_format_from_dataset_meta 纯函数）。

    meta 形态两态并存：result_store.get_dataset 返回 dict，bundle/导出侧是 JSON
    字符串——首版只按字符串解析，dict 抛 TypeError 被 except 吞掉、回退静默失效
    （探针 run-98bd9094be50 的 enabled=false 实锤），四态用例锁死。"""

    def test_dict_meta(self):
        from evals_core.runner.suite_runner import _answer_format_from_dataset_meta
        assert _answer_format_from_dataset_meta({"answer_format": "尾行只写答案"}) == "尾行只写答案"

    def test_str_meta(self):
        from evals_core.runner.suite_runner import _answer_format_from_dataset_meta
        assert _answer_format_from_dataset_meta('{"answer_format": "尾行只写答案"}') == "尾行只写答案"

    def test_bad_json_and_none_are_empty(self):
        from evals_core.runner.suite_runner import _answer_format_from_dataset_meta
        assert _answer_format_from_dataset_meta("{bad json") == ""
        assert _answer_format_from_dataset_meta(None) == ""
        assert _answer_format_from_dataset_meta({"answer_format": "  "}) == ""


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
