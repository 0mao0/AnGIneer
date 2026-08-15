"""阶段 3b 测试：docs-core retrieve_service——五路召回 + 融合 + doc_title 注入（rerank/装配归调用方）。"""
import os
import sys
import unittest
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../../services/docs-core/src")))

from docs_core.step09_query.protocols.contracts import RetrievedItem  # noqa: E402
from docs_core.step09_query.retrieve_service import retrieve_knowledge  # noqa: E402


class _FakeRetriever:
    def __init__(self, items):
        self._items = items

    def retrieve(self, *args, **kwargs):
        return list(self._items)


class _FailRetriever:
    def retrieve(self, *args, **kwargs):
        raise RuntimeError("boom")


def _make_item(item_id="a", doc_id="d1", text="正文证据"):
    return RetrievedItem(
        item_id=item_id,
        entity_type="chunk",
        doc_id=doc_id,
        title="条文",
        text=text,
        score=0.9,
        metadata={},
    )


class RetrieveKnowledgeTests(unittest.TestCase):
    def test_text_mode_fuses_sources_and_injects_doc_title(self):
        node = SimpleNamespace(id="d1", title="规范A", type="document")
        result = retrieve_knowledge(
            query="测试",
            library_id="lib-x",
            mode="text",
            dense=_FakeRetriever([_make_item()]),
            sparse=_FakeRetriever([]),
            clause=_FakeRetriever([]),
            doc_nodes=[node],
        )

        self.assertEqual(result["total"], 1)
        item = result["items"][0]
        self.assertEqual(item["item_id"], "a")
        self.assertEqual(item["metadata"]["doc_title"], "规范A")

    def test_table_mode_uses_table_and_formula_sources(self):
        result = retrieve_knowledge(
            query="表格",
            mode="table",
            table=_FakeRetriever([_make_item(item_id="t1", text="表格内容")]),
            formula=_FakeRetriever([]),
            doc_nodes=[],
        )

        self.assertEqual(result["total"], 1)
        self.assertEqual(result["items"][0]["item_id"], "t1")

    def test_scope_is_passed_to_retrievers(self):
        seen = {}

        class _Spy:
            def retrieve(self, request, nodes, *args):
                seen["library_id"] = request.library_id
                seen["doc_ids"] = list(request.doc_ids)
                return []

        retrieve_knowledge(
            query="q", library_id="lib-y", doc_ids=["d9"],
            dense=_Spy(), sparse=_Spy(), clause=_Spy(), doc_nodes=[],
        )

        self.assertEqual(seen["library_id"], "lib-y")
        self.assertEqual(seen["doc_ids"], ["d9"])

    def test_all_sources_fail_returns_error(self):
        result = retrieve_knowledge(
            query="q",
            dense=_FailRetriever(), sparse=_FailRetriever(), clause=_FailRetriever(),
            doc_nodes=[],
        )
        self.assertEqual(result["error"], "检索全部失败")

    def test_loads_doc_nodes_when_not_provided(self):
        node = SimpleNamespace(id="d1", title="规范B", type="document")
        with patch(
            "docs_core.step09_query.retrieve_service._load_doc_nodes",
            return_value=[node],
        ) as loader:
            result = retrieve_knowledge(
                query="q", library_id="lib-z",
                dense=_FakeRetriever([_make_item()]),
                sparse=_FakeRetriever([]),
                clause=_FakeRetriever([]),
            )

        loader.assert_called_once_with("lib-z", None)
        self.assertEqual(result["items"][0]["metadata"]["doc_title"], "规范B")


if __name__ == "__main__":
    unittest.main()
