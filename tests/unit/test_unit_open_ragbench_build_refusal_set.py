import os
import sys
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../../scripts")))

from open_ragbench import build_refusal_set  # noqa: E402


class BuildRefusalSetTests(unittest.TestCase):
    def _raw(self):
        queries = {
            "q-imported": {"query": "in corpus?", "type": "abstractive", "source": "text"},
            "q-out-1": {"query": "out 1?", "type": "abstractive", "source": "text"},
            "q-out-2": {"query": "out 2?", "type": "extractive", "source": "text-table"},
            "q-out-3": {"query": "out 3?", "type": "abstractive", "source": "text-image"},
            "q-no-pdf": {"query": "no pdf?", "type": "abstractive", "source": "text"},
        }
        qrels = {
            "q-imported": {"doc_id": "paper-in", "section_id": 1},
            "q-out-1": {"doc_id": "paper-out-1", "section_id": 2},
            "q-out-2": {"doc_id": "paper-out-2", "section_id": 3},
            "q-out-3": {"doc_id": "paper-out-1", "section_id": 4},
            "q-no-pdf": {"doc_id": "paper-no-pdf", "section_id": 5},
        }
        answers = {uid: f"answer for {uid}" for uid in queries}
        pdf_urls = {
            "paper-in": "http://x/in.pdf",
            "paper-out-1": "http://x/out1.pdf",
            "paper-out-2": "http://x/out2.pdf",
        }
        return queries, qrels, answers, pdf_urls

    def test_refusal_bundle_excludes_imported_and_missing_pdf(self):
        queries, qrels, answers, pdf_urls = self._raw()
        bundle = build_refusal_set.build_refusal_bundle(
            queries, qrels, answers, pdf_urls,
            imported_doc_ids={"paper-in"},
            library_id="lib-1",
            count=25,
            seed=42,
        )
        self.assertEqual(bundle["dataset"]["dataset_id"], "open-ragbench-refusal-v1")
        doc_ids = {item["tags"][2] for item in bundle["items"]}
        # 已入库与无 PDF 的论文都不应入选
        self.assertNotIn("paper-in", doc_ids)
        self.assertNotIn("paper-no-pdf", doc_ids)
        self.assertEqual(doc_ids, {"paper-out-1", "paper-out-2"})

    def test_refusal_items_marked_expected_and_skip_retrieval(self):
        queries, qrels, answers, pdf_urls = self._raw()
        bundle = build_refusal_set.build_refusal_bundle(
            queries, qrels, answers, pdf_urls,
            imported_doc_ids={"paper-in"},
            library_id="lib-1",
            count=25,
            seed=42,
        )
        for item in bundle["items"]:
            self.assertTrue(item["question_id"].startswith("refusal-"))
            self.assertTrue(item["answer"]["refusal_expected"])
            self.assertIsNone(item["retrieval"])
            self.assertEqual(item["library_id"], "lib-1")
            self.assertIn("refusal", item["tags"])

    def test_refusal_count_respects_quota(self):
        queries, qrels, answers, pdf_urls = self._raw()
        bundle = build_refusal_set.build_refusal_bundle(
            queries, qrels, answers, pdf_urls,
            imported_doc_ids={"paper-in"},
            library_id="lib-1",
            count=2,
            seed=42,
        )
        self.assertEqual(len(bundle["items"]), 2)


if __name__ == "__main__":
    unittest.main()
