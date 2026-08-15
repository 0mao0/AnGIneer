"""
单元测试：DocsRetrievalTool（B1 修复）。

B1：run() 调用 fuse_candidates 签名错误，必抛 TypeError；修复后应正常返回 items。
"""
import os
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../../services/engtools/src")))
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../../services/docs-core/src")))

from engtools.DocsRetrievalTool import DocsRetrievalTool
from docs_core.step09_query.protocols.contracts import RetrievedItem


def _item(item_id: str) -> RetrievedItem:
    return RetrievedItem(
        item_id=item_id,
        entity_type="chunk",
        doc_id="d1",
        title="t",
        text="x",
        score=0.8,
    )


class TestDocsRetrievalTool(unittest.TestCase):
    """B1：fuse 签名错误导致工具不可用。"""

    def test_run_returns_items_without_type_error(self):
        tool = DocsRetrievalTool()
        hits = [_item("a"), _item("b")]
        with patch("engtools.DocsRetrievalTool._resolve_doc_nodes", return_value=[]), patch(
            "docs_core.step09_query.retrieval.dense_retriever.dense_retriever.retrieve",
            return_value=hits,
        ), patch(
            "docs_core.step09_query.retrieval.sparse_retriever.sparse_retriever.retrieve",
            return_value=[],
        ):
            result = tool.run(query="测试", library_id="lib1")

        self.assertIn("items", result)
        self.assertEqual(len(result["items"]), 2)
        self.assertEqual(result["items"][0]["item_id"], "a")


if __name__ == "__main__":
    unittest.main()
