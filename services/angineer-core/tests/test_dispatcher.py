"""Dispatcher 检索链路单元测试。"""
import sys
import unittest
from pathlib import Path
from unittest.mock import patch, MagicMock


ANGINEER_CORE_SRC = Path(__file__).resolve().parents[1] / "src"
if str(ANGINEER_CORE_SRC) not in sys.path:
    sys.path.insert(0, str(ANGINEER_CORE_SRC))

from angineer_core.base_contracts import IntentResult
import requests


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

    def test_rerank_is_invoked_for_locate_tasks_even_when_candidate_count_is_small(self):
        """locate 任务候选数 ≤5 时 rerank 仍应执行。"""
        from angineer_core.dispatcher import Dispatcher
        from docs_core.query_protocols.contracts import RetrievedItem

        items = [
            RetrievedItem(item_id=f"id-{i}", entity_type="content", doc_id="d1",
                          title=f"t{i}", text=f"text{i}", score=1.0,
                          metadata={"source_kind": "canonical_sparse", "chunk_type": "content"})
            for i in range(3)
        ]
        dispatcher = Dispatcher()
        intent = IntentResult(
            intent_level="L1", primary_level="L1",
            intent_type="locate",
            service_mode="semantic_retrieval", execution_plan=["semantic_retrieval"],
        )
        doc_node = MagicMock()
        doc_node.id = "d1"
        doc_node.title = "doc1"

        with patch.object(Dispatcher, "_rerank_candidates", return_value=items) as mock_rerank:
            with patch("docs_core.retrieval.dense_retriever.DenseRetriever.retrieve", return_value=[]):
                with patch("docs_core.retrieval.sparse_retriever.SparseRetriever.retrieve", return_value=[]):
                    with patch("docs_core.retrieval.table_retriever.TableRetriever.retrieve", return_value=[]):
                        with patch("docs_core.retrieval.formula_retriever.FormulaRetriever.retrieve", return_value=[]):
                            with patch("docs_core.retrieval.hybrid_retriever.fuse_candidates", return_value=(items, {"sources": {}, "deduped_hits": 3, "filtered_hits": 3, "returned_hits": 3})):
                                with patch("ai_inference.llm_client.get_llm_client"):
                                    dispatcher._dispatch_semantic(
                                        query="4.2.3 条在哪",
                                        doc_nodes=[doc_node],
                                        library_id="default",
                                        doc_ids=["d1"],
                                        intent_result=intent,
                                    )
        self.assertTrue(mock_rerank.called,
                        "locate 类任务候选数小也应当调用 _rerank_candidates")

    def test_rerank_falls_back_to_local_reranker_when_remote_fails(self):
        """远端 reranker 失败时回退到本地 phrase rerank。"""
        from angineer_core.dispatcher import Dispatcher
        from docs_core.query_protocols.contracts import RetrievedItem

        candidates = [
            RetrievedItem(item_id=f"id-{i}", entity_type="content", doc_id="d1",
                          title=f"t{i}", text=f"text{i}", score=5.0 - i,
                          metadata={"source_kind": "canonical_sparse", "chunk_type": "content"})
            for i in range(6)
        ]
        with patch("requests.post", side_effect=requests.RequestException("boom")):
            with patch("docs_core.retrieval.reranker.rerank_candidates",
                       return_value=candidates) as mock_local:
                reranked = Dispatcher._rerank_candidates(
                    "4.2.3 条在哪", candidates, task_type="locate_qa",
                )
                self.assertTrue(mock_local.called,
                                "远端失败时应调用本地 phrase reranker")
                self.assertEqual(len(reranked), len(candidates))
