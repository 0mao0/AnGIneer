"""entity_search / _load_doc_nodes 双轨（HTTP 优先 + 本地回退 + 禁用开关）回归测试。"""
from types import SimpleNamespace

import pytest

from angineer_core import agent_tools
from angineer_core.agent_tools import RetrieverAdapter
from angineer_core.policy_query import _load_doc_nodes

ENTITY = {
    "entity_id": "e1",
    "name": "混凝土强度等级",
    "layer": "concept",
    "aliases": ["混凝土标号"],
    "description": "混凝土抗压强度分级指标",
    "source_doc": "doc-x",
    "source_clause": "4.1.1",
    "library_id": "default",
    "status": "approved",
}


class FakeClient:
    def __init__(self, entities=None, exc=None):
        self._entities = entities if entities is not None else [ENTITY]
        self._exc = exc
        self.calls = 0

    def entity_search(self, *, query, library_id, limit):
        self.calls += 1
        if self._exc:
            raise self._exc
        return list(self._entities)


class FakeGraphStore:
    """本地回退路径的 GraphStore 替身。"""

    def __init__(self, *args, **kwargs):
        FakeGraphStore.init_calls += 1

    init_calls = 0

    def search_entities(self, query, limit=20, library_id=None):
        return [ENTITY]


@pytest.fixture(autouse=True)
def _reset_fallback_env(monkeypatch):
    monkeypatch.delenv("ANGINEER_DISABLE_LOCAL_FALLBACK", raising=False)
    FakeGraphStore.init_calls = 0
    monkeypatch.setattr(
        "docs_core.step07_graph.graph_store.GraphStore", FakeGraphStore, raising=True
    )


def _tool(client):
    return RetrieverAdapter.entity_search(library_id="default", retrieval_client=client)


def test_http_path_skips_local_store():
    client = FakeClient()
    result = _tool(client).handler(query="混凝土")
    assert client.calls == 1
    assert FakeGraphStore.init_calls == 0
    assert result["total"] == 1
    assert result["entities"][0]["entity_id"] == "e1"
    assert result["evidences"][0]["kind"] == "graph_entity"


def test_fallback_to_local_on_http_failure():
    client = FakeClient(exc=RuntimeError("down"))
    result = _tool(client).handler(query="混凝土")
    assert FakeGraphStore.init_calls == 1  # 回退生效
    assert result["total"] == 1


def test_disable_switch_blocks_fallback(monkeypatch):
    monkeypatch.setenv("ANGINEER_DISABLE_LOCAL_FALLBACK", "1")
    client = FakeClient(exc=RuntimeError("down"))
    result = _tool(client).handler(query="混凝土")
    assert "error" in result
    assert FakeGraphStore.init_calls == 0


def test_disable_switch_without_client(monkeypatch):
    monkeypatch.setenv("ANGINEER_DISABLE_LOCAL_FALLBACK", "1")
    monkeypatch.delenv("ANGINEER_DOCS_API_URL", raising=False)
    result = _tool(None).handler(query="混凝土")
    assert "error" in result
    assert FakeGraphStore.init_calls == 0


def test_no_client_defaults_to_local():
    result = _tool(None).handler(query="混凝土")
    assert FakeGraphStore.init_calls == 1
    assert result["total"] == 1


# ---- policy_query._load_doc_nodes ----


class FakeNodesClient:
    def __init__(self, nodes=None, exc=None):
        self._nodes = nodes or []
        self._exc = exc

    def list_doc_nodes(self, library_id):
        if self._exc:
            raise self._exc
        return list(self._nodes)


def _node(node_id):
    return SimpleNamespace(id=node_id, type="document", title=node_id)


def test_doc_nodes_http_path(monkeypatch):
    monkeypatch.setattr(
        "angineer_core.docs_retrieval_client.client_from_env",
        lambda: FakeNodesClient(nodes=[_node("d1"), _node("d2")]),
    )
    nodes = _load_doc_nodes("default", ["d2"])
    assert [n.id for n in nodes] == ["d2"]


def test_doc_nodes_disable_switch_returns_empty(monkeypatch):
    monkeypatch.setenv("ANGINEER_DISABLE_LOCAL_FALLBACK", "1")
    monkeypatch.setattr(
        "angineer_core.docs_retrieval_client.client_from_env",
        lambda: FakeNodesClient(exc=RuntimeError("down")),
    )
    assert _load_doc_nodes("default", None) == []
