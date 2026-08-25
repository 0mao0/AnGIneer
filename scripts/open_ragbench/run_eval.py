"""导入题集、启动评测 run 并轮询到终态。"""
import argparse
import os
import sys
import time
from pathlib import Path

import requests

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from open_ragbench import common


def import_dataset(ep: common.Endpoints) -> None:
    with open(common.EVAL_DATASET_FILE, "rb") as fh:
        resp = requests.post(
            ep.eval_import,
            files={"file": (common.EVAL_DATASET_FILE.name, fh, "application/json")},
            timeout=60,
        )
    resp.raise_for_status()


def start_run(ep: common.Endpoints) -> str:
    resp = requests.post(ep.eval_runs, json={"dataset_id": common.DATASET_ID}, timeout=60)
    resp.raise_for_status()
    run_id = resp.json().get("run_id")
    if not run_id:
        raise RuntimeError(f"run 响应缺少 run_id: {resp.json()}")
    return run_id


def poll_run(ep: common.Endpoints, run_id: str, timeout: int, interval: int):
    deadline = time.time() + timeout
    while time.time() < deadline:
        resp = requests.get(ep.eval_run(run_id), timeout=60)
        resp.raise_for_status()
        run = resp.json()
        if run.get("status") not in ("running", "pending", "queued"):
            return run
        time.sleep(interval)
    return run


def run_eval(
    ep: common.Endpoints,
    out_path: Path = common.REPORTS_DIR / "open-ragbench-subset-v1-raw.json",
    poll_interval: int = 10,
    poll_timeout: int = 3600,
):
    import_dataset(ep)
    run_id = start_run(ep)
    run = poll_run(ep, run_id, poll_timeout, poll_interval)
    common.save_json(out_path, run)
    return run


def main() -> int:
    parser = argparse.ArgumentParser(description="运行 Open RAG Benchmark 子集评测")
    parser.add_argument("--aichat-api", default="http://localhost:8791")
    args = parser.parse_args()
    run = run_eval(common.Endpoints(aichat_api=args.aichat_api))
    print("评测完成:", run.get("run_id"), run.get("status"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
