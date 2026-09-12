"""两次评测 run 的逐题对比与回归门禁（CLI 薄壳）。

算法真相源在 evals_core.nightly.gate（服务内全内置流水线与这里共用同一实现），
本模块只保留：run 加载（baseline 快照 / raw json / evals.sqlite 三种形态）、
Markdown/JSON 落盘、基线 pin。门禁语义见 gate 模块 docstring。
"""
import argparse
import os
import sqlite3
import sys

from pathlib import Path

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from open_ragbench import common
from evals_core.nightly import gate as _gate

BASELINE_DIR = common.REPO_ROOT / "data" / "evals" / "baseline"
BASELINE_POINTER = BASELINE_DIR / "baseline_run.json"

# 算法真相源 re-export（保持既有调用面不变）
PREDICTION_KEEP = _gate.PREDICTION_KEEP
NET_REG_PP = _gate.NET_REG_PP
EVIDENCE_REASON_MAX = _gate.EVIDENCE_REASON_MAX
EVIDENCE_ANSWER_MAX = _gate.EVIDENCE_ANSWER_MAX
_parse_json_field = _gate.parse_json_field
question_map = _gate.question_map
passed = _gate.passed
failed = _gate.failed
is_anomalous = _gate.is_anomalous
attribute = _gate.attribute
evidence = _gate.evidence
paired_delta_ci = _gate.paired_delta_ci
bucket_ci_by_source = _gate.bucket_ci_by_source
evaluate_gate = _gate.evaluate_gate


def _normalize(run: dict) -> dict:
    return _gate.normalize_run(run)


def transition_matrix(base_map: dict, new_map: dict):
    """兼容旧调用面：返回 (matrix, actionable_ids, anomalies)。"""
    from open_ragbench import anomaly
    matrix, anomalies = _gate.transition_matrix(base_map, new_map)
    actionable_ids = set()
    for ids_list in anomaly.actionable(anomalies).values():
        actionable_ids.update(ids_list)
    return matrix, actionable_ids, anomalies


def load_run(spec: str, db_path: Path, aichat_api: str = "") -> dict:
    """返回 {"run_id","dataset_id","status","details":[...]}，details 字段已解析为 dict。

    spec 三选一："baseline"（钉住的快照）/ raw json 路径 / run-xxx（从 evals.sqlite 直读）。
    """
    if spec == "baseline":
        return _gate.load_baseline(BASELINE_DIR)
    if spec.endswith(".json") or Path(spec).exists():
        return _normalize(common.load_json(Path(spec)))
    return _normalize(_load_from_sqlite(db_path, spec))


def _load_from_sqlite(db_path: Path, run_id: str) -> dict:
    # 必须读写打开：WAL 模式库的只读 URI 连接在无法建 -shm 索引时（容器/跨用户权限，
    # 2026-09-12 钉基线实踩）会静默只读到已 checkpoint 的旧页——526 行明细读出 0 行，
    # 差点钉出空基线。query_only 保证连接行为仍是只读（写会直接报错）。
    conn = sqlite3.connect(str(db_path))
    conn.execute("PRAGMA query_only=ON")
    conn.row_factory = sqlite3.Row
    run = dict(conn.execute("SELECT * FROM eval_run WHERE run_id=?", (run_id,)).fetchone())
    details = []
    for row in conn.execute(
        "SELECT question_id,status,quality,prediction,scores,all_scores,error,latency_ms "
        "FROM eval_run_detail WHERE run_id=? ORDER BY id", (run_id,),
    ):
        d = dict(row)
        for key in ("prediction", "scores", "all_scores"):
            d[key] = _gate.parse_json_field(d.get(key))
        details.append(d)
    conn.close()
    # 非零校验：终态 run 报称有题却一行明细都没有 = 库状态可疑（WAL/权限/被清），宁可炸不可糊
    total = int(run.get("total_questions") or 0)
    if total and not details and str(run.get("status")) in ("completed", "cancelled", "failed"):
        raise RuntimeError(
            f"run {run_id} 状态 {run.get('status')}、total_questions={total}，但明细 0 行——"
            f"疑似 WAL 不可见或数据被清理，拒绝静默消费（拒绝产出空快照/空基线）")
    run.pop("summary_scores", None)
    # details 必须挂载返回：此前只 return run 本体（run 表无 details 列），CLI 用 run-xxx
    # 直读时永远拿到空明细 → 门禁矩阵空转绿灯（回归测试 test_compare_load 钉死此处）
    run["details"] = details
    return run


def render_gate_md(result: dict, new_run_id: str) -> str:
    m = result.get("matrix") or {}
    delta = result.get("delta")
    ci = result.get("delta_ci95") or (None, None)
    lo, hi = ci
    lines = [
        f"# 回归对比：{new_run_id} vs {result.get('base_label')}",
        "",
        f"- 可比题数 {result.get('comparable')}，Δ正确率 = {f'{delta * 100:+.2f}pp' if delta is not None else '—'}"
        + (f"（95%CI [{lo * 100:+.2f}, {hi * 100:+.2f}]pp）" if lo is not None else ""),
        f"- 过渡矩阵：双过 {m.get('pp')}｜新修复 {m.get('pf')}｜新回退 {m.get('fp')}｜双挂 {m.get('ff')}｜跳过 {m.get('skip')}",
        "",
        "## 回退题归因（新挂旧过）",
        "",
    ]
    for qid, bucket in sorted((result.get("regressions") or {}).items(), key=lambda kv: kv[1]):
        lines.append(f"- `{qid[:8]}` {bucket}")
    reasons = result.get("gate_reasons") or []
    lines += ["", "## 门禁", "", ("**RED**" if reasons else "**GREEN**")]
    for reason in reasons:
        lines.append(f"- {reason}")
    return "\n".join(lines) + "\n"


def cmd_compare(args) -> int:
    base_run = load_run(args.base, Path(args.db))
    new_run = load_run(args.new, Path(args.db))
    manifest = common.load_json(Path(args.manifest))
    result = _gate.compare_runs(base_run, new_run, manifest, resamples=args.resamples)
    out_md = Path(args.out)
    out_md.write_text(render_gate_md(result, str(new_run.get("run_id"))), encoding="utf-8")
    common.save_json(out_md.with_suffix(".json"), result)
    delta = result.get("delta")
    status = "RED" if result.get("gate_red") else "GREEN"
    print(f"GATE {status}: {new_run.get('run_id')} vs {result.get('base_label')} "
          f"Δ{f'{delta * 100:+.2f}pp' if delta is not None else '—'}"
          + ("".join(f" | {r}" for r in result.get("gate_reasons") or [])))
    return 1 if result.get("gate_red") else 0


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
    # raw 存仓库根相对路径且统一正斜杠（as_posix）：Windows 钉的基线会被拷到 Linux 服务器消费，
    # 原生分隔符会让服务端 Path().name 切不出文件名（2026-09-07 nightly 实踩）
    common.save_json(BASELINE_POINTER, {
        "label": args.label or run.get("run_id"), "run_id": run.get("run_id"),
        "dataset_id": run.get("dataset_id"),
        "raw": (BASELINE_DIR / raw_name).relative_to(common.REPO_ROOT).as_posix(),
    })
    print("基线已钉住:", BASELINE_POINTER)
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="nightly 逐题对比与回归门禁（算法在 evals_core.nightly.gate）")
    sub = parser.add_subparsers(dest="cmd", required=True)
    cmp_parser = sub.add_parser("compare", help="对比两个 run 并出门禁（红=exit 1）")
    cmp_parser.add_argument("--base", default="baseline", help="baseline | raw json 路径 | run-xxx")
    cmp_parser.add_argument("--new", required=True, help="raw json 路径 | run-xxx")
    cmp_parser.add_argument("--out", required=True, help="对比报告 md 输出路径（同名 .json 一并输出）")
    cmp_parser.add_argument("--db", default=str(common.REPO_ROOT / "data" / "evals" / "evals.sqlite"))
    cmp_parser.add_argument("--manifest", default=str(common.SUBSET_DIR / "subset_manifest_v2.json"))
    cmp_parser.add_argument("--resamples", type=int, default=1000)
    cmp_parser.set_defaults(func=cmd_compare)
    pin_parser = sub.add_parser("pin", help="钉住基线快照")
    pin_parser.add_argument("--raw", required=True)
    pin_parser.add_argument("--label", default="")
    pin_parser.set_defaults(func=cmd_pin)
    args = parser.parse_args()
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
