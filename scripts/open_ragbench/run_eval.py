"""导入题集、启动评测 run 并轮询到终态。"""
import argparse
import os
import sys
import time
from pathlib import Path

import requests

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from open_ragbench import common


def import_dataset(ep: common.Endpoints, dataset_file: Path = common.EVAL_DATASET_FILE) -> None:
    with open(dataset_file, "rb") as fh:
        resp = requests.post(
            ep.eval_import,
            files={"file": (dataset_file.name, fh, "application/json")},
            timeout=60,
        )
    resp.raise_for_status()


def start_run(ep: common.Endpoints, dataset_id: str = common.DATASET_ID) -> str:
    resp = requests.post(ep.eval_runs, json={"dataset_id": dataset_id}, timeout=60)
    resp.raise_for_status()
    run_id = resp.json().get("run_id")
    if not run_id:
        raise RuntimeError(f"run 响应缺少 run_id: {resp.json()}")
    return run_id


def poll_run(ep: common.Endpoints, run_id: str, timeout: int, interval: int):
    deadline = time.time() + timeout
    run = {}
    while time.time() < deadline:
        resp = requests.get(ep.eval_run(run_id), timeout=60)
        resp.raise_for_status()
        run = resp.json()
        if run.get("status") not in ("running", "pending", "queued"):
            return run
        time.sleep(interval)
    # 超时不再静默返回 running 中间快照（实踩：被当成"评测完成"落盘污染分析）
    raise TimeoutError(
        f"run {run_id} 轮询超时（{timeout}s），最后状态 {run.get('status')}，"
        f"进度 {run.get('completed_questions')}/{run.get('total_questions')}；"
        "评测仍在后端执行，请用 wait_run.py 或调大 --poll-timeout"
    )


def run_eval(
    ep: common.Endpoints,
    dataset_file: Path = common.EVAL_DATASET_FILE,
    dataset_id: str = common.DATASET_ID,
    out_path: Path = common.REPORTS_DIR / "open-ragbench-subset-v1-raw.json",
    poll_interval: int = 10,
    poll_timeout: int = 7200,
):
    import_dataset(ep, dataset_file)
    run_id = start_run(ep, dataset_id)
    run = poll_run(ep, run_id, poll_timeout, poll_interval)
    common.save_json(out_path, run)
    return run


def main() -> int:
    parser = argparse.ArgumentParser(description="运行 Open RAG Benchmark 子集评测")
    parser.add_argument("--aichat-api", default="http://localhost:8791")
    parser.add_argument("--dataset-file", default=str(common.EVAL_DATASET_FILE), help="题集 JSON 路径")
    parser.add_argument("--dataset-id", default=common.DATASET_ID, help="题集 ID")
    parser.add_argument("--out", default="", help="原始结果输出路径（默认 reports/<dataset-id>-raw.json）")
    parser.add_argument("--import-only", action="store_true", help="只导入题集到 evals，不启动评测 run")
    parser.add_argument("--poll-timeout", type=int, default=7200,
                        help="轮询总超时秒数（487 题全量建议 ≥21600；超时抛错不误报完成）")
    parser.add_argument("--auto-retry", action="store_true",
                        help="跑完自动重试异常题：judge_fail 仅重判分、exec_error 整题重跑（默认关）")
    parser.add_argument("--retry-max-rounds", type=int, default=2)
    args = parser.parse_args()
    dataset_file = Path(args.dataset_file)
    out_path = Path(args.out) if args.out else common.REPORTS_DIR / f"{args.dataset_id}-raw.json"
    ep = common.Endpoints(aichat_api=args.aichat_api)
    if args.import_only:
        import_dataset(ep, dataset_file)
        print("题集已导入 evals 页面:", args.dataset_id)
        return 0
    run = run_eval(
        ep,
        dataset_file=dataset_file,
        dataset_id=args.dataset_id,
        out_path=out_path,
        poll_timeout=args.poll_timeout,
    )
    if args.auto_retry:
        from open_ragbench import retry_anomalies as retry
        run_id = run.get("run_id")
        run, remaining = retry.retry_anomalies(
            ep, args.dataset_id, run_id,
            max_rounds=args.retry_max_rounds, poll_timeout=args.poll_timeout,
        )
        common.save_json(out_path, run)
        if remaining:
            print("异常重试轮数耗尽，剩余:", {k: len(v) for k, v in remaining.items()})
            return 2
    print("评测完成:", run.get("run_id"), run.get("status"), "结果:", out_path)
    return 0


if __name__ == "__main__":
    sys.exit(main())
