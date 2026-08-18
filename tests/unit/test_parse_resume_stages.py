# -*- coding: utf-8 -*-
import os
import sys
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../../services/docs-api")))

from resume_stages import compute_resume_stages


class ComputeResumeStagesTests(unittest.TestCase):
    def test_all_scope_skips_completed_and_resumes_from_running(self):
        rows = [
            {"stage": "source_prep", "status": "completed"},
            {"stage": "convert", "status": "skipped"},
            {"stage": "raw_parse", "status": "completed"},
            {"stage": "popo", "status": "running"},
        ]
        self.assertEqual(
            compute_resume_stages("all", rows),
            ["popo", "structure", "fts", "vectors", "graph"],
        )

    def test_structure_scope_only_resumes_structure(self):
        rows = [{"stage": "structure", "status": "running"}]
        self.assertEqual(compute_resume_stages("structure", rows), ["structure"])

    def test_all_scope_includes_index_stages(self):
        rows = [
            {"stage": "source_prep", "status": "completed"},
            {"stage": "convert", "status": "skipped"},
            {"stage": "raw_parse", "status": "completed"},
            {"stage": "popo", "status": "completed"},
            {"stage": "structure", "status": "completed"},
            {"stage": "fts", "status": "completed"},
            {"stage": "vectors", "status": "failed"},
        ]
        self.assertEqual(compute_resume_stages("all", rows), ["vectors", "graph"])

    def test_legacy_inference_adds_structure(self):
        rows = [
            {"stage": "source_prep", "status": "completed"},
            {"stage": "convert", "status": "skipped"},
            {"stage": "raw_parse", "status": "completed"},
            {"stage": "popo", "status": "running"},
        ]
        self.assertEqual(compute_resume_stages("", rows), ["popo", "structure"])

    def test_legacy_empty_rows_defaults_to_structure(self):
        self.assertEqual(compute_resume_stages("", []), ["structure"])

    def test_all_completed_returns_empty(self):
        rows = [
            {"stage": s, "status": "completed"}
            for s in ("source_prep", "convert", "raw_parse", "popo", "structure")
        ]
        self.assertEqual(compute_resume_stages("structure", rows), [])

    def test_resume_includes_stages_skipped_due_to_failed_dependency(self):
        rows = [
            {"stage": "source_prep", "status": "completed"},
            {"stage": "convert", "status": "completed"},
            {"stage": "raw_parse", "status": "completed"},
            {"stage": "popo", "status": "skipped", "message": "前置硬阶段 raw_parse 失败"},
            {"stage": "structure", "status": "skipped", "message": "前置硬阶段 raw_parse 失败"},
            {"stage": "fts", "status": "skipped", "message": "前置硬阶段 raw_parse 失败"},
            {"stage": "vectors", "status": "skipped", "message": "前置硬阶段 raw_parse 失败"},
            {"stage": "graph", "status": "skipped", "message": "前置硬阶段 raw_parse 失败"},
        ]
        self.assertEqual(
            compute_resume_stages("all", rows),
            ["popo", "structure", "fts", "vectors", "graph"],
        )

    def test_resume_keeps_legit_skipped_as_done(self):
        rows = [
            {"stage": "source_prep", "status": "completed"},
            {"stage": "convert", "status": "completed"},
            {"stage": "raw_parse", "status": "completed"},
            {"stage": "popo", "status": "skipped", "message": "无需 PoPo 强化"},
            {"stage": "structure", "status": "completed"},
            {"stage": "fts", "status": "completed"},
            {"stage": "vectors", "status": "skipped", "message": "无向量内容"},
            {"stage": "graph", "status": "completed"},
        ]
        self.assertEqual(compute_resume_stages("all", rows), [])


if __name__ == "__main__":
    unittest.main()
