"""chat 壳 HTTP 端口适配器测试（2026-10-12 独立壳修复）。

覆盖：注册开关（未配 URL / ANGINEER_HTTP_PORTS=0 不注册）、六适配器透传、
失败降级（绝不抛错——引擎对大部分端口调用没有 try）、table_blocks 显式失败、
engtool 注册表 duck-type、启动事件端到端注册。全部以桩 client 替身，不触网。
"""
import os
from unittest.mock import patch

import pytest

from angineer_core import ports
from angineer_core.server import http_ports


class _StubClient:
    """方法级桩：handlers["rerank"](...) —— 未提供的调用直接 AssertionError。"""

    def __init__(self, **handlers):
        self._handlers = handlers

    def __getattr__(self, name):
        def _call(*args, **kwargs):
            handler = self._handlers.get(name)
            if handler is None:
                raise AssertionError(f"stub client missing handler: {name}")
            return handler(*args, **kwargs)

        return _call


def test_disabled_without_url():
    with patch.dict(os.environ, {"ANGINEER_DOCS_API_URL": ""}):
        assert http_ports.http_ports_enabled() is False
        assert http_ports.register_http_ports() is False


def test_disabled_by_switch():
    with patch.dict(
        os.environ, {"ANGINEER_DOCS_API_URL": "http://x:8310", "ANGINEER_HTTP_PORTS": "0"}
    ):
        assert http_ports.http_ports_enabled() is False


def test_register_when_configured():
    with patch.dict(os.environ, {"ANGINEER_DOCS_API_URL": "http://x:8310"}), patch.object(
        http_ports, "client_from_env", lambda: object()
    ):
        assert http_ports.register_http_ports() is True
    assert ports.get_query_normalizer() is http_ports._normalize_query
    assert ports.get_relevant_citations() is http_ports._relevant_citations
    assert ports.get_table_blocks_provider() is http_ports._table_blocks
    assert ports.get_engtool_registry() is http_ports._engtool_registry
    assert ports.get_local_rerank() is http_ports._local_rerank
    assert ports.get_local_nodes_loader() is http_ports._local_nodes_loader


def test_adapters_pass_through():
    stub = _StubClient(
        normalize_query=lambda q: f"归一:{q}",
        rerank=lambda q, t, cands: ["reranked"] + list(cands),
        relevant_citations=lambda q, items, limit: [{"target_id": "t1", "limit": limit}],
        list_doc_nodes=lambda lib: [f"node:{lib}"],
        table_blocks=lambda lib, docs: [{"doc_id": lib, "docs": docs}],
    )
    with patch.object(http_ports, "client_from_env", lambda: stub):
        assert http_ports._normalize_query("第六十条") == "归一:第六十条"
        assert http_ports._normalize_query("") == ""  # 空查询不进 HTTP
        assert http_ports._local_rerank("q", "content_qa", ["a"]) == ["reranked", "a"]
        assert http_ports._relevant_citations("q", [1], 7) == [{"target_id": "t1", "limit": 7}]
        assert http_ports._local_nodes_loader("lib-a", None) == ["node:lib-a"]
        assert http_ports._table_blocks("lib-a", ["d"]) == [{"doc_id": "lib-a", "docs": ["d"]}]


def test_adapters_degrade_on_failure():
    def _boom(*_a, **_k):
        raise RuntimeError("retrieval down")

    stub = _StubClient(
        normalize_query=_boom, rerank=_boom, relevant_citations=_boom, list_doc_nodes=_boom
    )
    with patch.object(http_ports, "client_from_env", lambda: stub):
        assert http_ports._normalize_query("q") == "q"            # 原样返回
        assert http_ports._local_rerank("q", "t", ["c"]) == ["c"]  # 原序返回
        assert http_ports._relevant_citations("q", [1], 5) == []
        assert http_ports._local_nodes_loader("lib", None) == []
    # client 未配置（None）时同样降级
    with patch.object(http_ports, "client_from_env", lambda: None):
        assert http_ports._normalize_query("q") == "q"
        assert http_ports._relevant_citations("q", [1], 5) == []


def test_table_blocks_failure_raises():
    """table_blocks 例外：消费方 canonical_table_lookup 自带 try/except——显式失败上浮。"""

    def _boom(*_a, **_k):
        raise RuntimeError("retrieval down")

    with patch.object(http_ports, "client_from_env", lambda: _StubClient(table_blocks=_boom)):
        with pytest.raises(RuntimeError):
            http_ports._table_blocks("lib", None)
    with patch.object(http_ports, "client_from_env", lambda: None):
        with pytest.raises(RuntimeError):
            http_ports._table_blocks("lib", None)


def test_engtool_registry_shim():
    calls = {}

    def _run_engtool(name, kwargs):
        calls.update({"name": name, "kwargs": kwargs})
        return {"result": 6.0}

    with patch.object(http_ports, "client_from_env", lambda: _StubClient(run_engtool=_run_engtool)):
        registry = http_ports._engtool_registry()
        tool = registry.get_tool("calculator")
        assert tool.run(expression="3+3") == {"result": 6.0}
    assert calls == {"name": "calculator", "kwargs": {"expression": "3+3"}}


def test_startup_event_registers_ports():
    """壳启动事件端到端：配了 URL 时 TestClient 启动即注册六端口。"""
    pytest.importorskip("fastapi")
    pytest.importorskip("httpx")
    from fastapi.testclient import TestClient

    from angineer_core.server import app as shell_app

    with patch.dict(os.environ, {"ANGINEER_DOCS_API_URL": "http://retrieval.test:8310"}), patch.object(
        http_ports, "client_from_env", lambda: object()
    ):
        with TestClient(shell_app):
            assert ports.get_relevant_citations() is http_ports._relevant_citations
            assert ports.get_local_rerank() is http_ports._local_rerank


def test_engine_wiring_citations_via_registered_adapter():
    """引擎装配点直连验证（DredgeAI 验收锚的单元化）：注册后 _build_relevant_citations
    走 HTTP 适配器返回引用——修复前这里恒为 []（端口未注册 → 「citations 恒空」）。"""
    from angineer_core.agent_tools import _build_relevant_citations

    stub = _StubClient(relevant_citations=lambda q, items, limit: [{"target_id": "t-http"}])
    with patch.dict(os.environ, {"ANGINEER_DOCS_API_URL": "http://retrieval.test:8310"}), patch.object(
        http_ports, "client_from_env", lambda: stub
    ):
        assert http_ports.register_http_ports() is True
        cits = _build_relevant_citations("罐址选择的要求", [object()])
    assert cits and cits[0]["target_id"] == "t-http"
