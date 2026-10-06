"""迁移路由守卫：preview/submit 契约与过期预览 409（鉴权依赖整体 override）。"""
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import kb_migration_routes as kmr
from docs_core.kb_migrator import PreviewResult, PreviewStaleError


class _StubMigrator:
    def __init__(self):
        self.submitted = []
        # N3：volumes 端点读 meta_db/group_db_for/vector_store/libraries_root_for——不补则测试必 AttributeError/500
        import sqlite3
        import tempfile
        from pathlib import Path
        self._tmp = Path(tempfile.mkdtemp())
        self.meta_db = str(self._tmp / "meta.sqlite")
        with sqlite3.connect(self.meta_db) as conn:
            conn.execute("CREATE TABLE nodes (id TEXT PRIMARY KEY, type TEXT, library_id TEXT,"
                         " updated_at TEXT, deleted INTEGER DEFAULT 0)")
        self.vector_store = None

    def group_db_for(self, library_id):
        return str(self._tmp / "group_missing.sqlite")  # 不存在 → 端点 try 内吞掉，chunks=0

    def libraries_root_for(self, library_id):
        return self._tmp

    def compute_preview(self, **kw):
        return PreviewResult(op=kw["op"], source_library_id=kw["source_library_id"],
                             target_library_id=kw.get("new_library_id") or kw.get("target_library_id") or "",
                             doc_ids=sorted(kw.get("doc_ids") or []), counts={"docs": {}}, digest="d" * 64)

    def assert_preview_fresh(self, preview):
        if preview.digest == "stale":
            raise PreviewStaleError("过期")


class _StubRunner:
    def __init__(self, mig):
        self.migrator = mig
        self.submitted = []

    def submit(self, task_id, *, operator="admin"):
        self.submitted.append(task_id)

    def request_cancel(self, task_id):
        self.migrator_store_cancel = task_id


@pytest.fixture
def client(monkeypatch):
    mig = _StubMigrator()
    stub_runner = _StubRunner(mig)
    monkeypatch.setattr(kmr, "get_migrator", lambda: mig)
    monkeypatch.setattr(kmr, "get_runner", lambda: stub_runner)
    app = FastAPI()
    app.include_router(kmr.kb_migration_router, prefix="/api/knowledge")
    # 二轮评审采纳项：8 端点全挂 resolve_admin_session，测试整体 override
    app.dependency_overrides[kmr.resolve_admin_session] = lambda: {"username": "tester"}
    return TestClient(app), mig


def test_preview_endpoint(client):
    c, _ = client
    resp = c.post("/api/knowledge/migrations/preview", json={
        "op": "split", "source_library_id": "lib-a", "new_library_id": "lib-b",
        "new_name": "分册", "doc_ids": ["d1"]})
    assert resp.status_code == 200
    assert resp.json()["digest"] == "d" * 64


def test_submit_rejects_stale_preview(client):
    c, mig = client
    resp = c.post("/api/knowledge/migrations", json={
        "op": "split", "source_library_id": "lib-a", "new_library_id": "lib-b",
        "new_name": "分册", "doc_ids": ["d1"], "preview_digest": "stale"})
    assert resp.status_code == 409


def test_endpoints_require_admin(client):
    # 不 override 时（新 app 未挂 override）必须 401——鉴权不是纸糊的
    from fastapi import FastAPI as _F
    app = _F()
    app.include_router(kmr.kb_migration_router, prefix="/api/knowledge")
    c = TestClient(app)
    resp = c.get("/api/knowledge/migrations")
    assert resp.status_code == 401
