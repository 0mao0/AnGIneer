import os
import sys
import tempfile
import unittest



from docs_core.step07_graph.config import Confidence, load_seed_entities
from docs_core.step07_graph.graph_store import GraphStore
from docs_core.step07_graph.graph_orchestrator import GraphOrchestrator
from docs_core.step07_graph.evidence_builder import build_evidence_packets, EvidencePacket


class TestGraphOrchestrator(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.db_path = os.path.join(self.tmpdir, "test_graph.sqlite")
        self.store = GraphStore(self.db_path)
        self.orchestrator = GraphOrchestrator(self.store)

    def tearDown(self):
        self.store.close()
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_load_seed_entities(self):
        self.orchestrator.load_seed_entities()
        stats = self.store.get_stats()
        self.assertGreater(stats["entity_count"], 0)

    def test_expand_from_packet_with_matching_entities(self):
        self.orchestrator.load_seed_entities()
        text = "航道通航宽度（W）应根据设计船型、设计船速、风流条件确定。边坡稳定验算时应考虑设计低水位最不利工况。"
        packet = EvidencePacket(
            packet_id="p1",
            library_id="lib",
            doc_id="doc",
            section_path="4.2 航道通航宽度",
            raw_text=text,
        )
        result = self.orchestrator.expand_from_packet(packet)
        self.assertIn("packet_id", result)

    def test_expand_from_packet_with_no_matches(self):
        self.orchestrator.load_seed_entities()
        text = "这是完全不相关的文本，不包含任何种子实体。"
        packet = EvidencePacket(
            packet_id="p2",
            library_id="lib",
            doc_id="doc",
            section_path="无关章节",
            raw_text=text,
        )
        result = self.orchestrator.expand_from_packet(packet)
        self.assertEqual(result.get("entities_found", 0), 0)

    def test_stats_reflect_graph_state(self):
        self.orchestrator.load_seed_entities()
        stats = self.store.get_stats()
        self.assertIn("entity_count", stats)
        self.assertIn("relation_count", stats)

    def test_get_graph_snapshot(self):
        self.orchestrator.load_seed_entities()
        snapshot = self.orchestrator.get_graph_snapshot()
        self.assertIn("entities", snapshot)
        self.assertIn("relations", snapshot)
        self.assertIn("stats", snapshot)


if __name__ == "__main__":
    unittest.main()
