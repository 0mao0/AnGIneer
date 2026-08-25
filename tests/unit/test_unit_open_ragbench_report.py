import os
import sys
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../../scripts")))

from open_ragbench import report  # noqa: E402


class ReportTests(unittest.TestCase):
    def _detail(self, qid, source, hit5=1, mrr=1.0, correctness=0.8, quality="correct"):
        return {
            "question_id": qid,
            "quality": quality,
            "all_scores": {
                "retrieval": {"hit@1": 1, "hit@3": 1, "hit@5": hit5, "mrr": mrr, "citation_hit": 1},
                "answer": {"correctness_checked": True, "correctness_score": correctness},
            },
        }

    def test_group_and_summarize(self):
        details = [
            self._detail("q1", "text"),
            self._detail("q2", "text-image", hit5=0, mrr=0.0, correctness=0.2, quality="wrong"),
            self._detail("q3", "text-table"),
        ]
        manifest = {"questions": [
            {"uuid": "q1", "source": "text"},
            {"uuid": "q2", "source": "text-image"},
            {"uuid": "q3", "source": "text-table"},
        ]}
        summary = report.group_and_summarize(details, manifest)
        self.assertEqual(summary["text"]["count"], 1)
        self.assertEqual(summary["text"]["hit@5"], 1.0)
        self.assertEqual(summary["text-image"]["hit@5"], 0.0)
        self.assertEqual(summary["text-image"]["wrong"], 1)
        self.assertEqual(summary["overall"]["count"], 3)


if __name__ == "__main__":
    unittest.main()
