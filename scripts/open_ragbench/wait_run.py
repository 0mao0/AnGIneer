"""轮询评测 run 到终态（无总超时限制），完成后经 API 拉全量结果存 JSON。"""
import argparse
import sqlite3
import sys
import time
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from open_ragbench import common  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("--db", default=str(common.REPO_ROOT / "data" / "evals" / "evals.sqlite"))
    parser.add_argument("--aichat-api", default="http://localhost:8791")
    parser.add_argument("--interval", type=int, default=60)
    args = parser.parse_args()

    ep = common.Endpoints(aichat_api=args.aichat_api)
    while True:
        conn = sqlite3.connect(args.db)
        row = conn.execute(
            "SELECT status, completed_questions FROM eval_run WHERE run_id=?", (args.run_id,)
        ).fetchone()
        conn.close()
        if row is None:
            print(f"run {args.run_id} 不存在", flush=True)
            return 1
        status, done = row
        print(f"{args.run_id} {status} {done}/487", flush=True)
        if status not in ("running", "pending", "queued"):
            break
        time.sleep(args.interval)

    run = requests.get(ep.eval_run(args.run_id), timeout=120).json()
    common.save_json(Path(args.out), run)
    s = run.get("summary_scores") or {}
    print("终态:", status, "overall:", s.get("overall_score"), "结果已存:", args.out, flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
