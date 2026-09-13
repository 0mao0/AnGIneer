"""回归门禁（算法真相源，scripts/open_ragbench/compare_runs.py 的 CLI 复用本模块）。

对比对象必须是钉住的基线（不和"上一次 run"比——缓慢漂移会被逐轮消化）。
阈值按 2026-09-05 噪声实测校准：同代码有 18修复/15回退 的随机翻转，overall 二项
标准误 ~1.7pp——固定小阈值必然误报，一律用配对 bootstrap CI 判显著。
"""
import json
import random
from pathlib import Path
from typing import Optional, Tuple

from evals_core.runner import anomaly

PREDICTION_KEEP = ("intent", "task_type", "strategy")  # 基线快照保留的 prediction 小字段
NET_REG_PP = 0.01  # 1pp
EVIDENCE_REASON_MAX = 160
EVIDENCE_ANSWER_MAX = 260


def parse_json_field(value):
    if isinstance(value, dict):
        return value
    if isinstance(value, str) and value.strip():
        try:
            parsed = json.loads(value)
            return parsed if isinstance(parsed, dict) else {}
        except ValueError:
            return {}
    return {}


def normalize_run(run: dict) -> dict:
    for d in run.get("details") or []:
        for key in ("prediction", "scores", "all_scores"):
            d[key] = parse_json_field(d.get(key))
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
    return parse_json_field(d.get("all_scores")).get("answer", {}).get(key)


def _retrieval(d: dict, key):
    return parse_json_field(d.get("all_scores")).get("retrieval", {}).get(key)


def is_anomalous(d: dict) -> bool:
    types = anomaly.classify_detail(d, slow_ms=-1)
    return bool(set(types) & {anomaly.JUDGE_FAIL, anomaly.EXEC_ERROR})


def load_baseline(baseline_dir: Optional[Path] = None) -> dict:
    """读钉住的基线快照（baseline_run.json 指针 + 快照文件）。

    基线是**运行时状态、不进版本控制**（2026-09-13 实踩：指针被 git 跟踪 → 部署 reset 抹掉
    刚 pin 的 R3，nightly 拿旧基线跑出假绿灯）。缺指针时报可操作错误而非裸 FileNotFoundError；
    指针与快照缺失各自给不同的引导语（前者=没钉过/被删，后者=快照文件没随行）。
    """
    from . import paths
    base_dir = Path(baseline_dir) if baseline_dir else paths.baseline_dir()
    pointer_path = base_dir / "baseline_run.json"
    if not pointer_path.exists():
        raise FileNotFoundError(
            f"基线指针不存在: {pointer_path}（该环境还没有钉住基线；"
            f"用 scripts/open_ragbench/compare_runs.py pin --raw <run快照> --label <标签> 钉一份）")
    pointer = json.loads(pointer_path.read_text(encoding="utf-8"))
    # raw 可能是 Windows 机器钉的（"data\evals\baseline\..."）：POSIX Path 不切反斜杠，
    # 直接 .name 会把整串当文件名拼出双重路径（2026-09-07 nightly 实踩 FileNotFoundError），先归一化分隔符
    raw = str(pointer.get("raw", "")).replace("\\", "/")
    raw_name = Path(raw).name
    snapshot_path = base_dir / raw_name
    if not snapshot_path.exists():
        raise FileNotFoundError(
            f"基线快照不存在: {snapshot_path}（指针 run_id={pointer.get('run_id')} "
            f"label={pointer.get('label')!r} 指向的快照文件缺失，需重新 pin）")
    snapshot = json.loads(snapshot_path.read_text(encoding="utf-8"))
    snapshot["_baseline_label"] = pointer.get("label", "baseline")
    return normalize_run(snapshot)


# ---------- 过渡矩阵与归因 ----------

def transition_matrix(base_map: dict, new_map: dict):
    ids = sorted(set(base_map) & set(new_map))
    matrix = {"pp": [], "pf": [], "fp": [], "ff": [], "skip": []}
    anomalies = anomaly.detect_anomalies(list(new_map.values()))
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
    return matrix, anomalies


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
    b_pred, n_pred = parse_json_field(base.get("prediction")), parse_json_field(new.get("prediction"))
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


def evidence(base: dict, new: dict) -> dict:
    """回退题的逐题前后对比证据（站点展开查看用，字段全部可缺省，永不抛）。"""
    ev: dict = {}
    b_pred, n_pred = parse_json_field(base.get("prediction")), parse_json_field(new.get("prediction"))
    route = {}
    for field in PREDICTION_KEEP:
        bv, nv = b_pred.get(field), n_pred.get(field)
        if bv and nv and bv != nv:
            route[field] = {"base": bv, "new": nv}
    if route:
        ev["route"] = route
    retrieval = {}
    for key in ("hit@5_doc", "citation_hit"):
        bv, nv = _retrieval(base, key), _retrieval(new, key)
        if bv is not None or nv is not None:
            retrieval[key] = {"base": bv, "new": nv}
    if retrieval:
        ev["retrieval"] = retrieval
    b_sem, n_sem = _answer(base, "semantic_score"), _answer(new, "semantic_score")
    if b_sem is not None or n_sem is not None:
        ev["semantic"] = {"base": b_sem, "new": n_sem, "threshold": _answer(new, "semantic_threshold")}
    b_ha, n_ha = _answer(base, "has_answer"), _answer(new, "has_answer")
    if b_ha is not None and b_ha != n_ha:
        ev["has_answer"] = {"base": b_ha, "new": n_ha}
    reason = str(_answer(new, "semantic_reason") or "")[:EVIDENCE_REASON_MAX]
    if reason:
        ev["reason"] = reason
    excerpt = str(n_pred.get("answer") or "")[:EVIDENCE_ANSWER_MAX]
    if excerpt:
        ev["answer_excerpt"] = excerpt
    if new.get("error"):
        ev["error"] = str(new["error"])[:EVIDENCE_REASON_MAX]
    return ev


# ---------- 配对 bootstrap CI ----------

def paired_delta_ci(matrix: dict, resamples: int = 1000, seed: int = 42) -> Tuple[Optional[float], Optional[float]]:
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


def compare_runs(base_run: dict, new_run: dict, manifest: dict, resamples: int = 1000, seed: int = 42) -> dict:
    """两次 run（details 字段须为 dict，见 normalize_run）→ 门禁结论 dict（键与旧 gate.json 一致）。"""
    base_map, new_map = question_map(base_run), question_map(new_run)
    matrix, anomalies = transition_matrix(base_map, new_map)
    lo, hi = paired_delta_ci(matrix, resamples=resamples, seed=seed)
    comparable = sum(len(matrix[k]) for k in ("pp", "pf", "fp", "ff"))
    delta = (len(matrix["pf"]) - len(matrix["fp"])) / comparable if comparable else None
    bucket_cis = bucket_ci_by_source(matrix, base_map, new_map, manifest, resamples, seed)
    reasons = evaluate_gate(matrix, anomalies, (lo, hi), delta, bucket_cis)
    regressions = {qid: attribute(qid, base_map[qid], new_map[qid]) for qid in matrix["fp"]}
    base_label = base_run.get("_baseline_label") or base_run.get("run_id", "base")
    return {
        "base": base_run.get("run_id"), "new": new_run.get("run_id"), "base_label": base_label,
        "matrix": {k: len(v) for k, v in matrix.items()},
        "comparable": comparable,
        "delta": round(delta, 4) if delta is not None else None,
        "delta_ci95": [round(lo, 4), round(hi, 4)] if lo is not None else None,
        "buckets": bucket_cis, "anomalies": {k: v for k, v in anomalies.items() if v},
        "regressions": regressions, "fixed": sorted(matrix["pf"]),
        "regression_details": {qid: evidence(base_map[qid], new_map[qid]) for qid in matrix["fp"]},
        "gate_red": bool(reasons), "gate_reasons": reasons,
    }
