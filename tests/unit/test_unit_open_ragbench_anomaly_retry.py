"""客户端脚本层单测：anomaly 镜像与服务器侧规则一致性、retry 回路、poll 超时行为、报告门禁。"""
import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../../scripts")))
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "../.."))
for sub in ("evals-core", "angineer-core", "ai-inference", "sop-core"):
    p = os.path.join(ROOT, "services", sub, "src")
    if p not in sys.path:
        sys.path.insert(0, p)

from open_ragbench import anomaly as client_anomaly  # noqa: E402
from open_ragbench import report, retry_anomalies, run_eval  # noqa: E402
from evals_core.runner import anomaly as server_anomaly  # noqa: E402


class MirrorParityTests(unittest.TestCase):
    """两侧异常分类规则是同一契约的两份实现，必须逐字节同判（漂移防线）。"""

    SAMPLES = [
        {"question_id": "a", "status": "error", "error": "boom", "latency_ms": 5000},
        {"question_id": "b", "status": "completed", "scores": {"semantic_fallback": True}},
        {"question_id": "c", "status": "completed",
         "all_scores": {"answer": {"semantic_fallback": False, "has_answer": True}}},
        {"question_id": "d", "status": "completed", "scores": '{"semantic_fallback": true}'},
        {"question_id": "e", "status": "completed", "latency_ms": 121_000, "scores": {}},
        {"question_id": "f", "status": "completed", "scores": {
            "semantic_evaluated": False, "semantic_fallback": False,
            "semantic_reason": "有标准答案/要点时整体拒答按失败计"}},
    ]

    def test_parity(self):
        for d in self.SAMPLES:
            self.assertEqual(
                client_anomaly.classify_detail(d, slow_ms=-1),
                server_anomaly.classify_detail(d, slow_ms=-1),
                f"规则漂移: {d}",
            )

    def test_actionable_excludes_slow(self):
        anomalies = {client_anomaly.SLOW: ["e"], client_anomaly.JUDGE_FAIL: ["b"]}
        self.assertEqual(client_anomaly.actionable(anomalies), {client_anomaly.JUDGE_FAIL: ["b"]})


class RetryLoopTests(unittest.TestCase):
    def _run_payload(self, fallback=True):
        det = {"question_id": "q1", "status": "completed", "quality": "wrong",
               "scores": {"semantic_fallback": fallback}}
        return {"run_id": "r1", "status": "completed", "details": [det]}

    def test_retry_rescores_then_clean(self):
        seq = [self._run_payload(True), self._run_payload(False), self._run_payload(False)]
        with mock.patch.object(retry_anomalies, "get_full_run", side_effect=seq), \
             mock.patch.object(retry_anomalies, "poll", return_value=self._run_payload(False)), \
             mock.patch.object(retry_anomalies.requests, "post") as post:
            post.return_value.json.return_value = {"run_id": "r1"}
            run, remaining = retry_anomalies.retry_anomalies(
                mock.Mock(), "ds", "r1", max_rounds=2, log=lambda *a: None)
        payload = post.call_args.kwargs["json"]
        self.assertEqual(payload["resume_run_id"], "r1")
        self.assertEqual(payload["rescore_question_ids"], ["q1"])
        self.assertEqual(remaining, {})

    def test_clean_run_noop(self):
        with mock.patch.object(retry_anomalies, "get_full_run", return_value=self._run_payload(False)):
            run, remaining = retry_anomalies.retry_anomalies(mock.Mock(), "ds", "r1", log=lambda *a: None)
        self.assertEqual(remaining, {})


class PollTimeoutTests(unittest.TestCase):
    def test_timeout_raises_not_running_snapshot(self):
        resp = mock.Mock()
        resp.json.return_value = {"run_id": "r", "status": "running",
                                  "completed_questions": 3, "total_questions": 487}
        with mock.patch.object(run_eval.requests, "get", return_value=resp):
            with self.assertRaises(TimeoutError):
                run_eval.poll_run(mock.Mock(), "r", timeout=0, interval=0)


class ReportGateTests(unittest.TestCase):
    def _detail(self, qid, sem=1.0, fallback=False, quality="correct"):
        return {"question_id": qid, "quality": quality, "latency_ms": 30_000,
                "all_scores": {"retrieval": {"hit@5_doc": 1}, "answer": {
                    "correctness_checked": True, "correctness_score": sem,
                    "semantic_score": sem, "semantic_fallback": fallback}},
                "scores": {"semantic_fallback": fallback}}

    def test_anomaly_marks_preliminary(self):
        details = [self._detail("q1"), self._detail("q2", fallback=True, quality="wrong")]
        summary = report.group_and_summarize(details, {"questions": []})
        self.assertTrue(summary["anomaly_pending"])
        md = report.render_markdown(summary)
        self.assertIn("| overall *", md)
        self.assertIn("初步值", md)

    def test_clean_run_no_gate(self):
        details = [self._detail("q1"), self._detail("q2")]
        summary = report.group_and_summarize(details, {"questions": []})
        self.assertFalse(summary["anomaly_pending"])
        md = report.render_markdown(summary)
        self.assertNotIn("初步值", md)
        self.assertIn("分布口径", md)  # median/p90 区恒在


if __name__ == "__main__":
    unittest.main()
