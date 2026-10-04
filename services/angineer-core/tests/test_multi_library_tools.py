"""knowledge_search 多库（Phase B4）三块锁：

1. memo 键集合化：多库与单库不串桶、序不敏感、去重 strip 归一、单元素集合=单值；
2. 透传链中段：工厂→impl、impl→client.retrieve、impl→本地端口（条件注入）逐跳收到集合，
   且结果 scope 带 library_ids——删除任一注入行必须有对应用例变红；
3. Evidence 逐项标注来源库（评审 P0-1）：item.metadata["library_id"] 优先、空值回退首库。

item 形态按现码 agent_tools._items_to_evidences（getattr 读对象字段），用
angineer_core.docs_retrieval_client.RetrievedItem（pydantic 对象）构造。
"""
import pytest

from angineer_core import agent_tools
from angineer_core.docs_retrieval_client import RetrievedItem


def _kwargs(**over):
    base = dict(
        query="q", library_id="libA", doc_ids=[], top_k=20,
        task_type="content_qa", filters=None, dense=None, sparse=None, clause=None,
    )
    base.update(over)
    return base


@pytest.fixture(autouse=True)
def _memo_enabled(monkeypatch):
    monkeypatch.setattr(agent_tools, "route_parallel_enabled", lambda: True)
    with agent_tools._SEARCH_MEMO_LOCK:
        agent_tools._SEARCH_MEMO.clear()
    yield
    with agent_tools._SEARCH_MEMO_LOCK:
        agent_tools._SEARCH_MEMO.clear()


class TestSearchMemoKeyMulti:
    def test_multi_key_contains_library_set(self):
        key_multi = agent_tools._search_memo_key(_kwargs(library_ids=["libA", "libB"]))
        key_single = agent_tools._search_memo_key(_kwargs())
        assert key_multi is not None and key_single is not None
        assert key_multi != key_single

    def test_multi_key_order_insensitive(self):
        a = agent_tools._search_memo_key(_kwargs(library_ids=["libA", "libB"]))
        b = agent_tools._search_memo_key(_kwargs(library_id="libB", library_ids=["libB", "libA"]))
        assert a == b

    def test_single_element_list_same_key_as_str(self):
        # 兼容铁律 3 的 memo 侧镜像：单元素集合与旧单值同键（预检/主路不串桶）
        assert agent_tools._search_memo_key(
            _kwargs(library_ids=["libA"])
        ) == agent_tools._search_memo_key(_kwargs())

    def test_library_set_dedup_strip_and_single_pin(self):
        # 归一口径对齐 scope_hash_for：每项 strip 后排序去重，重复/空白不产生新键位
        assert agent_tools._search_memo_key(
            _kwargs(library_ids=[" libB ", "libA", "libB"])
        ) == agent_tools._search_memo_key(_kwargs(library_ids=["libA", "libB"]))
        # 单元素集合与单值同键（显式钉住，不依赖 _kwargs 的默认 library_id）
        assert agent_tools._search_memo_key(
            _kwargs(library_id="libZ", library_ids=["libZ"])
        ) == agent_tools._search_memo_key(_kwargs(library_id="libZ"))

    def test_impl_forwards_library_ids(self, monkeypatch):
        """第 0 跳：工厂 closure → _run_knowledge_search → impl 收到集合。"""
        seen = {}

        def fake_impl(**kwargs):
            seen.update(kwargs)
            return {"items": [], "ok": True}

        monkeypatch.setattr(agent_tools, "_run_knowledge_search_impl", fake_impl)
        tool = agent_tools.RetrieverAdapter.knowledge_search(
            library_id="libA", library_ids=["libA", "libB"],
        )
        tool.handler(query="q")
        assert seen.get("library_ids") == ["libA", "libB"]


class TestLibraryIdsPassthroughChain:
    """透传链中段锁：impl→client.retrieve 与 impl→本地端口两跳真收到集合。"""

    def test_client_retrieve_receives_set(self):
        captured = {}

        class _Client:
            def retrieve(self, *, mode, query, library_id, doc_ids, top_k,
                         task_type, filters, library_ids=None):
                captured["library_ids"] = library_ids
                return [], {}

        result = agent_tools._run_knowledge_search(
            query="q", library_id="libA", library_ids=["libA", "libB"],
            retrieval_client=_Client(), rerank=False, prefix="K",
        )
        assert captured["library_ids"] == ["libA", "libB"]  # 删 retrieve 注入行即 KeyError 红
        assert result.get("scope", {}).get("library_ids") == ["libA", "libB"]

    def test_local_port_receives_set_on_fallback(self, monkeypatch):
        from angineer_core import ports

        seen = {}

        def fake_port(*, query, library_id, doc_ids, top_k, task_type, filters,
                      nodes, dense, sparse, clause, formula, library_ids=None):
            seen["library_ids"] = library_ids
            return {"items": []}

        monkeypatch.setattr(ports, "_knowledge_local_search", fake_port)

        class _DownClient:
            def retrieve(self, **kwargs):
                raise RuntimeError("docs-api down")  # 强制回退本地端口

        result = agent_tools._run_knowledge_search(
            query="q", library_id="libA", library_ids=["libA", "libB"],
            retrieval_client=_DownClient(), rerank=False, prefix="K",
        )
        # 删条件注入行 → 端口只收 None → 红；端口收严格集合（非 or None 的 None 也可区分）
        assert seen["library_ids"] == ["libA", "libB"]
        assert result.get("scope", {}).get("library_ids") == ["libA", "libB"]


class TestEvidenceLibraryAttribution:
    def test_per_item_library_from_metadata(self):
        # P0 修复（评审 P0-1）：证据库标注逐项按 item.metadata，空值回退入参首库
        items = [
            RetrievedItem(
                item_id="i1", entity_type="content", doc_id="d1",
                metadata={"library_id": "libB"},
            ),
            RetrievedItem(item_id="i2", entity_type="content", doc_id="d2", metadata={}),
        ]
        evs = agent_tools._items_to_evidences(
            items, kind="text", source="knowledge", library_id="libA",
        )  # kind="text"：EvidenceKind 枚举无 "content"（计划片段笔误，见 base_contracts.py:188）
        assert evs[0]["library_id"] == "libB"  # item 自带标签优先
        assert evs[1]["library_id"] == "libA"  # 无标签回退集合首库
