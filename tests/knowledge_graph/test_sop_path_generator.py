import os
import sys
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../../services/sop-core/src")))

from docs_core.step07_graph.config import EntityLayer
from sop_core.sop_path_generator import SopPathGenerator


class TestSopPathGenerator(unittest.TestCase):
    def setUp(self):
        self.generator = SopPathGenerator()

    def test_path_to_sop_template(self):
        path = [
            {"name": "设计船型", "layer": EntityLayer.CONCEPT},
            {"relation": "constrains"},
            {"name": "航道通航宽度", "layer": EntityLayer.CONCEPT},
            {"relation": "computes_from"},
            {"name": "航道宽度计算", "layer": EntityLayer.ACTION},
        ]
        sop = self.generator.path_to_sop_template(path, "JTS 165 4.2")
        self.assertIn("id", sop)
        self.assertIn("steps", sop)
        self.assertGreater(len(sop["steps"]), 0)

    def test_merge_adjacent_concept_nodes(self):
        path = [
            {"name": "A", "layer": EntityLayer.CONCEPT},
            {"relation": "constrains"},
            {"name": "B", "layer": EntityLayer.CONCEPT},
            {"relation": "requires"},
            {"name": "C", "layer": EntityLayer.ACTION},
        ]
        merged = self.generator._merge_concept_nodes(path)
        self.assertLessEqual(len(merged), len(path))

    def test_generate_sop_skeleton(self):
        entities = {
            "设计船型": EntityLayer.CONCEPT,
            "航道通航宽度": EntityLayer.CONCEPT,
            "设计低水位": EntityLayer.CONDITION,
            "航道宽度计算": EntityLayer.ACTION,
        }
        path_entities = ["设计船型", "航道通航宽度", "航道宽度计算"]
        skeleton = self.generator.generate_sop_skeleton(
            sop_id="test_calc",
            title="航道通航宽度计算",
            path_entities=path_entities,
            entities=entities,
            source_clause="JTS 165 4.2",
        )
        self.assertEqual(skeleton["id"], "test_calc")
        self.assertIn("steps", skeleton)
        self.assertIn("blackboard", skeleton)
