"""POST /exports/preview v2 响应形状：逐库明细（大包总大小 + 各小包）＋旧字段名兼容。

路由边界测试：stub 掉 scan_selection（真统计逻辑在 docs-core 单测里），只钉响应契约。
"""
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import export_routes
from admin_auth import resolve_admin_session


@pytest.fixture()
def client(monkeypatch):
    fake = {
        "embed_model": "qwen3-embed-8b",
        "libraries": [
            {"library_id": "lib-a", "name": "库A", "group_name": "standards", "collection": "coll-a",
             "files_bytes": 100, "file_count": 2, "sqlite_estimate": 50, "vector_points": 3,
             "snapshot_estimate": 21000, "counts": {"docs": 2, "chunks": 2}},
            {"library_id": "lib-b", "name": "库B", "group_name": "standards", "collection": "coll-b",
             "files_bytes": 200, "file_count": 1, "sqlite_estimate": 70, "vector_points": 7,
             "snapshot_estimate": 49000, "counts": {"docs": 1, "chunks": 1}},
        ],
        "totals": {"files_bytes": 300, "file_count": 3, "sqlite_estimate": 120, "vector_points": 10,
                   "snapshot_estimate": 70000, "total_estimate": 70420},
        "warnings": [],
    }
    monkeypatch.setattr(export_routes, "scan_selection", lambda *a, **k: fake)
    app = FastAPI()
    app.include_router(export_routes.export_router, prefix="/api/knowledge")
    app.dependency_overrides[resolve_admin_session] = lambda: {"sub": "admin"}
    return TestClient(app)


def test_preview_v2_shape(client):
    resp = client.post("/api/knowledge/exports/preview", json={"libraries": ["lib-a", "lib-b"]})
    assert resp.status_code == 200
    body = resp.json()
    assert body["kind"] == "bundle"
    assert body["schema_version"] == 2
    assert body["embed_model"] == "qwen3-embed-8b"
    assert [lib["library_id"] for lib in body["libraries"]] == ["lib-a", "lib-b"]
    lib = body["libraries"][0]
    for key in ("library_id", "name", "group_name", "collection", "files_bytes", "file_count",
                "sqlite_estimate", "vector_points", "snapshot_estimate", "counts", "total_estimate"):
        assert key in lib, key
    assert lib["total_estimate"] == 100 + 50 + 21000
    assert lib["counts"] == {"docs": 2, "chunks": 2}
    # 旧字段名兼容（前端渐进改）
    assert body["files_bytes"] == 300
    assert body["file_count"] == 3
    assert body["sqlite_bytes"] == 120
    assert body["total_estimate"] == 70420
    assert body["peers"] == []
    assert body["selectable_library_ids"] == ["lib-a", "lib-b"]
