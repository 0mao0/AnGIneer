"""解析回归只读接口测试：鉴权、列表倒序、损坏降级、详情、run_id 防穿越。

看板定位（用户明确要求）：数据由开发机 `run_parse_regression.py --publish` 同步上来，
服务器只读不执行——所以这里也只测"读"，不存在任何写/触发接口。
"""
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

# chat_auth 依赖 models.user（docs-api 侧）——用桩模块顶掉，只测路由与鉴权装配本身
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


PAYLOAD = {
    "schema": 1, "run_id": "20260917-0837", "kind": "run", "limit": 200, "seed": 42,
    "pages_scored": 200, "pages_official": 199, "page_ids_hash": "fee2959a7a67",
    "git": "v0.2.65-4-g6d06f3d", "mineru_version": "3.4.5(n=200)",
    "timing": {"predict": 2709.4, "official": 190.8}, "skipped": [],
    "metrics": {"official": {"text_edit": 0.0724}, "struct_chain": {"block_recall": 0.8825}},
    "metric_meta": {"text_edit": {"label": "文本 Edit_dist", "higher_is_better": False, "ratio": True}},
    "delta": {"gate": "none", "reason": "首次跑"},
    "by_category": [{"category": "text_block", "gt_blocks": 1946, "recall": 0.9486}],
}


class ParseRegressionRoutesTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.eval_dir = Path(self.tmp.name) / "evals"
        self.eval_dir.mkdir()
        self.root = self.eval_dir / "parse_regression"
        self.root.mkdir()
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

    def _write_run(self, run_id: str, payload=None, raw_text=None):
        run_dir = self.root / run_id
        run_dir.mkdir()
        (run_dir / "publish.json").write_text(
            json.dumps(payload) if raw_text is None else raw_text, encoding="utf-8")
        (run_dir / "summary.md").write_text("# 解析回归\n| 指标 | 值 |", encoding="utf-8")
        (run_dir / "struct_chain_report.md").write_text("# A② 报告", encoding="utf-8")
        return run_dir

    def test_requires_session_401(self):
        with _patch_auth(False):
            r = self._client().get("/api/evals/parse-regression")
        self.assertEqual(r.status_code, 401)

    def test_non_admin_403(self):
        with _patch_auth(True, is_admin=False):
            r = self._client().get("/api/evals/parse-regression")
        self.assertEqual(r.status_code, 403)

    def test_empty_root_is_not_an_error(self):
        """服务器还没同步过数据时列表为空但不报错，前端据此提示'先在本机跑一次'。"""
        with _patch_auth(True, is_admin=True):
            r = self._client().get("/api/evals/parse-regression")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json(), {"runs": [], "root_exists": True})

    def test_missing_root_reports_flag(self):
        import shutil
        shutil.rmtree(self.root)
        with _patch_auth(True, is_admin=True):
            r = self._client().get("/api/evals/parse-regression")
        self.assertEqual(r.status_code, 200)
        self.assertFalse(r.json()["root_exists"])

    def test_list_sorted_by_run_date_and_corrupt_degrade(self):
        """排序按结果日期（不是目录名字典序）：baseline-* 不该跑到 2026* 前面。"""
        self._write_run("baseline-20260913", {**PAYLOAD, "run_id": "baseline-20260913",
                                             "run_date": "2026-09-13", "kind": "offline-reprojection"})
        self._write_run("20260917-0837", {**PAYLOAD, "run_date": "2026-09-17"})
        self._write_run("20260918-0100", None, raw_text="{坏 json")
        with _patch_auth(True, is_admin=True):
            r = self._client().get("/api/evals/parse-regression")
        self.assertEqual(r.status_code, 200)
        runs = r.json()["runs"]
        # 损坏条目按目录名里的日期兜底排序，仍在最前（它是最新的）
        self.assertEqual([x["run_id"] for x in runs], ["20260918-0100", "20260917-0837", "baseline-20260913"])
        self.assertEqual(runs[0]["state"], "corrupt")           # 损坏目录不炸列表
        self.assertEqual(runs[1]["pages_scored"], 200)
        self.assertEqual(runs[2]["kind"], "offline-reprojection")

    def test_ts_fallback_when_run_date_absent(self):
        """老载荷没有 run_date：退到 ts（同一套归一化），不因为字段缺失就排到末尾。"""
        self._write_run("20260916-0100", {**PAYLOAD, "run_id": "20260916-0100", "run_date": None,
                                          "ts": "20260916-0100"})
        self._write_run("20260917-0837", {**PAYLOAD, "run_date": "2026-09-17"})
        with _patch_auth(True, is_admin=True):
            runs = self._client().get("/api/evals/parse-regression").json()["runs"]
        self.assertEqual([x["run_id"] for x in runs], ["20260917-0837", "20260916-0100"])

    def test_detail_returns_payload_and_reports(self):
        self._write_run("20260917-0837", PAYLOAD)
        with _patch_auth(True, is_admin=True):
            r = self._client().get("/api/evals/parse-regression/20260917-0837")
        self.assertEqual(r.status_code, 200)
        body = r.json()
        self.assertEqual(body["run"]["metrics"]["official"]["text_edit"], 0.0724)
        self.assertEqual(body["run"]["by_category"][0]["category"], "text_block")
        self.assertIn("解析回归", body["summary_md"])
        self.assertIn("A② 报告", body["struct_report_md"])

    def test_traversal_and_missing_404(self):
        with _patch_auth(True, is_admin=True):
            c = self._client()
            for bad in ("..", "../evals.sqlite", "a/b", "x" * 65):
                self.assertEqual(c.get(f"/api/evals/parse-regression/{bad}").status_code, 404, bad)
            self.assertEqual(c.get("/api/evals/parse-regression/20990101-0000").status_code, 404)


if __name__ == "__main__":
    unittest.main()
