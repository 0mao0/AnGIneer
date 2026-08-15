# -*- coding: utf-8 -*-
import unittest
from unittest.mock import MagicMock, patch

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "services", "docs-core", "src"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "services", "api-server"))

from docs_core.parse_pipeline import (
    STAGE_REGISTRY,
    StageContext,
    derive_overall_status,
    resolve_stage_order,
    run_pipeline,
)


class TestResolveStageOrder(unittest.TestCase):
    def test_all_order(self):
        order = resolve_stage_order("all")
        self.assertEqual(
            order,
            ["source_prep", "convert", "raw_parse", "popo", "structure", "fts", "vectors", "graph"],
        )

    def test_subset_respects_dependency(self):
        order = resolve_stage_order(["graph"])
        self.assertEqual(order, ["graph"])

    def test_subset_ordering(self):
        order = resolve_stage_order(["vectors", "fts"])
        self.assertEqual(order, ["fts", "vectors"])

    def test_unknown_stage_rejected(self):
        with self.assertRaises(ValueError):
            resolve_stage_order(["bogus"])


class TestDeriveOverallStatus(unittest.TestCase):
    def _stages(self, **overrides):
        base = {key: "completed" for key in STAGE_REGISTRY}
        base.update(overrides)
        return base

    def test_all_completed(self):
        self.assertEqual(derive_overall_status(self._stages()), "completed")

    def test_soft_failure_is_partial(self):
        self.assertEqual(derive_overall_status(self._stages(vectors="failed")), "partial")

    def test_hard_failure_is_failed(self):
        self.assertEqual(derive_overall_status(self._stages(structure="failed")), "failed")

    def test_running_wins(self):
        self.assertEqual(derive_overall_status(self._stages(vectors="running")), "processing")

    def test_skipped_counts_as_done(self):
        self.assertEqual(derive_overall_status(self._stages(popo="skipped", sop="skipped")), "completed")

    def test_popo_failed_solo_ok_is_completed(self):
        self.assertEqual(derive_overall_status(self._stages(popo="failed")), "completed")

    def test_popo_failed_solo_failed_is_failed(self):
        self.assertEqual(derive_overall_status(self._stages(popo="failed", structure="failed")), "failed")

    def test_empty_is_queued(self):
        self.assertEqual(derive_overall_status({}), "queued")


class TestRunPipeline(unittest.TestCase):
    def _ctx(self):
        return StageContext(
            task_id="t1", library_id="lib", doc_id="doc1", file_path="a.pdf",
            temp_output_dir="/tmp/parse-doc1"
        )

    def setUp(self):
        self._original_runs = {}
        self._original_verifies = {}
        for key, stage_def in STAGE_REGISTRY.items():
            self._original_runs[key] = stage_def.run
            self._original_verifies[key] = stage_def.verify

    def tearDown(self):
        for key, stage_def in STAGE_REGISTRY.items():
            stage_def.run = self._original_runs[key]
            stage_def.verify = self._original_verifies[key]

    def _set_all_ok(self):
        for key, stage_def in STAGE_REGISTRY.items():
            stage_def.run = lambda ctx, k=key: f"{k} ok"
            stage_def.verify = lambda ctx, k=key: "核查通过"

    def test_verify_passes_notify_frontend(self):
        self._set_all_ok()
        meta = MagicMock()
        run_pipeline(self._ctx(), "all", meta_store=meta)
        messages = [c.kwargs.get("message") for c in meta.upsert_parse_stage.call_args_list]
        self.assertIn("核查通过", messages)

    def test_verify_failure_marks_failed(self):
        self._set_all_ok()
        STAGE_REGISTRY["convert"].verify = lambda ctx: (_ for _ in ()).throw(RuntimeError("输入不存在"))
        results = run_pipeline(self._ctx(), "all", meta_store=MagicMock())
        self.assertEqual(results["convert"], "failed")
        self.assertEqual(results["raw_parse"], "skipped")

    def test_cancel_propagates_not_failed(self):
        from docs_core.parse_pipeline import ParseTaskCancelledError
        self._set_all_ok()
        meta = MagicMock()
        def raise_cancel():
            raise ParseTaskCancelledError("cancelled")
        with self.assertRaises(ParseTaskCancelledError):
            run_pipeline(self._ctx(), "all", meta_store=meta, raise_if_cancelled=raise_cancel)
        statuses = [c.kwargs.get("status") for c in meta.upsert_parse_stage.call_args_list]
        self.assertNotIn("failed", statuses)

    def test_soft_failure_does_not_stop_later_stages(self):
        self._set_all_ok()
        STAGE_REGISTRY["vectors"].run = lambda ctx: (_ for _ in ()).throw(RuntimeError("embedding down"))
        results = run_pipeline(self._ctx(), "all", meta_store=MagicMock())
        self.assertEqual(results["vectors"], "failed")
        self.assertEqual(results["graph"], "completed")

    def test_hard_failure_skips_rest(self):
        self._set_all_ok()
        STAGE_REGISTRY["raw_parse"].run = lambda ctx: (_ for _ in ()).throw(RuntimeError("mineru down"))
        results = run_pipeline(self._ctx(), "all", meta_store=MagicMock())
        self.assertEqual(results["raw_parse"], "failed")
        self.assertEqual(results["structure"], "skipped")
        self.assertEqual(results["vectors"], "skipped")

    def test_dependency_failed_marks_skipped(self):
        self._set_all_ok()
        STAGE_REGISTRY["structure"].run = lambda ctx: (_ for _ in ()).throw(RuntimeError("solo down"))
        results = run_pipeline(self._ctx(), "all", meta_store=MagicMock())
        self.assertEqual(results["structure"], "failed")
        self.assertEqual(results["fts"], "skipped")
        self.assertEqual(results["graph"], "skipped")

    def test_skip_sentinel(self):
        self._set_all_ok()
        STAGE_REGISTRY["popo"].run = lambda ctx: "__skipped__:未启用"
        results = run_pipeline(self._ctx(), "all", meta_store=MagicMock())
        self.assertEqual(results["popo"], "skipped")
        self.assertEqual(results["structure"], "completed")


class TestValidateStageRetry(unittest.TestCase):
    def test_retry_rejects_running_document(self):
        from docs_core.parse_pipeline import validate_stage_retry
        with self.assertRaises(ValueError):
            validate_stage_retry(node_status="processing", stage_key="vectors")

    def test_retry_rejects_unknown_stage(self):
        from docs_core.parse_pipeline import validate_stage_retry
        with self.assertRaises(ValueError):
            validate_stage_retry(node_status="completed", stage_key="bogus")

    def test_retry_accepts_valid(self):
        from docs_core.parse_pipeline import validate_stage_retry
        validate_stage_retry(node_status="completed", stage_key="vectors")


if __name__ == "__main__":
    unittest.main()
