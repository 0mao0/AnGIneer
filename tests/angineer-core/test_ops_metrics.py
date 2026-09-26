"""ops_metrics 观测落盘单测（需求 §4 修正：验收观测不得只依赖容器日志）。

覆盖：按日 JSONL 追加、行格式（ts_utc/ts_bj/kind/业务字段）、目录 env 覆盖、
停用开关、IO 异常静默（打点永不影响主链路）。
"""
import json
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../../services/angineer-core/src")))
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../../services/ai-inference/src")))

from angineer_core.ops_metrics import ops_enabled, ops_dir, record_event  # noqa: E402


class OpsMetricsTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self._old = {k: os.environ.get(k) for k in ("ANGINEER_OPS_DIR", "ANGINEER_OPS_DISABLE")}
        os.environ["ANGINEER_OPS_DIR"] = self._tmp.name
        os.environ.pop("ANGINEER_OPS_DISABLE", None)

    def tearDown(self):
        for k, v in self._old.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        self._tmp.cleanup()

    def test_record_event_writes_jsonl_line(self):
        record_event("ttft", {"run_id": "r1", "turns": 1, "ttft_ms": 3200})
        files = [f for f in os.listdir(self._tmp.name) if f.startswith("ttft-") and f.endswith(".jsonl")]
        self.assertEqual(len(files), 1)
        with open(os.path.join(self._tmp.name, files[0]), encoding="utf-8") as f:
            lines = [json.loads(l) for l in f if l.strip()]
        self.assertEqual(len(lines), 1)
        row = lines[0]
        self.assertEqual(row["kind"], "ttft")
        self.assertEqual(row["run_id"], "r1")
        self.assertEqual(row["ttft_ms"], 3200)
        self.assertIn("ts_utc", row)
        self.assertIn("ts_bj", row)

    def test_same_day_appends_single_file(self):
        record_event("classify", {"dur_ms": 1.0})
        record_event("classify", {"dur_ms": 2.0})
        files = [f for f in os.listdir(self._tmp.name) if f.startswith("classify-")]
        self.assertEqual(len(files), 1)
        with open(os.path.join(self._tmp.name, files[0]), encoding="utf-8") as f:
            self.assertEqual(sum(1 for _ in f), 2)

    def test_disable_switch(self):
        os.environ["ANGINEER_OPS_DISABLE"] = "1"
        self.assertFalse(ops_enabled())
        record_event("ttft", {"x": 1})
        self.assertEqual(os.listdir(self._tmp.name), [])

    def test_io_failure_swallowed(self):
        # 指向一个"文件"路径当目录用 → mkdir/open 必失败，但 record_event 不得抛
        bad = os.path.join(self._tmp.name, "not_a_dir")
        with open(bad, "w", encoding="utf-8") as f:
            f.write("x")
        os.environ["ANGINEER_OPS_DIR"] = bad
        record_event("ttft", {"x": 1})  # 不抛即通过

    def test_ops_dir_override_honored(self):
        self.assertEqual(ops_dir(), self._tmp.name)


if __name__ == "__main__":
    unittest.main()
