"""判官评分双刻度归一化：0–1 小数 → 0–10 整数（DeepEval GEval 口径）。

2026-09-28 探针实锤：判官（Qwen3.8）在 0–10 整数（"10"/"8"）与 0–1 小数（"0.8"）两种
刻度间抽签；DeepEval 未传 rubric 时假定 0–10 并做 score/10（g_eval.py:153），于是
"0.8"（本意「良好」）被算成 0.08 判 wrong。探针 30 次调用里 6×0.08 + 1×0.07 与原始
日志 "0.8"×6 + "0.7"×1 逐一对上，且判词均为正面。池内 sem∈(0,0.1] 占 47/522 行。
"""
import json
import sys
from pathlib import Path

EVALS_CORE_SRC = Path(__file__).resolve().parents[1] / "src"
if str(EVALS_CORE_SRC) not in sys.path:
    sys.path.insert(0, str(EVALS_CORE_SRC))

from evals_core.runner.judge_deepeval import _normalize_judge_score_scale  # noqa: E402


def test_fractional_scale_is_multiplied():
    text = json.dumps({"score": 0.8, "reason": "fully captures the core conclusion"})
    out, raw, fixed = _normalize_judge_score_scale(text)
    assert fixed is True
    assert raw == 0.8
    assert json.loads(out)["score"] == 8
    assert json.loads(out)["reason"] == "fully captures the core conclusion"


def test_fractional_scale_string_value():
    out, raw, fixed = _normalize_judge_score_scale('{"score": "0.7"}')
    assert fixed is True and raw == 0.7 and json.loads(out)["score"] == 7


def test_integer_scale_is_untouched():
    for value in (0, 7, 8, 9, 10):
        text = json.dumps({"score": value})
        out, raw, fixed = _normalize_judge_score_scale(text)
        assert fixed is False and out == text and raw == value


def test_exact_one_is_ambiguous_and_left_alone():
    # 1 既可能是 0–1 刻度满分、也可能是 0–10 刻度的 1 分，不猜（防把真错题抬成满分）
    text = json.dumps({"score": 1})
    out, raw, fixed = _normalize_judge_score_scale(text)
    assert fixed is False and out == text and raw == 1.0


def test_non_numeric_and_missing_score_pass_through():
    text = json.dumps({"reason": "no score field"})
    assert _normalize_judge_score_scale(text) == (text, None, False)
    text2 = json.dumps({"score": "high"})
    assert _normalize_judge_score_scale(text2) == (text2, None, False)
    assert _normalize_judge_score_scale("") == ("", None, False)
    assert _normalize_judge_score_scale("not json") == ("not json", None, False)
