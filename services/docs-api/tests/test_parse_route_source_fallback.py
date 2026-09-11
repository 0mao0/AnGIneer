"""POST /api/knowledge/parse 的 file_path 兜底契约。

生产实况：nodes.file_path 里 183 条是开发机绝对路径（D:\\AI\\AnGIneer\\...），
在 Linux 容器里 Path(...).exists() 恒为 False。修复前该路由直接 404「源文件不存在」，
而原件就躺在 libraries/<lib>/documents/<doc>/source/ 下 —— 「开始解析」因此点不通。
本测试锁住三点：失效路径要走规范目录兜底、兜底拿不到仍 404、有效路径保持原样不变。
"""
import sys
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

API_ROOT = Path(__file__).resolve().parents[1]
if str(API_ROOT) not in sys.path:
    sys.path.insert(0, str(API_ROOT))

import docs_routes  # noqa: E402

LIB = "lib-b07ed174"
DOC = "v1-dba3751d9acb"
# 生产实况里的失效路径形如 D:\AI\AnGIneer\data\knowledge_base\libraries\...，
# 但那份库在开发机上真实存在，直接用它做夹具会在 Windows 上走不到兜底分支。
# 故换成一个不存在的根：形态一致（带盘符 + 反斜杠），任何机器上都解析不到。
FOREIGN_PATH = rf"D:\__missing_machine__\libraries\{LIB}\documents\{DOC}\source\2404.14603v2.pdf"


class _RecordingOrchestrator:
    """替身：记录路由把哪个路径交给了编排层，不真起解析线程。"""

    def __init__(self) -> None:
        self.ensure_calls: list = []
        self.create_calls: list = []

    def ensure_document(self, library_id, file_path, doc_id=None):
        self.ensure_calls.append({"library_id": library_id, "file_path": file_path, "doc_id": doc_id})
        return doc_id

    def create_parse_task(self, library_id, doc_id, file_path, parse_options=None):
        self.create_calls.append({"library_id": library_id, "doc_id": doc_id, "file_path": file_path})
        return {"task_id": "parse-test", "doc_id": doc_id, "status": "processing", "progress": 0, "stage": "queued"}


@pytest.fixture
def client(monkeypatch):
    stub = _RecordingOrchestrator()
    monkeypatch.setattr(docs_routes, "parse_orchestrator", stub)
    app = FastAPI()
    app.include_router(docs_routes.docs_router, prefix="/api/knowledge")
    return TestClient(app), stub


def _make_canonical_source(tmp_path, monkeypatch, name: str = "2404.14603v2.pdf") -> Path:
    monkeypatch.setenv("KNOWLEDGE_BASE_DIR", str(tmp_path))
    source_dir = tmp_path / "libraries" / LIB / "documents" / DOC / "source"
    source_dir.mkdir(parents=True)
    source = source_dir / name
    source.write_bytes(b"%PDF-1.5\n")
    return source


def test_foreign_path_fixture_is_really_unresolvable() -> None:
    """护栏：FOREIGN_PATH 若在某台机器上真存在，下面两个用例就失去意义。"""
    assert not Path(FOREIGN_PATH).exists()


def test_foreign_file_path_falls_back_to_canonical(client, tmp_path, monkeypatch) -> None:
    canonical = _make_canonical_source(tmp_path, monkeypatch)
    http, stub = client

    resp = http.post("/api/knowledge/parse", json={"library_id": LIB, "doc_id": DOC, "file_path": FOREIGN_PATH})

    assert resp.status_code == 200, resp.text
    assert stub.create_calls[0]["file_path"] == str(canonical)


def test_404_when_neither_path_nor_canonical_exists(client, tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("KNOWLEDGE_BASE_DIR", str(tmp_path))
    http, stub = client

    resp = http.post("/api/knowledge/parse", json={"library_id": LIB, "doc_id": DOC, "file_path": FOREIGN_PATH})

    assert resp.status_code == 404
    assert "源文件不存在" in resp.json()["detail"]
    assert stub.create_calls == []


def test_valid_file_path_is_used_as_is(client, tmp_path, monkeypatch) -> None:
    """上传通道不能退化：请求路径真实存在时原样使用，不被规范目录顶替。"""
    monkeypatch.setenv("KNOWLEDGE_BASE_DIR", str(tmp_path / "empty_kb"))
    uploaded = tmp_path / "incoming.pdf"
    uploaded.write_bytes(b"%PDF-1.5\n")
    http, stub = client

    resp = http.post("/api/knowledge/parse", json={"library_id": LIB, "doc_id": DOC, "file_path": str(uploaded)})

    assert resp.status_code == 200, resp.text
    assert stub.create_calls[0]["file_path"] == str(uploaded)
