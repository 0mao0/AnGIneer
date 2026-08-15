"""阶段 0 契约测试：RouteDecision / ScopeContext / Evidence 类型定义（不改链路行为）。"""
import os
import sys
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../../services/angineer-core/src")))

from angineer_core.base_contracts import (  # noqa: E402
    Evidence,
    IntentResult,
    RouteDebug,
    RouteDecision,
    ScopeContext,
)


class ScopeContextTests(unittest.TestCase):
    def test_default_library_is_default_but_explicit(self):
        scope = ScopeContext()
        self.assertEqual(scope.library_id, "default")
        self.assertEqual(scope.doc_ids, [])
        self.assertEqual(scope.filters, {})

    def test_explicit_values_are_kept(self):
        scope = ScopeContext(
            library_id="lib-a",
            doc_ids=["d1", "d2"],
            filters={"section_path": "第1章"},
            source="request",
            request_id="req-1",
        )
        self.assertEqual(scope.library_id, "lib-a")
        self.assertEqual(scope.doc_ids, ["d1", "d2"])
        self.assertEqual(scope.filters["section_path"], "第1章")
        self.assertEqual(scope.request_id, "req-1")


class RouteDebugTests(unittest.TestCase):
    def test_defaults(self):
        debug = RouteDebug()
        self.assertFalse(debug.fallback)
        self.assertEqual(debug.confidence, 0.0)
        self.assertIsNone(debug.level)
        self.assertIsNone(debug.service_mode)
        self.assertIsNone(debug.reason)


class RouteDecisionTests(unittest.TestCase):
    def test_defaults_are_safe(self):
        decision = RouteDecision()
        self.assertEqual(decision.scene, "qa")
        self.assertFalse(decision.fallback)
        self.assertFalse(decision.route_debug.fallback)
        self.assertEqual(decision.scope.library_id, "default")
        self.assertEqual(decision.attempts, [])
        self.assertIsInstance(decision.intent_result, IntentResult)

    def test_fallback_decision_carries_debug(self):
        decision = RouteDecision(
            scene="docs",
            fallback=True,
            route_debug=RouteDebug(fallback=True, reason="classifier_error"),
        )
        self.assertTrue(decision.fallback)
        self.assertTrue(decision.route_debug.fallback)
        self.assertEqual(decision.route_debug.reason, "classifier_error")

    def test_json_round_trip(self):
        decision = RouteDecision(
            scene="docs",
            scope=ScopeContext(library_id="lib-a", doc_ids=["d1"]),
            attempts=["L2 条款/表格定位", "L1 语义检索"],
            confidence=0.8,
            route_debug=RouteDebug(level="L2", service_mode="sql_first", confidence=0.8),
        )
        restored = RouteDecision.model_validate_json(decision.model_dump_json())
        self.assertEqual(restored.scope.library_id, "lib-a")
        self.assertEqual(restored.attempts, ["L2 条款/表格定位", "L1 语义检索"])
        self.assertEqual(restored.route_debug.level, "L2")


class EvidenceTests(unittest.TestCase):
    def test_requires_evidence_id(self):
        with self.assertRaises(Exception):
            Evidence()

    def test_defaults_and_kinds(self):
        ev = Evidence(evidence_id="e1")
        self.assertEqual(ev.kind, "text")
        self.assertEqual(ev.library_id, "default")
        table = Evidence(evidence_id="t1", kind="table", source="table", score=0.9)
        self.assertEqual(table.kind, "table")
        self.assertEqual(table.source, "table")

    def test_json_round_trip(self):
        ev = Evidence(
            evidence_id="e1",
            kind="formula",
            doc_id="d1",
            doc_title="规范",
            content="E=mc^2",
            page_idx=3,
            section_path="第2章",
            score=0.7,
            source="formula",
        )
        restored = Evidence.model_validate_json(ev.model_dump_json())
        self.assertEqual(restored.evidence_id, "e1")
        self.assertEqual(restored.page_idx, 3)
        self.assertEqual(restored.section_path, "第2章")


if __name__ == "__main__":
    unittest.main()
