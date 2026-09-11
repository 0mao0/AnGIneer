"""DeepEval 判分引擎（EVAL_ENGINE=deepeval 时启用）。

边界：只接管「LLM 判分」这一层的 prompt 管理/解析/重试琐事；judge 候选链纪律
（EVAL_JUDGE_CONFIGS → EVAL_JUDGE_MODEL，绝不落到被测模型自判）、哨兵留痕
（judge_used/judge_failover）、关键词兜底语义全部保留在 answer_eval.py 不变。

回滚：EVAL_ENGINE=legacy（默认）即恢复原判分链路。
"""
import logging
import time
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

# 与 answer_eval.DEFAULT_SEMANTIC_THRESHOLD 对齐（判分口径不变，仅换实现）
SEMANTIC_THRESHOLD = 0.65

# 新增维度的判分上下文规模上限（控制 judge token 成本）
_MAX_CONTEXTS = 10
_MAX_CONTEXT_CHARS = 1000

# 移植自 SEMANTIC_EVAL_PROMPT v3 的判分 rubric（语义保持逐条一致）
_GEVAL_CRITERIA = """\
判断系统答案（actual output）是否在语义上等价于或包含了标准答案（expected output）的核心信息。
评分标准：1.0=完整包含标准答案的核心信息、语义等价；0.7-0.9=包含大部分核心信息但有少量遗漏或不精确；
0.4-0.6=包含部分核心信息但有明显遗漏或偏差；0.0-0.3=与标准答案核心信息不符或缺失严重。
判定规则：当标准答案是简短的是/否判断时，系统答案首句给出同义结论（是/否/Yes/No/不是）即视为命中核心信息，
展开解释或末尾追问不属于扣分项；系统答案比标准答案更详细、但已完整包含核心信息时应给 1.0 或 0.9，
不得因详略差异或表述风格不同而扣分；核心结论正确、仅遗漏个别次要数值或细节时应给 0.7~0.9，
不得因遗漏次要数值/细节而整体判错。\
"""


def deepeval_available() -> bool:
    try:
        import deepeval  # noqa: F401

        return True
    except ImportError:
        return False


try:
    from deepeval.models.base_model import DeepEvalBaseLLM as _BaseLLM
except ImportError:  # 无 deepeval 时的占位基类（deepeval_available() 会拦截使用）
    _BaseLLM = object  # type: ignore[assignment]


class DGXJudge(_BaseLLM):
    """DeepEval 自定义 LLM：内部走 ai_inference 候选链（纪律与哨兵同 legacy 判分）。

    候选链由调用方解析后传入；每次 generate 按序尝试、失败切下一项、全失败抛异常。
    最近一次调用的 judge 来源记录在 last_judge_used / last_judge_failover（哨兵留痕）。
    """

    def __init__(self, candidates: List[Optional[str]]) -> None:
        self._candidates = list(candidates)
        self.last_judge_used: Optional[str] = None
        self.last_judge_failover: bool = False

    # ---- DeepEvalBaseLLM 接口 ----
    def load_model(self) -> "DGXJudge":
        return self

    def get_model_name(self) -> str:
        return f"dgx-judge({','.join(str(c or '<default>') for c in self._candidates)})"

    def generate(self, prompt: str, *args: Any, **kwargs: Any) -> str:
        from ai_inference.llm_client import chat_result_guarded, get_llm_client

        client = get_llm_client()
        last_exc: Optional[Exception] = None
        for index, config_name in enumerate(self._candidates):
            try:
                # 与 legacy 判分同款参数：instruct 模式 + 温度 0.1（见 answer_eval 注释）
                result = chat_result_guarded(
                    client,
                    [{"role": "user", "content": prompt}],
                    mode="instruct",
                    config_name=config_name,
                    temperature=0.1,
                )
                self.last_judge_used = config_name or "<被测默认>"
                self.last_judge_failover = index > 0
                return result.text
            except Exception as exc:  # noqa: BLE001 —— 单候选失败切下一候选
                last_exc = exc
        raise RuntimeError(f"judge 候选链全部失败（{len(self._candidates)} 个端点）: {last_exc}")

    async def a_generate(self, prompt: str, *args: Any, **kwargs: Any) -> str:
        return self.generate(prompt, *args, **kwargs)


def _extract_contexts(prediction: Dict[str, Any]) -> List[str]:
    """从 prediction 提取判分用检索上下文文本（evidences 优先，retrieved_items 兜底）。"""
    contexts: List[str] = []
    for evidence in prediction.get("evidences") or []:
        if isinstance(evidence, dict):
            text = str(evidence.get("content") or "").strip()
            if text:
                contexts.append(text[:_MAX_CONTEXT_CHARS])
    if not contexts:
        for item in prediction.get("retrieved_items") or []:
            if isinstance(item, dict):
                text = str(item.get("text") or "").strip()
                if text:
                    contexts.append(text[:_MAX_CONTEXT_CHARS])
    return contexts[:_MAX_CONTEXTS]


def evaluate_via_deepeval(
    *,
    question: str,
    answer: str,
    gold_answer: str,
    checks: List[Dict[str, Any]],
    prediction: Dict[str, Any],
    judge_config_name: Optional[str] = None,
) -> Dict[str, Any]:
    """DeepEval 判分入口：返回与 legacy semantic_result 同构的 dict + 新增维度字段。

    语义对齐约定：
    - semantic_score/passed/reason 由 GEval（移植 rubric）产出，阈值 0.65 不变
    - GEval 失败 → semantic_evaluated=False + semantic_fallback=True（调用方走关键词兜底，
      与 legacy 判分失败路径语义一致）
    - 新增维度（faithfulness/answer_relevancy/contextual_precision）独立失败独立记 None，
      不影响 correctness 口径
    """
    from deepeval.metrics import (
        AnswerRelevancyMetric,
        ContextualPrecisionMetric,
        FaithfulnessMetric,
        GEval,
    )
    from deepeval.test_case import LLMTestCase, SingleTurnParams

    from evals_core.runner.answer_eval import _build_gold_answer, _resolve_judge_candidates

    started = time.time()
    judge = DGXJudge(_resolve_judge_candidates(judge_config_name))
    built_gold = _build_gold_answer(gold_answer, checks)
    contexts = _extract_contexts(prediction)

    test_case = LLMTestCase(
        input=question,
        actual_output=answer,
        expected_output=built_gold,
        retrieval_context=contexts or None,
    )

    result: Dict[str, Any] = {
        "semantic_score": None,
        "semantic_reason": "",
        "semantic_evaluated": False,
        "semantic_fallback": True,
        "semantic_passed": None,
        "semantic_threshold": SEMANTIC_THRESHOLD,
        "judge_used": None,
        "judge_failover": False,
        "eval_engine": "deepeval",
    }

    # 1) correctness：GEval 移植现有 rubric（口径不变只换实现）
    try:
        geval = GEval(
            name="answer_correctness",
            criteria=_GEVAL_CRITERIA,
            # 显式参数面：只评 actual_output vs expected_output（与 legacy 判分同口径）
            evaluation_params=[SingleTurnParams.ACTUAL_OUTPUT, SingleTurnParams.EXPECTED_OUTPUT],
            model=judge,
            threshold=SEMANTIC_THRESHOLD,
            async_mode=False,
        )
        geval.measure(test_case)
        score = max(0.0, min(1.0, float(geval.score or 0.0)))
        result.update(
            semantic_score=round(score, 4),
            semantic_reason=str(geval.reason or ""),
            semantic_evaluated=True,
            semantic_fallback=False,
            semantic_passed=score >= SEMANTIC_THRESHOLD,
            judge_used=judge.last_judge_used,
            judge_failover=judge.last_judge_failover,
        )
    except Exception as exc:  # noqa: BLE001
        result["semantic_reason"] = f"DeepEval GEval 判分失败: {exc}"
        logger.warning("GEval 判分失败: %s", exc)

    # 2) 新增维度：独立失败独立记 None，不污染 correctness 口径
    # EVAL_DEEPVAL_EXTRA=0/false 可关闭扩展维度（每题省 3~6 次 judge 调用，nightly 提速）
    import os as _os

    extra_enabled = (_os.getenv("EVAL_DEEPVAL_EXTRA", "1") or "1").strip().lower() not in ("0", "false", "no", "off")
    if not extra_enabled:
        result["eval_duration"] = round(time.time() - started, 2)
        return result

    def _measure_extra(metric: Any, score_key: str, reason_key: str) -> None:
        try:
            metric.measure(test_case)
            result[score_key] = round(float(metric.score or 0.0), 4)
            result[reason_key] = str(getattr(metric, "reason", "") or "")
        except Exception as exc:  # noqa: BLE001
            result[score_key] = None
            result[reason_key] = f"{metric.__class__.__name__} 失败: {exc}"
            logger.warning("%s 失败: %s", metric.__class__.__name__, exc)

    _measure_extra(
        AnswerRelevancyMetric(model=judge, async_mode=False),
        "answer_relevancy_score",
        "answer_relevancy_reason",
    )
    if contexts:
        _measure_extra(
            FaithfulnessMetric(model=judge, async_mode=False),
            "faithfulness_score",
            "faithfulness_reason",
        )
        if gold_answer.strip():
            _measure_extra(
                ContextualPrecisionMetric(model=judge, async_mode=False),
                "contextual_precision_score",
                "contextual_precision_reason",
            )

    result["eval_duration"] = round(time.time() - started, 2)
    return result
