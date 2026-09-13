"""全内置流水线单测：正常收口、异常补判续跑、失败必落 error 结论（"当天必有结论"不变式）。"""
import asyncio
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "../.."))
P = os.path.join(ROOT, "services", "evals-core", "src")
if P not in sys.path:
    sys.path.insert(0, P)

from evals_core.nightly import pipeline  # noqa: E402


def _detail(qid, quality, sem=0.9, hit5=1):
    return {
        "question_id": qid, "status": "completed", "quality": quality, "latency_ms": 10_000,
        "prediction": {"answer": f"A-{qid}", "intent": "L1"},
        "scores": {},
        "all_scores": {
            "retrieval": {"hit@5_doc": hit5, "citation_hit": 1},
            "answer": {"semantic_score": sem, "semantic_reason": "覆盖完整", "has_answer": True,
                       "semantic_threshold": 0.65},
        },
    }


_BASE_DETAILS = [_detail("q1", "correct"), _detail("q2", "wrong", sem=0.1), _detail("q3", "correct")]
_NEW_DETAILS = [_detail("q1", "correct"), _detail("q2", "correct", sem=0.8), _detail("q3", "correct")]
_SUMMARY = {"overall_score": 2 / 3, "correct": 2, "total": 3, "errored": 0, "judge_failed_count": 0}


class _Env(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.env = mock.patch.dict(os.environ, {
            "NIGHTLY_ROOT": str(self.tmp / "nightly"),
            "NIGHTLY_SETTINGS_FILE": str(self.tmp / "nightly_settings.json"),
            "NIGHTLY_MANIFEST": str(self._write("manifest.json",
                                                {"questions": [{"uuid": q, "query": f"Q {q}", "source": "text"}
                                                               for q in ("q1", "q2", "q3")]})),
            "NIGHTLY_DATASET_DIR": str(self._mk("datasets")),
            "NIGHTLY_WECOM_WEBHOOK": "http://wecom.invalid/hook",
        })
        self.env.start()
        self.addCleanup(self.env.stop)
        (self.tmp / "datasets" / "ds.json").write_text(json.dumps(
            {"items": [{"question_id": q, "question": f"题干 {q}"} for q in ("q1", "q2", "q3")]}), encoding="utf-8")

    def _write(self, name, payload):
        path = self.tmp / name
        path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
        return path

    def _mk(self, name):
        d = self.tmp / name
        d.mkdir(parents=True, exist_ok=True)
        return d

    def _common_patches(self, run_sequence, details_sequence, resume_spy=None):
        """把外部 I/O 全部换成假象：suite_runner/result_store/baseline/send/sleep。"""
        run_iter = iter(run_sequence)
        details_iter = iter(details_sequence)
        patches = [
            mock.patch.object(pipeline.suite_runner, "start_eval_run",
                              side_effect=lambda **kw: resume_spy(kw) if resume_spy else {"run_id": "run-x"}),
            mock.patch.object(pipeline.result_store, "get_run", side_effect=lambda _id: next(run_iter)),
            mock.patch.object(pipeline.result_store, "list_run_details", side_effect=lambda _id, light=False: list(next(details_iter))),
            mock.patch("evals_core.nightly.gate.load_baseline",
                       return_value={"run_id": "run-base", "details": list(_BASE_DETAILS), "_baseline_label": "R2"}),
            mock.patch("evals_core.dataset.manager.get_dataset",
                       return_value={"dataset_id": "ds", "title": "冒烟集", "question_count": 25}),
            mock.patch("evals_core.nightly.pipeline.notify.send", return_value='{"errcode":0}'),
            mock.patch.object(pipeline, "_sleep", new=lambda _s: asyncio.sleep(0)),
        ]
        for p in patches:
            p.start()
            self.addCleanup(p.stop)


class PipelineGreenTests(_Env):
    def test_full_success_publishes_green_entry(self):
        # get_run 消费点：初始轮询(running→completed) / 补判收尾 / _compute；details：补判检测 / _compute
        done = {"status": "completed", "summary_scores": _SUMMARY,
                "started_at": "2026-09-06T01:00:00", "completed_at": "2026-09-06T02:00:00"}
        self._common_patches(
            run_sequence=[{"status": "running"}, done, done, done],
            details_sequence=[_NEW_DETAILS, _NEW_DETAILS])
        result = asyncio.run(pipeline.run_nightly(dataset_id="ds", retry_rounds=0, resamples=50))
        self.assertEqual(result["state"], "green")
        day_dirs = list((self.tmp / "nightly").iterdir())
        self.assertEqual(len(day_dirs), 1)
        entry = json.loads((day_dirs[0] / "nightly.json").read_text(encoding="utf-8"))
        self.assertEqual(entry["state"], "green")
        self.assertEqual(entry["run_id"], "run-x")
        self.assertEqual(entry["subject"], "冒烟集（25 题）")
        self.assertEqual(entry["correct"], 2)
        self.assertTrue((day_dirs[0] / "report.md").exists())
        self.assertEqual([i["question"] for i in entry["fixed_items"]], ["题干 q2"])

    def test_judge_anomaly_gets_rescored_via_resume(self):
        dirty = [dict(_detail("q1", "correct"), scores={"semantic_fallback": True}),
                 _detail("q2", "correct", sem=0.8), _detail("q3", "correct")]
        resume_calls = []

        def resume_spy(kw):
            resume_calls.append(kw)
            return {"run_id": kw.get("resume_run_id") or "run-x"}

        done = {"status": "completed", "summary_scores": _SUMMARY,
                "started_at": "2026-09-06T01:00:00", "completed_at": "2026-09-06T02:00:00"}
        self._common_patches(
            # 消费点：初始轮询 / resume 后轮询 / 第2轮检测干净收尾 / _compute
            run_sequence=[done, done, done, done],
            details_sequence=[dirty, _NEW_DETAILS, _NEW_DETAILS],
            resume_spy=resume_spy)
        result = asyncio.run(pipeline.run_nightly(dataset_id="ds", retry_rounds=2, resamples=50))
        self.assertEqual(result["state"], "green")
        # 补判轮用 rescore_question_ids 识别：初始启动现在同样带 resume_run_id
        # （断点续跑探测，fc0704b），不能再靠"含该键的调用"挑补判轮。
        resume = next(c for c in resume_calls if c.get("rescore_question_ids"))
        self.assertEqual(resume["resume_run_id"], result["run_id"])  # 补判原地复用同一 run
        self.assertEqual(resume["rescore_question_ids"], ["q1"])


class PipelineErrorTests(_Env):
    def test_start_failure_still_publishes_error_day(self):
        patches = [
            mock.patch.object(pipeline.suite_runner, "start_eval_run", side_effect=RuntimeError("题库缺失")),
            mock.patch("evals_core.dataset.manager.get_dataset", return_value=None),
            mock.patch("evals_core.nightly.pipeline.notify.send", return_value='{"errcode":0}'),
        ]
        for p in patches:
            p.start()
            self.addCleanup(p.stop)
        result = asyncio.run(pipeline.run_nightly(dataset_id="ds", retry_rounds=0))
        self.assertEqual(result["state"], "error")
        self.assertIn("题库缺失", result["detail"])
        entry = json.loads(next((self.tmp / "nightly").glob("*/nightly.json")).read_text(encoding="utf-8"))
        self.assertEqual(entry["state"], "error")
        self.assertEqual(entry["subject"], "ds")  # 题集查不到时维护内容退回 dataset_id
        self.assertIn("题库缺失", entry["note"])
        self.assertEqual(entry["verdict"], "评测中断，未出结果")

    def test_retry_rounds_exhausted_is_error(self):
        dirty = [dict(_detail("q1", "correct"), scores={"semantic_fallback": True}),
                 _detail("q2", "correct"), _detail("q3", "correct")]
        self._common_patches(
            run_sequence=[{"status": "completed"}, {"status": "completed"}],
            details_sequence=[dirty, dirty, dirty])
        result = asyncio.run(pipeline.run_nightly(dataset_id="ds", retry_rounds=1, resamples=50))
        self.assertEqual(result["state"], "error")
        self.assertIn("未清零异常", result["detail"])


if __name__ == "__main__":
    unittest.main()
