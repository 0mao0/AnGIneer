"""nightly 结论 started_at 字段：UTC naive 规范化为北京 +08、缺省留空（前端时长列的数据契约）。"""
import os
import sys
import unittest

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "../.."))
P = os.path.join(ROOT, "services", "evals-core", "src")
if P not in sys.path:
    sys.path.insert(0, P)

from evals_core.nightly import archive  # noqa: E402


class TestToBJT(unittest.TestCase):
    def test_utc_naive_converted(self):
        # evals 库存的是 UTC naive（容器 UTC）：17:00 = 北京次日 01:00
        self.assertEqual(archive._to_bjt("2026-09-08T17:00:00"), "2026-09-09T01:00:00+08:00")

    def test_aware_passthrough_converted(self):
        self.assertEqual(archive._to_bjt("2026-09-08T17:00:00+00:00"), "2026-09-09T01:00:00+08:00")

    def test_empty_and_bad(self):
        self.assertEqual(archive._to_bjt(""), "")
        self.assertEqual(archive._to_bjt("not-a-date"), "")


class TestEntryContract(unittest.TestCase):
    def test_build_entry_carries_bjt_started_at(self):
        entry = archive.build_entry(
            {"matrix": {}, "delta": 0.03}, {"overall_score": 0.88}, {},
            "ds-1", "2026-09-09", run_id="run-x", started_at="2026-09-08T17:00:00")
        self.assertEqual(entry["started_at"], "2026-09-09T01:00:00+08:00")
        self.assertIn("+08:00", entry["generated_at"])

    def test_build_entry_defaults_empty(self):
        # 历史兼容：不传时字段存在且为空串（前端时长列显示“—”，不是缺键）
        entry = archive.build_entry({"matrix": {}}, {}, {}, "ds-1", "2026-09-09")
        self.assertEqual(entry["started_at"], "")

    def test_build_error_entry_started_at(self):
        entry = archive.build_error_entry("ds-1", "2026-09-09", "boom", started_at="2026-09-08T17:00:00")
        self.assertEqual(entry["started_at"], "2026-09-09T01:00:00+08:00")
        self.assertEqual(archive.build_error_entry("ds-1", "2026-09-09", "boom")["started_at"], "")


if __name__ == "__main__":
    unittest.main()
