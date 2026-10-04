"""中断档重判（req-nightly-interrupt-resume §2-B2 / 验收 A2）。

slot 名（HHMM-6hex）不含 run_id，corrupt 挡 ↔ 带中断章 cancelled run 按
「活跃区间覆盖挡日期 + 同日内定序配对」重判为 interrupted；无候选 / 无章
（人为停止）/ JSON 真不可读 一律维持 corrupt。
"""

import json
import sys
import tempfile
import unittest
from pathlib import Path

TESTS_DIR = Path(__file__).resolve().parent
SRC = TESTS_DIR.parent / "src"
for p in (str(SRC), str(TESTS_DIR)):
    if p not in sys.path:
        sys.path.insert(0, p)

from evals_core.nightly import archive
from evals_core.storage import result_store

DS = "ds-nightly"


class InterruptedCase(unittest.TestCase):
    """临时 evals 库 + 临时 nightly 目录；Windows 上先关连接再删临时目录。"""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self._orig_db = result_store._DB_PATH
        result_store._DB_PATH = str(Path(self._tmp.name) / "evals.sqlite")
        result_store._LOCAL = None
        result_store.init_db()
        self.root = Path(self._tmp.name) / "nightly"
        self.day_dir = self.root / "2026-10-04"

    def tearDown(self):
        try:
            conn = result_store._get_conn()
        except Exception:
            conn = None
        if conn is not None:
            try:
                conn.close()
            except Exception:
                pass
        result_store._LOCAL = None
        result_store._DB_PATH = self._orig_db
        self._tmp.cleanup()

    # ---- 造数 ----

    def insert_interrupted_run(self, run_id: str, started_utc: str, ended_utc: str,
                               completed: int = 869, total: int = 1040,
                               correct: int = 758, wrong: int = 107, stamp: bool = True,
                               dataset_id: str = DS) -> None:
        """cancelled run；stamp=True 盖启动清扫中断章（部署砸掉），False=人为停止。"""
        summary = {"overall_score": 0.0, "total": total, "correct": correct, "wrong": wrong,
                   "skipped": total - completed, "errored": 0}
        if stamp:
            summary["interrupted_by_startup_sweep"] = True
        conn = result_store._get_conn()
        conn.execute(
            "INSERT INTO eval_run (run_id, dataset_id, status, total_questions,"
            " completed_questions, started_at, completed_at, summary_scores, owner_pid)"
            " VALUES (?, ?, 'cancelled', ?, ?, ?, ?, ?, 1)",
            (run_id, dataset_id, total, completed, started_utc, ended_utc,
             json.dumps(summary, ensure_ascii=False)),
        )
        conn.commit()

    def make_slot(self, slot: str, material: bool = True) -> Path:
        """中断现场：有 B 层素材产物、无 nightly.json。"""
        slot_dir = self.day_dir / archive.RUNS_SUBDIR / slot
        slot_dir.mkdir(parents=True, exist_ok=True)
        if material:
            (slot_dir / "material_parity.json").write_text("{}", encoding="utf-8")
        return slot_dir

    def entries(self, dataset_id: str = DS):
        return archive.list_entries(self.day_dir, "2026-10-04", dataset_id=dataset_id)

    # ---- A2 行为锁 ----

    def test_interrupted_slot_resolved_with_db_fields(self):
        # 北京 16:08 起跑（UTC 08:08）、20:31 盖章（UTC 12:31）——10-04 实踩形态
        self.insert_interrupted_run("run-061266cfa555", "2026-10-04T08:08:07", "2026-10-04T12:31:00")
        self.make_slot("1608-abcdef")
        got = self.entries()
        self.assertEqual(len(got), 1)
        e = got[0]
        self.assertEqual(e["state"], "interrupted")
        self.assertEqual(e["run_id"], "run-061266cfa555")
        self.assertEqual(e["started_at"], "2026-10-04T16:08:07+08:00")   # UTC naive → 北京
        self.assertEqual(e["generated_at"], "2026-10-04T20:31:00+08:00")  # 盖章时刻=时长终点
        self.assertEqual((e["progress"]["completed"], e["progress"]["total"]), (869, 1040))
        self.assertEqual(e["progress"]["correct"], 758)
        self.assertIn("继续评测", e["verdict"])
        self.assertNotIn("overall_score", e)  # sweep 的 0.0 绝不进「平均分」列

    def test_no_candidate_stays_corrupt(self):
        self.make_slot("1608-abcdef")
        got = self.entries()
        self.assertEqual(got[0]["state"], "corrupt")

    def test_unstamped_cancelled_stays_corrupt(self):
        """人为停止（无章 cancelled）不归入中断：与续跑探测同判据，中断=可续跑。"""
        self.insert_interrupted_run("run-manual-stop", "2026-10-04T08:08:07",
                                    "2026-10-04T09:00:00", stamp=False)
        self.make_slot("1608-abcdef")
        self.assertEqual(self.entries()[0]["state"], "corrupt")

    def test_broken_json_stays_corrupt(self):
        """结论文件真不可读 = 真损坏，即使同日有带章 run 也不重判。"""
        self.insert_interrupted_run("run-x", "2026-10-04T08:08:07", "2026-10-04T12:31:00")
        slot_dir = self.make_slot("1608-abcdef")
        (slot_dir / "nightly.json").write_text("{坏 json", encoding="utf-8")
        got = self.entries()
        self.assertEqual(got[0]["state"], "corrupt")
        self.assertEqual(got[0]["corrupt_reason"], "unreadable")

    def test_candidate_on_other_day_not_matched(self):
        """活跃区间不覆盖挡日期 → 不硬凑。"""
        self.insert_interrupted_run("run-old", "2026-10-01T08:00:00", "2026-10-01T09:00:00")
        self.make_slot("1608-abcdef")
        self.assertEqual(self.entries()[0]["state"], "corrupt")

    def test_cross_day_stamp_covers_slot_day(self):
        """23:55 起跑、次日 00:10 重启盖章：completed_at 跨日仍覆盖前一天的挡。"""
        self.insert_interrupted_run("run-cross", "2026-10-03T15:55:00", "2026-10-03T16:10:00")
        # 北京日期：started 10-03 23:55，盖章 10-04 00:10 → 覆盖 10-03 与 10-04
        slot_dir = self.root / "2026-10-03" / archive.RUNS_SUBDIR / "2355-abcdef"
        slot_dir.mkdir(parents=True, exist_ok=True)
        (slot_dir / "material_parity.json").write_text("{}", encoding="utf-8")
        got = archive.list_entries(self.root / "2026-10-03", "2026-10-03", dataset_id=DS)
        self.assertEqual(got[0]["state"], "interrupted")

    def test_multi_slot_pairing_is_deterministic(self):
        """同日两挡两候选：挡名序 ↔ started_at 序 一一配对，互不串档。"""
        self.insert_interrupted_run("run-early", "2026-10-04T01:00:00", "2026-10-04T02:00:00",
                                    completed=100, total=487)
        self.insert_interrupted_run("run-late", "2026-10-04T08:00:00", "2026-10-04T12:00:00",
                                    completed=869, total=1040)
        self.make_slot("0900-aaaaaa")   # 北京 09:00 档 ↔ run-early（UTC 01:00=北京 09:00）
        self.make_slot("1608-bbbbbb")   # 北京 16:08 档 ↔ run-late
        got = {e["slot"]: e for e in self.entries()}
        self.assertEqual(got["0900-aaaaaa"]["run_id"], "run-early")
        self.assertEqual(got["0900-aaaaaa"]["progress"]["completed"], 100)
        self.assertEqual(got["1608-bbbbbb"]["run_id"], "run-late")

    def test_dataset_filter_excludes_other_dataset_runs(self):
        self.insert_interrupted_run("run-other-ds", "2026-10-04T08:08:07",
                                    "2026-10-04T12:31:00", dataset_id="ds-other")
        self.make_slot("1608-abcdef")
        self.assertEqual(self.entries(dataset_id=DS)[0]["state"], "corrupt")

    def test_normal_entries_untouched_and_sort(self):
        """绿档不被重判影响；interrupted 带 started_at 参与正常时间排序（不再垫底）。"""
        archive.publish_day(
            {**{"state": "green", "overall_score": 0.9, "correct": 480, "total": 487,
                "verdict": "v"}, "date": "2026-10-04",
             "started_at": "2026-10-04T01:00:00+08:00"},
            None, root=self.root, slot="0100-cccccc")
        self.insert_interrupted_run("run-late", "2026-10-04T08:00:00", "2026-10-04T12:00:00")
        self.make_slot("1608-abcdef")
        got = self.entries()
        self.assertEqual([e["state"] for e in got], ["interrupted", "green"])  # 新→旧按开跑时刻
        green = got[1]
        self.assertEqual(green["overall_score"], 0.9)


class RunningStateCase(InterruptedCase):
    """在跑中重判（2026-10-05 实踩）：评测跑了 3 小时、结论文件还没写，页面不得顶「损坏」。"""

    def insert_running_run(self, run_id: str, started_utc: str, completed: int = 822,
                           total: int = 1040, dataset_id: str = DS) -> None:
        conn = result_store._get_conn()
        conn.execute(
            "INSERT INTO eval_run (run_id, dataset_id, status, total_questions,"
            " completed_questions, started_at, owner_pid)"
            " VALUES (?, ?, 'running', ?, ?, ?, 1)",
            (run_id, dataset_id, total, completed, started_utc),
        )
        conn.commit()

    def test_missing_slot_with_running_run_is_running(self):
        """实况复刻：北京 04:01 起跑（容器=北京时区、started_at 同值）、挡名 0400、无结论文件。"""
        self.insert_running_run("run-79a5e37a9a39", "2026-10-04T04:01:03")
        self.make_slot("0400-efccaf")
        got = self.entries()
        e = got[0]
        self.assertEqual(e["state"], "running")
        self.assertEqual(e["run_id"], "run-79a5e37a9a39")
        # started_at 展示暂维持 _to_bjt 原语义（UTC naive→北京）；容器=北京时区的口径问题另案
        self.assertEqual(e["started_at"], "2026-10-04T12:01:03+08:00")
        self.assertEqual((e["correct"], e["total"]), (822, 1040))
        self.assertIn("评测进行中", e["verdict"])
        self.assertTrue(e["generated_at"])  # 时长列锚点：现在−起跑

    def test_running_not_matched_when_run_started_other_day(self):
        """起跑日期不覆盖挡日期 → 不硬凑，维持 corrupt。"""
        self.insert_running_run("run-old", "2026-10-01T01:00:00")
        self.make_slot("1608-abcdef")
        self.assertEqual(self.entries()[0]["state"], "corrupt")

    def test_running_other_dataset_stays_corrupt(self):
        self.insert_running_run("run-other", "2026-10-04T20:01:03", dataset_id="ds-other")
        self.make_slot("1608-abcdef")
        self.assertEqual(self.entries(dataset_id=DS)[0]["state"], "corrupt")

    def test_running_and_interrupted_slots_resolve_independently(self):
        """同库双挡（10-05 生产实况）：10-04 在跑挡配 running run、10-05 挡维持 corrupt
        （running run 活跃区间不覆盖次日），互不串。"""
        self.insert_running_run("run-live", "2026-10-04T04:01:03")
        self.make_slot("1201-living")   # started 北京 10-04 12:01（_to_bjt 语义）覆盖 10-04
        slot2 = self.root / "2026-10-05" / archive.RUNS_SUBDIR / "0400-tmr"
        slot2.mkdir(parents=True)
        (slot2 / "material_parity.json").write_text("{}", encoding="utf-8")
        got = {e["slot"]: e["state"] for e in self.entries()}
        self.assertEqual(got, {"1201-living": "running"})
        # 10-05 无 running/cancelled 候选 → 维持 corrupt
        got2 = archive.list_entries(self.root / "2026-10-05", "2026-10-05", dataset_id=DS)
        self.assertEqual(got2[0]["state"], "corrupt")

    def test_unreadable_never_becomes_running(self):
        """真损坏（文件在、读不动）不参与重判：有在跑 run 也维持 corrupt/unreadable。"""
        self.insert_running_run("run-live", "2026-10-04T20:01:03")
        slot_dir = self.make_slot("0400-efccaf")
        (slot_dir / "nightly.json").write_text("{坏 json", encoding="utf-8")
        got = self.entries()
        self.assertEqual(got[0]["state"], "corrupt")
        self.assertEqual(got[0]["corrupt_reason"], "unreadable")


if __name__ == "__main__":
    unittest.main()
