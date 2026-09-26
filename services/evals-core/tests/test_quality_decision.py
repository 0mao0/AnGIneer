"""判分缺失的 quality 判定：主评测器没出分就是未评估，绝不拿检索分顶替。

2026-09-25 实踩（判分模型名错配、915 题判分崩）：旧逻辑在 primary score is None 时
从其他评测器取分兜底，而 retrieval.score 几乎恒为 1.0，整批题被记成答对，卡片报
92.4%；同 run 补判正常后 87.31%，虚高 53 题。2026-09-23 同口径：442/476 题被顶成
correct，当晚 88.78% vs 同日真判 83.46%。
"""
import sys
from pathlib import Path

EVALS_CORE_SRC = Path(__file__).resolve().parents[1] / "src"
if str(EVALS_CORE_SRC) not in sys.path:
    sys.path.insert(0, str(EVALS_CORE_SRC))

from evals_core.runner.suite_runner import _decide_quality  # noqa: E402

ANSWER = "answer"


def test_primary_score_at_or_above_threshold_is_correct():
    assert _decide_quality(ANSWER, {"answer": {"score": 0.9}}) == ("completed", "correct")
    assert _decide_quality(ANSWER, {"answer": {"score": 0.8}}) == ("completed", "correct")  # 阈值含边界


def test_primary_score_below_threshold_is_wrong():
    assert _decide_quality(ANSWER, {"answer": {"score": 0.0}}) == ("completed", "wrong")
    assert _decide_quality(ANSWER, {"answer": {"score": 0.79}}) == ("completed", "wrong")


def test_keyword_check_downgrade_still_applies():
    """主分过了但关键词复核没过 → 仍是 wrong（原口径不变，只是搬进同一个判定函数）。"""
    scores = {"answer": {"score": 0.9, "correctness_checked": True, "correctness_score": 0.0}}
    assert _decide_quality(ANSWER, scores) == ("completed", "wrong")


def test_judge_broken_with_perfect_retrieval_is_unjudged_not_correct():
    """判分崩 + 检索满分：旧逻辑在这里记 correct —— 09-25 那晚 92.4% 的虚高就出自这一支。"""
    scores = {"answer": {"semantic_fallback": True}, "retrieval": {"score": 1.0}}
    assert _decide_quality(ANSWER, scores) == ("completed", None)


def test_judge_broken_with_failed_retrieval_is_unjudged_not_wrong():
    """检索分 0.0 的判分崩题同样未评估：旧逻辑记 wrong，同样与答案内容无关、纯属随机。"""
    scores = {"answer": {"semantic_fallback": True}, "retrieval": {"score": 0.0}}
    assert _decide_quality(ANSWER, scores) == ("completed", None)


def test_missing_primary_score_without_other_evaluators_is_unjudged():
    assert _decide_quality(ANSWER, {}) == ("completed", None)


def test_non_answer_primary_gets_the_same_discipline():
    """换 primary 也一样：主评测器没出分就是未评估 —— 维度之间不能互相顶替。"""
    scores = {"sop": {}, "answer": {"score": 1.0}}
    assert _decide_quality("sop", scores) == ("completed", None)
