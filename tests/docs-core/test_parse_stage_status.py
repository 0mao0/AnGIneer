"""单阶段重跑后的整体状态推导：软阶段失败不能把已完成内容覆盖成 failed。"""
import os
import sys
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT / "services" / "docs-core" / "src"))

from docs_core.parse_pipeline import derive_merged_overall_status  # noqa: E402


class ParseStageStatusTests(unittest.TestCase):
    def test_soft_stage_failure_keeps_partial_not_failed(self):
        existing = {key: "completed" for key in (
            "source_prep", "convert", "raw_parse", "popo", "structure", "fts", "graph",
        )}
        status = derive_merged_overall_status(existing, {"vectors": "failed"})
        self.assertEqual(status, "partial")

    def test_hard_stage_failure_is_failed(self):
        existing = {key: "completed" for key in (
            "source_prep", "convert", "popo", "structure", "fts", "vectors", "graph",
        )}
        status = derive_merged_overall_status(existing, {"raw_parse": "failed"})
        self.assertEqual(status, "failed")

    def test_single_stage_completed_keeps_completed(self):
        existing = {key: "completed" for key in (
            "source_prep", "convert", "raw_parse", "popo", "structure", "fts", "vectors",
        )}
        status = derive_merged_overall_status(existing, {"graph": "completed"})
        self.assertEqual(status, "completed")

    def test_popo_failed_with_structure_completed_still_completed(self):
        existing = {key: "completed" for key in (
            "source_prep", "convert", "raw_parse", "structure", "fts", "vectors", "graph",
        )}
        existing["popo"] = "failed"
        status = derive_merged_overall_status(existing, {"vectors": "completed"})
        self.assertEqual(status, "completed")

    def test_dependency_skipped_stages_make_merged_status_partial(self):
        existing = {key: "skipped" for key in (
            "popo", "structure", "fts", "vectors", "graph",
        )}
        existing.update({
            "source_prep": "completed",
            "convert": "completed",
            "raw_parse": "completed",
        })
        status = derive_merged_overall_status(
            existing,
            {"raw_parse": "completed"},
            dependency_skipped={"popo", "structure", "fts", "vectors", "graph"},
        )
        self.assertEqual(status, "partial")

    def test_legit_skipped_without_dependency_marker_keeps_completed(self):
        existing = {key: "completed" for key in (
            "source_prep", "convert", "raw_parse", "popo", "structure", "fts", "vectors", "graph",
        )}
        existing["popo"] = "skipped"
        status = derive_merged_overall_status(
            existing,
            {"structure": "completed"},
            dependency_skipped={"structure", "fts"},
        )
        self.assertEqual(status, "completed")


if __name__ == "__main__":
    unittest.main()
