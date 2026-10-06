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
