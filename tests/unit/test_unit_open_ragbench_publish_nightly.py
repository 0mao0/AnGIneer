"""publish_nightly + notify 站点链接测试。"""
import io
import json
import os
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest import mock

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../../scripts")))

from open_ragbench import notify, publish_nightly  # noqa: E402

GATE = {
    "run_id": "a", "new": "run-new-123", "base_label": "R2 85.01%",
    "gate_red": False, "delta": 0.0267, "delta_ci95": [0.0, 0.0575],
    "matrix": {"pp": 396, "pf": 31, "fp": 18, "ff": 42, "skip": 0},
    "regressions": {"0870996e-b926": "refusal(该答却拒答/无答案)"},
    "gate_reasons": [],
}
RAW_SUMMARY = {"overall_score": 0.8768, "correct": 427, "total": 487,
               "errored": 0, "judge_failed_count": 0}


class PublishNightlyTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.artifacts = self.tmp / "evals-nightly"
        self.artifacts.mkdir()
        self.target = self.tmp / "nightly"
        self.target.mkdir()

    def _write_artifacts(self):
        (self.artifacts / "gate.json").write_text(json.dumps(GATE), encoding="utf-8")
        (self.artifacts / "raw.json").write_text(
            json.dumps({"run_id": "run-new-123", "summary_scores": RAW_SUMMARY}), encoding="utf-8")
        (self.artifacts / "report.md").write_text("# 报告 GREEN", encoding="utf-8")

    def _run_main(self, argv):
        with mock.patch.object(sys, "argv", ["publish_nightly.py"] + argv):
            return publish_nightly.main()

    def test_green_day_entry_fields(self):
        self._write_artifacts()
        entry = publish_nightly.build_nightly_entry(self.artifacts, "ds", "2026-09-06")
        self.assertEqual(entry["state"], "green")
        self.assertEqual(entry["run_id"], "run-new-123")
        self.assertEqual(entry["overall_score"], 0.8768)
        self.assertEqual(entry["delta"], 0.0267)
        self.assertEqual(entry["matrix"], {"pp": 396, "pf": 31, "fp": 18, "ff": 42})  # skip 已剔除
        self.assertEqual(list(entry["regressions"].values())[0].split("(")[0], "refusal")

    def test_red_day_state_and_reasons(self):
        gate = dict(GATE, gate_red=True, gate_reasons=["overall 净降"])
        (self.artifacts / "gate.json").write_text(json.dumps(gate), encoding="utf-8")
        entry = publish_nightly.build_nightly_entry(self.artifacts, "ds", "2026-09-06")
        self.assertEqual(entry["state"], "red")
        self.assertEqual(entry["gate_reasons"], ["overall 净降"])

    def test_missing_gate_writes_error_day(self):
        entry = publish_nightly.build_nightly_entry(
            self.artifacts, "ds", "2026-09-06", error_note="eval=failure report=skipped")
        self.assertEqual(entry["state"], "error")
        self.assertIn("eval=failure", entry["note"])
        self.assertEqual(entry["verdict"], "评测中断，未出结果")

    def _write_dataset(self):
        ds = self.tmp / "dataset.json"
        ds.write_text(json.dumps({"questions": [
            {"question_id": "q-a", "question": "题干 A 全文"},
            {"question_id": "q-c", "question": "题干 C"},
            {"question_id": "f-1", "question": "修复题 1"},
        ]}, ensure_ascii=False), encoding="utf-8")
        return ds

    def test_verdict_and_items_with_dataset(self):
        gate = dict(GATE, fixed=["f-1", "f-2"], regressions={
            "q-b": "severe_miss(sem<0.2)",
            "q-a": "refusal(该答却拒答/无答案)",
            "q-c": "refusal(该答却拒答/无答案)",
        }, regression_details={
            "q-a": {"semantic": {"base": 0.9, "new": 0.4}, "reason": "整体拒答"},
        })
        (self.artifacts / "gate.json").write_text(json.dumps(gate, ensure_ascii=False), encoding="utf-8")
        entry = publish_nightly.build_nightly_entry(
            self.artifacts, "ds", "2026-09-06", dataset_file=self._write_dataset())
        self.assertEqual(entry["verdict"], "提升 3pp，另有 3 题转错")  # 0.0267→取整 3pp；转错题数来自 regressions
        self.assertEqual([i["qid"] for i in entry["regression_items"]], ["q-a", "q-c", "q-b"])  # 按归因桶排序截断
        first = entry["regression_items"][0]
        self.assertEqual(first["bucket"], "refusal")  # 机读码与详情分离
        self.assertEqual(first["bucket_detail"], "refusal(该答却拒答/无答案)")
        self.assertEqual(first["question"], "题干 A 全文")
        self.assertEqual(first["evidence"], {"semantic": {"base": 0.9, "new": 0.4}, "reason": "整体拒答"})
        self.assertNotIn("evidence", entry["regression_items"][2])  # 无证据的题不带该键
        self.assertNotIn("evidence", entry["fixed_items"][0])       # 修复题不带证据
        self.assertEqual(entry["regression_items"][2]["question"], "")  # 题集缺该题 → 空串不炸
        self.assertEqual(entry["fixed_items"][0],
                         {"qid": "f-1", "question": "修复题 1", "bucket": "", "bucket_detail": ""})

    def test_verdict_red_counts_regressions(self):
        gate = dict(GATE, gate_red=True)
        (self.artifacts / "gate.json").write_text(json.dumps(gate), encoding="utf-8")
        entry = publish_nightly.build_nightly_entry(self.artifacts, "ds", "2026-09-06")
        self.assertEqual(entry["verdict"], "回退 1 题，需排查")
        self.assertEqual(entry["regression_items"][0]["question"], "")  # 未传题集仍可发布

    def test_items_capped(self):
        gate = dict(
            GATE,
            regressions={f"q-{i:03d}": f"severe_miss(r{i})" for i in range(60)},
            fixed=[f"f-{i:03d}" for i in range(30)],
        )
        (self.artifacts / "gate.json").write_text(json.dumps(gate), encoding="utf-8")
        entry = publish_nightly.build_nightly_entry(self.artifacts, "ds", "2026-09-06")
        self.assertEqual(len(entry["regression_items"]), publish_nightly.REGRESSION_ITEMS_MAX)
        self.assertEqual(len(entry["fixed_items"]), publish_nightly.FIXED_ITEMS_MAX)

    def test_main_end_to_end_and_prune(self):
        self._write_artifacts()
        old_day = self.target / "2026-07-01"
        old_day.mkdir()
        (old_day / "nightly.json").write_text("{}", encoding="utf-8")
        rc = self._run_main(["--artifacts", str(self.artifacts), "--target", str(self.target),
                             "--date", "2026-09-06", "--keep-days", "30", "--error-note", "x"])
        self.assertEqual(rc, 0)
        self.assertEqual((self.target / "2026-09-06" / "report.md").read_text(encoding="utf-8"), "# 报告 GREEN")
        self.assertFalse(old_day.exists())

    def test_prune_keeps_illegal_named_dirs(self):
        weird = self.target / "debug-manual"
        weird.mkdir()
        self.assertEqual(publish_nightly.prune_old(self.target, 30, "2026-09-06"), [])
        self.assertTrue(weird.exists())


class NotifySiteLinkTests(unittest.TestCase):
    """notify 查看行：站点 + 运行日志双链接；缺站点回退单链接（无 WEBHOOK 时打印文本路径）。"""

    def _run_notify(self, argv, env=None):
        buf = io.StringIO()
        with mock.patch.object(sys, "argv", ["notify.py"] + argv), \
             mock.patch.dict(os.environ, env or {}, clear=False), \
             mock.patch.dict(os.environ, {}, clear=True), redirect_stdout(buf):
            rc = notify.main()
        return rc, buf.getvalue()

    def test_dual_links(self):
        rc, out = self._run_notify(
            ["--gate-state", "success", "--site-url", "http://site/nightly", "--run-url", "http://gh/run"])
        self.assertEqual(rc, 0)
        self.assertIn("查看：[夜间维护](http://site/nightly)｜[运行日志](http://gh/run)", out)

    def test_no_site_falls_back_to_run_log_only(self):
        _, out = self._run_notify(["--gate-state", "success", "--run-url", "http://gh/run"])
        self.assertIn("查看：[运行日志](http://gh/run)", out)
        self.assertNotIn("夜间维护](", out)


if __name__ == "__main__":
    unittest.main()
