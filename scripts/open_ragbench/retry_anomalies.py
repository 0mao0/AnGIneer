"""异常题自动重试回路：检测→分类→resume（judge_fail 仅重判分，exec_error 整题重跑）→轮询。

背景（2026-09-05）：judge 隧道断连会让题目 semantic_fallback=True 被按 0 分静默计入，
污染 overall 且无提示。本回路把当天手工的「标记→resume 补判」流程固化：
- judge_fail → 走 rescore_question_ids（复用存量 prediction 仅重判分，零答案抖动）；
- exec_error → 整题重跑（resume 天然只跑未完成/排除题，无需特殊参数）；
- slow → 只进观察单，不重跑；
- 轮数上限防死循环（内网确认型故障可能反复出现）。
"""
import argparse
import os
import sys
import time
from pathlib import Path

import requests

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from open_ragbench import anomaly, common


def get_full_run(ep: common.Endpoints, run_id: str) -> dict:
    resp = requests.get(ep.eval_run(run_id), timeout=120)
    resp.raise_for_status()
    return resp.json()


def poll(ep: common.Endpoints, run_id: str, interval: int = 10, timeout: int = 7200) -> dict:
    deadline = time.time() + timeout
    run = {}
    while time.time() < deadline:
        run = get_full_run(ep, run_id)
        if run.get("status") not in ("running", "pending", "queued"):
            return run
        time.sleep(interval)
    raise TimeoutError(f"run {run_id} 轮询超时（{timeout}s），最后状态 {run.get('status')}")


def resume(ep: common.Endpoints, dataset_id: str, run_id: str, rescore_ids: list) -> str:
    payload = {"dataset_id": dataset_id, "resume_run_id": run_id}
    if rescore_ids:
        payload["rescore_question_ids"] = rescore_ids
    resp = requests.post(ep.eval_runs, json=payload, timeout=60)
    resp.raise_for_status()
    return resp.json()["run_id"]


def retry_anomalies(
    ep: common.Endpoints,
    dataset_id: str,
    run_id: str,
    max_rounds: int = 2,
    poll_interval: int = 10,
    poll_timeout: int = 7200,
    log=print,
):
    """返回 (final_run, remaining_anomalies)。remaining 非空表示轮数耗尽仍有异常。"""
    run = get_full_run(ep, run_id)
    for round_no in range(1, max_rounds + 1):
        anomalies = anomaly.detect(run.get("details") or [])
        todo = anomaly.actionable(anomalies)
        if not todo:
            return run, {}
        judge_fail = todo.get(anomaly.JUDGE_FAIL, [])
        exec_error = todo.get(anomaly.EXEC_ERROR, [])
        log(
            f"[retry {round_no}/{max_rounds}] judge_fail={len(judge_fail)} "
            f"exec_error={len(exec_error)}（rescore={len(judge_fail)}，整题重跑={len(exec_error)}）"
        )
        resume(ep, dataset_id, run_id, judge_fail)
        run = poll(ep, run_id, interval=poll_interval, timeout=poll_timeout)
    remaining = anomaly.actionable(anomaly.detect(run.get("details") or []))
    if remaining:
        log(f"[retry] 轮数耗尽仍有异常: { {k: len(v) for k, v in remaining.items()} }")
    return run, remaining


def main() -> int:
    parser = argparse.ArgumentParser(description="对已完成评测 run 的异常题做自动重试（补判/重跑）")
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--dataset-id", default=common.DATASET_ID)
    parser.add_argument("--aichat-api", default="http://localhost:8791")
    parser.add_argument("--max-rounds", type=int, default=2)
    parser.add_argument("--out", default="", help="重试后全量结果落盘路径（可选）")
    args = parser.parse_args()

    ep = common.Endpoints(aichat_api=args.aichat_api)
    run, remaining = retry_anomalies(ep, args.dataset_id, args.run_id, max_rounds=args.max_rounds)
    if args.out:
        common.save_json(Path(args.out), run)
    print("终态:", run.get("status"), "剩余异常:", {k: len(v) for k, v in remaining.items()} or "无")
    return 1 if remaining else 0


if __name__ == "__main__":
    sys.exit(main())
