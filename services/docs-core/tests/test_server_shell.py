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


# ---- engine 端口 HTTP 面（2026-10-12 独立壳修复：chat 壳 http_ports 适配器消费）----


def _phrase_items():
    """两候选：i2 phrase 命中（query「罐址选择的要求」→ n-gram「罐址选择」），i1 无关。"""
    return [
        {"item_id": "i1", "entity_type": "block", "doc_id": "d1", "title": "无关条目",
         "text": "完全无关的文本内容", "score": 0.30,
         "metadata": {"doc_title": "别的书", "cite": "K1"}},
        {"item_id": "i2", "entity_type": "block", "doc_id": "d2", "title": "罐址选择",
         "text": "罐址选择应避开软土地基与活动断层", "score": 0.20,
         "citation_target_id": "ct-2",
         "metadata": {"doc_title": "液化天然气码头设计规范", "cite": "K2", "page_idx": 3}},
    ]


def test_engine_ports_normalize_query():
    client, _ = _client_and_module()
    resp = client.post("/api/knowledge/internal/normalize-query", json={"query": "第六十条"})
    assert resp.status_code == 200
    assert "60" in resp.json()["query"]  # 中文数字条款号 → 阿拉伯数字（真实实现）


def test_engine_ports_rerank():
    client, _ = _client_and_module()
    resp = client.post(
        "/api/knowledge/internal/rerank",
        json={"query": "罐址选择的要求", "task_type": "content_qa", "candidates": _phrase_items()},
    )
    assert resp.status_code == 200
    cands = resp.json()["candidates"]
    assert len(cands) == 2
    # phrase 命中 +0.15：0.20→0.35 越过 i1 的 0.30，排第一；rerank_score 回写
    assert cands[0]["item_id"] == "i2"
    assert cands[0]["rerank_score"] > cands[1]["rerank_score"]


def test_engine_ports_relevant_citations():
    client, _ = _client_and_module()
    resp = client.post(
        "/api/knowledge/internal/relevant-citations",
        json={"query": "罐址选择的要求", "items": _phrase_items(), "limit": 5},
    )
    assert resp.status_code == 200
    cits = resp.json()["citations"]
    # phrase 命中优先且只取命中项；字段透传（target_id/marker/page_idx/snippet）
    assert len(cits) == 1
    assert cits[0]["doc_id"] == "d2"
    assert cits[0]["target_id"] == "ct-2"
    assert cits[0]["marker"] == "K2"
    assert cits[0]["page_idx"] == 3
    assert cits[0]["snippet"].startswith("罐址选择")


def test_engine_ports_table_blocks_passthrough():
    client, _ = _client_and_module()
    from docs_core.step09_query import agent_port

    with patch.object(
        agent_port, "table_blocks_provider", return_value=[{"doc_id": "d1"}]
    ) as m:
        resp = client.post(
            "/api/knowledge/internal/table-blocks",
            json={"library_id": "lib-a", "doc_ids": []},
        )
    assert resp.status_code == 200
    assert resp.json()["blocks"] == [{"doc_id": "d1"}]
    m.assert_called_once_with("lib-a", None)  # 空 doc_ids 传 None（全库找文件语义）


class _StubRegistry:
    def __init__(self, tool):
        self._tool = tool

    def get_tool(self, name):
        return self._tool


def test_engine_ports_engtool_run_all_paths():
    client, _ = _client_and_module()
    from docs_core.step09_query import agent_port

    calls = {}

    class _Tool:
        def run(self, **kwargs):
            calls.update(kwargs)
            return {"result": 6.0}

    with patch.object(agent_port, "engtool_registry", return_value=_StubRegistry(_Tool())):
        resp = client.post(
            "/api/knowledge/internal/engtool-run",
            json={"name": "calculator", "kwargs": {"expression": "3+3"}},
        )
    assert resp.status_code == 200
    assert resp.json()["result"] == {"result": 6.0}
    assert calls == {"expression": "3+3"}

    # 工具不存在 → 404（对齐进程内 LookupError("Tool not found")）
    with patch.object(agent_port, "engtool_registry", return_value=_StubRegistry(None)):
        assert client.post(
            "/api/knowledge/internal/engtool-run", json={"name": "nope", "kwargs": {}}
        ).status_code == 404

    # 注册表不可用（engtools 缺失）→ 503
    with patch.object(agent_port, "engtool_registry", side_effect=ImportError("no engtools")):
        assert client.post(
            "/api/knowledge/internal/engtool-run", json={"name": "x", "kwargs": {}}
        ).status_code == 503

    # 执行异常 → 500
    class _Boom:
        def run(self, **kwargs):
            raise RuntimeError("boom")

    with patch.object(agent_port, "engtool_registry", return_value=_StubRegistry(_Boom())):
        assert client.post(
            "/api/knowledge/internal/engtool-run", json={"name": "x", "kwargs": {}}
        ).status_code == 500


def test_token_gate_covers_engine_ports():
    client, _ = _client_and_module()
    with patch.dict(os.environ, {"ANGINEER_API_TOKEN": "tok-2"}):
        assert client.post(
            "/api/knowledge/internal/normalize-query", json={"query": "第六十条"}
        ).status_code == 401
        ok = client.post(
            "/api/knowledge/internal/normalize-query",
            json={"query": "第六十条"},
            headers={"X-API-Key": "tok-2"},
        )
        assert ok.status_code == 200
