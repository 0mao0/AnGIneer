"""FinanceBench 跑批结果汇总（判据见 docs/plan-financebench-arms.md，口径跑前写死）。

正确率口径：semantic 通过（scores.evaluated=true 且 semantic_score>=semantic_threshold）。
judge_fail = error 非空 或 scores.evaluated=false —— >15 题（10%）触预注册红线，本轮无效。
拒答 = is_refusal 且未过语义；分题型 = 题集 tags[0]。

用法：python scripts/financebench/summarize_run.py --raw <run-raw.json> [--out summary.json]
"""
import argparse
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "services" / "evals-core" / "src"))
DATASET = REPO / "data" / "evals" / "datasets" / "financebench-open-150-v1.json"

from evals_core.runner.answer_eval import is_refusal  # 引擎单真相，勿自写标记表


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--raw", required=True)
    parser.add_argument("--dataset", default=str(DATASET))
    parser.add_argument("--out", default="")
    args = parser.parse_args()

    run = json.loads(Path(args.raw).read_text(encoding="utf-8"))
    bundle = json.loads(Path(args.dataset).read_text(encoding="utf-8"))
    qtype = {it["question_id"]: (it.get("tags") or [""])[0] for it in bundle["items"]}
    thr = 0.65

    total = correct = judge_fail = refusal = 0
    hit1 = hit3 = hit5 = 0
    by_type: dict = {}
    for d in run.get("details", []):
        total += 1
        scores = d.get("scores") or {}
        passed = bool(scores.get("evaluated")) and float(scores.get("semantic_score") or 0) >= thr
        if d.get("error") or not scores.get("evaluated"):
            judge_fail += 1
        if passed:
            correct += 1
        else:
            answer = (d.get("prediction") or {}).get("answer") or ""
            if is_refusal(answer):
                refusal += 1
        ret = (d.get("all_scores") or {}).get("retrieval") or {}
        hit1 += bool(ret.get("hit@1_doc"))
        hit3 += bool(ret.get("hit@3_doc"))
        hit5 += bool(ret.get("hit@5_doc"))
        t = qtype.get(d.get("question_id"), "") or "unknown"
        st = by_type.setdefault(t, [0, 0])
        st[0] += 1
        st[1] += int(passed)

    summary = {
        "run_id": run.get("run_id"),
        "dataset_id": run.get("dataset_id"),
        "status": run.get("status"),
        "total": total,
        "accuracy": round(correct / total, 4) if total else None,
        "correct": correct,
        "judge_fail": judge_fail,
        "judge_fail_redline": judge_fail > 15,
        "refusal": refusal,
        "hit@1_doc": round(hit1 / total, 4) if total else None,
        "hit@3_doc": round(hit3 / total, 4) if total else None,
        "hit@5_doc": round(hit5 / total, 4) if total else None,
        "by_question_type": {k: {"n": v[0], "correct": v[1], "acc": round(v[1] / v[0], 4)} for k, v in sorted(by_type.items())},
        "anchor_note": "论文锚点：oracle 85% / 现实RAG最优档 50% / 8配置汇总 47%（判分口径不同，并列呈现）",
    }
    text = json.dumps(summary, ensure_ascii=False, indent=2)
    print(text)
    if args.out:
        Path(args.out).write_text(text, encoding="utf-8")
    return 2 if summary["judge_fail_redline"] else 0


if __name__ == "__main__":
    sys.exit(main())
