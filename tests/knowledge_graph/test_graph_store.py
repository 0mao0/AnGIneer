import os
import sys
import tempfile
import unittest


from docs_core.step07_graph.config import EntityLayer, RelationType, Confidence
from docs_core.step07_graph.graph_store import GraphStore, GraphEntity, GraphRelation


class TestGraphStore(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.db_path = os.path.join(self.tmpdir, "test_graph.sqlite")
        self.store = GraphStore(self.db_path)

    def tearDown(self):
        self.store.close()
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_init_creates_tables(self):
        with self.store._connect() as conn:
            tables = conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
            table_names = [t[0] for t in tables]
        self.assertIn("graph_entities", table_names)
        self.assertIn("graph_relations", table_names)

    def test_upsert_entity_creates(self):
        entity = GraphEntity(name="航道", layer=EntityLayer.CONCEPT, aliases=["通航航道"])
        result = self.store.upsert_entity(entity)
        self.assertIsNotNone(result.entity_id)
        self.assertEqual(result.name, "航道")

    def test_upsert_entity_updates_existing(self):
        e1 = self.store.upsert_entity(GraphEntity(name="航道", layer=EntityLayer.CONCEPT))
        e2 = self.store.upsert_entity(GraphEntity(name="航道", layer=EntityLayer.CONCEPT, aliases=["通航航道"]))
        self.assertEqual(e1.entity_id, e2.entity_id)
        self.assertIn("通航航道", e2.aliases)

    def test_get_entity_by_name(self):
        self.store.upsert_entity(GraphEntity(name="航道", layer=EntityLayer.CONCEPT))
        entity = self.store.get_entity_by_name("航道")
        self.assertIsNotNone(entity)
        self.assertEqual(entity.name, "航道")

    def test_get_entity_not_found(self):
        entity = self.store.get_entity_by_name("不存在")
        self.assertIsNone(entity)

    def test_add_relation(self):
        e1 = self.store.upsert_entity(GraphEntity(name="航道", layer=EntityLayer.CONCEPT))
        e2 = self.store.upsert_entity(GraphEntity(name="设计船型", layer=EntityLayer.CONCEPT))
        rel = self.store.add_relation(
            source_id=e1.entity_id,
            target_id=e2.entity_id,
            relation_type=RelationType.CONSTRAINS,
            confidence=Confidence.AI_EXTRACTED,
            evidence_text="设计船型决定了航道宽度",
            source_clause="JTS 165 4.2.1",
        )
        self.assertIsNotNone(rel.relation_id)
        self.assertEqual(rel.relation_type, RelationType.CONSTRAINS)
        self.assertEqual(rel.confidence, Confidence.AI_EXTRACTED)

    def test_add_duplicate_relation_updates_confidence(self):
        e1 = self.store.upsert_entity(GraphEntity(name="航道", layer=EntityLayer.CONCEPT))
        e2 = self.store.upsert_entity(GraphEntity(name="设计船型", layer=EntityLayer.CONCEPT))
        r1 = self.store.add_relation(e1.entity_id, e2.entity_id, RelationType.CONSTRAINS, Confidence.AI_EXTRACTED)
        r2 = self.store.add_relation(e1.entity_id, e2.entity_id, RelationType.CONSTRAINS, Confidence.QUESTION_VALIDATED, evidence_text="题目验证通过")
        self.assertEqual(r1.relation_id, r2.relation_id)
        self.assertGreaterEqual(r2.confidence, Confidence.QUESTION_VALIDATED)

    def test_get_relations_by_entity(self):
        e1 = self.store.upsert_entity(GraphEntity(name="航道", layer=EntityLayer.CONCEPT))
        e2 = self.store.upsert_entity(GraphEntity(name="设计船型", layer=EntityLayer.CONCEPT))
        e3 = self.store.upsert_entity(GraphEntity(name="设计流速", layer=EntityLayer.CONCEPT))
        self.store.add_relation(e1.entity_id, e2.entity_id, RelationType.CONSTRAINS, Confidence.AI_EXTRACTED)
        self.store.add_relation(e1.entity_id, e3.entity_id, RelationType.CONSTRAINS, Confidence.AI_EXTRACTED)
        rels = self.store.get_relations_by_entity(e1.entity_id)
        self.assertEqual(len(rels), 2)

    def test_get_relations_by_entity_bidirectional(self):
        e1 = self.store.upsert_entity(GraphEntity(name="航道", layer=EntityLayer.CONCEPT))
        e2 = self.store.upsert_entity(GraphEntity(name="设计船型", layer=EntityLayer.CONCEPT))
        self.store.add_relation(e1.entity_id, e2.entity_id, RelationType.CONSTRAINS, Confidence.AI_EXTRACTED)
        rels_out = self.store.get_relations_by_entity(e1.entity_id, direction="outgoing")
        rels_in = self.store.get_relations_by_entity(e2.entity_id, direction="incoming")
        self.assertEqual(len(rels_out), 1)
        self.assertEqual(len(rels_in), 1)

    def test_search_entities(self):
        self.store.upsert_entity(GraphEntity(name="航道通航宽度", layer=EntityLayer.CONCEPT))
        self.store.upsert_entity(GraphEntity(name="航道水深", layer=EntityLayer.CONCEPT))
        self.store.upsert_entity(GraphEntity(name="码头前沿", layer=EntityLayer.CONCEPT))
        results = self.store.search_entities("航道")
        self.assertEqual(len(results), 2)

    def test_list_entities_by_layer(self):
        self.store.upsert_entity(GraphEntity(name="航道", layer=EntityLayer.CONCEPT))
        self.store.upsert_entity(GraphEntity(name="冬季工况", layer=EntityLayer.CONDITION))
        self.store.upsert_entity(GraphEntity(name="承载力验算", layer=EntityLayer.ACTION))
        concepts = self.store.list_entities_by_layer(EntityLayer.CONCEPT)
        conditions = self.store.list_entities_by_layer(EntityLayer.CONDITION)
        self.assertEqual(len(concepts), 1)
        self.assertEqual(len(conditions), 1)

    def test_mark_relation_conflict(self):
        e1 = self.store.upsert_entity(GraphEntity(name="航道", layer=EntityLayer.CONCEPT))
        e2 = self.store.upsert_entity(GraphEntity(name="设计船型", layer=EntityLayer.CONCEPT))
        rel = self.store.add_relation(e1.entity_id, e2.entity_id, RelationType.CONSTRAINS, Confidence.AI_EXTRACTED)
        self.store.mark_relation_conflict(rel.relation_id, "题目答案与规范不一致")
        updated = self.store.get_relation(rel.relation_id)
        self.assertEqual(updated.confidence, Confidence.CONFLICT)
        self.assertIsNotNone(updated.conflict_note)


if __name__ == "__main__":
    unittest.main()
