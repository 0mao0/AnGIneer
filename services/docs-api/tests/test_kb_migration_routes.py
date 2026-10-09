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


class _StubStore:
    def __init__(self, task=None):
        self.task = task
        self.created = []
        self.updated = []

    def get_task(self, task_id):
        return self.task if self.task and self.task["id"] == task_id else None

    def create_task(self, task_id, **kw):
        self.created.append((task_id, kw))

    def update_task(self, task_id, **kw):
        self.updated.append((task_id, kw))


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


def test_volumes_endpoint_shape(client, monkeypatch):
    c, mig = client  # fixture 已 patch get_migrator/get_runner（stub 已按 N3 补齐 volumes 成员）
    import types
    from docs_core import library_registry
    # 缓存 5 分钟：测试间强制失效，避免顺序依赖
    monkeypatch.setattr(kmr, "_VOLUMES_CACHE", {"at": 0.0, "data": None})
    monkeypatch.setattr(library_registry, "list_libraries", lambda: [
        types.SimpleNamespace(library_id="lib-a", name="A", status="active", collection="g1")])
    resp = c.get("/api/knowledge/migrations/volumes")
    assert resp.status_code == 200
    body = resp.json()
    assert len(body["volumes"]) == 1 and body["volumes"][0]["library_id"] == "lib-a"
    assert body["thresholds"]["docs"] == 1000


def test_submit_marks_second_gate_for_existing_destination(client):
    """拆入已有库/合并：submit 落 gate_second=True（目标库任务期间同上门禁）；拆到新库为 False。"""
    c, mig = client
    mig.store = _StubStore()
    resp = c.post("/api/knowledge/migrations", json={
        "op": "split", "source_library_id": "lib-a", "target_library_id": "lib-t",
        "doc_ids": ["d1"], "preview_digest": "d" * 64})
    assert resp.status_code == 200
    (_, kw), = mig.store.created
    assert kw["params"]["gate_second"] is True
    mig.store.created.clear()
    resp = c.post("/api/knowledge/migrations", json={
        "op": "split", "source_library_id": "lib-a", "new_library_id": "lib-new",
        "new_name": "分册", "doc_ids": ["d1"], "preview_digest": "d" * 64})
    assert resp.status_code == 200
    (_, kw), = mig.store.created
    assert kw["params"]["gate_second"] is False


def test_rollback_split_into_existing_uses_migrated_doc_ids(client, monkeypatch):
    """拆入已有库回滚：doc_ids=原任务 migrated_doc_ids（不取目标库全部文档），目标库不退役标记落 params。"""
    c, mig = client
    import types
    task = {"id": "mig-1", "op": "split", "status": "completed",
            "params": {"op": "split", "source_library_id": "lib-a",
                       "target_library_id": "lib-t", "doc_ids": ["d1"]},
            "migrated_doc_ids": ["d1"]}
    mig.store = _StubStore(task)
    from docs_core import library_registry
    monkeypatch.setattr(library_registry, "get_library",
                        lambda lib: types.SimpleNamespace(collection="g1"))
    resp = c.post("/api/knowledge/migrations/mig-1/rollback")
    assert resp.status_code == 200
    (_, kw), = mig.store.created
    params = kw["params"]
    assert params["library_id"] == "lib-t"          # 持有方=已有库目标
    assert params["doc_ids"] == ["d1"]              # 目标库自有文档绝不动
    assert params["destination_is_new"] is False
    assert params["gate_second"] is True


def test_endpoints_require_admin(client):
    # 不 override 时（新 app 未挂 override）必须 401——鉴权不是纸糊的
    from fastapi import FastAPI as _F
    app = _F()
    app.include_router(kmr.kb_migration_router, prefix="/api/knowledge")
    c = TestClient(app)
    resp = c.get("/api/knowledge/migrations")
    assert resp.status_code == 401


def test_volumes_refresh_forces_rescan(client, monkeypatch):
    """refresh=1（面板刷新按钮）强制重扫绕过 5 分钟缓存；不带参仍读缓存（2026-10-09 业主定版）。"""
    c, _mig = client
    import types
    from docs_core import library_registry
    monkeypatch.setattr(library_registry, "list_libraries", lambda: [
        types.SimpleNamespace(library_id="lib-a", name="A", status="active", collection="g1")])
    # 预热缓存为哨兵（at 极大值=永不过期，不引 time）
    monkeypatch.setattr(kmr, "_VOLUMES_CACHE", {"at": 1e18, "data": {"volumes": [], "thresholds": {}}})
    cached = c.get("/api/knowledge/migrations/volumes")
    assert cached.status_code == 200
    assert cached.json()["volumes"] == []                 # 命中缓存（哨兵）
    forced = c.get("/api/knowledge/migrations/volumes?refresh=1")
    assert forced.status_code == 200
    assert [v["library_id"] for v in forced.json()["volumes"]] == ["lib-a"]   # 绕过缓存真重扫
    assert forced.json()["thresholds"]["docs"] == 1000    # 重扫后回写缓存（阈值来自真实常量）
