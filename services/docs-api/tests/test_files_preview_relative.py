"""GET /api/files 对相对 file_path 的展开契约（Stage A 第 4 读点）。

Stage A 后 nodes.file_path 为相对 data 根路径，前端（useWorkspacePreview 默认解析器）
把该相对值原样拼进 /api/files?path=。修复前路由用 os.path.abspath 按进程 cwd 展开，
相对值会解析到 docs-api 的工作目录（容器里是 /app）→ 溯源预览 403/404。
"""
import sys
from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient

API_ROOT = Path(__file__).resolve().parents[1]
if str(API_ROOT) not in sys.path:
    sys.path.insert(0, str(API_ROOT))

import docs_routes  # noqa: E402


def test_files_preview_accepts_relative_path(tmp_path, monkeypatch):
    monkeypatch.setenv("ANGINEER_DATA_ROOT", str(tmp_path))
    monkeypatch.setattr(docs_routes, "_allowed_roots_cache", None)
    rel = "knowledge/libraries/lib-x/documents/d1/source/a.md"
    f = tmp_path / rel
    f.parent.mkdir(parents=True)
    f.write_text("hello", encoding="utf-8")

    app = FastAPI()
    app.include_router(docs_routes.preview_router, prefix="/api")
    resp = TestClient(app).get("/api/files", params={"path": rel})
    assert resp.status_code == 200, resp.text
    assert resp.text == "hello"


def test_files_preview_legacy_absolute_still_works(tmp_path, monkeypatch):
    monkeypatch.setenv("ANGINEER_DATA_ROOT", str(tmp_path))
    monkeypatch.setattr(docs_routes, "_allowed_roots_cache", None)
    absf = tmp_path / "knowledge" / "libraries" / "lib-y" / "documents" / "d2" / "source" / "b.md"
    absf.parent.mkdir(parents=True)
    absf.write_text("world", encoding="utf-8")

    app = FastAPI()
    app.include_router(docs_routes.preview_router, prefix="/api")
    resp = TestClient(app).get("/api/files", params={"path": str(absf)})
    assert resp.status_code == 200, resp.text
    assert resp.text == "world"
