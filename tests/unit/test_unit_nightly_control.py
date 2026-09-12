"""nightly_control（内置调度器+流水线挂接）与 paths 约定单测：全内置，无 GitHub。"""
import asyncio
import json
import os
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest import mock
from zoneinfo import ZoneInfo

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "../.."))
for _rel in ("services/aichat-api", "services/evals-core/src", "services/ai-inference/src"):
    p = os.path.join(ROOT, _rel)
    if p not in sys.path:
        sys.path.insert(0, p)

import nightly_control as nc  # noqa: E402
from evals_core.nightly import paths as npaths  # noqa: E402

BJT = ZoneInfo("Asia/Shanghai")


class _TmpSettings(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = str(Path(self.tmp.name) / "nightly_settings.json")
        patch = mock.patch.dict(os.environ, {"NIGHTLY_SETTINGS_FILE": self.path})
        patch.start()
        self.addCleanup(patch.stop)


class PathsTests(unittest.TestCase):
    def test_default_paths_follow_result_store(self):
        from evals_core.storage import result_store
        with tempfile.TemporaryDirectory() as td, mock.patch.dict(os.environ, {}, clear=True):
            with mock.patch.object(result_store, "_DB_PATH", str(Path(td) / "evals" / "evals.sqlite")):
                self.assertEqual(str(npaths.settings_file()),
                                 str(Path(td) / "evals" / "nightly_settings.json"))
                self.assertEqual(str(npaths.nightly_root()), str(Path(td) / "evals" / "nightly"))
                self.assertEqual(str(npaths.baseline_dir()), str(Path(td) / "evals" / "baseline"))
                self.assertEqual(str(npaths.dataset_json_path("ds-1")),
                                 str(Path(td) / "evals" / "datasets" / "ds-1.json"))
                # 文件名跟着 MANIFEST_DEFAULT 走（v3 题集时代曾在此硬编码 v2 造成升级后测试空转失败）
                self.assertEqual(
                    str(npaths.manifest_path()),
                    str(Path(td) / "open_ragbench" / "subset" / Path(npaths.MANIFEST_DEFAULT).name))


class SettingsTests(_TmpSettings):
    def test_defaults_when_missing(self):
        cfg = nc.load_settings()
        self.assertEqual(cfg["enabled"], True)  # 每晚定时执行是默认选择
        self.assertEqual((cfg["hour"], cfg["minute"]), (1, 0))
        # 题集代际升级（v2→v3）时这里别再硬编码——测的是"缺文件时逐键回退 DEFAULT_SETTINGS"
        self.assertEqual(cfg["dataset_id"], nc.DEFAULT_SETTINGS["dataset_id"])
        self.assertIsNone(cfg["last_dispatch"])

    def test_roundtrip_keeps_new_keys_and_history(self):
        cfg = nc.normalize_settings({"enabled": True, "hour": 2, "minute": 30,
                                     "dataset_id": "smoke", "timeout_minutes": 60, "retry_rounds": 1})
        cfg["last_dispatch"] = {"slot": "s", "ok": True}
        nc.save_settings(cfg)
        again = nc.load_settings()
        self.assertEqual(again["dataset_id"], "smoke")
        self.assertEqual((again["hour"], again["minute"]), (2, 30))
        self.assertEqual(again["timeout_minutes"], 60)
        self.assertEqual(again["last_dispatch"]["slot"], "s")

    def test_normalize_validation(self):
        ok = nc.normalize_settings({"enabled": True, "hour": 23, "minute": 59})
        self.assertEqual(ok["retry_rounds"], 2)  # 缺省补齐
        for bad in ({"hour": 24}, {"minute": 60}, {"timeout_minutes": 9}, {"retry_rounds": 4},
                    {"dataset_id": "a/../b"}, {"dataset_id": ""}, "not-dict", {"enabled": "yes"}):
            with self.assertRaises(ValueError):
                nc.normalize_settings(bad)

    def test_load_tolerates_corrupt_file(self):
        Path(self.path).write_text("{坏 json", encoding="utf-8")
        self.assertEqual(nc.load_settings()["enabled"], True)  # 损坏退回默认=启用定时


class FireTimeTests(unittest.TestCase):
    def test_next_fire_uses_beijing_time(self):
        now = datetime(2026, 9, 6, 9, 0, tzinfo=timezone.utc)  # 北京 17:00
        nxt = nc.next_fire_at({"enabled": True, "hour": 1, "minute": 0}, now)
        self.assertEqual(nxt.astimezone(BJT).strftime("%Y-%m-%d %H:%M"), "2026-09-07 01:00")

    def test_due_gate_slot_idempotent(self):
        cfg = {"enabled": True, "hour": 1, "minute": 0}
        before = datetime(2026, 9, 6, 16, 0, tzinfo=timezone.utc)
        after = datetime(2026, 9, 6, 17, 5, tzinfo=timezone.utc)
        self.assertFalse(nc.due(cfg, before))
        self.assertTrue(nc.due(cfg, after))
        self.assertFalse(nc.due(dict(cfg, last_dispatch={"slot": nc.slot_of(cfg, after)}), after))
        self.assertFalse(nc.due(dict(cfg, enabled=False), after))

    def test_due_manual_dispatch_satisfies_today_slot(self):
        """manual 派发（slot 带 "manual:" 前缀）满足当日幂等：当天不再被调度器补跑；
        次日时段到、无更新派发时仍能正常触发（2026-09-07 幽灵评测事故回归）。"""
        cfg = {"enabled": True, "hour": 1, "minute": 0}
        manual = {"slot": "manual:2026-09-07T16:41+08:00", "at": "2026-09-07T16:41:14+08:00", "ok": True}
        same_day = datetime(2026, 9, 7, 10, 0, tzinfo=timezone.utc)  # 北京 18:00，manual 之后
        self.assertFalse(nc.due(dict(cfg, last_dispatch=manual), same_day))
        next_day = datetime(2026, 9, 8, 1, 5, tzinfo=timezone.utc)   # 北京 09:05，新一天时段已过
        self.assertTrue(nc.due(dict(cfg, last_dispatch=manual), next_day))
        # at 缺失/不可解析时保持旧行为：时段后即视为该跑，宁可多跑不漏跑
        self.assertTrue(nc.due(dict(cfg, last_dispatch={"slot": "manual:x"}), same_day))


class RunPlanTests(unittest.TestCase):
    def test_plan_shape_models_and_concurrency(self):
        ns = lambda **kw: type("Ns", (), kw)
        with tempfile.TemporaryDirectory() as td, mock.patch.dict(
                os.environ, {"NIGHTLY_SETTINGS_FILE": str(Path(td) / "s.json"), "EVAL_CONCURRENCY": "5"}):
            with mock.patch("evals_core.dataset.manager.get_dataset",
                            return_value={"dataset_id": "ds-1", "title": "冒烟集", "question_count": 25}), \
                 mock.patch("evals_core.runner.answer_eval._judge_candidates",
                            return_value=["DeepSeek-V4-Flash-Judge", None]), \
                 mock.patch("ai_inference.llm_config.load_llm_models_from_env",
                            return_value=[ns(name="Qwen3.6-35B"), ns(name="Other")]):
                plan = nc.run_plan()
        self.assertEqual(plan["dataset"]["title"], "冒烟集")
        self.assertEqual(plan["dataset"]["question_count"], 25)
        self.assertEqual(plan["answer_model"], "Qwen3.6-35B")
        self.assertEqual(plan["judge_models"], ["DeepSeek-V4-Flash-Judge", "兜底=作答模型"])
        self.assertEqual(plan["concurrency"], 5)


class LaunchTests(unittest.TestCase):
    """launch 并发锁 + 结束后 last_dispatch 记录（scheduler 槽位幂等 / manual 不占槽）。"""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        env = mock.patch.dict(os.environ, {"NIGHTLY_SETTINGS_FILE": str(Path(self.tmp.name) / "s.json")})
        env.start()
        self.addCleanup(env.stop)
        self.result = {"state": "green", "ok": True, "run_id": "run-x", "detail": ""}
        nc._active = None

    async def _fake_pipeline(self, **kwargs):
        return dict(self.result)

    def test_launch_records_manual_result(self):
        with mock.patch.object(nc.pipeline, "run_nightly", side_effect=self._fake_pipeline):
            nc._active = None

            async def scenario():
                started = await nc.launch("manual")
                self.assertTrue(started["ok"])
                await nc._active
            asyncio.run(scenario())
        stored = json.loads(Path(nc.paths.settings_file()).read_text(encoding="utf-8"))
        self.assertTrue(stored["last_dispatch"]["slot"].startswith("manual:"))
        self.assertEqual(stored["last_dispatch"]["state"], "green")

    def test_scheduler_slot_recorded_and_blocks_same_slot(self):
        cfg = nc.normalize_settings({"enabled": True, "hour": 1, "minute": 0})
        now = datetime(2026, 9, 6, 17, 5, tzinfo=timezone.utc)
        nc._record(cfg, now, "scheduler", nc.slot_of(cfg, now), self.result)
        stored = nc.load_settings()
        self.assertEqual(stored["last_dispatch"]["slot"], "2026-09-07 01:00")
        self.assertFalse(nc.due(stored, now))  # 同槽不重复触发

    def test_launch_rejects_concurrent(self):
        nc._active = None

        async def scenario():
            holder = asyncio.create_task(asyncio.sleep(30))
            nc._active = holder
            second = await nc.launch("manual")
            holder.cancel()
            return second
        second = asyncio.run(scenario())
        self.assertFalse(second["ok"])
        self.assertIn("运行", second["detail"])


class StopAndRunningRowTests(unittest.TestCase):
    """手动停止（不留痕不发通知）与列表虚拟运行行的编排/字段口径。"""

    def tearDown(self):
        nc._stop_requested = False
        nc._current_run_id = ""
        nc._active = None

    def test_stop_rejected_when_not_running(self):
        nc._active = None
        r = nc.stop_pipeline()
        self.assertFalse(r["ok"])
        self.assertFalse(nc._stop_requested)

    def test_stop_sets_flag_and_stops_current_run(self):
        stop_mock = mock.MagicMock(return_value=True)

        async def scenario():
            holder = asyncio.create_task(asyncio.sleep(30))
            nc._active = holder
            nc._current_run_id = "run-abc"
            with mock.patch.object(nc.suite_runner, "stop_eval_run", stop_mock):
                r = nc.stop_pipeline()
            holder.cancel()
            return r

        r = asyncio.run(scenario())
        self.assertTrue(r["ok"])
        self.assertEqual(r["run_id"], "run-abc")
        self.assertTrue(nc._stop_requested)  # 收口靠它：不落 error 档、不发通知
        stop_mock.assert_called_once_with("run-abc")

    def test_stopped_pipeline_publishes_nothing(self):
        """should_stop 置位 → run 被取消也走 stopped 收口：不落盘、不发企微。"""
        from evals_core.nightly import pipeline

        seen = []

        async def scenario():
            with mock.patch.object(pipeline.suite_runner, "start_eval_run",
                                   return_value={"run_id": "run-9"}), \
                 mock.patch.object(pipeline.suite_runner, "stop_eval_run") as stop_mock, \
                 mock.patch.object(pipeline.result_store, "get_run",
                                   return_value={"status": "cancelled"}), \
                 mock.patch.object(pipeline.archive, "publish_day") as pub, \
                 mock.patch.object(pipeline.notify, "send") as send:
                res = await pipeline.run_nightly(
                    dataset_id="ds-a", retry_rounds=0,
                    on_run_started=seen.append, should_stop=lambda: True)
            return res, stop_mock, pub, send

        res, stop_mock, pub, send = asyncio.run(scenario())
        self.assertEqual(seen, ["run-9"])  # 开跑即上报 run_id（列表运行行的进度来源）
        stop_mock.assert_called_once_with("run-9")
        self.assertEqual(res["state"], "stopped")
        self.assertFalse(res["ok"])
        pub.assert_not_called()
        send.assert_not_called()

    def test_running_entry_fields_and_none_when_not_running(self):
        nc._active = None
        self.assertIsNone(nc.running_entry())

    def test_running_entry_seed_row_during_start_gap(self):
        """起跑间隙（run 未上报/未建档）也有行——点「立即运行」立即可见"启动中"。"""
        async def scenario():
            holder = asyncio.create_task(asyncio.sleep(30))
            nc._active = holder
            nc._current_run_id = ""
            seed = nc.running_entry()
            holder.cancel()
            return seed

        seed = asyncio.run(scenario())
        self.assertTrue(seed["running"])
        self.assertIsNone(seed["correct"])
        self.assertIn("启动中", seed["verdict"])

    def test_running_entry_fields_and_none_when_running_row_exists(self):
        async def scenario():
            holder = asyncio.create_task(asyncio.sleep(30))
            nc._active = holder
            nc._current_run_id = "run-live"
            with mock.patch.object(nc.result_store, "get_run", return_value={
                    "status": "running", "started_at": "2026-09-07T07:09:53.188818",
                    "completed_questions": 43, "total_questions": 487}):
                entry = nc.running_entry()
            holder.cancel()
            return entry

        entry = asyncio.run(scenario())
        self.assertEqual(entry["date"], "running")
        self.assertTrue(entry["running"])
        self.assertEqual(entry["state"], "running")
        self.assertEqual((entry["correct"], entry["total"]), (43, 487))
        # evals 库存 UTC naive 起跑时刻，展示口径统一带北京偏移
        self.assertTrue(entry["generated_at"].startswith("2026-09-07T15:09"))
        self.assertTrue(entry["generated_at"].endswith("+08:00"))


class TestResolveWebhook(unittest.TestCase):
    """通知目标解析：两群变量优先，皆空回退旧部署契约（迁移期静默失效防复发）。"""

    _KEYS = ("WEBHOOK_SYSTEM", "WEBHOOK_OWNER", "NIGHTLY_WECOM_WEBHOOK", "WEBHOOK")

    def _resolve(self, **env):
        full = {k: "" for k in self._KEYS}
        full.update(env)
        with mock.patch.dict(os.environ, full, clear=False):
            return nc._resolve_webhook()

    def test_system_and_owner_joined(self):
        self.assertEqual(
            self._resolve(WEBHOOK_SYSTEM=" https://a ", WEBHOOK_OWNER="https://b"),
            "https://a,https://b")

    def test_multi_group_in_one_var_preserved(self):
        self.assertEqual(self._resolve(WEBHOOK_SYSTEM="https://a,https://b"), "https://a,https://b")

    def test_legacy_nightly_var_fallback(self):
        self.assertEqual(self._resolve(NIGHTLY_WECOM_WEBHOOK="https://a;https://b"), "https://a;https://b")

    def test_legacy_webhook_var_fallback(self):
        self.assertEqual(self._resolve(WEBHOOK="https://c"), "https://c")

    def test_new_var_beats_legacy(self):
        self.assertEqual(
            self._resolve(WEBHOOK_OWNER="https://o", NIGHTLY_WECOM_WEBHOOK="https://legacy"),
            "https://o")

    def test_none_configured_empty(self):
        self.assertEqual(self._resolve(), "")


if __name__ == "__main__":
    unittest.main()
