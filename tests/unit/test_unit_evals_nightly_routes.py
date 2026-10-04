"""夜间维护只读接口测试：鉴权（401/403）、列表/详情、日期防穿越、损坏目录降级。"""
import json
import os
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest import mock

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "../.."))
for rel in (
    "services/aichat-api",
    "services/evals-core/src",
    "services/angineer-core/src",
    "services/ai-inference/src",
    "services/sop-core/src",
):
    p = os.path.join(ROOT, rel)
    if p not in sys.path:
        sys.path.insert(0, p)

# chat_auth 依赖 models.user（docs-api 侧）——测试里用桩模块顶掉，只测路由与鉴权装配本身
_chat_auth_stub = types.ModuleType("chat_auth")
_chat_auth_stub.resolve_session_principal = lambda request: False
sys.modules.setdefault("chat_auth", _chat_auth_stub)

import evals_routes  # noqa: E402


class _Principal:
    def __init__(self, is_admin):
        self.is_admin = is_admin
        self.is_active = True
        self.library_ids = []


def _patch_auth(is_authenticated: bool, is_admin: bool = False):
    def _resolve(request):
        if not is_authenticated:
            return False
        request.state.session_user = _Principal(is_admin)
        return True
    return mock.patch.object(evals_routes, "resolve_session_principal", side_effect=_resolve)


class NightlyRoutesTests(unittest.TestCase):
    def setUp(self):
        # TestClient 门户线程持有的 sqlite 连接主线程关不掉，Windows 下临时目录清理
        # 会撞文件锁——ignore_cleanup_errors 容忍残留（tmp 目录由 OS 回收）
        self.tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.addCleanup(self.tmp.cleanup)
        self.eval_dir = Path(self.tmp.name) / "evals"
        self.eval_dir.mkdir()
        self.nightly = self.eval_dir / "nightly"
        self.nightly.mkdir()
        self.db_patch = mock.patch.object(evals_routes.result_store, "_DB_PATH",
                                          str(self.eval_dir / "evals.sqlite"))
        self.db_patch.start()
        self.addCleanup(self.db_patch.stop)

    def _client(self):
        from fastapi import FastAPI
        from fastapi.testclient import TestClient
        app = FastAPI()
        app.include_router(evals_routes.evals_router, prefix="/api/evals")
        return TestClient(app, base_url="http://test")

    def _write_day(self, date: str, payload, raw_text=None):
        day = self.nightly / date
        day.mkdir(exist_ok=True)   # 迁移期允许与 runs/<slot> 挡同居一日
        (day / "nightly.json").write_text(
            json.dumps(payload) if raw_text is None else raw_text, encoding="utf-8")
        (day / "report.md").write_text("# 报告\n门禁 GREEN", encoding="utf-8")
        return day

    DAY = {"state": "green", "overall_score": 0.8768, "correct": 427, "total": 487,
           "delta": 0.0267, "base_label": "R2", "matrix": {"pp": 396, "pf": 31, "fp": 18, "ff": 42}}

    def test_requires_session_401(self):
        with _patch_auth(False):
            r = self._client().get("/api/evals/nightly")
        self.assertEqual(r.status_code, 401)

    def test_non_admin_403(self):
        with _patch_auth(True, is_admin=False):
            r = self._client().get("/api/evals/nightly")
        self.assertEqual(r.status_code, 403)

    def test_list_desc_and_corrupt_degrade(self):
        self._write_day("2026-09-05", self.DAY)
        self._write_day("2026-09-06", self.DAY)
        self._write_day("2026-09-07", None, raw_text="{坏 json")
        with _patch_auth(True, is_admin=True):
            r = self._client().get("/api/evals/nightly")
        self.assertEqual(r.status_code, 200)
        days = r.json()["days"]
        self.assertEqual([d["date"] for d in days], ["2026-09-07", "2026-09-06", "2026-09-05"])
        self.assertEqual(days[0]["state"], "corrupt")       # 损坏目录不炸全局
        self.assertEqual(days[1]["overall_score"], 0.8768)

    def test_detail_returns_report_md(self):
        self._write_day("2026-09-06", self.DAY)
        with _patch_auth(True, is_admin=True):
            r = self._client().get("/api/evals/nightly/2026-09-06")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()["nightly"]["delta"], 0.0267)

    # ---- 同日每跑一挡（2026-09-27：多跑不合并、做了 3 次留 3 次）----

    def _write_slot(self, day: str, slot: str, **over):
        from evals_core.nightly import archive
        entry = {**self.DAY, "date": day, "slot_note": slot,
                 "started_at": over.pop("started_at", f"{day}T16:33:00+08:00")}
        archive.publish_day({**entry, **over}, f"# 报告 {slot}", root=self.nightly, slot=slot)

    def test_list_expands_each_slot_newest_first(self):
        self._write_slot("2026-09-27", "0115-a1b2c3", started_at="2026-09-27T01:15:00+08:00")
        self._write_slot("2026-09-27", "1633-d4e5f6", started_at="2026-09-27T16:33:00+08:00")
        self._write_day("2026-09-26", self.DAY)
        with _patch_auth(True, is_admin=True):
            days = self._client().get("/api/evals/nightly").json()["days"]
        self.assertEqual([(d["date"], d.get("slot", "")) for d in days],
                         [("2026-09-27", "1633-d4e5f6"), ("2026-09-27", "0115-a1b2c3"),
                          ("2026-09-26", "")])

    def test_detail_with_slot_reads_that_slot_only(self):
        self._write_slot("2026-09-27", "0115-a1b2c3", overall_score=0.84)
        self._write_slot("2026-09-27", "1633-d4e5f6", overall_score=0.85)
        with _patch_auth(True, is_admin=True):
            c = self._client()
            r = c.get("/api/evals/nightly/2026-09-27", params={"slot": "1633-d4e5f6"})
            self.assertEqual(r.status_code, 200)
            self.assertEqual(r.json()["nightly"]["overall_score"], 0.85)
            self.assertEqual(r.json()["nightly"]["slot"], "1633-d4e5f6")
            self.assertIn("1633", r.json()["report_md"])
            # 不传 slot 且该日没有旧平铺档 → 404（而不是随机挑一挡）
            self.assertEqual(c.get("/api/evals/nightly/2026-09-27").status_code, 404)
            self.assertEqual(c.get("/api/evals/nightly/2026-09-27",
                                   params={"slot": "不存在"}).status_code, 404)

    def test_slot_query_blocks_traversal(self):
        self._write_slot("2026-09-27", "0115-a1b2c3")
        with _patch_auth(True, is_admin=True):
            c = self._client()
            self.assertEqual(c.get("/api/evals/nightly/2026-09-27",
                                   params={"slot": "..%2F..%2Fetc"}).status_code, 404)
            self.assertEqual(c.get("/api/evals/nightly/2026-09-27",
                                   params={"slot": "a b"}).status_code, 404)

    def test_delete_slot_keeps_siblings_and_legacy(self):
        self._write_slot("2026-09-27", "0115-a1b2c3")
        self._write_slot("2026-09-27", "1633-d4e5f6")
        self._write_day("2026-09-27", self.DAY)          # 同日的旧平铺档（迁移期共存）
        with _patch_auth(True, is_admin=True):
            r = self._client().delete("/api/evals/nightly/2026-09-27", params={"slot": "1633-d4e5f6"})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()["slot"], "1633-d4e5f6")
        day = self.nightly / "2026-09-27"
        self.assertFalse((day / "runs" / "1633-d4e5f6").exists())
        self.assertTrue((day / "runs" / "0115-a1b2c3" / "nightly.json").exists())
        self.assertTrue((day / "nightly.json").exists())

    def test_delete_legacy_removes_flat_files_keeps_runs(self):
        """旧接口形态（不带 slot）删除：只清平铺文件，runs/ 下新管线的挡一概不动。"""
        self._write_slot("2026-09-27", "0115-a1b2c3")
        self._write_day("2026-09-27", self.DAY)
        with _patch_auth(True, is_admin=True):
            r = self._client().delete("/api/evals/nightly/2026-09-27")
        self.assertEqual(r.status_code, 200)
        day = self.nightly / "2026-09-27"
        self.assertFalse((day / "nightly.json").exists())
        self.assertFalse((day / "report.md").exists())
        self.assertTrue((day / "runs" / "0115-a1b2c3" / "nightly.json").exists())

    def test_same_day_error_sidecar_is_surfaced(self):
        """同日既出了结论、又挂过一条派发时，列表与详情都要把失败带出来。

        error 档按 archive.publish_day 的规矩改落 sidecar（不盖结论）——若接口不把它透出来，
        页面上就只剩一条绿结论，与群里那条失败卡片对不上号（2026-09-26 两头都实踩过）。
        """
        from evals_core.nightly import archive
        day = self._write_day("2026-09-26", self.DAY)
        (day / archive.ERROR_SIDECAR).write_text(json.dumps({
            "state": "error", "note": "补判轮数耗尽仍有未清零异常: judge_fail=1",
            "verdict": "中断于 1040/1040，未出结论", "run_id": "run-err",
            "started_at": "2026-09-26T01:00:51+08:00", "generated_at": "2026-09-26T03:17:30+08:00",
            "progress": {"completed": 1040, "total": 1040, "correct": 904, "score": 0.8692},
        }), encoding="utf-8")
        with _patch_auth(True, is_admin=True):
            listed = self._client().get("/api/evals/nightly").json()["days"][0]
            detail = self._client().get("/api/evals/nightly/2026-09-26").json()["nightly"]
        for got in (listed, detail):
            self.assertEqual(got["state"], "green")                                # 结论仍是主位
            self.assertEqual(got["same_day_error"]["note"], "补判轮数耗尽仍有未清零异常: judge_fail=1")
            self.assertEqual(got["same_day_error"]["progress"]["correct"], 904)

    def test_traversal_and_missing_404(self):
        with _patch_auth(True, is_admin=True):
            c = self._client()
            self.assertEqual(c.get("/api/evals/nightly/..%2F..%2Fetc").status_code, 404)
            self.assertEqual(c.get("/api/evals/nightly/2026-9-6").status_code, 404)   # 格式不合法
            self.assertEqual(c.get("/api/evals/nightly/2026-09-01").status_code, 404)  # 无该日

    def test_missing_root_returns_empty(self):
        import shutil
        shutil.rmtree(self.nightly)
        with _patch_auth(True, is_admin=True):
            r = self._client().get("/api/evals/nightly")
        self.assertEqual(r.json(), {"days": []})

    # ---- 中断档重判（req-nightly-interrupt-resume §2-B2：部署砸 run 的档不再显示「损坏」）----

    def _insert_interrupted_run(self, run_id: str, dataset_id: str,
                                started_utc: str, ended_utc: str,
                                completed: int = 869, total: int = 1040) -> None:
        from evals_core.storage import result_store
        result_store._LOCAL = None  # 防串用上一个用例的线程连接
        result_store.init_db()
        summary = {"overall_score": 0.0, "total": total, "correct": 758, "wrong": 107,
                   "skipped": total - completed, "errored": 0,
                   "interrupted_by_startup_sweep": True}
        conn = result_store._get_conn()
        conn.execute(
            "INSERT INTO eval_run (run_id, dataset_id, status, total_questions,"
            " completed_questions, started_at, completed_at, summary_scores, owner_pid)"
            " VALUES (?, ?, 'cancelled', ?, ?, ?, ?, ?, 1)",
            (run_id, dataset_id, total, completed, started_utc, ended_utc,
             json.dumps(summary, ensure_ascii=False)),
        )
        conn.commit()

        def _release_conn():  # Windows：先关连接再让临时目录清理，否则文件锁报错
            try:
                result_store._get_conn().close()
            except Exception:
                pass
            result_store._LOCAL = None
        self.addCleanup(_release_conn)

    def _make_interrupted_slot(self, date: str, slot: str) -> None:
        """中断现场：有素材产物、无 nightly.json（corrupt 占位）。"""
        slot_dir = self.nightly / date / "runs" / slot
        slot_dir.mkdir(parents=True)
        (slot_dir / "material_parity.json").write_text("{}", encoding="utf-8")

    def test_interrupted_slot_listed_with_progress_and_time(self):
        from evals_core.nightly import paths
        self._insert_interrupted_run("run-061266cfa555", paths.DATASET_DEFAULT,
                                     "2026-10-04T08:08:07", "2026-10-04T12:31:00")
        self._make_interrupted_slot("2026-10-04", "1608-abcdef")
        with _patch_auth(True, is_admin=True):
            c = self._client()
            days = c.get("/api/evals/nightly").json()["days"]
            self.assertEqual(days[0]["state"], "interrupted")
            self.assertEqual(days[0]["started_at"], "2026-10-04T16:08:07+08:00")
            self.assertEqual((days[0]["progress"]["completed"], days[0]["progress"]["total"]),
                             (869, 1040))
            # 详情同口径
            d = c.get("/api/evals/nightly/2026-10-04", params={"slot": "1608-abcdef"}).json()["nightly"]
            self.assertEqual(d["state"], "interrupted")
            self.assertEqual(d["run_id"], "run-061266cfa555")

    def test_interrupted_slot_delete_removes_run(self):
        """中断档删除可连带删 run（重判回填 run_id 前，删除只清目录、run 成孤儿）。"""
        from evals_core.nightly import paths
        from evals_core.storage import result_store
        self._insert_interrupted_run("run-del", paths.DATASET_DEFAULT,
                                     "2026-10-04T08:08:07", "2026-10-04T12:31:00")
        self._make_interrupted_slot("2026-10-04", "1608-abcdef")
        with _patch_auth(True, is_admin=True):
            r = self._client().delete("/api/evals/nightly/2026-10-04",
                                      params={"slot": "1608-abcdef"})
        self.assertEqual(r.status_code, 200)
        self.assertTrue(r.json()["deleted_run"])
        result_store._get_conn().close()
        result_store._LOCAL = None
        self.assertIsNone(result_store.get_run("run-del"))

    def test_corrupt_slot_without_candidate_stays_corrupt(self):
        """真损坏（无任何带章 run）不硬凑中断。"""
        self._make_interrupted_slot("2026-10-04", "1608-abcdef")
        with _patch_auth(True, is_admin=True):
            days = self._client().get("/api/evals/nightly").json()["days"]
        self.assertEqual(days[0]["state"], "corrupt")

    # ---- 调度配置接口（GET/PUT settings、POST run-now）----

    def _settings_env(self):
        import nightly_control  # noqa: F401  同一模块对象，patch 才对路由生效
        return mock.patch.dict(os.environ,
                               {"NIGHTLY_SETTINGS_FILE": str(self.eval_dir / "nightly_settings.json")})

    def test_settings_requires_admin(self):
        with self._settings_env(), _patch_auth(False):
            self.assertEqual(self._client().get("/api/evals/nightly/settings").status_code, 401)
        with self._settings_env(), _patch_auth(True, is_admin=False):
            r = self._client().put("/api/evals/nightly/settings", json={"enabled": True, "hour": 1, "minute": 0})
            self.assertEqual(r.status_code, 403)

    def test_settings_default_put_validation_persist(self):
        settings_file = self.eval_dir / "nightly_settings.json"
        with self._settings_env(), _patch_auth(True, is_admin=True):
            c = self._client()
            r = c.get("/api/evals/nightly/settings")
            self.assertEqual(r.status_code, 200)
            self.assertEqual(r.json()["enabled"], True)            # 每晚定时执行=默认选择
            self.assertIsNotNone(r.json()["next_fire_at"])         # 默认启用 → 必有下次触发
            r = c.put("/api/evals/nightly/settings", json={"enabled": True, "hour": 2, "minute": 30})
            self.assertTrue(r.json()["enabled"])
            self.assertIsNotNone(r.json()["next_fire_at"])        # 启用后必有下次触发时刻
            self.assertIn('"hour": 2', settings_file.read_text(encoding="utf-8"))
            self.assertEqual(c.put("/api/evals/nightly/settings", json={"hour": 24}).status_code, 400)

    def test_run_now_launches_pipeline_contract(self):
        # 路由契约：转调 nightly_control.launch("manual") 并透传启动结果；
        # launch/流水线的行为在 test_unit_nightly_control / nightly_pipeline 覆盖
        import nightly_control
        with self._settings_env(), mock.patch.object(
            nightly_control, "launch",
            new=mock.AsyncMock(return_value={"ok": True, "started_at": "2026-09-06T13:00:00+08:00", "detail": "started"}),
        ) as launched, _patch_auth(True, is_admin=True):
            r = self._client().post("/api/evals/nightly/run-now")
        self.assertEqual(r.status_code, 200)
        self.assertTrue(r.json()["ok"])
        self.assertEqual(r.json()["at"], "2026-09-06T13:00:00+08:00")
        self.assertEqual(launched.await_args[0][0], "manual")

    def test_run_plan_preview_and_running_flag(self):
        import nightly_control
        with self._settings_env(), _patch_auth(True, is_admin=True):
            c = self._client()
            self.assertFalse(c.get("/api/evals/nightly/settings").json()["running"])
            with mock.patch.object(nightly_control, "run_plan",
                                   return_value={"dataset": {"id": "ds", "title": "T"}}):
                rp = c.get("/api/evals/nightly/run-plan")
            self.assertEqual(rp.status_code, 200)
            self.assertEqual(rp.json()["dataset"]["title"], "T")
        with self._settings_env(), _patch_auth(False):
            self.assertEqual(self._client().get("/api/evals/nightly/run-plan").status_code, 401)

    def test_run_now_reports_busy(self):
        import nightly_control
        with self._settings_env(), mock.patch.object(
            nightly_control, "launch",
            new=mock.AsyncMock(return_value={"ok": False, "started_at": "", "detail": "已有一条夜间流水线在运行，请等待其完成"}),
        ), _patch_auth(True, is_admin=True):
            r = self._client().post("/api/evals/nightly/run-now")
        self.assertEqual(r.status_code, 200)
        self.assertFalse(r.json()["ok"])
        self.assertIn("运行", r.json()["detail"])


if __name__ == "__main__":
    unittest.main()
