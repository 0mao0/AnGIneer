"""Dispatcher 检索链路单元测试。"""
import sys
import unittest
from pathlib import Path
from unittest.mock import patch, MagicMock


ANGINEER_CORE_SRC = Path(__file__).resolve().parents[1] / "src"
if str(ANGINEER_CORE_SRC) not in sys.path:
    sys.path.insert(0, str(ANGINEER_CORE_SRC))

from angineer_core.base_contracts import IntentResult


class DispatcherRetrievalTests(unittest.TestCase):
    """验证 dispatcher 检索路径的参数透传。"""

    def test_dispatch_semantic_passes_filters_into_fuse_candidates(self):
        """当前 _dispatch_semantic 未将 filters 传入 fuse_candidates。"""
        from angineer_core.dispatcher import Dispatcher

        dispatcher = Dispatcher()
        intent = IntentResult(
            intent_level="L1",
            primary_level="L1",
            service_mode="semantic_retrieval",
            execution_plan=["semantic_retrieval"],
        )

        doc_node = MagicMock()
        doc_node.id = "doc-1"
        doc_node.title = "\u793a\u4f8b\u6587\u6863"

        with patch("docs_core.retrieval.hybrid_retriever.fuse_candidates") as mock_fuse:
            mock_fuse.return_value = ([], {"sources": {}})
            with patch("docs_core.retrieval.dense_retriever.DenseRetriever.retrieve", return_value=[]):
                with patch("docs_core.retrieval.sparse_retriever.SparseRetriever.retrieve", return_value=[]):
                    with patch("docs_core.retrieval.table_retriever.TableRetriever.retrieve", return_value=[]):
                        with patch("docs_core.retrieval.formula_retriever.FormulaRetriever.retrieve", return_value=[]):
                            with patch("ai_inference.llm_client.get_llm_client"):
                                dispatcher._dispatch_semantic(
                                    query="\u6297\u9707\u6761\u6587\u5728\u54ea\u91cc",
                                    doc_nodes=[doc_node],
                                    library_id="default",
                                    doc_ids=["doc-1"],
                                    intent_result=intent,
                                )
            kwargs = mock_fuse.call_args.kwargs
            self.assertIn("filters", kwargs, "fuse_candidates 应收到 filters 参数，但当前未传")
