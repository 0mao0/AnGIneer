import os
import sys
import unittest



from docs_core.step07_graph.config import EntityLayer
from docs_core.step07_graph.relation_infer import RelationInferrer


class TestRelationInferrer(unittest.TestCase):
    def setUp(self):
        self.inferrer = RelationInferrer()

    def test_cooccurrence_relations(self):
        text = "设计船型决定了航道宽度"
        entities = ["设计船型", "航道", "设计高水位"]
        rels = self.inferrer.cooccurrence_relations(text, entities, within_distance=300)
        self.assertGreater(len(rels), 0)

    def test_cooccurrence_no_match(self):
        text = "一段很长的无关文本..." * 100
        entities = ["设计船型", "航道"]
        rels = self.inferrer.cooccurrence_relations(text, entities, within_distance=100)
        self.assertEqual(len(rels), 0)

    def test_infer_relations_empty_when_few_entities(self):
        rels = self.inferrer.infer_relations("text", ["单一实体"])
        self.assertEqual(len(rels), 0)

    def test_infer_relations_empty_when_no_entities(self):
        rels = self.inferrer.infer_relations("text", [])
        self.assertEqual(len(rels), 0)
