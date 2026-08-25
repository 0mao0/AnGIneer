"""按题型汇总评测 run 结果并生成 Markdown 报告。"""
import argparse
import sys
from pathlib import Path

from open_ragbench import common


def _mean(values):
    vals = [float(v) for v in values if v is not None]
    return round(sum(vals) / len(vals), 4) if vals else None


def summarize_bucket(details):
    def get(d, section, key):
        return d.get("all_scores", {}).get(section, {}).get(key)

    hits1 = [get(d, "retrieval", "hit@1") for d in details]
    hits3 = [get(d, "retrieval", "hit@3") for d in details]
    hits5 = [get(d, "retrieval", "hit@5") for d in details]
    mrr = [get(d, "retrieval", "mrr") for d in details]
    citation = [get(d, "retrieval", "citation_hit") for d in details]
    answers = [
        get(d, "answer", "correctness_score")
        for d in details
        if get(d, "answer", "correctness_checked")
    ]
    return {
        "count": len(details),
        "hit@1": _mean(hits1),
        "hit@3": _mean(hits3),
        "hit@5": _mean(hits5),
        "mrr": _mean(mrr),
        "citation_hit": _mean(citation),
        "answer_correctness": _mean(answers),
        "correct": sum(1 for d in details if d.get("quality") == "correct"),
        "wrong": sum(1 for d in details if d.get("quality") == "wrong"),
    }


def group_and_summarize(run_details, manifest):
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
    return summary


def render_markdown(summary) -> str:
    lines = [
        "# Open RAG Benchmark 子集评测报告",
        "",
        "text-image 题目为已知限制：当前问答链路纯文本，图片仅靠标题/上下文/OCR 文本回答。",
        "",
        "| 题型 | 题数 | hit@1 | hit@3 | hit@5 | MRR | citation_hit | 回答正确率 | 正确 | 错误 |",
        "| :--- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for source in common.SOURCES + ["other", "overall"]:
        if source not in summary:
            continue
        b = summary[source]
        lines.append(
            f"| {source} | {b['count']} | {b['hit@1']} | {b['hit@3']} | {b['hit@5']} | "
            f"{b['mrr']} | {b['citation_hit']} | {b['answer_correctness']} | {b['correct']} | {b['wrong']} |"
        )
    return "\n".join(lines) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description="生成 Open RAG Benchmark 子集评测报告")
    parser.add_argument("--raw", default=str(common.REPORTS_DIR / "open-ragbench-subset-v1-raw.json"))
    parser.add_argument("--out", default=str(common.REPORTS_DIR / "open-ragbench-subset-v1.md"))
    args = parser.parse_args()

    run = common.load_json(Path(args.raw))
    manifest = common.load_json(common.SUBSET_MANIFEST)
    summary = group_and_summarize(run.get("details", []), manifest)
    common.save_json(common.REPORTS_DIR / "open-ragbench-subset-v1-summary.json", summary)
    Path(args.out).write_text(render_markdown(summary), encoding="utf-8")
    print("报告已生成:", args.out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
