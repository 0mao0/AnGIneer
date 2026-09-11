"""按题型汇总评测 run 结果并生成 Markdown 报告（算法真相源，scripts 侧 CLI 复用）。

统计口径约定（2026-09-05 教训）：均值会被 judge 重试挂起题带偏，跨 run 对比看
median/p90；section/citation 指标只在有对应标注的题上聚合（N/A 不计 0 不进分母）。
"""
import random

from evals_core.runner import anomaly

SOURCES = ["text", "text-image", "text-table", "text-table-image"]


def _mean(values):
    vals = [float(v) for v in values if v is not None]
    return round(sum(vals) / len(vals), 4) if vals else None


def _median_p90(values):
    vals = sorted(float(v) for v in values if v is not None)
    if not vals:
        return None, None
    median = vals[len(vals) // 2] if len(vals) % 2 else (vals[len(vals) // 2 - 1] + vals[len(vals) // 2]) / 2
    p90 = vals[min(int(0.9 * len(vals)), len(vals) - 1)]
    return round(median, 4), round(p90, 4)


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

    section_gold_details = [d for d in details if get(d, "retrieval", "metric_granularity") == "section"]
    target_gold_details = [d for d in details if get(d, "retrieval", "gold_target_types")]
    hits1 = [get(d, "retrieval", "hit@1") for d in section_gold_details]
    hits3 = [get(d, "retrieval", "hit@3") for d in section_gold_details]
    hits5 = [get(d, "retrieval", "hit@5") for d in section_gold_details]
    mrr = [get(d, "retrieval", "mrr") for d in section_gold_details]
    hits1_doc = [get(d, "retrieval", "hit@1_doc") for d in details]
    hits3_doc = [get(d, "retrieval", "hit@3_doc") for d in details]
    hits5_doc = [get(d, "retrieval", "hit@5_doc") for d in details]
    mrr_doc = [get(d, "retrieval", "mrr_doc") for d in details]
    citation = [get(d, "retrieval", "citation_hit") for d in target_gold_details]
    answers = [get(d, "answer", "correctness_score") for d in details if get(d, "answer", "correctness_checked")]
    refusal_expected = [d for d in details if get(d, "answer", "refusal_expected")]
    refusal_correct = [d for d in refusal_expected if get(d, "answer", "refusal_correct")]
    sem_median, sem_p90 = _median_p90([get(d, "answer", "semantic_score") for d in details])
    lat_median, lat_p90 = _median_p90([d.get("latency_ms") for d in details])
    # DeepEval 引擎扩展维度（legacy 引擎无这些键；median 口径，None 不计入分母）
    faith_median, _ = _median_p90([get(d, "answer", "faithfulness_score") for d in details])
    relev_median, _ = _median_p90([get(d, "answer", "answer_relevancy_score") for d in details])
    ctxp_median, _ = _median_p90([get(d, "answer", "contextual_precision_score") for d in details])
    return {
        "count": len(details),
        "semantic_median": sem_median,
        "semantic_p90": sem_p90,
        "latency_median_s": round(lat_median / 1000, 1) if lat_median is not None else None,
        "latency_p90_s": round(lat_p90 / 1000, 1) if lat_p90 is not None else None,
        "faithfulness_median": faith_median,
        "answer_relevancy_median": relev_median,
        "contextual_precision_median": ctxp_median,
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
    buckets = {s: [] for s in SOURCES}
    buckets["other"] = []
    for d in run_details:
        source = source_by_uuid.get(d.get("question_id"), "other")
        if source not in buckets:
            source = "other"
        buckets[source].append(d)
    summary = {}
    for source in SOURCES + ["other"]:
        if buckets[source]:
            summary[source] = summarize_bucket(buckets[source])
    summary["overall"] = summarize_bucket(run_details)
    # 异常题门禁：judge_fail/exec_error 未清零前 overall 只是初步值（基础设施失败
    # 混在模型失败里会系统性压低分数，2026-09-05 实踩；先补判/重跑再看终版）
    anomalies = anomaly.detect_anomalies(run_details)
    summary["anomalies"] = anomalies
    summary["anomaly_pending"] = bool(
        [q for k in (anomaly.JUDGE_FAIL, anomaly.EXEC_ERROR) for q in anomalies.get(k, [])])
    summary["overall"]["slow_count"] = len(anomalies.get(anomaly.SLOW, []))
    # 题干摘录：报告里给读者看题面而不是 UUID（慢题观察单等处消费；截 70 字符）
    summary["question_titles"] = {
        str(q.get("uuid")): str(q.get("query") or "")[:70]
        for q in manifest.get("questions", []) if q.get("uuid")
    }
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
    anomaly_pending = bool(summary.get("anomaly_pending"))
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

    for source in SOURCES + ["other", "overall"]:
        if source not in summary:
            continue
        b = summary[source]
        mark = " *" if (source == "overall" and anomaly_pending) else ""
        lines.append(
            f"| {source}{mark} | {b['count']} | {fmt(b['hit@1'])} | {fmt(b['hit@3'])} | {fmt(b['hit@5'])} | {fmt(b['mrr'])} | "
            f"{b['hit@1_doc']} | {b['hit@3_doc']} | {b['hit@5_doc']} | {b['mrr_doc']} | "
            f"{fmt(b['citation_hit'])} | {b['answer_correctness']} | {b['correct']} | {b['wrong']} |"
        )
    if anomaly_pending:
        pending = {k: v for k, v in (summary.get("anomalies") or {}).items() if k != anomaly.SLOW and v}
        lines.append("")
        lines.append(
            "> ⚠ **overall 为初步值\\***：异常题未清零（"
            + "，".join(f"{k}={len(v)}" for k, v in pending.items())
            + "）。等待自动补判/重跑收口后再看终版。"
        )
    dist_lines = []
    for source in SOURCES + ["other", "overall"]:
        b = summary.get(source)
        if not b:
            continue
        dist_lines.append(
            f"| {source} | {fmt(b.get('semantic_median'))} / {fmt(b.get('semantic_p90'))} | "
            f"{fmt(b.get('latency_median_s'))} / {fmt(b.get('latency_p90_s'))} |"
        )
    if dist_lines:
        lines += ["", "## 分布口径（median / p90）", "", "| 题型 | semantic_score | 单题耗时(s) |", "| :--- | ---: | ---: |"] + dist_lines
    # DeepEval 扩展维度（仅当存在数据时展示；首版只展示不进门禁）
    ext_rows = []
    for source in SOURCES + ["other", "overall"]:
        b = summary.get(source)
        if not b or b.get("faithfulness_median") is None:
            continue
        ext_rows.append(
            f"| {source} | {b['faithfulness_median']} | {fmt(b.get('answer_relevancy_median'))} | {fmt(b.get('contextual_precision_median'))} |"
        )
    if ext_rows:
        lines += [
            "",
            "## 扩展维度（DeepEval 引擎，median；只展示不进门禁）",
            "",
            "| 题型 | faithfulness（忠实度） | answer_relevancy（相关性） | contextual_precision（上下文精度） |",
            "| :--- | ---: | ---: | ---: |",
        ] + ext_rows
    slow_ids = (summary.get("anomalies") or {}).get(anomaly.SLOW) or []
    if slow_ids:
        titles = summary.get("question_titles") or {}
        lines += ["", f"**慢题观察单（>{anomaly.DEFAULT_SLOW_MS // 1000}s，不计异常不重跑）**: {len(slow_ids)} 题"]
        for qid in slow_ids[:20]:
            title = titles.get(str(qid)) or ""
            label = (title + "…") if len(title) >= 70 else title
            lines.append(f"- {label or str(qid)[:8]}")
        if len(slow_ids) > 20:
            lines.append(f"- …其余 {len(slow_ids) - 20} 题")
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
