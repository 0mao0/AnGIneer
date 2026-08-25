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


if __name__ == "__main__":
    unittest.main()
