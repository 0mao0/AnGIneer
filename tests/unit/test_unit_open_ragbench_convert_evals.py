import os
import sys
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../../scripts")))

from open_ragbench import convert_evals  # noqa: E402


class ConvertEvalsTests(unittest.TestCase):
    def test_bundle_maps_question_and_gold(self):
        manifest = {
            "questions": [{
                "uuid": "q1",
                "query": "what is X?",
                "type": "abstractive",
                "source": "text-image",
                "doc_id": "p1",
                "answer": "X is Y",
            }],
        }
        bundle = convert_evals.build_eval_bundle(manifest, "lib-1")
        self.assertEqual(bundle["dataset"]["dataset_id"], "open-ragbench-subset-v1")
        self.assertEqual(bundle["dataset"]["library_id"], "lib-1")
        item = bundle["items"][0]
        self.assertEqual(item["question_id"], "q1")
        self.assertEqual(item["doc_ids"], [])
        self.assertEqual(item["retrieval"]["gold_doc_ids"], ["p1"])
        self.assertEqual(item["answer"]["gold_answer"], "X is Y")
        self.assertEqual(item["tags"][0], "text-image")

    def test_bundle_maps_arxiv_doc_id_to_internal(self):
        """gold_doc_ids 应映射为内部 doc_id，arxiv id 保留在 tags/notes 中。"""
        manifest = {
            "questions": [{
                "uuid": "q1",
                "query": "what is X?",
                "type": "abstractive",
                "source": "text",
                "doc_id": "2409.16644v2",
                "answer": "X is Y",
            }],
        }
        bundle = convert_evals.build_eval_bundle(
            manifest, "lib-1", doc_id_map={"2409.16644v2": "v1-b95b01b6ef00"}
        )
        item = bundle["items"][0]
        self.assertEqual(item["retrieval"]["gold_doc_ids"], ["v1-b95b01b6ef00"])
        self.assertEqual(item["retrieval"]["notes"], "arxiv:2409.16644v2")
        self.assertIn("2409.16644v2", item["tags"])


if __name__ == "__main__":
    unittest.main()
