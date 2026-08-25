import os
import sys
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../../scripts")))

from open_ragbench import select_subset  # noqa: E402


class SelectSubsetTests(unittest.TestCase):
    def _fixtures(self):
        queries = {
            "q1": {"query": "t1", "type": "abstractive", "source": "text"},
            "q2": {"query": "t2", "type": "extractive", "source": "text"},
            "q3": {"query": "i1", "type": "abstractive", "source": "text-image"},
            "q4": {"query": "tb1", "type": "extractive", "source": "text-table"},
            "q5": {"query": "tbi1", "type": "abstractive", "source": "text-table-image"},
        }
        qrels = {
            "q1": {"doc_id": "p1", "section_id": 0},
            "q2": {"doc_id": "p2", "section_id": 0},
            "q3": {"doc_id": "p3", "section_id": 0},
            "q4": {"doc_id": "p4", "section_id": 0},
            "q5": {"doc_id": "p5", "section_id": 0},
        }
        answers = {"q1": "a1", "q2": "a2", "q3": "a3", "q4": "a4", "q5": "a5"}
        pdf_urls = {
            "p1": "u1", "p2": "u2", "p3": "u3", "p4": "u4", "p5": "u5",
            "hn1": "h1", "hn2": "h2",
        }
        return queries, qrels, answers, pdf_urls

    def test_manifest_covers_all_sources_and_hard_negatives(self):
        queries, qrels, answers, pdf_urls = self._fixtures()
        manifest = select_subset.build_manifest(
            queries, qrels, answers, pdf_urls,
            seed=1, min_per_source=1, max_questions=10, hard_negative_count=1,
        )
        sources = {q["source"] for q in manifest["questions"]}
        self.assertEqual(sources, {"text", "text-image", "text-table", "text-table-image"})
        hn = [p for p in manifest["papers"] if p["is_hard_negative"]]
        self.assertEqual(len(hn), 1)
        self.assertIn(hn[0]["paper_id"], {"hn1", "hn2"})

    def test_every_question_has_answer_and_url(self):
        queries, qrels, answers, pdf_urls = self._fixtures()
        manifest = select_subset.build_manifest(
            queries, qrels, answers, pdf_urls,
            seed=2, min_per_source=1, max_questions=10, hard_negative_count=0,
        )
        for q in manifest["questions"]:
            self.assertTrue(q["answer"])
            self.assertEqual(q["doc_id"], qrels[q["uuid"]]["doc_id"])

    def test_deterministic_with_same_seed(self):
        queries, qrels, answers, pdf_urls = self._fixtures()
        a = select_subset.build_manifest(queries, qrels, answers, pdf_urls, seed=7, min_per_source=1)
        b = select_subset.build_manifest(queries, qrels, answers, pdf_urls, seed=7, min_per_source=1)
        self.assertEqual([q["uuid"] for q in a["questions"]], [q["uuid"] for q in b["questions"]])


if __name__ == "__main__":
    unittest.main()
