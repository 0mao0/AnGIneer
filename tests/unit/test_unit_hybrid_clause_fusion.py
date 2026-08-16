"""融合检索：条款号直达候选在 table_qa 下不能被表格候选淹没。"""
import os
import sys
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT / "services" / "docs-core" / "src"))

from docs_core.step09_query.protocols.contracts import RetrievedItem  # noqa: E402
from docs_core.step09_query.retrieval.hybrid_retriever import fuse_candidates  # noqa: E402
from docs_core.step09_query.retrieval.sparse_retriever import pick_chunk_keyword  # noqa: E402


def _table_item(i: int, score: float) -> RetrievedItem:
    return RetrievedItem(
        item_id=f"table-{i}",
        entity_type="table",
        doc_id="doc-t",
        title="表",
        text=f"表格内容 {i}",
        score=score,
        retrieval_policy="canonical_dense",
        metadata={"source_kind": "canonical_dense", "chunk_type": "table_row_key"},
    )


def _clause_item() -> RetrievedItem:
    return RetrievedItem(
        item_id="clause-6.2.8.1",
        entity_type="paragraph",
        doc_id="doc-c",
        title="6.2.8.1",
        text="6.2.8.1 每潮次船舶乘潮进出港所需的持续时间可按式(6.2.8)确定",
        score=14.0,
        retrieval_policy="clause_direct",
        metadata={"source_kind": "clause_direct", "chunk_type": "paragraph", "clause_id": "6.2.8.1"},
    )


class HybridClauseFusionTests(unittest.TestCase):
    def test_clause_direct_survives_table_qa(self):
        dense = [_table_item(i, 0.9 - i * 0.01) for i in range(10)]
        fused, _debug = fuse_candidates(
            {"dense": dense, "clause": [_clause_item()]},
            "table_qa",
            top_k=20,
        )
        fused_ids = [item.item_id for item in fused]
        self.assertIn("clause-6.2.8.1", fused_ids[:5])

    def test_table_rows_with_same_key_do_not_accumulate(self):
        items = []
        for i in range(5):
            items.append(
                RetrievedItem(
                    item_id=f"row-{i}",
                    entity_type="table",
                    doc_id="doc-t",
                    title="表",
                    text=f"行 {i}",
                    score=0.9 - i * 0.1,
                    retrieval_policy="canonical_dense",
                    metadata={
                        "source_kind": "canonical_dense",
                        "chunk_type": "table_row_key",
                        "table_id": "table-doc-t:0:1",
                    },
                )
            )
        fused, _debug = fuse_candidates({"dense": items}, "table_qa", top_k=10)
        self.assertEqual(len(fused), 1)
        self.assertLess(fused[0].rerank_score, 1.0)

    def test_hash_fallback_dense_does_not_dominate_sparse(self):
        dense = []
        for i in range(3):
            dense.append(
                RetrievedItem(
                    item_id=f"hash-{i}",
                    entity_type="content",
                    doc_id="doc-h",
                    title="船闸规范",
                    text=f"结构计算内容 {i}",
                    score=0.9 - i * 0.1,
                    retrieval_policy="canonical_dense",
                    metadata={
                        "source_kind": "canonical_dense",
                        "chunk_type": "content",
                        "embedding_fallback": True,
                    },
                )
            )
        sparse = RetrievedItem(
            item_id="clause-block",
            entity_type="paragraph",
            doc_id="doc-s",
            title="6.2.8.1",
            text="每潮次船舶乘潮进出港所需的持续时间可按式(6.2.8)确定",
            score=6.0,
            retrieval_policy="canonical_sparse",
            metadata={"source_kind": "canonical_sparse", "chunk_type": "paragraph"},
        )
        fused, _debug = fuse_candidates({"dense": dense, "sparse": [sparse]}, "content_qa", top_k=10)
        self.assertEqual(fused[0].item_id, "clause-block")

    def test_pick_chunk_keyword_prefers_short_ngram(self):
        self.assertEqual(pick_chunk_keyword("乘潮进港时间怎么计算"), "乘潮")
        self.assertEqual(pick_chunk_keyword("6.2.8.1是什么", ["6.2.8.1"]), "6.2.8.1")
        self.assertEqual(pick_chunk_keyword("LNG ship berth"), "lng")


if __name__ == "__main__":
    unittest.main()
