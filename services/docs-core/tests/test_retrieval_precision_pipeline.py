"""检索精度链路测试。"""
import sys
import unittest
from pathlib import Path


DOCS_CORE_SRC = Path(__file__).resolve().parents[1] / "src"
if str(DOCS_CORE_SRC) not in sys.path:
    sys.path.insert(0, str(DOCS_CORE_SRC))

from docs_core.query_protocols.contracts import KnowledgeQueryFilter, RetrievedItem


class RetrievalPrecisionPipelineTests(unittest.TestCase):
    """验证检索链路的正确性。"""

    def test_fuse_candidates_filters_by_tags_from_metadata(self):
        """融合时应按 tags 做 ANY-OF 过滤。"""
        from docs_core.retrieval.hybrid_retriever import fuse_candidates

        matched = RetrievedItem(
            item_id="matched-id",
            entity_type="content",
            doc_id="doc-1",
            title="抗震要求",
            text="抗震设计时应符合下列规定",
            score=1.0,
            metadata={
                "entity_tags": ["抗震"],
                "conditions": [],
                "exam_tags": [],
                "source_kind": "canonical_sparse",
                "chunk_type": "content",
                "section_path": "第六章",
            },
        )
        distractor = RetrievedItem(
            item_id="distractor-id",
            entity_type="content",
            doc_id="doc-1",
            title="换算要求",
            text="换算系数为1.5",
            score=1.0,
            metadata={
                "entity_tags": ["换算"],
                "conditions": [],
                "exam_tags": [],
                "source_kind": "canonical_sparse",
                "chunk_type": "content",
                "section_path": "第三章",
            },
        )
        filtered, debug = fuse_candidates(
            {"canonical_sparse": [matched, distractor]},
            task_type="locate_qa",
            top_k=5,
            filters=KnowledgeQueryFilter(tags=["抗震"]),
        )
        self.assertEqual([item.item_id for item in filtered], ["matched-id"])
        self.assertEqual(debug["filtered_hits"], 1)

    def test_fuse_candidates_tags_any_of_semantics(self):
        """请求 tags 与候选 entity_tags/conditions/exam_tags 任一交集命中即可保留。"""
        from docs_core.retrieval.hybrid_retriever import fuse_candidates

        item = RetrievedItem(
            item_id="multi-tag-id",
            entity_type="content",
            doc_id="doc-1",
            title="强制性条文",
            text="必须符合下列要求",
            score=1.0,
            metadata={
                "entity_tags": ["抗震"],
                "conditions": ["强制性条文"],
                "exam_tags": ["注册结构"],
                "source_kind": "canonical_sparse",
                "chunk_type": "content",
                "section_path": "第六章",
            },
        )
        filtered, _ = fuse_candidates(
            {"canonical_sparse": [item]},
            task_type="locate_qa",
            top_k=5,
            filters=KnowledgeQueryFilter(tags=["强制性条文"]),
        )
        self.assertEqual(len(filtered), 1)
