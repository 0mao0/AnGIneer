"""docs-core [server] 壳管道测试：health / 鉴权门 / 路由接线 / download inline。

全桩替身（docs_service、stats、retrieve 均替换），不触库、不触网。
自建 docs_service 实例的统计口径由 docs_core.knowledge_stats 单元照看（同源抽出）。
"""
import os
import sys
from unittest.mock import patch

import pytest

pytest.importorskip("fastapi")
pytest.importorskip("httpx")

from fastapi.testclient import TestClient  # noqa: E402


class _StubNode:
    def __init__(self, library_id):
        self.type = "document"
        self.library_id = library_id

    def model_dump(self, mode="json"):
        return {"id": "doc-1", "title": "示例文档", "type": "document",
                "library_id": self.library_id}


class _StubDocsService:
    def __init__(self):
        self.library_id = "lib-a"

    def list_libraries(self):
        return [{"id": "lib-a", "name": "库A", "group": "system"}]

    def list_nodes(self, library_id):
        return [_StubNode(library_id)]

    def get_node(self, doc_id):
        if doc_id == "doc-missing":
            return None
        return _StubNode(self.library_id)


def _client_and_module():
    from docs_core.server import app as shell_app

    return TestClient(shell_app), sys.modules["docs_core.server.app"]


def test_health_ok():
    client, _ = _client_and_module()
    resp = client.get("/health")
    assert resp.status_code == 200
    body = resp.json()
    assert body["service"] == "retrieval-api"
    assert body["status"] in ("ok", "degraded")
    assert "data_root" in body


def test_libraries_and_doc_nodes():
    client, mod = _client_and_module()
    with patch.object(mod, "get_docs_service", return_value=_StubDocsService()):
        resp = client.get("/api/knowledge/libraries")
        assert resp.status_code == 200
        assert resp.json()[0]["id"] == "lib-a"

        resp = client.get("/api/knowledge/internal/doc-nodes", params={"library_id": "lib-a"})
        assert resp.status_code == 200
        body = resp.json()
        assert body["total"] == 1
        assert body["nodes"][0]["type"] == "document"


def test_retrieve_passthrough():
    client, mod = _client_and_module()
    captured = {}

    def _stub_retrieve(**kwargs):
        captured.update(kwargs)
        return {"items": [], "stage_times": {"dense": 0.01}}

    with patch.object(mod, "retrieve_knowledge", _stub_retrieve):
        resp = client.post(
            "/api/knowledge/internal/retrieve",
            json={"query": "低水位", "library_id": "lib-a", "top_k": 5, "mode": "text"},
        )
    assert resp.status_code == 200
    assert resp.json()["stage_times"] == {"dense": 0.01}
    assert captured["library_id"] == "lib-a"
    assert captured["top_k"] == 5
    # 空集合透传为 None（单库语义，与内部服务逐位一致）
    assert captured["library_ids"] is None


def test_stats_passthrough():
    client, mod = _client_and_module()
    with patch.object(
        mod, "compute_knowledge_stats", return_value={"library_id": "lib-a", "stub": True}
    ):
        resp = client.get("/api/knowledge/stats", params={"library_id": "lib-a"})
    assert resp.status_code == 200
    assert resp.json()["stub"] is True


def test_download_missing_node_404_and_inline_header(tmp_path):
    client, mod = _client_and_module()
    src = tmp_path / "示例文档.pdf"
    src.write_bytes(b"%PDF-1.4 stub")

    stub = _StubDocsService()
    with patch.object(mod, "get_docs_service", return_value=stub), patch.object(
        mod.file_storage,
        "get_doc_manifest",
        return_value={"source_file": str(src)},
    ):
        assert client.get("/api/knowledge/documents/doc-missing/download").status_code == 404

        resp = client.get(
            "/api/knowledge/documents/doc-1/download",
            params={"disposition": "inline"},
        )
        assert resp.status_code == 200
        assert "inline" in resp.headers.get("content-disposition", "")

        resp2 = client.get("/api/knowledge/documents/doc-1/download")
        assert resp2.status_code == 200
        assert "attachment" in resp2.headers.get("content-disposition", "")


def test_token_gate_optional():
    client, mod = _client_and_module()
    stub = _StubDocsService()
    with patch.dict(os.environ, {"ANGINEER_API_TOKEN": "tok-1"}), \
         patch.object(mod, "get_docs_service", return_value=stub):
        assert client.get("/api/knowledge/libraries").status_code == 401
        assert client.get("/health").status_code == 200
        ok = client.get("/api/knowledge/libraries", headers={"X-API-Key": "tok-1"})
        assert ok.status_code == 200
