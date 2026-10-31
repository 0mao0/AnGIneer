"""GET /api/files 的 probe=1 / web=1 语义与「URL 定文件」契约（2026-10-31）。

背景：600s 时间窗锁退役。锁防住了加载中途换文件（pdf.js 不发 If-Range，两份字节
被拼乱 → 卡死第 1 块），但副作用是锁定期内第二次打开也拿不到副本（81.8MB 实踩）。
现契约：web=1 → 副本（未就绪回退原件并后台构建）；无 web → **恒原件**（即使副本已
存在）；raw=1 恒原件（下载）。切换由前端 probe=1 探测就绪后换 URL 完成——同一 URL
字节口径恒定，拼乱类 bug 从机制上不可能发生。
"""
import sys
from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient

API_ROOT = Path(__file__).resolve().parents[1]
if str(API_ROOT) not in sys.path:
    sys.path.insert(0, str(API_ROOT))

import docs_routes  # noqa: E402


def _make_app():
    app = FastAPI()
    app.include_router(docs_routes.preview_router, prefix="/api")
    return TestClient(app)


def _make_pdf(tmp_path, rel: str, body: bytes = b"%PDF-1.4 tiny"):
    f = tmp_path / rel
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_bytes(body)
    return f


def test_probe_reports_not_ready_for_small_pdf(tmp_path, monkeypatch):
    monkeypatch.setenv("ANGINEER_DATA_ROOT", str(tmp_path))
    monkeypatch.setattr(docs_routes, "_allowed_roots_cache", None)
    rel = "knowledge/libraries/lib-x/documents/d1/source/a.pdf"
    _make_pdf(tmp_path, rel)  # <1MB：副本条件不满足

    resp = _make_app().get("/api/files", params={"path": rel, "probe": 1})
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("application/json")
    assert resp.json() == {"copy_ready": False}


def test_probe_reports_ready_when_copy_exists(tmp_path, monkeypatch):
    monkeypatch.setenv("ANGINEER_DATA_ROOT", str(tmp_path))
    monkeypatch.setattr(docs_routes, "_allowed_roots_cache", None)
    rel = "knowledge/libraries/lib-x/documents/d1/source/a.pdf"
    _make_pdf(tmp_path, rel)
    copy = tmp_path / "cache" / "pdf_web" / "fake.pdf"
    copy.parent.mkdir(parents=True, exist_ok=True)
    copy.write_bytes(b"%PDF-1.4 copy")
    monkeypatch.setattr(docs_routes, "get_or_build_web_pdf", lambda _p: str(copy))

    resp = _make_app().get("/api/files", params={"path": rel, "probe": 1})
    assert resp.status_code == 200
    assert resp.json() == {"copy_ready": True}


def test_plain_url_serves_original_even_when_copy_exists(tmp_path, monkeypatch):
    """URL 定文件契约的核心回归：无 web=1 恒原件——副本就绪也不许中途换。"""
    monkeypatch.setenv("ANGINEER_DATA_ROOT", str(tmp_path))
    monkeypatch.setattr(docs_routes, "_allowed_roots_cache", None)
    rel = "knowledge/libraries/lib-x/documents/d1/source/a.pdf"
    original = _make_pdf(tmp_path, rel, b"%PDF-1.4 original-bytes")
    copy = tmp_path / "cache" / "pdf_web" / "fake.pdf"
    copy.parent.mkdir(parents=True, exist_ok=True)
    copy.write_bytes(b"%PDF-1.4 copy-bytes")
    monkeypatch.setattr(docs_routes, "get_or_build_web_pdf", lambda _p: str(copy))

    resp = _make_app().get("/api/files", params={"path": rel})
    assert resp.status_code == 200
    assert resp.content == original.read_bytes()

    # raw=1（下载）同样恒原件，web=1 不影响
    resp = _make_app().get("/api/files", params={"path": rel, "raw": 1, "web": 1})
    assert resp.status_code == 200
    assert resp.content == original.read_bytes()


def test_web_url_serves_copy_when_ready_falls_back_to_original(tmp_path, monkeypatch):
    monkeypatch.setenv("ANGINEER_DATA_ROOT", str(tmp_path))
    monkeypatch.setattr(docs_routes, "_allowed_roots_cache", None)
    rel = "knowledge/libraries/lib-x/documents/d1/source/a.pdf"
    original = _make_pdf(tmp_path, rel, b"%PDF-1.4 original-bytes")
    copy = tmp_path / "cache" / "pdf_web" / "fake.pdf"
    copy.parent.mkdir(parents=True, exist_ok=True)
    copy.write_bytes(b"%PDF-1.4 copy-bytes")

    # 未就绪（构建器返回 None）→ 回退原件，不 404
    monkeypatch.setattr(docs_routes, "get_or_build_web_pdf", lambda _p: None)
    resp = _make_app().get("/api/files", params={"path": rel, "web": 1})
    assert resp.status_code == 200
    assert resp.content == original.read_bytes()

    # 就绪 → 副本
    monkeypatch.setattr(docs_routes, "get_or_build_web_pdf", lambda _p: str(copy))
    resp = _make_app().get("/api/files", params={"path": rel, "web": 1})
    assert resp.status_code == 200
    assert resp.content == copy.read_bytes()


def test_probe_and_web_ignored_for_non_pdf(tmp_path, monkeypatch):
    monkeypatch.setenv("ANGINEER_DATA_ROOT", str(tmp_path))
    monkeypatch.setattr(docs_routes, "_allowed_roots_cache", None)
    rel = "knowledge/libraries/lib-x/documents/d1/source/a.md"
    f = _make_pdf(tmp_path, rel, b"hello markdown")

    resp = _make_app().get("/api/files", params={"path": rel, "probe": 1})
    assert resp.json() == {"copy_ready": False}

    resp = _make_app().get("/api/files", params={"path": rel, "web": 1})
    assert resp.status_code == 200
    assert resp.content == f.read_bytes()
