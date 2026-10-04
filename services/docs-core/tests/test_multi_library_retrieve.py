"""retrieve_knowledge 多库扇出：分组并行、按库分池融合、40 候选池、错误分支。"""
import sys

from docs_core.step09_query.protocols.contracts import KnowledgeNode, RetrievedItem
from docs_core.step09_query.retrieve_service import retrieve_knowledge


class _FakeDense:
    def __init__(self):
        self.calls: list[tuple[str, list[str]]] = []

    def retrieve(self, request, nodes, task_type):
        self.calls.append((request.library_id, [n.id for n in nodes]))
        return [
            RetrievedItem(
                item_id=f"{n.id}:c1", entity_type="content", doc_id=n.id,
                title=n.title, text="x", score=1.0 - i * 0.1,
                citation_target_id=f"T-{n.id}", retrieval_policy="dense",
                metadata={"citation_target_id": f"T-{n.id}"},
            )
            for i, n in enumerate(nodes)
        ]


class _Empty:
    def retrieve(self, request, nodes, *args): return []


class _Raises:
    def __init__(self, msg: str = "boom"):
        self.msg = msg

    def retrieve(self, *args, **kwargs):
        raise RuntimeError(self.msg)


def _nodes() -> dict[str, list[KnowledgeNode]]:
    # KnowledgeNode.library_id 为必填契约字段（现码 models 校准）
    return {
        "libA": [KnowledgeNode(id="a1", type="document", title="A1", library_id="libA")],
        "libB": [KnowledgeNode(id="b1", type="document", title="B1", library_id="libB")],
    }


class TestRetrieveMultiLibrary:
    def test_multi_merges_both_libraries_with_tags(self, monkeypatch):
        nodes_map = _nodes()
        monkeypatch.setattr(
            "docs_core.step09_query.retrieve_service._load_doc_nodes",
            lambda lib, doc_ids: nodes_map.get(lib, []),
        )
        dense = _FakeDense()
        result = retrieve_knowledge(
            query="q", library_ids=["libA", "libB"], top_k=20,
            mode="text", dense=dense, sparse=_Empty(), clause=_Empty(),
        )
        libs = {it["metadata"].get("library_id") for it in result["items"]}
        assert libs == {"libA", "libB"}
        # 同 citation_target 形状（T-a1/T-b1 不同）不合并；两库候选都进结果
        assert {it["doc_id"] for it in result["items"]} == {"a1", "b1"}
        # 分组扇出契约：测试注册表隔离下两库均未注册 → 全局默认 collection → 同组一组，
        # dense 每组被调一次、入参节点=组内并集、library_id=组首库（collection 路由）
        assert dense.calls == [("libA", ["a1", "b1"])]

    def test_single_library_unchanged_pool_keys(self, monkeypatch):
        nodes_map = _nodes()
        monkeypatch.setattr(
            "docs_core.step09_query.retrieve_service._load_doc_nodes",
            lambda lib, doc_ids: nodes_map.get(lib, []),
        )
        dense = _FakeDense()
        result = retrieve_knowledge(
            query="q", library_id="libA", top_k=20,
            mode="text", dense=dense, sparse=_Empty(), clause=_Empty(),
        )
        assert "dense" in result["debug"]["sources"]  # 铁律 1：单库池键无 @ 后缀
        assert not any("@" in key for key in result["debug"]["sources"])
        assert all(not it["metadata"].get("library_id") for it in result["items"])
        assert dense.calls == [("libA", ["a1"])]

    def test_sparse_failure_partial_errors_key_and_other_paths_kept(self, monkeypatch):
        nodes_map = _nodes()
        monkeypatch.setattr(
            "docs_core.step09_query.retrieve_service._load_doc_nodes",
            lambda lib, doc_ids: nodes_map.get(lib, []),
        )
        result = retrieve_knowledge(
            query="q", library_ids=["libA", "libB"], top_k=20,
            mode="text", dense=_FakeDense(), sparse=_Raises("fts down"), clause=_Empty(),
        )
        errors = result.get("partial_errors") or {}
        # 未注册库同组 → 错误键为 {kind}@{组内库+连接}
        assert "sparse@libA+libB" in errors
        assert "fts down" in errors["sparse@libA+libB"]
        assert "error" not in result
        # dense 路结果完整保留（两库都打标）
        assert {it["metadata"].get("library_id") for it in result["items"]} == {"libA", "libB"}

    def test_all_paths_failure_returns_error_detail(self, monkeypatch):
        nodes_map = _nodes()
        monkeypatch.setattr(
            "docs_core.step09_query.retrieve_service._load_doc_nodes",
            lambda lib, doc_ids: nodes_map.get(lib, []),
        )
        result = retrieve_knowledge(
            query="q", library_ids=["libA", "libB"], top_k=20,
            mode="text", dense=_Raises("d"), sparse=_Raises("s"), clause=_Raises("c"),
        )
        assert result.get("error") == "检索全部失败"
        assert set(result.get("detail") or {}) == {
            "dense@libA+libB", "sparse@libA+libB", "clause@libA+libB",
        }


class _FakeSvc:
    """伪 docs_service：仅 meta_store.get_node_library_id 读穿（分桶归属用）。"""

    def __init__(self, mapping: dict[str, str], error: bool = False):
        self._mapping = mapping
        self._error = error

    class _MetaStore:
        def __init__(self, outer):
            self._outer = outer

        def get_node_library_id(self, doc_id):
            if self._outer._error:
                raise RuntimeError("meta db down")
            return self._outer._mapping.get(doc_id)

    @property
    def meta_store(self):
        return self._MetaStore(self)


class TestDocNodesBucketing:
    """doc_nodes 外部注入路径：按 meta 读穿归属分桶（评审 P2-12 + 修复轮 Important 1/4c）。"""

    def _patch_svc(self, monkeypatch, svc):
        import docs_core.docs_service  # noqa: F401 — 确保 sys.modules 里是真模块（非包代理）
        real = sys.modules["docs_core.docs_service"]
        monkeypatch.setattr(real, "get_docs_service", lambda: svc)

    def test_injected_nodes_bucketed_by_meta_library(self, monkeypatch):
        # meta 归属刻意与注入顺序相反：a1→libB、b1→libA——打标只可能来自读穿而非平铺顺序
        self._patch_svc(monkeypatch, _FakeSvc({"a1": "libB", "b1": "libA"}))
        result = retrieve_knowledge(
            query="q", library_ids=["libA", "libB"], top_k=20,
            mode="text", dense=_FakeDense(), sparse=_Empty(), clause=_Empty(),
            doc_nodes=[
                KnowledgeNode(id="a1", type="document", title="A1", library_id="libA"),
                KnowledgeNode(id="b1", type="document", title="B1", library_id="libB"),
            ],
        )
        tags = {it["doc_id"]: it["metadata"].get("library_id") for it in result["items"]}
        assert tags == {"a1": "libB", "b1": "libA"}

    def test_meta_store_error_falls_back_to_head_library(self, monkeypatch):
        # Important 1 守卫：meta 库抛错不许整请求 500——全部节点回退集合首库
        self._patch_svc(monkeypatch, _FakeSvc({}, error=True))
        result = retrieve_knowledge(
            query="q", library_ids=["libA", "libB"], top_k=20,
            mode="text", dense=_FakeDense(), sparse=_Empty(), clause=_Empty(),
            doc_nodes=[
                KnowledgeNode(id="a1", type="document", title="A1", library_id="libA"),
                KnowledgeNode(id="b1", type="document", title="B1", library_id="libB"),
            ],
        )
        assert "error" not in result
        assert {it["metadata"].get("library_id") for it in result["items"]} == {"libA"}
