"""评测器基类与注册表。"""
from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional

_EVALUATOR_REGISTRY: Dict[str, type] = {}


class BaseEvaluator(ABC):
    """评测器抽象基类。"""

    @abstractmethod
    def run_prediction(self, question: Dict[str, Any]) -> Dict[str, Any]:
        """对单题执行预测调用。"""
        ...

    @abstractmethod
    def evaluate(self, question: Dict[str, Any], gold: Dict[str, Any], prediction: Dict[str, Any]) -> Dict[str, Any]:
        """对单题计算评测指标。"""
        ...


def register_evaluator(name: str, evaluator_cls: type) -> None:
    """注册评测器到全局注册表。"""
    _EVALUATOR_REGISTRY[name] = evaluator_cls


def get_evaluator(name: str) -> Optional[BaseEvaluator]:
    """从注册表获取评测器实例。"""
    cls = _EVALUATOR_REGISTRY.get(name)
    if cls is None:
        return None
    return cls()


def list_evaluator_names() -> List[str]:
    """列出所有已注册的评测器名称。"""
    return list(_EVALUATOR_REGISTRY.keys())
