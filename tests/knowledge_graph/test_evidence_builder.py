import os
import sys
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../../services/knowledge-graph/src")))

from knowledge_graph.evidence_builder import build_evidence_packets


class TestEvidenceBuilder(unittest.TestCase):
    def _build(self, document_content, **kwargs):
        defaults = dict(
            library_id="lib",
            doc_id="doc",
            doc_title="Doc",
            document_content=document_content,
            structured_items=[],
            doc_blocks_graph=None,
        )
        defaults.update(kwargs)
        return build_evidence_packets(**defaults)

    def test_empty_document_yields_single_fallback_packet(self):
        packets = self._build("")
        self.assertEqual(len(packets), 1)
        self.assertEqual(packets[0].section_path, "")

    def test_sections_are_parsed(self):
        content = "# 概述\n这是概述内容。\n\n## 计算方法\n这是计算内容。"
        packets = self._build(content)
        sections = [p.section_path for p in packets]
        combined = " ".join(sections)
        self.assertIn("概述", combined)
        self.assertIn("计算方法", combined)

    def test_small_sections_are_merged(self):
        small = "这是一段小节正文内容。" * 40
        content = "\n\n".join([f"# {chr(65 + i)}\n{small}" for i in range(10)])
        packets = self._build(content, max_chars_per_packet=20000)
        self.assertLess(len(packets), 10)

    def test_oversized_section_is_split(self):
        para = "段落内容填充。" * 50
        body = "\n\n".join([para] * 60)
        content = f"# 大节\n{body}"
        packets = self._build(content, max_chars_per_packet=4000)
        self.assertGreater(len(packets), 1)
        for p in packets:
            self.assertLessEqual(len(p.raw_text), 4000)

    def test_structured_items_assigned_to_sections(self):
        content = "# 总则\n总则内容。\n\n# 计算\n计算内容。"
        items = [
            {"id": "b1", "type": "text", "section_path": "总则", "content": "总则内容。"},
            {"id": "b2", "type": "formula", "section_path": "计算", "content": "D = T + Z1", "formula": "D = T + Z1"},
        ]
        packets = self._build(content, structured_items=items)
        for p in packets:
            for bid in p.block_ids:
                self.assertIsNotNone(bid)

    def test_entities_and_conditions_extracted(self):
        items = [
            {"id": "b1", "type": "text", "entities": ["航道", "设计船型"], "conditions": ["设计低水位"], "content": "text"},
        ]
        packets = self._build("# T\ncontent", structured_items=items)
        all_entities = []
        all_conditions = []
        for p in packets:
            all_entities.extend(p.entities)
            all_conditions.extend(p.conditions)
        self.assertIn("航道", all_entities)
        self.assertIn("设计低水位", all_conditions)
