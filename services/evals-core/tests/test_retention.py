"""run 明细三级保留策略（2026-09-15 磁盘策略：≤3 天全量 / 3–90 天裁过程快照 / >90 天删）。

- 全量窗口（含当天）内的 run 一字节不动；
- 窗口外 90 天内的 run 只裁过程快照字段（retrieval_debug/retrieved_items/evidences/
  route_debug/flow_debug/trace_meta），answer/citations/prompt_versions 等结论字段保留——
  门禁/报告/rescore/EVAL_DEEPVAL_EXTRA=0 的补判都不依赖被裁字段；
- >90 天整 run 删除，但基线指针 run 与 running run 例外；
- 幂等：再跑一遍 enforce 不产生新的写入。
"""
import json
import os
import shutil
import sys
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "src")))

from evals_core.storage import result_store, retention  # noqa: E402


def _utc_ago(days: int, hour_bjt: int = 4):
    """days 天前（按北京时间日界）的 naive UTC 时间戳。

    固定北京 04:00（= naive UTC 前一天 20:00）：无论测试何时跑，BJT 日界都是
    days 天前，同时 UTC 日历日比 BJT 早一天——enforce 若忘做 +8h 会把它裁早（boundary 钉住）。"""
    target_bjt = (datetime.utcnow() + timedelta(hours=8) - timedelta(days=days)).replace(
        hour=hour_bjt, minute=0, second=0, microsecond=0)
    return (target_bjt - timedelta(hours=8)).isoformat(timespec="seconds")


PRED_FULL = {
    "answer": "42",
    "citations": [{"section_path": "a/b"}],
    "intent": {"intent_level": "L1"},
    "prompt_versions": {"v": 3},
    "retrieval_debug": {"candidates": "x" * 200},
    "retrieved_items": [{"text": "y" * 200}],
    "evidences": [{"content": "z" * 200}],
    "route_debug": {"steps": [1, 2, 3]},
    "flow_debug": {"trace": "w" * 100},
    "trace_meta": {"ms": 123},
}
SNAPSHOT_KEYS = {"retrieval_debug", "retrieved_items", "evidences", "route_debug", "flow_debug", "trace_meta"}
KEPT_KEYS = {"answer", "citations", "intent", "prompt_versions"}


class RetentionSuite(unittest.TestCase):
    def _reset_conn(self):
        """_get_conn 按线程缓存连接：换 _DB_PATH 必须同时清掉缓存，否则跨用例串数据。"""
        local = result_store._get_thread_local()
        conn = getattr(local, "conn", None)
        if conn is not None:
            try:
                conn.close()
            except Exception:
                pass
            del local.conn

    def setUp(self):
        self._tmp = tempfile.mkdtemp()
        self._orig_db = result_store._DB_PATH
        self._reset_conn()
        result_store._DB_PATH = str(Path(self._tmp) / "evals.sqlite")
        result_store.init_db()

    def tearDown(self):
        self._reset_conn()
        result_store._DB_PATH = self._orig_db
        shutil.rmtree(self._tmp, ignore_errors=True)

    def _mk_run(self, run_id, ago_days, status="completed"):
        conn = result_store._get_conn()
        ts = _utc_ago(ago_days)
        conn.execute(
            "INSERT INTO eval_run (run_id, dataset_id, status, total_questions, completed_questions,"
            " started_at, completed_at, summary_scores, config_snapshot, run_name, is_full_run, owner_pid)"
            " VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
            (run_id, "ds", status, 2, 2, ts, ts, "{}", "{}", "", 1, 0),
        )
        for qid in ("q1", "q2"):
            result_store.insert_run_detail({
                "run_id": run_id, "question_id": qid, "status": "ok", "quality": "",
                "prediction": dict(PRED_FULL),
                "scores": {"semantic_score": 0.9},
                "all_scores": {},
                "all_predictions": {"answer": dict(PRED_FULL)},
                "error": "", "latency_ms": 10,
            })
        conn.commit()

    def _details(self, run_id):
        conn = result_store._get_conn()
        return [dict(r) for r in conn.execute(
            "select * from eval_run_detail where run_id=? order by question_id", (run_id,))]

    def _enforce(self, **kw):
        today = (datetime.utcnow() + timedelta(hours=8)).strftime("%Y-%m-%d")
        return retention.enforce(result_store._get_conn(), today, **kw)

    def test_full_window_untouched(self):
        self._mk_run("r-fresh", 0)
        self._mk_run("r-edge", 2)  # 含当天的 3 天窗口最后一天
        stats = self._enforce()
        self.assertEqual(stats["deleted_runs"], 0)
        self.assertEqual(stats["compacted_runs"], 0)
        for rid in ("r-fresh", "r-edge"):
            d = self._details(rid)[0]
            self.assertTrue(json.loads(d["prediction"]).keys() & SNAPSHOT_KEYS,
                            f"{rid} 在全量窗口内，必须原样保留")

    def test_bjt_boundary(self):
        # naive UTC 日历日 = today-3（若忘做 +8h 会被误裁），BJT 日界 = today-2 = 全量窗口最后一天
        conn = result_store._get_conn()
        ts_utc = _utc_ago(2)
        self._mk_run("r-bound", 2)
        conn.execute("update eval_run set started_at=?, completed_at=? where run_id='r-bound'", (ts_utc, ts_utc))
        conn.commit()
        self._enforce()
        d = self._details("r-bound")[0]
        self.assertTrue(json.loads(d["prediction"]).keys() & SNAPSHOT_KEYS,
                        "BJT 日界换算错会把窗口内 run 裁掉")

    def test_compact_keeps_conclusion_fields(self):
        self._mk_run("r-mid", 10)
        stats = self._enforce()
        self.assertEqual(stats["compacted_runs"], 1)
        d = self._details("r-mid")[0]
        pred = json.loads(d["prediction"])
        self.assertEqual(pred.keys() & SNAPSHOT_KEYS, set(), "过程快照必须裁掉")
        self.assertTrue(KEPT_KEYS <= set(pred.keys()), "结论字段必须保留")
        self.assertEqual(pred["answer"], "42")
        ap = json.loads(d["all_predictions"])["answer"]
        self.assertEqual(ap.keys() & SNAPSHOT_KEYS, set(), "all_predictions 重复快照同样裁")
        self.assertEqual(d["status"], "ok")
        # 幂等：再 enforce 无新动作
        again = self._enforce()
        self.assertEqual(again["compacted_runs"], 0)

    def test_delete_after_90_days_with_protection(self):
        self._mk_run("r-old", 95)
        self._mk_run("r-baseline", 200)
        self._mk_run("r-running", 95, status="running")
        stats = self._enforce(baseline_run="r-baseline")
        self.assertEqual(stats["deleted_runs"], 1, "只删未受保护的过期 run")
        conn = result_store._get_conn()
        self.assertIsNone(conn.execute("select 1 from eval_run where run_id='r-old'").fetchone())
        self.assertEqual(len(conn.execute("select 1 from eval_run_detail where run_id='r-old'").fetchall()), 0,
                         "明细必须成对删除（CASCADE 从未开启）")
        self.assertIsNotNone(conn.execute("select 1 from eval_run where run_id='r-baseline'").fetchone())
        self.assertIsNotNone(conn.execute("select 1 from eval_run where run_id='r-running'").fetchone())

    def test_unparseable_prediction_survives(self):
        self._mk_run("r-bad", 10)
        conn = result_store._get_conn()
        conn.execute("update eval_run_detail set prediction='not json' where run_id='r-bad' and question_id='q1'")
        conn.commit()
        self._enforce()  # 不崩
        d = self._details("r-bad")[0]
        self.assertEqual(d["prediction"], "not json", "解析失败的行原样保留，不造数据")

    def test_baseline_pointer_read(self):
        base_dir = Path(result_store._DB_PATH).parent / "baseline"
        base_dir.mkdir(parents=True)
        (base_dir / "baseline_run.json").write_text(json.dumps({"run_id": "run-pin"}), encoding="utf-8")
        self.assertEqual(retention.baseline_run_id(), "run-pin")


if __name__ == "__main__":
    unittest.main()
