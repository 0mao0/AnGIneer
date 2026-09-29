# -*- coding: utf-8 -*-
"""intent 评测器单测：路由派生 / 断言分级（route 致命、level·mode 仅记录）/ xfail 语义 / 注入缺失报错。"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from evals_core.runner import intent_eval  # noqa: E402
from evals_core.runner.base import get_evaluator, list_evaluator_names  # noqa: E402


def _gold(level="L2", mode="structured_lookup", **kw):
    g = {"level": level, "mode": mode}
    g.update(kw)
    return g


class TestDeriveRoute:
    def test_casual_chat_wins_over_level(self):
        assert intent_eval.derive_route("L1", "casual_chat") == "L0"

    def test_meta_wins_over_level(self):
        assert intent_eval.derive_route("L1", "meta_query") == "meta"

    def test_complex_for_l3_l4(self):
        assert intent_eval.derive_route("L3", "standard_sop") == "complex"
        assert intent_eval.derive_route("L4", "dynamic_orchestration") == "complex"

    def test_l2_and_structured_lookup(self):
        assert intent_eval.derive_route("L2", "structured_lookup") == "L2"
        assert intent_eval.derive_route("L1", "structured_lookup") == "L2"

    def test_default_is_l1(self):
        assert intent_eval.derive_route("L1", "semantic_retrieval") == "L1"
        assert intent_eval.derive_route("", "") == "L1"

    def test_route_matches_agent_policy_order(self):
        """sql_first 也归 L2（agent_policy.build_attempts 的 L2 分支含 sql_first）。"""
        assert intent_eval.derive_route("L1", "sql_first") == "L2"


class TestRunIntentItem:
    def test_pass_when_route_and_level_match(self):
        out = intent_eval.run_intent_item({"intent": _gold()}, {"level": "L2", "mode": "structured_lookup"})
        assert out["status"] == "PASS"
        assert out["failed"] == []
        assert out["gold_route"] == "L2" and out["got_route"] == "L2"

    def test_route_fatal_by_default(self):
        """route 是致命项：错桶即 FAIL，即使 level 与 mode 各自能对上别的真值。"""
        out = intent_eval.run_intent_item({"intent": _gold()}, {"level": "L1", "mode": "semantic_retrieval"})
        assert out["status"] == "FAIL"
        assert out["fatal_failed"] == ["route"]

    def test_level_mismatch_is_not_fatal_by_default(self):
        """L3↔L4 同属 complex 桶：route 对、level 错 → PASS（生产不改注入工具）。"""
        out = intent_eval.run_intent_item(
            {"intent": _gold("L3", "standard_sop")}, {"level": "L4", "mode": "dynamic_orchestration"}
        )
        assert out["status"] == "PASS"
        assert "level" in out["failed"] and "mode" in out["failed"]
        assert out["fatal_failed"] == []

    def test_strict_level_makes_level_fatal(self):
        out = intent_eval.run_intent_item(
            {"intent": _gold("L3", "standard_sop", strict_level=True)},
            {"level": "L4", "mode": "dynamic_orchestration"},
        )
        assert out["status"] == "FAIL"
        assert "level" in out["fatal_failed"]

    def test_strict_mode_makes_mode_fatal(self):
        out = intent_eval.run_intent_item(
            {"intent": _gold("L2", "structured_lookup", strict_mode=True)},
            {"level": "L2", "mode": "sql_first"},
        )
        assert out["status"] == "FAIL"
        assert "mode" in out["fatal_failed"]

    def test_gold_route_falls_back_to_derivation(self):
        """金标未写 route 时现场派生，避免金标与派生规则漂移。"""
        out = intent_eval.run_intent_item({"intent": _gold("L4", "dynamic_orchestration")},
                                         {"level": "L3", "mode": "standard_sop"})
        assert out["gold_route"] == "complex"
        assert out["status"] == "PASS"

    def test_reads_intent_gold_key_too(self):
        """题集入库后键名是 intent_gold（Row 契约），两种键都要认。"""
        out = intent_eval.run_intent_item({"intent_gold": _gold()}, {"level": "L2", "mode": "structured_lookup"})
        assert out["status"] == "PASS"

    def test_xfail_semantics(self):
        """xfail：致命项仍挂 → XFAIL-OK（缺口仍在）；全过 → XPASS（缺口已修，提示摘标记）。"""
        still_broken = intent_eval.run_intent_item(
            {"intent": _gold(xfail=True)}, {"level": "L1", "mode": "semantic_retrieval"}
        )
        assert still_broken["status"] == "XFAIL-OK"
        assert still_broken["fatal_failed"] == ["route"]

        fixed = intent_eval.run_intent_item(
            {"intent": _gold(xfail=True)}, {"level": "L2", "mode": "structured_lookup"}
        )
        assert fixed["status"].startswith("XPASS")

    def test_empty_gold_fails_loudly(self):
        """空金标不得静默通过：派生出的默认 L1 会与模型默认答案撞成假绿。"""
        out = intent_eval.run_intent_item({}, {"level": "L1", "mode": "semantic_retrieval"})
        assert out["status"] == "FAIL"
        assert out["fatal_failed"] == ["gold"]
        assert "金标块为空" in out["checks"]["gold"]

    def test_family_and_trap_passthrough(self):
        out = intent_eval.run_intent_item(
            {"intent": _gold(family="L2_clause_number", trap="问出处非内容")},
            {"level": "L2", "mode": "structured_lookup"},
        )
        assert out["family"] == "L2_clause_number" and out["trap"] == "问出处非内容"


class TestEvaluator:
    def test_registered(self):
        assert "intent" in list_evaluator_names()
        assert get_evaluator("intent") is not None

    def test_run_prediction_errors_without_injection(self):
        """未注入分类器时报错，绝不静默跳过（与 probe_eval 同纪律）。"""
        intent_eval.set_intent_classifier(None)
        out = intent_eval.IntentEvaluator().run_prediction({"question": "什么是乘潮水位？"})
        assert "error" in out
        assert "未注入" in out["error"]

    def test_run_prediction_maps_intent_result(self):
        class _R:
            intent_level = "L2"
            service_mode = "structured_lookup"
            intent_type = "clause_lookup"
            reason = "r"

        intent_eval.set_intent_classifier(lambda q: _R())
        try:
            pred = intent_eval.IntentEvaluator().run_prediction({"question": "依据JTS 181确定航道宽度的取值"})
            assert pred["level"] == "L2" and pred["route"] == "L2"
            assert pred["probe_mode"] == "classify_only"
        finally:
            intent_eval.set_intent_classifier(None)

    def test_evaluate_score_semantics(self):
        ev = intent_eval.IntentEvaluator()
        ok = ev.evaluate({"intent_gold": _gold()}, {}, {"level": "L2", "mode": "structured_lookup"})
        assert ok["score"] == 1.0 and ok["status"] == "PASS"
        bad = ev.evaluate({"intent_gold": _gold()}, {}, {"level": "L1", "mode": "semantic_retrieval"})
        assert bad["score"] == 0.0 and bad["status"] == "FAIL"

    def test_score_below_threshold_maps_to_wrong(self):
        """_decide_quality 阈值 0.8：FAIL 的 0.0 必须落在 wrong 侧。"""
        from evals_core.runner.suite_runner import PASSED_THRESHOLD

        assert 0.0 < PASSED_THRESHOLD and 1.0 >= PASSED_THRESHOLD


class TestSuiteRunnerWiring:
    def test_intent_gold_takes_exclusive_route(self):
        from evals_core.runner.suite_runner import _determine_evaluator_names

        assert _determine_evaluator_names({"intent_gold": _gold()}) == ["intent"]

    def test_intent_wins_over_probe_when_both_present(self):
        from evals_core.runner.suite_runner import _determine_evaluator_names

        assert _determine_evaluator_names({"intent_gold": _gold(), "probe_gold": {"xfail": False}}) == ["intent"]

    def test_probe_still_exclusive_without_intent(self):
        from evals_core.runner.suite_runner import _determine_evaluator_names

        assert _determine_evaluator_names({"probe_gold": {"xfail": False}}) == ["probe"]
