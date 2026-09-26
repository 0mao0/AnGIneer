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
from evals_core.runner import anomaly  # noqa: E402


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

# 素材检查（B 层）的假结果：不 patch 的话 _material_health 会真的对着本机知识库跑一遍
# （200+ 篇 jsonl + Qdrant 逐篇计数）——单测从秒级变成十几分钟，且结论依赖本机数据。
_FAKE_MATERIAL = {
    "severity": "ok",
    "libraries": "all",
    "docs_checked": 3,
    "docs_with_issues": 0,
    "totals": {"blocks": 30, "blocks_with_text": 24, "blocks_uncovered": 0, "blocks_text_lost": 0,
               "chunks": 12, "vector_points": 12,
               "docs_index_not_planned": 0, "blocks_symbol_mismatch": 0},
    "symbol_mismatch_samples": [],
    "issues": [],
}


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
            # 断点续跑探测会去 list_runs 扫真实 evals.sqlite（本机 4.6GB）——单测里固定"没有可续跑 run"
            mock.patch.object(pipeline.result_store, "list_runs", return_value=[]),
            mock.patch("evals_core.nightly.gate.load_baseline",
                       return_value={"run_id": "run-base", "details": list(_BASE_DETAILS), "_baseline_label": "R2"}),
            mock.patch("evals_core.dataset.manager.get_dataset",
                       return_value={"dataset_id": "ds", "title": "冒烟集", "question_count": 25}),
            mock.patch("evals_core.nightly.pipeline.notify.send", return_value='{"errcode":0}'),
            mock.patch("evals_core.material_parity.run_check",
                       side_effect=lambda **kw: dict(_FAKE_MATERIAL)),
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
            # 这两个不 patch 就会打真实存储：素材检查扫本机知识库、续跑探测扫 4.6GB evals.sqlite
            mock.patch("evals_core.material_parity.run_check",
                       side_effect=lambda **kw: dict(_FAKE_MATERIAL)),
            mock.patch.object(pipeline.result_store, "list_runs", return_value=[]),
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
        # 用 exec_error（问答链路本身炸）立意：judge_fail 在容忍闸口内已改为放行出结论
        # （见 JudgeToleranceTests），exec_error 不在容忍范围、照旧必须判 error。
        dirty = [dict(_detail("q1", "wrong"), status="error", error="链路超时"),
                 _detail("q2", "correct"), _detail("q3", "correct")]
        self._common_patches(
            run_sequence=[{"status": "completed"}, {"status": "completed"}],
            details_sequence=[dirty, dirty, dirty])
        result = asyncio.run(pipeline.run_nightly(dataset_id="ds", retry_rounds=1, resamples=50))
        self.assertEqual(result["state"], "error")
        self.assertIn("未清零异常", result["detail"])


class JudgeToleranceTests(_Env):
    """判分缺失的容忍闸口：judge 侧抖动不再废掉整晚结论，但必须留痕、也不得掩盖真故障。

    2026-09-26 实踩：1040 题里 1 题判分崩（判分模型回了非法 JSON）、补判 2 轮未清零，
    当晚整条流水线无门禁结论 —— 而那道题的作答与检索其实都是好的，掉的是一整晚的结论。
    """

    @staticmethod
    def _judge_broken(qid):
        return dict(_detail(qid, "correct"), scores={"semantic_fallback": True})

    def _run_and_capture_card(self, details_first, **kwargs):
        done = {"status": "completed", "summary_scores": _SUMMARY,
                "started_at": "2026-09-06T01:00:00", "completed_at": "2026-09-06T02:00:00"}
        cards = []
        # webhook 必须显式传：pipeline 只认入参（读 .env 是 nightly_control._resolve_webhook 的活），
        # 不传则 _notify_best_effort 直接「未配置 webhook 跳过通知」，卡片断言永远收不到东西。
        kwargs.setdefault("webhook", "http://wecom.invalid/hook")
        self._common_patches(
            run_sequence=[{"status": "running"}, done, done, done, done],
            details_sequence=[details_first, _NEW_DETAILS])
        with mock.patch("evals_core.nightly.pipeline.notify.send",
                        side_effect=lambda url, text: (cards.append(text), '{}')[1]):
            result = asyncio.run(pipeline.run_nightly(dataset_id="ds", retry_rounds=0, resamples=50, **kwargs))
        return result, cards

    def test_judge_fail_within_tolerance_still_publishes_conclusion(self):
        dirty = [self._judge_broken("q1"), _detail("q2", "correct", sem=0.8), _detail("q3", "correct")]
        result, cards = self._run_and_capture_card(dirty)
        self.assertEqual(result["state"], "green")
        self.assertEqual(result["judge_missing"], 1)
        self.assertIn("判分缺失 1 题（阈值内放行）", result["detail"])
        entry = json.loads(next((self.tmp / "nightly").glob("*/nightly.json")).read_text(encoding="utf-8"))
        self.assertEqual(entry["judge_missing"], {anomaly.JUDGE_FAIL: ["q1"]})
        # 放行后的"绿"不能被读成"全量都判过了"：卡片必须自己把这批题说出来
        self.assertEqual(len(cards), 1)
        self.assertIn("判分缺失：1 题", cards[0])
        self.assertIn("分数偏乐观", cards[0])

    def test_judge_fail_beyond_tolerance_is_still_error(self):
        dirty = [self._judge_broken(q) for q in ("q1", "q2", "q3")]   # 3/3 题，远超 0.5%
        result, cards = self._run_and_capture_card(dirty)
        self.assertEqual(result["state"], "error")
        self.assertIn(f"{anomaly.JUDGE_FAIL}=3", result["detail"])
        self.assertIn("执行失败", cards[0])          # 超阈值照旧发失败卡片（error 档不走结论那路）

    def test_exec_error_is_never_tolerinated(self):
        """只容忍 judge 侧：问答链路本身炸了一道题，也不能被阈值放过去。"""
        dirty = [dict(_detail("q1", "wrong"), status="error", error="链路超时"),
                 _detail("q2", "correct", sem=0.8), _detail("q3", "correct")]
        result, _cards = self._run_and_capture_card(dirty)
        self.assertEqual(result["state"], "error")
        self.assertIn(f"{anomaly.EXEC_ERROR}=1", result["detail"])

    def test_threshold_is_tunable_via_env_without_code_change(self):
        dirty = [self._judge_broken(q) for q in ("q1", "q2", "q3")]
        with mock.patch.dict(os.environ, {"NIGHTLY_JUDGE_FAIL_MAX_PCT": "100", "NIGHTLY_JUDGE_FAIL_MAX": "20"}):
            result, _cards = self._run_and_capture_card(dirty)
        self.assertEqual(result["state"], "green")
        self.assertEqual(result["judge_missing"], 3)


if __name__ == "__main__":
    unittest.main()
