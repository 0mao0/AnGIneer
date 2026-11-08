"""上一轮轻对照 + 卡片基线/上一轮两行的渲染（2026-11-08 双对照修复）。"""
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO / "services" / "evals-core" / "src"))
sys.path.insert(0, str(REPO / "services" / "shared" / "src"))

from evals_core.nightly import gate, notify  # noqa: E402


def _run(rid, quals, started_at="2026-10-30T17:12:32+00:00"):
    return {"run_id": rid, "started_at": started_at,
            "details": [{"question_id": q, "quality": v} for q, v in quals.items()]}


def test_compare_with_previous_delta_and_matrix():
    prev = _run("prev", {"q1": "correct", "q2": "wrong", "q3": "correct", "q4": "wrong"})
    cur = _run("cur", {"q1": "correct", "q2": "correct", "q3": "correct", "q4": "wrong"})
    res = gate.compare_with_previous(prev, cur)
    assert res["run_id"] == "prev"
    assert res["matrix"] == {"pp": 2, "pf": 1, "fp": 0, "ff": 1}
    assert res["comparable"] == 4
    assert abs(res["delta"] - 0.25) < 1e-9


def test_compare_with_previous_identical_runs_zero_delta():
    quals = {"q1": "correct", "q2": "wrong"}
    res = gate.compare_with_previous(_run("prev", quals), _run("cur", quals))
    assert res["delta"] == 0.0
    assert res["matrix"] == {"pp": 1, "pf": 0, "fp": 0, "ff": 1}


def test_notify_card_shows_baseline_date_and_prev_line():
    gate_res = {
        "delta": 0.1212, "delta_ci95": [0.0303, 0.2424],
        "matrix": {"pp": 22, "pf": 4, "fp": 0, "ff": 7},
        "base_label": "v4.1-recaliber-2026-10-09（6 题拒答标注修正重判）",
        "prev": {"run_id": "run-dc96eac2", "started_at": "2026-10-30T17:12:32+00:00",
                 "matrix": {"pp": 22, "pf": 0, "fp": 0, "ff": 7}, "delta": 0.0},
    }
    raw = {"started_at": "2026-11-08T02:32:59+00:00",
           "completed_at": "2026-11-08T02:37:35+00:00",
           "summary_scores": {"overall_score": 0.7879, "correct": 26, "total": 33,
                              "judge_failed_count": 0, "errored": 0}}
    text = notify.build_message(raw, gate_res, "green")
    assert "基线：2026-10-09（" in text
    assert "较上一轮（10-30）：基本持平 0.0 个百分点（净增 0 题）" in text
