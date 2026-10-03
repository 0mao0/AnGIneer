"""数值容差评测器（OfficeQA 类历史档案题集）。

与 answer_eval 同链：run_prediction 复用 AnswerEvaluator 的 RAG 问答链（检索→生成），
不重写。差异只在 evaluate：不走判官语义分，用官方 vendored 判分器
（officeqa_reward，逐字未改）做确定性数值/文本比对——零判官方差，成绩可直接
对官方榜（引用带档位与日期，见 docs/plan-officeqa-arms.md）。

金标块结构（eval_question.numeric_gold）：
  {"answer": "543 million", "tolerance": 0.0}
  - answer = 官方 officeqa CSV 的 ground truth 原文（含单位/货币符号/括号列表形态）。
  - tolerance = 相对误差（官方 score_answer 口径：0.0 精确 / 0.01 = 1% / 0.05 = 5%）。
  判分口径三件套（官方 policy，原样继承）：
  - 答案取 <FINAL_ANSWER> 尾段（我们的 RAG 链不产该标签，等价于全文）；
  - 直答形态闸：多行/超 250 字/数字个数不符 = 判 0（答非所问形态不给过）；
  - "unable to determine" 拒答文本 = 判 0。

防误判纪律：判分器抛异常（官方实现遇解析问题会 raise）→ score=None → skipped，
绝不静默给 0 或拿检索分顶成 correct（与 rubric_eval/_decide_quality 同纪律；
方向是防误伤，非防假绿——确定性判分没有判官崩这一说）。
"""
from typing import Any, Dict, Optional

from evals_core.runner.answer_eval import AnswerEvaluator, is_refusal
from evals_core.runner.base import register_evaluator
from evals_core.runner import officeqa_reward


class NumericEvaluator(AnswerEvaluator):
    """数值容差题评测器：复用 RAG 问答链生成答案，evaluate 走官方确定性判分器。"""

    def evaluate(self, question: Dict[str, Any], gold: Dict[str, Any], prediction: Dict[str, Any]) -> Dict[str, Any]:
        gold_block = gold or question.get("numeric_gold") or {}
        expected = str(gold_block.get("answer") or "").strip()
        answer = str(prediction.get("answer") or "").strip()
        try:
            tolerance = float(gold_block.get("tolerance", 0.0) or 0.0)
        except (TypeError, ValueError):
            tolerance = 0.0
        tolerance = min(max(tolerance, 0.0), 1.0)

        result: Dict[str, Any] = {
            "evaluated": True,
            "expected": expected,
            "tolerance": tolerance,
            "refusal": is_refusal(answer) if answer else True,
        }
        if not expected:
            # 金标缺失必须响亮失败（与 rubric/intent 同纪律）：空 gold 判满分=假绿
            result.update(score=None, numeric_status="NO_GOLD", evaluated=False)
        elif not answer:
            # 真空答案：确定性判 0（不是未评估——没答就是没答对）
            result.update(score=0.0, numeric_status="EMPTY", reason="Predicted answer is empty")
        else:
            try:
                final = officeqa_reward.extract_final_answer(answer)
                shape_ok, shape_reason = officeqa_reward._is_direct_answer_only(expected, final)
                if shape_ok:
                    ok, reason = officeqa_reward.fuzzy_match_answer(expected, final, tolerance)
                    status = "PASS" if ok else "WRONG"
                else:
                    ok, reason, status = False, shape_reason, "SHAPE_FAIL"
                result.update(score=1.0 if ok else 0.0, numeric_status=status, reason=reason)
            except Exception as exc:  # noqa: BLE001 —— 判分器解析崩→未评估，不冒充 0 分
                result.update(score=None, numeric_status="SCORER_ERROR", evaluated=False,
                              error=f"官方判分器异常：{exc}")

        # 观测标注随 prediction 落库（与 answer_eval/rubric_eval 同口径）
        if prediction.get("final_outcome"):
            result["final_outcome"] = str(prediction["final_outcome"])
        try:
            result["llm_error_count"] = int(prediction.get("llm_error_count") or 0)
        except (TypeError, ValueError):
            result["llm_error_count"] = 0
        return result


register_evaluator("numeric", NumericEvaluator)
