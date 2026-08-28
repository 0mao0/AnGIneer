"""冒烟门禁：跑小体量题集并与基线对比，回退即失败（exit 1）。

用法：
    python scripts/open_ragbench/run_smoke.py                    # 对比基线
    python scripts/open_ragbench/run_smoke.py --update-baseline  # 记录当前为基线
"""
import argparse
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from open_ragbench import common, run_eval as run_eval_mod

# 允许的指标下浮容差（题集小，单题波动大）
SCORE_TOLERANCE = 0.05


def check_regression(current, baseline, tolerance: float = SCORE_TOLERANCE):
    """对比当前 run 与基线，返回问题列表（空 = 通过）。"""
    problems = []
    for key in ("overall_score", "refusal_accuracy"):
        base = baseline.get(key)
        now = current.get(key)
        if base is None or now is None:
            continue
        if now < base - tolerance:
            problems.append(f"{key}: {now} < 基线 {base} - 容差 {tolerance}")
    return problems


def extract_metrics(run):
    summary = run.get("summary") or run.get("summary_scores") or {}
    return {
        "overall_score": summary.get("overall_score"),
        "retrieval_score": summary.get("retrieval_score"),
        "answer_score": summary.get("answer_score"),
        "refusal_accuracy": summary.get("refusal_accuracy"),
        "hallucination_on_unanswerable": summary.get("hallucination_on_unanswerable"),
        "run_id": run.get("run_id"),
        "status": run.get("status"),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="冒烟门禁评测")
    parser.add_argument("--aichat-api", default="http://localhost:8791")
    parser.add_argument("--update-baseline", action="store_true", help="将本次结果记录为新基线")
    parser.add_argument("--poll-timeout", type=int, default=3600)
    args = parser.parse_args()

    if not common.SMOKE_DATASET_FILE.exists():
        print("冒烟题集不存在，请先运行 build_smoke_set.py")
        return 2

    ep = common.Endpoints(aichat_api=args.aichat_api)
    run = run_eval_mod.run_eval(
        ep,
        dataset_file=common.SMOKE_DATASET_FILE,
        dataset_id=common.SMOKE_DATASET_ID,
        out_path=common.REPORTS_DIR / f"{common.SMOKE_DATASET_ID}-raw.json",
        poll_timeout=args.poll_timeout,
    )
    metrics = extract_metrics(run)
    print("冒烟结果:", metrics)

    if args.update_baseline:
        common.save_json(common.SMOKE_BASELINE_FILE, metrics)
        print("基线已更新:", common.SMOKE_BASELINE_FILE)
        return 0

    if not common.SMOKE_BASELINE_FILE.exists():
        common.save_json(common.SMOKE_BASELINE_FILE, metrics)
        print("无基线，已记录首次结果为基线:", common.SMOKE_BASELINE_FILE)
        return 0

    baseline = common.load_json(common.SMOKE_BASELINE_FILE)
    problems = check_regression(metrics, baseline)
    if problems:
        print("冒烟门禁未通过：")
        for problem in problems:
            print(" -", problem)
        return 1
    print("冒烟门禁通过")
    return 0


if __name__ == "__main__":
    sys.exit(main())
