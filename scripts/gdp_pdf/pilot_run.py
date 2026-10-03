"""GDP.pdf 试点跑：进程内直接驱动 RubricEvaluator（不经 aichat-api HTTP、不写 evals 库）。

用途：小样本快速验证「解析入库→检索→生成→判官逐条判 rubric」全链与判分口径，
产出 all_pass 率 + mean_criteria + 检索命中，供决定是否全量入库 + 进 UI/生产。

跑的是磁盘上的新码（services/evals-core/src），无需重启任何服务。

用法（仓库根目录）：
  python scripts/gdp_pdf/pilot_run.py --bundle data/evals/datasets/gdp-pdf-v1.json --limit 10
  python scripts/gdp_pdf/pilot_run.py --ids <taskid1>,<taskid2>   # 指定题
"""
import argparse
import json
import os
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "services" / "evals-core" / "src"))


def _load_env():
    try:
        from dotenv import load_dotenv

        load_dotenv(REPO / ".env")
    except ImportError:
        pass


def _predicted_doc_ids(prediction: dict) -> list:
    out = []
    for item in prediction.get("retrieved_items") or []:
        d = str(item.get("doc_id") or "")
        if d and d not in out:
            out.append(d)
    return out


def run_one(ev, item: dict, judge: str = "", answer_model: str = "") -> dict:
    question = {
        "question_id": item["question_id"],
        "question": item["question"],
        "library_id": item["library_id"],
        "doc_ids": item.get("doc_ids") or [],
        "rubric_gold": item.get("rubric") or {},
        "retrieval_gold": item.get("retrieval") or {},
        # 旋钮：被测模型 config_name + run 级判官 judge_config_name（与 answer 评测器同字段）
        "config_name": answer_model or None,
        "judge_config_name": judge or None,
    }
    t0 = time.time()
    prediction = ev.run_prediction(question)
    if not prediction or "error" in prediction:
        return {"question_id": item["question_id"], "error": (prediction or {}).get("error", "no prediction")}
    scores = ev.evaluate(question, question["rubric_gold"], prediction)
    gold_docs = (item.get("retrieval") or {}).get("gold_doc_ids") or []
    predicted = _predicted_doc_ids(prediction)
    hit1 = bool(predicted) and gold_docs and predicted[0] == gold_docs[0]
    hitk = bool(set(gold_docs) & set(predicted[:8]))
    answer = str(prediction.get("answer") or "")
    return {
        "question_id": item["question_id"],
        "domain": (item.get("tags") or [""])[0],
        "question": item["question"][:160],
        "answer_head": answer[:220],
        "answer_len": len(answer),
        "status": scores.get("rubric_status"),
        "all_pass": scores.get("all_pass"),
        "n_pass": scores.get("n_pass"),
        "n_total": scores.get("n_total"),
        "mean_criteria": scores.get("mean_criteria"),
        "judge_used": scores.get("judge_used"),
        "retrieval_hit1": hit1,
        "retrieval_hit_top8": hitk,
        "latency_s": round(time.time() - t0, 1),
        "failed_criteria": [c for c in scores.get("per_criterion", []) if not c.get("pass")][:6],
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--bundle", default=str(REPO / "data" / "evals" / "datasets" / "gdp-pdf-v1.json"))
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--ids", default="", help="逗号分隔 task_id 白名单")
    ap.add_argument("--judge", default="", help="判官 LLM 配置名（空=默认候选链；想贴官方数就传对应端点）")
    ap.add_argument("--answer-model", default="", help="被测模型 config_name（空=默认）")
    ap.add_argument("--out", default=str(REPO / "data" / "evals" / "originals" / "gdp_pdf" / "pilot_result.json"))
    args = ap.parse_args()
    _load_env()

    # 进程内回放：补注册 docs-core 引擎端口（local_nodes_loader/检索八件套）+ 运行时工具，
    # 否则 run_eval_query 检索空 → 假拒答（同 case_trace._ensure_engine_ports 纪律）。
    from evals_core.runner import case_trace
    case_trace._register_runtime_tools()
    case_trace._ensure_engine_ports()

    from evals_core.runner.rubric_eval import RubricEvaluator

    bundle = json.loads(Path(args.bundle).read_text(encoding="utf-8"))
    items = bundle["items"]
    if args.ids:
        want = {x.strip() for x in args.ids.split(",") if x.strip()}
        items = [it for it in items if it["question_id"] in want]
    if args.limit:
        items = items[: args.limit]

    ev = RubricEvaluator()
    rows = []
    for i, it in enumerate(items, 1):
        print(f"[{i}/{len(items)}] {it.get('tags',[''])[0]:24s} {it['question'][:60]}…", flush=True)
        r = run_one(ev, it, judge=args.judge, answer_model=args.answer_model)
        rows.append(r)
        if "error" in r:
            print(f"    ERROR {r['error']}", flush=True)
        else:
            print(f"    {r['status']:14s} all_pass={r['all_pass']} {r['n_pass']}/{r['n_total']} mean={r['mean_criteria']} hit1={r['retrieval_hit1']} {r['latency_s']}s", flush=True)

    done = [r for r in rows if "error" not in r]
    n = len(done) or 1
    summary = {
        "total": len(rows),
        "errors": len(rows) - len(done),
        "all_pass_rate": round(sum(1 for r in done if r["all_pass"]) / n, 3),
        "mean_criteria_avg": round(sum(r["mean_criteria"] or 0 for r in done) / n, 3),
        "retrieval_hit1_rate": round(sum(1 for r in done if r["retrieval_hit1"]) / n, 3),
        "retrieval_hit_top8_rate": round(sum(1 for r in done if r["retrieval_hit_top8"]) / n, 3),
        "refusals": sum(1 for r in done if r["status"] == "REFUSAL"),
        "judge_fallback": sum(1 for r in done if r["status"] == "JUDGE_FALLBACK"),
    }
    Path(args.out).write_text(json.dumps({"summary": summary, "rows": rows}, ensure_ascii=False, indent=2), encoding="utf-8")
    print("\n== SUMMARY ==", json.dumps(summary, ensure_ascii=False, indent=2))
    print("明细:", args.out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
