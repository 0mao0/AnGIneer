"""按题型汇总评测 run 结果并生成 Markdown 报告（含 bootstrap 置信区间）。"""
import argparse
import os
import random
import sys
from pathlib import Path

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from open_ragbench import common


def _mean(values):
    vals = [float(v) for v in values if v is not None]
    return round(sum(vals) / len(vals), 4) if vals else None


def bootstrap_ci(details, metric_fn, resamples: int = 1000, seed: int = 42):
    """按题重采样计算指标的 95% 置信区间。返回 (lower, upper) 或 None。"""
    values = [metric_fn(d) for d in details]
    values = [v for v in values if v is not None]
    n = len(values)
    if n < 2:
        return None
    rnd = random.Random(seed)
    means = []
    for _ in range(resamples):
        sample = [values[rnd.randrange(n)] for _ in range(n)]
        means.append(sum(sample) / n)
    means.sort()
    lower = means[int(0.025 * resamples)]
    upper = means[min(int(0.975 * resamples), resamples - 1)]
    return (round(lower, 4), round(upper, 4))


def summarize_bucket(details):
    def get(d, section, key):
        return d.get("all_scores", {}).get(section, {}).get(key)

    # section/citation 指标只在有对应标注的题上聚合（无标注题该指标为 N/A，不计 0 也不计入分母）
    section_gold_details = [d for d in details if get(d, "retrieval", "metric_granularity") == "section"]
    target_gold_details = [
        d for d in details
        if get(d, "retrieval", "gold_target_types")
    ]
    hits1 = [get(d, "retrieval", "hit@1") for d in section_gold_details]
    hits3 = [get(d, "retrieval", "hit@3") for d in section_gold_details]
    hits5 = [get(d, "retrieval", "hit@5") for d in section_gold_details]
    mrr = [get(d, "retrieval", "mrr") for d in section_gold_details]
    hits1_doc = [get(d, "retrieval", "hit@1_doc") for d in details]
    hits3_doc = [get(d, "retrieval", "hit@3_doc") for d in details]
    hits5_doc = [get(d, "retrieval", "hit@5_doc") for d in details]
    mrr_doc = [get(d, "retrieval", "mrr_doc") for d in details]
    citation = [get(d, "retrieval", "citation_hit") for d in target_gold_details]
    answers = [
        get(d, "answer", "correctness_score")
        for d in details
        if get(d, "answer", "correctness_checked")
    ]
    refusal_expected = [d for d in details if get(d, "answer", "refusal_expected")]
    refusal_correct = [d for d in refusal_expected if get(d, "answer", "refusal_correct")]
    return {
        "count": len(details),
        "hit@1": _mean(hits1),
        "hit@3": _mean(hits3),
        "hit@5": _mean(hits5),
        "mrr": _mean(mrr),
        "hit@1_doc": _mean(hits1_doc),
        "hit@3_doc": _mean(hits3_doc),
        "hit@5_doc": _mean(hits5_doc),
        "mrr_doc": _mean(mrr_doc),
        "citation_hit": _mean(citation),
        "answer_correctness": _mean(answers),
        "correct": sum(1 for d in details if d.get("quality") == "correct"),
        "wrong": sum(1 for d in details if d.get("quality") == "wrong"),
        "refusal_total": len(refusal_expected),
        "refusal_correct": len(refusal_correct),
        "refusal_accuracy": round(len(refusal_correct) / len(refusal_expected), 4) if refusal_expected else None,
        "hallucination_on_unanswerable": len(refusal_expected) - len(refusal_correct),
    }


def group_and_summarize(run_details, manifest, ci_resamples: int = 1000):
    source_by_uuid = {q["uuid"]: q.get("source", "text") for q in manifest.get("questions", [])}
    buckets = {s: [] for s in common.SOURCES}
    buckets["other"] = []
    for d in run_details:
        source = source_by_uuid.get(d.get("question_id"), "other")
        if source not in buckets:
            source = "other"
        buckets[source].append(d)
    summary = {}
    for source in common.SOURCES + ["other"]:
        if buckets[source]:
            summary[source] = summarize_bucket(buckets[source])
    summary["overall"] = summarize_bucket(run_details)
    # 整体关键指标的 bootstrap 95% CI（按题重采样）
    summary["overall"]["hit@5_doc_ci"] = bootstrap_ci(
        run_details,
        lambda d: d.get("all_scores", {}).get("retrieval", {}).get("hit@5_doc"),
        resamples=ci_resamples,
    )
    summary["overall"]["correct_rate_ci"] = bootstrap_ci(
        run_details,
        lambda d: 1.0 if d.get("quality") == "correct" else (0.0 if d.get("quality") == "wrong" else None),
        resamples=ci_resamples,
    )
    return summary


def render_markdown(summary) -> str:
    lines = [
        "# Open RAG Benchmark 子集评测报告",
        "",
        "text-image 题目为已知限制：当前问答链路纯文本，图片仅靠标题/上下文/OCR 文本回答。",
        "",
        "| 题型 | 题数 | hit@1(sec) | hit@3(sec) | hit@5(sec) | MRR(sec) | hit@1(doc) | hit@3(doc) | hit@5(doc) | MRR(doc) | citation_hit | 回答正确率 | 正确 | 错误 |",
        "| :--- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    def fmt(value):
        return "—" if value is None else value

    for source in common.SOURCES + ["other", "overall"]:
        if source not in summary:
            continue
        b = summary[source]
        lines.append(
            f"| {source} | {b['count']} | {fmt(b['hit@1'])} | {fmt(b['hit@3'])} | {fmt(b['hit@5'])} | {fmt(b['mrr'])} | "
            f"{b['hit@1_doc']} | {b['hit@3_doc']} | {b['hit@5_doc']} | {b['mrr_doc']} | "
            f"{fmt(b['citation_hit'])} | {b['answer_correctness']} | {b['correct']} | {b['wrong']} |"
        )
    overall = summary.get("overall") or {}
    if overall.get("hit@5_doc_ci"):
        lines += [
            "",
            "## 置信区间（bootstrap 95%）",
            "",
            f"- hit@5(doc): {overall['hit@5_doc']} ∈ {overall['hit@5_doc_ci']}",
            f"- 整体正确率: {overall['correct']}/{overall['count']} ∈ {overall.get('correct_rate_ci')}",
        ]
    if overall.get("refusal_total"):
        lines += [
            "",
            "## 拒答专项",
            "",
            f"- 拒答题数: {overall['refusal_total']}",
            f"- 拒答正确: {overall['refusal_correct']}（正确率 {overall['refusal_accuracy']}）",
            f"- 不可答幻觉数: {overall['hallucination_on_unanswerable']}",
        ]
    return "\n".join(lines) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description="生成 Open RAG Benchmark 子集评测报告")
    parser.add_argument("--raw", default=str(common.REPORTS_DIR / "open-ragbench-subset-v1-raw.json"))
    parser.add_argument("--out", default=str(common.REPORTS_DIR / "open-ragbench-subset-v1.md"))
    parser.add_argument("--manifest", default=str(common.SUBSET_MANIFEST), help="子集 manifest（题型归属）")
    parser.add_argument("--resamples", type=int, default=1000, help="bootstrap 重采样次数")
    args = parser.parse_args()

    run = common.load_json(Path(args.raw))
    manifest = common.load_json(Path(args.manifest))
    summary = group_and_summarize(run.get("details", []), manifest, ci_resamples=args.resamples)
    out_path = Path(args.out)
    common.save_json(out_path.with_suffix(".summary.json"), summary)
    out_path.write_text(render_markdown(summary), encoding="utf-8")
    print("报告已生成:", out_path)
    return 0


if __name__ == "__main__":
    sys.exit(main())
