"""两次评测 run 的逐题对比与回归门禁（过渡矩阵 + 归因桶 + 配对 bootstrap 显著性）。

run 输入形态三选一：
- "baseline"：读 data/evals/baseline/baseline_run.json 钉住的快照（nightly 门禁推荐，
  不和"上一次 run"比——缓慢漂移会被逐轮消化，基线必须是钉住的）；
- raw json 路径（pin 子命令产出的裁剪快照或完整 raw 均可）；
- run-xxx：从 evals.sqlite 直读。

门禁（阈值按 2026-09-05 噪声实测校准：同代码 R1→R2 有 18修复/15回退 的随机翻转，
overall 二项标准误 ~1.7pp，text-table n=60 标准误 ~5pp，固定小阈值必然误报）：
- 新 run 存在可处理异常（judge_fail/exec_error）→ 直接红（先补判再谈分数）；
- overall 配对 bootstrap ΔCI 上界 < 0 且净降 ≥ 1pp → 红；
- 题型桶（n≥30）ΔCI 上界 < 0 → 红（显著性判据，小桶不用固定 pp 阈值）。
slow 只进观察单。回退题归因桶见 attribute()。
"""
import argparse
import json
import os
import random
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from open_ragbench import anomaly, common

BASELINE_DIR = common.REPO_ROOT / "data" / "evals" / "baseline"
BASELINE_POINTER = BASELINE_DIR / "baseline_run.json"
PREDICTION_KEEP = ("intent", "task_type", "strategy")  # 基线快照保留的 prediction 小字段
NET_REG_PP = 0.01  # 1pp


# ---------- run 加载与归一 ----------

def _parse_json_field(value):
    if isinstance(value, dict):
        return value
    if isinstance(value, str) and value.strip():
        try:
            parsed = json.loads(value)
            return parsed if isinstance(parsed, dict) else {}
        except ValueError:
            return {}
    return {}


def load_run(spec: str, db_path: Path, aichat_api: str = "") -> dict:
    """返回 {"run_id","dataset_id","status","details":[...]}，details 字段已解析为 dict。"""
    if spec == "baseline":
        pointer = common.load_json(BASELINE_POINTER)
        raw_path = (common.REPO_ROOT / pointer["raw"]).resolve()
        run = common.load_json(raw_path)
        run["_baseline_label"] = pointer.get("label", "baseline")
        return _normalize(run)
    if spec.endswith(".json") or Path(spec).exists():
        return _normalize(common.load_json(Path(spec)))
    return _normalize(_load_from_sqlite(db_path, spec))


def _load_from_sqlite(db_path: Path, run_id: str) -> dict:
    conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    run = dict(conn.execute("SELECT * FROM eval_run WHERE run_id=?", (run_id,)).fetchone())
    details = []
    for row in conn.execute(
        "SELECT question_id,status,quality,prediction,scores,all_scores,error,latency_ms "
        "FROM eval_run_detail WHERE run_id=? ORDER BY id", (run_id,),
    ):
        d = dict(row)
        for key in ("prediction", "scores", "all_scores"):
            d[key] = _parse_json_field(d.get(key))
        details.append(d)
    conn.close()
    if "summary_scores" in run:
        run.pop("summary_scores")
    return run


def _normalize(run: dict) -> dict:
    for d in run.get("details") or []:
        for key in ("prediction", "scores", "all_scores"):
            d[key] = _parse_json_field(d.get(key))
    return run


def question_map(run: dict) -> dict:
    """question_id -> 去重后详情（同题多行保留最后一条=最新）。"""
    out = {}
    for d in run.get("details") or []:
        out[str(d.get("question_id") or "")] = d
    return out


def passed(d: dict) -> bool:
    return d.get("quality") == "correct"


def failed(d: dict) -> bool:
    return d.get("quality") == "wrong"


def _answer(d: dict, key):
    return _parse_json_field(d.get("all_scores")).get("answer", {}).get(key)


def _retrieval(d: dict, key):
    return _parse_json_field(d.get("all_scores")).get("retrieval", {}).get(key)


def is_anomalous(d: dict) -> bool:
    types = anomaly.classify_detail(d, slow_ms=-1)
    return bool(set(types) & {anomaly.JUDGE_FAIL, anomaly.EXEC_ERROR})


# ---------- 过渡矩阵与归因 ----------

def transition_matrix(base_map: dict, new_map: dict):
    ids = sorted(set(base_map) & set(new_map))
    matrix = {"pp": [], "pf": [], "fp": [], "ff": [], "skip": []}
    anomalies = anomaly.detect(list(new_map.values()))
    actionable_ids = set()
    for ids_list in anomaly.actionable(anomalies).values():
        actionable_ids.update(ids_list)
    for qid in ids:
        b, n = base_map[qid], new_map[qid]
        if not (passed(b) or failed(b)) or not (passed(n) or failed(n)):
            matrix["skip"].append(qid)
        elif passed(b) and passed(n):
            matrix["pp"].append(qid)
        elif passed(b) and failed(n):
            matrix["fp"].append(qid)
        elif failed(b) and passed(n):
            matrix["pf"].append(qid)
        else:
            matrix["ff"].append(qid)
    return matrix, actionable_ids, anomalies


def attribute(qid: str, base: dict, new: dict) -> str:
    """新挂旧过题的归因桶（先基础设施、再检索、再作答行为、最后语义深浅）。"""
    if is_anomalous(new):
        return "infra_anomaly(先补判再归因)"
    b_hit5, n_hit5 = _retrieval(base, "hit@5_doc"), _retrieval(new, "hit@5_doc")
    if b_hit5 == 1 and n_hit5 == 0:
        return "retrieval_regression(hit@5丢失)"
    reason = str(_answer(new, "semantic_reason") or "")
    if "拒答" in reason or _answer(new, "has_answer") is False:
        return "refusal(该答却拒答/无答案)"
    b_pred, n_pred = _parse_json_field(base.get("prediction")), _parse_json_field(new.get("prediction"))
    for field in PREDICTION_KEEP:
        bv, nv = b_pred.get(field), n_pred.get(field)
        if bv and nv and bv != nv:
            return f"route_change({field}: {bv}→{nv})"
    sem = _answer(new, "semantic_score")
    if sem is None:
        return "no_semantic_eval(规则路径/缺评)"
    if sem >= 0.5:
        return "partial_coverage(0.5≤sem<过线)"
    if sem >= 0.2:
        return "wrong_conclusion(0.2≤sem<0.5)"
    return "severe_miss(sem<0.2)"


# ---------- 配对 bootstrap CI ----------

def paired_delta_ci(matrix: dict, resamples: int = 1000, seed: int = 42):
    """新-旧 正确率差的配对 bootstrap 95%CI：同题 (base, new) 成对重采样，保留题级相关性。"""
    pairs = []
    for key, base_val, new_val in (("pp", 1, 1), ("pf", 0, 1), ("fp", 1, 0), ("ff", 0, 0)):
        pairs += [(base_val, new_val)] * len(matrix[key])
    n = len(pairs)
    if n < 2:
        return None, None
    rnd = random.Random(seed)
    deltas = []
    for _ in range(resamples):
        diff = sum(new_v - base_v for base_v, new_v in (pairs[rnd.randrange(n)] for _ in range(n)))
        deltas.append(diff / n)
    deltas.sort()
    return deltas[int(0.025 * resamples)], deltas[min(int(0.975 * resamples), resamples - 1)]


def bucket_ci_by_source(matrix, base_map, new_map, manifest, resamples, seed):
    """按题型（manifest.source）分桶做配对 CI，题数 ≥30 的桶参与门禁。"""
    source_by_id = {q["uuid"]: q.get("source", "other") for q in manifest.get("questions", [])}
    per_source = {}
    for key in ("pp", "pf", "fp", "ff"):
        for qid in matrix[key]:
            per_source.setdefault(source_by_id.get(qid, "other"), {k: [] for k in ("pp", "pf", "fp", "ff")})[key].append(qid)
    out = {}
    for source, mat in per_source.items():
        n = sum(len(v) for v in mat.values())
        ci_lo, ci_hi = paired_delta_ci({k: v for k, v in mat.items()}, resamples=resamples, seed=seed) if n >= 2 else (None, None)
        delta = (len(mat["pf"]) - len(mat["fp"])) / n if n else None
        out[source] = {"n": n, "delta": round(delta, 4) if delta is not None else None,
                       "ci": (ci_lo, ci_hi) if ci_lo is not None else None, "gate": n >= 30}
    return out


# ---------- 门禁判定 ----------

def evaluate_gate(matrix, anomalies, overall_ci, overall_delta, bucket_cis):
    reasons = []
    pending = {k: v for k, v in anomalies.items() if k != anomaly.SLOW and v}
    if pending:
        reasons.append("新 run 存在未清零异常: " + ", ".join(f"{k}={len(v)}" for k, v in pending.items()))
    lo, hi = overall_ci
    if overall_delta is not None and overall_delta <= -NET_REG_PP and hi is not None and hi < 0:
        reasons.append(f"overall 净降 {overall_delta * 100:.2f}pp（95%CI 上界 {hi * 100:+.2f}pp < 0，显著）")
    for source, b in bucket_cis.items():
        if b["gate"] and b["ci"] and b["ci"][1] is not None and b["ci"][1] < 0 and (b["delta"] or 0) < 0:
            reasons.append(f"题型 {source} 显著回退（Δ{b['delta'] * 100:+.2f}pp，CI 上界 {b['ci'][1] * 100:+.2f}pp）")
    return reasons


# ---------- 主命令 ----------

def cmd_compare(args) -> int:
    base_run = load_run(args.base, Path(args.db))
    new_run = load_run(args.new, Path(args.db))
    base_map, new_map = question_map(base_run), question_map(new_run)
    matrix, _, anomalies = transition_matrix(base_map, new_map)
    lo, hi = paired_delta_ci(matrix, resamples=args.resamples)
    comparable = sum(len(matrix[k]) for k in ("pp", "pf", "fp", "ff"))
    delta = (len(matrix["pf"]) - len(matrix["fp"])) / comparable if comparable else None
    manifest = common.load_json(Path(args.manifest))
    bucket_cis = bucket_ci_by_source(matrix, base_map, new_map, manifest, args.resamples, seed=42)
    reasons = evaluate_gate(matrix, anomalies, (lo, hi), delta, bucket_cis)
    regressions = {qid: attribute(qid, base_map[qid], new_map[qid]) for qid in matrix["fp"]}

    base_label = base_run.get("_baseline_label") or base_run.get("run_id", "base")
    result = {
        "base": base_run.get("run_id"), "new": new_run.get("run_id"), "base_label": base_label,
        "matrix": {k: len(v) for k, v in matrix.items()},
        "comparable": comparable,
        "delta": round(delta, 4) if delta is not None else None,
        "delta_ci95": [round(lo, 4), round(hi, 4)] if lo is not None else None,
        "buckets": bucket_cis, "anomalies": {k: v for k, v in anomalies.items() if v},
        "regressions": regressions, "gate_red": bool(reasons), "gate_reasons": reasons,
    }
    lines = [
        f"# 回归对比：{new_run.get('run_id')} vs {base_label}",
        "",
        f"- 可比题数 {comparable}，Δ正确率 = {f'{delta * 100:+.2f}pp' if delta is not None else '—'}"
        + (f"（95%CI [{lo * 100:+.2f}, {hi * 100:+.2f}]pp）" if lo is not None else ""),
        f"- 过渡矩阵：双过 {len(matrix['pp'])}｜新修复 {len(matrix['pf'])}｜新回退 {len(matrix['fp'])}｜双挂 {len(matrix['ff'])}｜跳过 {len(matrix['skip'])}",
        "",
        "## 回退题归因（新挂旧过）",
        "",
    ]
    for qid, bucket in sorted(regressions.items(), key=lambda kv: kv[1]):
        lines.append(f"- `{qid[:8]}` {bucket}")
    lines += ["", "## 门禁", "", ("**RED**" if reasons else "**GREEN**")]
    for reason in reasons:
        lines.append(f"- {reason}")
    out_md = Path(args.out)
    out_md.write_text("\n".join(lines) + "\n", encoding="utf-8")
    common.save_json(out_md.with_suffix(".json"), result)
    status = "RED" if reasons else "GREEN"
    print(f"GATE {status}: {new_run.get('run_id')} vs {base_label} Δ{f'{delta * 100:+.2f}pp' if delta is not None else '—'}"
          + ("".join(f" | {r}" for r in reasons)))
    return 1 if reasons else 0


def cmd_pin(args) -> int:
    """把 raw run 裁剪成对比专用基线快照（去 prediction 大字段）并更新钉住指针。"""
    run = _normalize(common.load_json(Path(args.raw)))
    pruned_details = []
    for d in run.get("details") or []:
        pred = {k: d["prediction"].get(k) for k in PREDICTION_KEEP if d.get("prediction") and d["prediction"].get(k)}
        pruned_details.append({
            "question_id": d.get("question_id"), "status": d.get("status"), "quality": d.get("quality"),
            "scores": d.get("scores"), "all_scores": d.get("all_scores"),
            "error": d.get("error"), "latency_ms": d.get("latency_ms"), "prediction": pred,
        })
    BASELINE_DIR.mkdir(parents=True, exist_ok=True)
    raw_name = f"{run.get('dataset_id', 'run')}-{run.get('run_id')}.baseline.json"
    snapshot = {"run_id": run.get("run_id"), "dataset_id": run.get("dataset_id"),
                "status": run.get("status"), "details": pruned_details}
    common.save_json(BASELINE_DIR / raw_name, snapshot)
    common.save_json(BASELINE_POINTER, {
        "label": args.label or run.get("run_id"), "run_id": run.get("run_id"),
        "dataset_id": run.get("dataset_id"),
        "raw": str((BASELINE_DIR / raw_name).relative_to(common.REPO_ROOT)),
    })
    print("基线已钉住:", BASELINE_POINTER)
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="两次评测 run 逐题对比与回归门禁")
    sub = parser.add_subparsers(dest="cmd", required=True)
    cmp_parser = sub.add_parser("compare", help="对比两个 run 并出门禁（红=exit 1）")
    cmp_parser.add_argument("--base", default="baseline", help="baseline | raw json 路径 | run-xxx")
    cmp_parser.add_argument("--new", required=True, help="raw json 路径 | run-xxx")
    cmp_parser.add_argument("--out", required=True, help="对比报告 md 输出路径（同名 .json 一并输出）")
    cmp_parser.add_argument("--db", default=str(common.REPO_ROOT / "data" / "evals" / "evals.sqlite"))
    cmp_parser.add_argument("--manifest", default=str(common.SUBSET_DIR / "subset_manifest_v2.json"))
    cmp_parser.add_argument("--resamples", type=int, default=1000)
    cmp_parser.set_defaults(func=cmd_compare)
    pin_parser = sub.add_parser("pin", help="把 raw run 钉为基线（存裁剪快照 + 指针）")
    pin_parser.add_argument("--raw", required=True)
    pin_parser.add_argument("--label", default="")
    pin_parser.set_defaults(func=cmd_pin)
    args = parser.parse_args()
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
