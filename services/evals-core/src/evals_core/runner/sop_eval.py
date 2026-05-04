"""SOP 评测器骨架。"""
from typing import Any, Dict

from evals_core.runner.base import BaseEvaluator, register_evaluator


class SopEvaluator(BaseEvaluator):
    """SOP 执行评测器（首期骨架）。"""

    def run_prediction(self, question: Dict[str, Any]) -> Dict[str, Any]:
        """SOP 评测预测尚未实现。"""
        return {"status": "not_yet_implemented"}

    def evaluate(self, question: Dict[str, Any], gold: Dict[str, Any], prediction: Dict[str, Any]) -> Dict[str, Any]:
        """SOP 评测评估尚未实现。"""
        return {"score": 0.0, "evaluated": False, "reason": "not_yet_implemented"}


register_evaluator("sop", SopEvaluator)
