"""judge_deepeval 判分引擎接入回归测试。

替身类替身 DeepEval 指标（不打真实 LLM）；覆盖：
- EVAL_ENGINE 开关分发（legacy 不受影响）
- deepeval 缺失时的优雅回退
- DGXJudge 候选链顺序/失败切换/哨兵留痕
- evaluate_via_deepeval 的 legacy 同构字段 + 新维度 + 独立失败语义
- _extract_contexts 的 evidences 优先/retrieved_items 兜底/截断上限
"""
import json
import os
import sys

import pytest
import ai_inference.llm_client as _llm_pkg_import  # noqa: F401  # 确保子模块已入 sys.modules（包属性被代理遮蔽）

llm_client_module = sys.modules["ai_inference.llm_client"]

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "src")))

from evals_core.runner import answer_eval  # noqa: E402
from evals_core.runner import judge_deepeval  # noqa: E402
from evals_core.runner.judge_deepeval import DGXJudge, _extract_contexts  # noqa: E402


# ---- DGXJudge 候选链 ----


def test_judge_first_candidate_success(monkeypatch):
    calls = []

    class FakeResult:
        text = '{"score": 0.9}'

    def fake_guarded(client, messages, mode=None, config_name=None, temperature=None):
        calls.append(config_name)
        return FakeResult()

    monkeypatch.setattr(llm_client_module, "chat_result_guarded", fake_guarded)
    monkeypatch.setattr(llm_client_module, "get_llm_client", lambda: object())

    judge = DGXJudge(["judge-a", "judge-b"])
    assert judge.generate("prompt") == '{"score": 0.9}'
    assert calls == ["judge-a"]
    assert judge.last_judge_used == "judge-a"
    assert judge.last_judge_failover is False


def test_judge_failover_chain(monkeypatch):
    calls = []

    class FakeResult:
        text = "ok"

    def fake_guarded(client, messages, mode=None, config_name=None, temperature=None):
        calls.append(config_name)
        if config_name == "judge-a":
            raise ConnectionError("down")
        return FakeResult()

    monkeypatch.setattr(llm_client_module, "chat_result_guarded", fake_guarded)
    monkeypatch.setattr(llm_client_module, "get_llm_client", lambda: object())

    judge = DGXJudge(["judge-a", "judge-b"])
    assert judge.generate("prompt") == "ok"
    assert calls == ["judge-a", "judge-b"]
    assert judge.last_judge_used == "judge-b"
    assert judge.last_judge_failover is True


def test_judge_all_candidates_fail_raises(monkeypatch):
    def fake_guarded(*args, **kwargs):
        raise ConnectionError("down")

    monkeypatch.setattr(llm_client_module, "chat_result_guarded", fake_guarded)
    monkeypatch.setattr(llm_client_module, "get_llm_client", lambda: object())

    judge = DGXJudge(["judge-a", "judge-b"])
    with pytest.raises(RuntimeError, match="候选链全部失败"):
        judge.generate("prompt")


# ---- _extract_contexts ----


def test_contexts_evidences_priority_and_caps():
    prediction = {
        "evidences": [{"content": f"证据{i}"} for i in range(15)],
        "retrieved_items": [{"text": "不应被用"}],
    }
    contexts = _extract_contexts(prediction)
    assert len(contexts) == judge_deepeval._MAX_CONTEXTS
    assert contexts[0] == "证据0"


def test_contexts_fallback_to_retrieved_items():
    prediction = {"retrieved_items": [{"text": "x" * 2000}]}
    contexts = _extract_contexts(prediction)
    assert len(contexts) == 1
    assert len(contexts[0]) == judge_deepeval._MAX_CONTEXT_CHARS


# ---- EVAL_ENGINE 分发 ----


def test_dispatch_default_legacy(monkeypatch):
    monkeypatch.delenv("EVAL_ENGINE", raising=False)
    called = []
    monkeypatch.setattr(
        "evals_core.runner.judge_deepeval.evaluate_via_deepeval",
        lambda **kwargs: called.append(1),
    )

    def boom(*args, **kwargs):
        raise ConnectionError("legacy path invoked (test double)")

    monkeypatch.setattr(llm_client_module, "chat_result_guarded", boom)
    monkeypatch.setattr(llm_client_module, "get_llm_client", lambda: object())
    result = answer_eval._llm_semantic_evaluate("答案", "标准", [], 0.65)
    assert result["semantic_fallback"] is True  # legacy 全链失败兜底
    assert not called  # deepeval 未被调用


def test_dispatch_deepeval(monkeypatch):
    monkeypatch.setenv("EVAL_ENGINE", "deepeval")
    monkeypatch.setattr("evals_core.runner.judge_deepeval.deepeval_available", lambda: True)
    expected = {"semantic_score": 0.9, "semantic_evaluated": True, "semantic_fallback": False, "eval_engine": "deepeval"}
    monkeypatch.setattr(
        "evals_core.runner.judge_deepeval.evaluate_via_deepeval",
        lambda **kwargs: expected,
    )
    result = answer_eval._llm_semantic_evaluate("答案", "标准", [], 0.65)
    assert result["semantic_score"] == 0.9
    assert result["eval_engine"] == "deepeval"


def test_dispatch_deepeval_missing_package(monkeypatch):
    monkeypatch.setenv("EVAL_ENGINE", "deepeval")
    monkeypatch.setattr("evals_core.runner.judge_deepeval.deepeval_available", lambda: False)
    result = answer_eval._llm_semantic_evaluate("答案", "标准", [], 0.65)
    assert result["semantic_evaluated"] is False
    assert result["semantic_fallback"] is True
    assert "未安装" in result["semantic_reason"]


# ---- evaluate_via_deepeval 同构映射（替身 DeepEval 指标）----


class _FakeMetricBase:
    score_value = 0.8
    reason_value = "替身理由"
    fail = False

    def __init__(self, *args, **kwargs):
        pass

    def measure(self, test_case):
        if self.fail:
            raise RuntimeError("替身失败")
        self.score = self.score_value
        self.reason = self.reason_value


class FakeGEval(_FakeMetricBase):
    pass


class FakeFaithfulness(_FakeMetricBase):
    score_value = 0.95


class FakeRelevancy(_FakeMetricBase):
    score_value = 0.88


class FakeCtxPrecision(_FakeMetricBase):
    score_value = 0.7


@pytest.fixture()
def fake_deepeval(monkeypatch):
    import deepeval.metrics

    monkeypatch.setattr(deepeval.metrics, "GEval", FakeGEval)
    monkeypatch.setattr(deepeval.metrics, "FaithfulnessMetric", FakeFaithfulness)
    monkeypatch.setattr(deepeval.metrics, "AnswerRelevancyMetric", FakeRelevancy)
    monkeypatch.setattr(deepeval.metrics, "ContextualPrecisionMetric", FakeCtxPrecision)
    monkeypatch.setenv("EVAL_JUDGE_CONFIGS", json.dumps(["judge-a"]))


def test_evaluate_via_deepeval_maps_legacy_fields_and_new_dims(fake_deepeval):
    result = judge_deepeval.evaluate_via_deepeval(
        question="混凝土强度等级如何确定？",
        answer="应按立方体抗压强度标准值确定。",
        gold_answer="按立方体抗压强度标准值确定",
        checks=[],
        prediction={"evidences": [{"content": "4.1.1 混凝土强度等级应..."}]},
        judge_config_name=None,
    )
    # legacy 同构字段
    assert result["semantic_score"] == 0.8
    assert result["semantic_evaluated"] is True
    assert result["semantic_fallback"] is False
    assert result["semantic_passed"] is True  # 0.8 >= 0.65
    assert result["semantic_threshold"] == 0.65
    assert result["eval_engine"] == "deepeval"
    # 新维度
    assert result["faithfulness_score"] == 0.95
    assert result["answer_relevancy_score"] == 0.88
    assert result["contextual_precision_score"] == 0.7


def test_evaluate_via_deepeval_geval_failure_keeps_fallback_semantics(fake_deepeval, monkeypatch):
    class FailGEval(_FakeMetricBase):
        fail = True

    import deepeval.metrics

    monkeypatch.setattr(deepeval.metrics, "GEval", FailGEval)
    result = judge_deepeval.evaluate_via_deepeval(
        question="q",
        answer="a",
        gold_answer="g",
        checks=[],
        prediction={"evidences": [{"content": "ctx"}]},
    )
    # GEval 失败 → 与 legacy 判分失败同语义（调用方走关键词兜底）
    assert result["semantic_evaluated"] is False
    assert result["semantic_fallback"] is True
    assert result["semantic_passed"] is None
    # 其余维度独立成功不受影响
    assert result["faithfulness_score"] == 0.95


def test_evaluate_via_deepeval_skips_context_metrics_without_contexts(fake_deepeval):
    result = judge_deepeval.evaluate_via_deepeval(
        question="q",
        answer="a",
        gold_answer="g",
        checks=[],
        prediction={},
    )
    assert result["answer_relevancy_score"] == 0.88
    assert "faithfulness_score" not in result or result["faithfulness_score"] is None
    assert "contextual_precision_score" not in result
