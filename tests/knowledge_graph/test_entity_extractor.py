import os
import sys
import unittest



from docs_core.step07_graph.config import EntityLayer, load_seed_entities
from docs_core.step07_graph.entity_extractor import EntityExtractor
from docs_core.step07_graph.graph_store import GraphStore


class TestEntityExtractor(unittest.TestCase):
    def setUp(self):
        self.extractor = EntityExtractor()

    def test_find_seed_occurrences_in_text(self):
        seeds = load_seed_entities()[:5]
        text = "航道宽度应根据设计船型和通航要求确定。航道水深需考虑设计低水位的影响。"
        occurrences = self.extractor.find_seed_occurrences(text, seeds)
        self.assertGreater(len(occurrences), 0)
        found_names = {o[0] for o in occurrences}
        self.assertTrue(any("航道" in n for n in found_names))

    def test_find_entities_near_term(self):
        seeds = load_seed_entities()[:6]
        text = """4.2.1 航道通航宽度应按下式计算：
        设计船宽（B）为船舶满载时的最大宽度。
        航道边坡的稳定性应根据土质条件确定。
        富裕宽度（c）为船岸间距，按表4.2.1取值。"""
        related = self.extractor.find_related_entities(text, "航道", seeds)
        self.assertGreater(len(related), 0)

    def test_classify_entity_layer(self):
        concept = self.extractor.classify_entity("设计船型")
        condition = self.extractor.classify_entity("设计高水位工况")
        action = self.extractor.classify_entity("承载力计算")
        self.assertEqual(concept, EntityLayer.CONCEPT)
        self.assertEqual(condition, EntityLayer.CONDITION)
        self.assertEqual(action, EntityLayer.ACTION)
