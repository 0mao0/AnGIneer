"""P3-1 导入路由契约：上传/预检、应用状态机、清理与守卫。"""
import io
import time
import zipfile
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import import_routes
from admin_auth import resolve_admin_session


def _zip_bytes() -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_STORED) as z:
        z.writestr("manifest.json", '{"kind":"library","schema_version":2}')
    return buf.getvalue()


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(import_routes, "_tasks", {})
    monkeypatch.setattr(import_routes, "_active_apply", None)
    monkeypatch.setattr(import_routes, "resolve_data_root", lambda: tmp_path)

    def fake_apply(package, **kwargs):
        if kwargs.get("apply"):
            return {"mode": "applied", "libraries": kwargs.get("libraries") or ["lib-a"]}
        return {
            "mode": "dry-run",
            "libraries": [{
                "library_id": "lib-a", "name": "A", "group_name": "evals",
                "collection": "lib-a", "index_path": str(tmp_path / "idx.sqlite"),
                "files": 2, "bytes": 100, "counts": {"docs": 1, "chunks": 2, "vectors": 0},
            }],
        }

    monkeypatch.setattr(import_routes, "apply_import", fake_apply)
    app = FastAPI()
    app.include_router(import_routes.import_router, prefix="/api/knowledge")
    app.dependency_overrides[resolve_admin_session] = lambda: {"sub": "admin"}
    return TestClient(app)


def _upload(client, data=None, filename="pkg.zip"):
    return client.post(
        "/api/knowledge/imports/upload",
        files={"file": (filename, data if data is not None else _zip_bytes(), "application/zip")},
        data={"group_name": "evals", "with_vectors": "false"},
    )


def test_upload_preview(client):
    resp = _upload(client)
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "previewed"
    assert body["preview"]["libraries"][0]["library_id"] == "lib-a"
    assert Path(body["preview"]["libraries"][0]["index_path"]).name == "idx.sqlite"


def test_upload_rejects_non_zip(client):
    resp = _upload(client, b"not zip")
    assert resp.status_code == 400


def test_upload_rejects_oversize(client, monkeypatch):
    monkeypatch.setattr(import_routes, "IMPORT_MAX_BYTES", 10)
    resp = _upload(client)
    assert resp.status_code == 413


def test_delete_preview_cleans_scratch(client, tmp_path):
    task_id = _upload(client).json()["task_id"]
    scratch = tmp_path / "scratch/imports" / task_id
    assert (scratch / "package.zip").exists()
    assert client.delete(f"/api/knowledge/imports/{task_id}").status_code == 200
    assert not scratch.exists()
    assert client.get(f"/api/knowledge/imports/{task_id}/status").status_code == 404


def test_apply_failure_keeps_scratch_for_cleanup(client, tmp_path, monkeypatch):
    original = import_routes.apply_import

    def fail_apply(package, **kwargs):
        if kwargs.get("apply"):
            raise RuntimeError("boom")
        return original(package, **kwargs)

    monkeypatch.setattr(import_routes, "apply_import", fail_apply)
    task_id = _upload(client).json()["task_id"]
    assert client.post(
        f"/api/knowledge/imports/{task_id}/apply",
        json={"group_name": "evals", "libraries": ["lib-a"]},
    ).status_code == 200
    deadline = time.time() + 3
    status = "running"
    while time.time() < deadline:
        status = client.get(f"/api/knowledge/imports/{task_id}/status").json()["status"]
        if status != "running":
            break
        time.sleep(0.02)
    assert status == "failed"
    scratch = tmp_path / "scratch/imports" / task_id
    assert (scratch / "package.zip").exists()  # 失败保留暂存供排障
    assert client.delete(f"/api/knowledge/imports/{task_id}").status_code == 200
    assert not scratch.exists()


def test_apply_then_status_and_delete(client):
    task_id = _upload(client).json()["task_id"]
    resp = client.post(f"/api/knowledge/imports/{task_id}/apply",
                       json={"group_name": "evals", "libraries": ["lib-a"]})
    assert resp.status_code == 200
    deadline = time.time() + 3
    status = "running"
    while time.time() < deadline:
        body = client.get(f"/api/knowledge/imports/{task_id}/status").json()
        status = body["status"]
        if status != "running":
            break
        time.sleep(0.02)
    assert status == "completed"
    assert client.delete(f"/api/knowledge/imports/{task_id}").status_code == 200
    assert client.get(f"/api/knowledge/imports/{task_id}/status").status_code == 404


def test_apply_unknown_group_rejected(client):
    task_id = _upload(client).json()["task_id"]
    resp = client.post(f"/api/knowledge/imports/{task_id}/apply",
                       json={"group_name": "../bad", "libraries": ["lib-a"]})
    assert resp.status_code == 400
