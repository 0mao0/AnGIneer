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
                # N/A 语义（2026-09-05）：section 级指标只在 metric_granularity=section 时聚合，
                # fixture 显式声明 section gold 才能命中 hit@N(sec) 断言
                "retrieval": {"metric_granularity": "section", "gold_target_types": ["content"],
                              "hit@1": 1, "hit@3": 1, "hit@5": hit5, "mrr": mrr, "citation_hit": 1},
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

    def test_summarize_doc_metrics_and_refusal(self):
        details = [
            {
                "question_id": "q1",
                "quality": "correct",
                "all_scores": {
                    "retrieval": {
                        "hit@5": 0.0, "mrr": 0.0,
                        "hit@1_doc": 1.0, "hit@3_doc": 1.0, "hit@5_doc": 1.0, "mrr_doc": 1.0,
                    },
                    "answer": {"correctness_checked": True, "correctness_score": 1.0},
                },
            },
            {
                "question_id": "refusal-1",
                "quality": "correct",
                "all_scores": {
                    "answer": {"evaluated": True, "refusal_expected": True, "refusal_correct": True},
                },
            },
            {
                "question_id": "refusal-2",
                "quality": "wrong",
                "all_scores": {
                    "answer": {"evaluated": True, "refusal_expected": True, "refusal_correct": False},
                },
            },
        ]
        manifest = {"questions": [{"uuid": "q1", "source": "text"}]}
        summary = report.group_and_summarize(details, manifest)
        overall = summary["overall"]
        self.assertEqual(overall["hit@5_doc"], 1.0)
        self.assertEqual(overall["mrr_doc"], 1.0)
        self.assertEqual(overall["refusal_total"], 2)
        self.assertEqual(overall["refusal_correct"], 1)
        self.assertEqual(overall["refusal_accuracy"], 0.5)
        self.assertEqual(overall["hallucination_on_unanswerable"], 1)
        markdown = report.render_markdown(summary)
        self.assertIn("hit@5(doc)", markdown)
        self.assertIn("拒答专项", markdown)

    def test_bootstrap_ci(self):
        details = [
            {"question_id": f"q{i}", "quality": "correct" if i < 8 else "wrong",
             "all_scores": {"retrieval": {"hit@5_doc": 1.0 if i < 8 else 0.0}}}
            for i in range(10)
        ]
        ci = report.bootstrap_ci(
            details,
            lambda d: d["all_scores"]["retrieval"]["hit@5_doc"],
            resamples=500,
            seed=1,
        )
        self.assertIsNotNone(ci)
        lower, upper = ci
        self.assertLessEqual(lower, 0.8)
        self.assertGreaterEqual(upper, 0.8)
        self.assertIsNone(report.bootstrap_ci(details[:1], lambda d: 1.0))

    def test_group_and_summarize_includes_ci(self):
        details = [
            {"question_id": f"q{i}", "quality": "correct" if i % 2 else "wrong",
             "all_scores": {"retrieval": {"hit@5_doc": float(i % 2)}}}
            for i in range(20)
        ]
        summary = report.group_and_summarize(details, {"questions": []}, ci_resamples=200)
        self.assertIn("hit@5_doc_ci", summary["overall"])
        self.assertIn("correct_rate_ci", summary["overall"])


if __name__ == "__main__":
    unittest.main()
