import os
import sys
import tempfile
import unittest


from docs_core.step07_graph.graph_store import GraphStore
from docs_core.step07_graph.graph_orchestrator import GraphOrchestrator
from docs_core.step07_graph.evidence_builder import build_evidence_packets
from docs_core.step07_graph.config import Confidence, RelationType


class TestKnowledgeGraphIntegration(unittest.TestCase):
    """End-to-end test: seed entities → evidence packets → graph expansion → SOP generation."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.db_path = os.path.join(self.tmpdir, "test_graph.sqlite")
        self.store = GraphStore(self.db_path)
        self.orchestrator = GraphOrchestrator(self.store)

    def tearDown(self):
        self.store.close()
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_full_pipeline_with_mock_document(self):
        # Step 1: Load seeds
        count = self.orchestrator.load_seed_entities()
        self.assertGreater(count, 0)

        # Step 2: Simulate document content (mimicking JTS 165 style)
        doc_content = """# JTS 165-2013 海港总体设计规范

## 4 航道
### 4.1 一般规定
4.1.1 航道选线应考虑港口总体规划、航行条件和建设条件。
4.1.2 航道轴线宜为直线。

### 4.2 航道通航宽度
4.2.1 航道通航宽度（W）应按下列公式计算：
W = A + b + c
式中：A为航迹带宽度（m），b为船岸间距（m），c为富裕宽度（m）。
航迹带宽度A应根据设计船型、设计船速、风流条件确定。

### 4.3 航道设计水深
4.3.1 航道设计水深（D）应按下式计算：
D = T + Z1 + Z2 + Z3 + Z4
式中：T为设计船型满载吃水（m）。
Z1为龙骨下最小富裕深度（m），应根据底质条件确定。
Z2为波浪富裕深度（m）。
Z3为船舶纵倾富裕深度（m）。
Z4为备淤深度（m），应根据回淤强度确定。
4.3.2 计算设计水深时，设计低水位为起算水位。

### 5 码头
### 5.1 码头前沿设计水深
5.1.1 码头前沿设计水深及底高程的计算方法应符合第4.3节的规定。
5.1.2 码头前沿顶高程应根据设计高水位和设计波高确定。"""

        packets = build_evidence_packets(
            library_id="lib",
            doc_id="doc",
            doc_title="JTS 165-2013",
            document_content=doc_content,
            structured_items=[],
        )

        self.assertGreater(len(packets), 0)

        # Step 3: Expand graph using heuristic methods (no LLM needed)
        result = self.orchestrator.expand_all_packets(packets)
        self.assertIsNotNone(result)

        # Step 4: Verify graph has content
        stats = self.store.get_stats()
        self.assertGreater(stats["entity_count"], 30)  # seeds + new

        # Step 5: Verify key entities exist
        entities_to_check = ["航道", "设计船型", "设计低水位", "设计高水位"]
        for name in entities_to_check:
            entity = self.store.get_entity_by_name(name)
            self.assertIsNotNone(entity, f"Entity '{name}' should exist in graph")

        # Step 6: Verify a relation exists
        channel = self.store.get_entity_by_name("航道")
        shiptype = self.store.get_entity_by_name("设计船型")
        if channel and shiptype:
            rels = self.store.get_relations_by_entity(channel.entity_id)
            self.assertGreater(len(rels), 0)

        # Step 7: Get snapshot
        snapshot = self.orchestrator.get_graph_snapshot()
        self.assertIn("entities", snapshot)
        self.assertIn("relations", snapshot)

    def test_seed_entity_has_high_confidence_after_human_review(self):
        self.orchestrator.load_seed_entities()
        a = self.store.get_entity_by_name("航道")
        b = self.store.get_entity_by_name("设计船型")
        self.assertIsNotNone(a)
        self.assertIsNotNone(b)
        rel = self.store.add_relation(a.entity_id, b.entity_id, RelationType.CONSTRAINS, Confidence.HUMAN_REVIEWED)
        self.assertEqual(rel.confidence, Confidence.HUMAN_REVIEWED)

    def test_conflict_marking(self):
        self.orchestrator.load_seed_entities()
        a = self.store.get_entity_by_name("航道")
        b = self.store.get_entity_by_name("设计船型")
        self.assertIsNotNone(a)
        self.assertIsNotNone(b)
        rel = self.store.add_relation(a.entity_id, b.entity_id, RelationType.CONSTRAINS, Confidence.AI_EXTRACTED)
        self.store.mark_relation_conflict(rel.relation_id, "题目与规范不一致")
        updated = self.store.get_relation(rel.relation_id)
        self.assertEqual(updated.confidence, Confidence.CONFLICT)


if __name__ == "__main__":
    unittest.main()
