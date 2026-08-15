import os
import sys
import unittest



from docs_core.step07_graph.question_mapper import QuestionMapper, StructuredQuestion


class TestQuestionMapper(unittest.TestCase):
    def setUp(self):
        self.mapper = QuestionMapper()

    def test_cluster_questions_by_signature(self):
        q1 = StructuredQuestion(
            question_id="q1",
            condition="设计低水位",
            question="航道水深应为多少？",
            answer="D = T + Z1 + Z2 + Z3 + Z4",
            clauses=["JTS 165 5.2.1"],
        )
        q2 = StructuredQuestion(
            question_id="q2",
            condition="设计低水位",
            question="码头前沿水深如何计算？",
            answer="D = T + Z1 + Z2 + Z3 + Z4",
            clauses=["JTS 165 5.2.1"],
        )
        q3 = StructuredQuestion(
            question_id="q3",
            condition="极端高水位",
            question="防波堤顶高程应为多少？",
            answer="按极端高水位+设计波高确定",
            clauses=["JTS 154 4.1"],
        )
        clusters = self.mapper.cluster_questions([q1, q2, q3])
        self.assertEqual(len(clusters), 2)

    def test_extract_simple_entities_from_question(self):
        q = StructuredQuestion(
            question_id="q1",
            condition="设计低水位，冬季工况",
            question="航道边坡稳定验算时，安全系数取多少？",
            answer="1.3",
            clauses=["JTS 165 6.3"],
        )
        entities = self.mapper.extract_entities_from_question(q)
        self.assertIn("航道", entities)
        self.assertIn("边坡", entities)
        self.assertIn("设计低水位", entities)

    def test_build_path_signature(self):
        sig = self.mapper._build_path_signature(["设计船型", "航道通航宽度", "航道宽度计算"])
        self.assertEqual(sig, "设计船型::航道通航宽度::航道宽度计算")

    def test_select_representative_questions(self):
        qs = [StructuredQuestion(question_id=f"q{i}", condition="c", question=f"q{i}", answer="a", clauses=[]) for i in range(50)]
        reps = self.mapper.select_representatives(qs, max_per_cluster=3)
        self.assertEqual(len(reps), 3)
