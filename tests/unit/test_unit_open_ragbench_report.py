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

    def test_slow_watchlist_shows_question_titles_not_uuids(self):
        details = [
            {**self._detail("aaaa1111-0000", "text"), "latency_ms": 130_000},
            {**self._detail("bbbb2222-0000", "text"), "latency_ms": 125_000},
            self._detail("cccc3333-0000", "text"),  # 正常耗时，不进观察单
        ]
        manifest = {"questions": [
            {"uuid": "aaaa1111-0000", "query": "How does TADA handle real-time data assimilation?"},
            {"uuid": "bbbb2222-0000", "query": "What is the role of sliding window in assimilation?"},
            {"uuid": "cccc3333-0000", "query": "fast one"},
        ]}
        summary = report.group_and_summarize(details, manifest)
        markdown = report.render_markdown(summary)
        self.assertIn("How does TADA handle real-time data assimilation?", markdown)
        self.assertIn("What is the role of sliding window", markdown)
        self.assertIn("慢题观察单", markdown)
        slow_section = markdown.split("慢题观察单")[1].split("##")[0]
        self.assertNotIn("aaaa1111", slow_section)  # 题面替代 id，读者看得懂

    def test_slow_watchlist_falls_back_to_qid_prefix(self):
        details = [{**self._detail("zz9876543210", "text"), "latency_ms": 200_000}]
        summary = report.group_and_summarize(details, {"questions": []})
        markdown = report.render_markdown(summary)
        self.assertIn("zz9876543210"[:8], markdown)  # manifest 缺题面时退回 qid 前 8 位

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


class RetrievalGranularityNoteTests(unittest.TestCase):
    """检索口径分母可见化（2026-09-13）。

    hit@*(sec) 列的分母只是"有 section 级金标"的题；另有少量题仅有文档级金标（按 doc 粒度
    计分，粒度更粗、更宽松）、以及无检索金标的题（拒答题）。不写清分母，读者会把 sec 列的
    均值误当成全量均值。
    """

    def _section_detail(self, qid):
        return {
            "question_id": qid, "quality": "correct",
            "all_scores": {
                "retrieval": {"metric_granularity": "section", "hit@1": 1, "hit@3": 1, "hit@5": 1,
                              "mrr": 1.0, "hit@5_doc": 1.0},
                "answer": {"correctness_checked": True, "correctness_score": 1.0},
            },
        }

    def _doc_detail(self, qid):
        return {
            "question_id": qid, "quality": "correct",
            "all_scores": {
                "retrieval": {"metric_granularity": "doc", "hit@1_doc": 1.0, "hit@3_doc": 1.0,
                              "hit@5_doc": 1.0, "mrr_doc": 1.0},
                "answer": {"correctness_checked": True, "correctness_score": 1.0},
            },
        }

    def _refusal_detail(self, qid):
        return {"question_id": qid, "quality": "correct",
                "all_scores": {"answer": {"evaluated": True, "refusal_expected": True, "refusal_correct": True}}}

    def test_counts_split_by_granularity(self):
        details = [self._section_detail("q1"), self._doc_detail("q2"), self._refusal_detail("refusal-1")]
        summary = report.group_and_summarize(details, {"questions": []})
        self.assertEqual(summary["overall"]["retrieval_granularity"],
                         {"section": 1, "doc": 1, "none": 1})

    def test_note_shown_when_granularity_is_mixed(self):
        details = [self._section_detail("q1"), self._doc_detail("q2"), self._refusal_detail("refusal-1")]
        markdown = report.render_markdown(report.group_and_summarize(details, {"questions": []}))
        self.assertIn("检索口径", markdown)
        self.assertIn("分母 1 题（有 section 级金标）", markdown)
        self.assertIn("1 题仅有文档级金标", markdown)
        self.assertIn("无检索金标", markdown)

    def test_no_note_when_everything_is_section_level(self):
        details = [self._section_detail("q1"), self._section_detail("q2")]
        markdown = report.render_markdown(report.group_and_summarize(details, {"questions": []}))
        self.assertNotIn("检索口径", markdown, "口径统一时不应产生噪声说明")


if __name__ == "__main__":
    unittest.main()
