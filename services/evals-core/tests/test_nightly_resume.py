"""nightly 断点续跑回归（2026-09-12 部署重建砸 run 实踩的两个修复）。

覆盖：
- caliber_fingerprint：口径指纹随 env 变化
- 启动清扫给中断 run 盖章（人为停止不经过该路径 → 无章不会被复活）
- _find_resume_candidate：章/窗口/口径/已完成数四重守卫 + 探测失败退化
- run_nightly 接线：候选注入 start_eval_run(resume_run_id)，无候选传 None
"""
import asyncio
import os
import sys
from datetime import datetime, timedelta

import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "src")))

from evals_core.nightly import pipeline  # noqa: E402
from evals_core.runner import suite_runner  # noqa: E402


FP = {"eval_engine": "deepeval", "deepval_extra": "0", "judge_model": "J", "steps_fp": "abc"}


def _mk_run(run_id="run-x", status="cancelled", done=400, ago_min=30, stamp=True, fp=FP):
    summary = {"total": 526, "correct": 300}
    if stamp:
        summary["interrupted_by_startup_sweep"] = True
    return {
        "run_id": run_id, "status": status, "completed_questions": done,
        "completed_at": (datetime.now() - timedelta(minutes=ago_min)).isoformat(timespec="seconds"),
        "summary_scores": summary, "config_snapshot": {"caliber_fp": fp},
    }


@pytest.fixture()
def fp(monkeypatch):
    monkeypatch.setattr(suite_runner, "caliber_fingerprint", lambda: dict(FP))
    return FP


# ---- 口径指纹 ----


def test_caliber_fingerprint_env_sensitivity(monkeypatch):
    monkeypatch.setenv("EVAL_ENGINE", "deepeval")
    monkeypatch.setenv("EVAL_JUDGE_MODEL", "judge-a")
    a = suite_runner.caliber_fingerprint()
    assert a["eval_engine"] == "deepeval" and a["judge_model"] == "judge-a"
    monkeypatch.setenv("EVAL_JUDGE_MODEL", "judge-b")
    assert suite_runner.caliber_fingerprint() != a, "judge 变化必须改变指纹（续跑守卫的根基）"


def test_manifest_stamped_with_fingerprint(fp, monkeypatch):
    # build_run_manifest 依赖 angineer_core 整套配置装配，桩掉模块只验盖章行为
    import types

    fake_mod = types.ModuleType("angineer_core.run_manifest")
    fake_mod.build_run_manifest = lambda config_name: {"base": True}
    monkeypatch.setitem(sys.modules, "angineer_core.run_manifest", fake_mod)
    m = suite_runner._manifest_with_judge(None, None)
    assert m["caliber_fp"] == FP


# ---- 启动清扫盖章 ----


def test_sweep_stamps_interrupted(monkeypatch):
    captured = {}
    monkeypatch.setattr(suite_runner.result_store, "list_runs",
                        lambda dataset_id=None: [{"run_id": "old-1", "status": "running", "owner_pid": 999999, "total_questions": 10}])
    monkeypatch.setattr(suite_runner, "_pid_alive", lambda pid: False)
    monkeypatch.setattr(suite_runner.result_store, "list_run_details",
                        lambda run_id, light=False: [{"status": "completed", "quality": "correct"}] * 6)
    monkeypatch.setattr(suite_runner.result_store, "cancel_run",
                        lambda run_id, summary: captured.update(run_id=run_id, summary=summary))
    assert suite_runner.sweep_interrupted_runs() == 1
    assert captured["summary"].get("interrupted_by_startup_sweep") is True


# ---- 续跑候选守卫 ----


def _candidate_with(monkeypatch, rows, fp=FP):
    monkeypatch.setattr(pipeline.result_store, "list_runs", lambda dataset_id=None: rows)


def test_candidate_accepted(fp, monkeypatch):
    _candidate_with(monkeypatch, [_mk_run()])
    assert pipeline._find_resume_candidate("d") == "run-x"


def test_candidate_takes_most_recent_within_window(fp, monkeypatch):
    # list_runs 契约=started_at 倒序 → 首个合格者胜出；首条已完成数为 0 应跳过后取次条
    _candidate_with(monkeypatch, [_mk_run(run_id="run-a", done=0), _mk_run(run_id="run-b")])
    assert pipeline._find_resume_candidate("d") == "run-b"


def test_candidate_rejects_manual_stop(fp, monkeypatch):
    _candidate_with(monkeypatch, [_mk_run(stamp=False)])
    assert pipeline._find_resume_candidate("d") == ""


def test_candidate_rejects_stale_outside_window(fp, monkeypatch):
    _candidate_with(monkeypatch, [_mk_run(ago_min=11 * 60)])
    assert pipeline._find_resume_candidate("d") == ""


def test_candidate_rejects_caliber_mismatch(fp, monkeypatch):
    _candidate_with(monkeypatch, [_mk_run(fp={"eval_engine": "legacy"})])
    assert pipeline._find_resume_candidate("d") == ""


def test_candidate_rejects_zero_progress_and_noncancelled(fp, monkeypatch):
    _candidate_with(monkeypatch, [_mk_run(done=0), _mk_run(run_id="run-y", status="completed")])
    assert pipeline._find_resume_candidate("d") == ""


def test_candidate_probing_failure_degrades_to_fresh(fp, monkeypatch):
    def boom(dataset_id=None):
        raise RuntimeError("db locked")
    monkeypatch.setattr(pipeline.result_store, "list_runs", boom)
    assert pipeline._find_resume_candidate("d") == ""


# ---- run_nightly 接线 ----


def _patch_flow(monkeypatch, resume_id):
    captured = {}

    def fake_start(**kw):
        captured.update(kw)
        return {"run_id": resume_id or "run-new"}

    async def fake_wait(run_id, deadline):
        return {"status": "completed"}

    async def fake_retry(*a, **k):
        return {}

    async def fake_publish(*a, **k):
        return {"state": "green", "ok": True, "run_id": captured.get("resume_run_id") or "run-new"}

    monkeypatch.setattr(pipeline.suite_runner, "start_eval_run", fake_start)
    monkeypatch.setattr(pipeline, "_await_terminal", fake_wait)
    monkeypatch.setattr(pipeline, "_auto_retry", fake_retry)
    monkeypatch.setattr(pipeline, "_compute_and_publish", fake_publish)
    monkeypatch.setattr(pipeline, "_find_resume_candidate", lambda ds, w: resume_id)
    return captured


def test_run_nightly_wires_resume_id(monkeypatch):
    captured = _patch_flow(monkeypatch, "run-old")
    out = asyncio.run(pipeline.run_nightly(dataset_id="d"))
    assert captured.get("resume_run_id") == "run-old"
    assert out["state"] == "green"


def test_run_nightly_no_candidate_starts_fresh(monkeypatch):
    captured = _patch_flow(monkeypatch, "")
    asyncio.run(pipeline.run_nightly(dataset_id="d"))
    assert captured.get("resume_run_id") is None
