"""候选集合对账报告（CLI 薄壳）——plan-ls-routing.md §5 施工主线第①项。

算法真相源在 evals_core.runner.recall_audit；本模块只做 run 选取、doc_catalog
matter 解析注入与打印/落盘。evals-core 核心不 import docs-core，目录映射在本壳完成：
resolver 按 question.library_id 查 docs-core FTS 库的 doc_catalog 表（只读），
查不到该库/该表时返回 None，对账自动降级 text_regex 正则并在 matter_source 如实标注。

用法（示例）：
  python scripts/recall_audit_report.py --latest --dataset harvey-firm-knowledge-v1
  python scripts/recall_audit_report.py --run-id <run_id> --backfill --show-missing 8
  python scripts/recall_audit_report.py --latest --json out.json
"""
from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
for _p in ("services/evals-core/src", "services/shared/src", "services/docs-core/src",
           "services/tree-core/src"):
    sys.path.insert(0, str(REPO / _p))

from evals_core.runner.recall_audit import compute_audit, summarize_audits  # noqa: E402
from evals_core.storage import result_store  # noqa: E402


class MatterResolverFactory:
    """按库缓存 doc_id→matter_id 映射（doc_catalog 只读；失败降级 None=正则 fallback）。"""

    def __init__(self) -> None:
        self._cache: dict = {}

    def for_library(self, library_id: str):
        if library_id in self._cache:
            return self._cache[library_id]
        mapping: dict = {}
        try:
            from docs_core.library_registry import resolve_index_db_path

            path = resolve_index_db_path(library_id)
            con = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
            try:
                rows = con.execute(
                    "select doc_id, matter_id from doc_catalog where library_id=? and matter_id<>''",
                    (library_id,),
                ).fetchall()
                mapping = {str(r[0]): str(r[1]) for r in rows}
            finally:
                con.close()
        except Exception:  # noqa: BLE001 —— 降级为正则 fallback，不阻断报告
            mapping = {}
        resolver = (lambda doc_id: mapping.get(doc_id)) if mapping else None
        self._cache[library_id] = resolver
        return resolver


def _pick_run(args) -> dict:
    if args.run_id:
        run = result_store.get_run(args.run_id)
        if not run:
            raise SystemExit(f"run 不存在: {args.run_id}")
        return run
    runs = [r for r in result_store.list_runs() if r.get("status") == "completed"]
    if args.dataset:
        runs = [r for r in runs if r.get("dataset_id") == args.dataset]
    if not runs:
        raise SystemExit("没有已完成的 run 可选")
    runs.sort(key=lambda r: str(r.get("started_at") or ""), reverse=True)
    return runs[0]


def main() -> int:
    parser = argparse.ArgumentParser(description="候选集合对账报告（算法在 evals_core.runner.recall_audit）")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--run-id", help="指定 run")
    group.add_argument("--latest", action="store_true", help="最近一个 completed run")
    parser.add_argument("--dataset", help="--latest 时按数据集过滤")
    parser.add_argument("--backfill", action="store_true", help="把对账结果写回 eval_run_detail.recall_audit 列")
    parser.add_argument("--show-missing", type=int, default=5, help="逐题表展示缺失金标前 N 个（默认 5）")
    parser.add_argument("--json", dest="json_out", help="逐题结果落盘 JSON 路径")
    args = parser.parse_args()

    run = _pick_run(args)
    run_id = run["run_id"]
    dataset_id = run.get("dataset_id") or ""
    print(f"run={run_id} dataset={dataset_id} started={run.get('started_at')}")
    if args.backfill:
        result_store.init_db()  # 幂等：确保 recall_audit 列已补齐（旧库 ALTER 兜底）

    questions = {str(q.get("question_id") or ""): q for q in result_store.list_questions(dataset_id)}
    factory = MatterResolverFactory()

    rows = []
    audits = []
    seen: set = set()
    for d in result_store.list_run_details(run_id):
        qid = str(d.get("question_id") or "")
        if qid in seen:  # 续跑残留重复行：与 _compute_summary 同口径取首条
            continue
        seen.add(qid)
        q = questions.get(qid, {})
        prediction = d.get("prediction")
        if not isinstance(prediction, dict):
            prediction = {}
        resolver = factory.for_library(str(q.get("library_id") or "")) if q else None
        audit = compute_audit(prediction, q, matter_resolver=resolver)
        audits.append(audit)
        if args.backfill:
            result_store.update_run_detail(run_id, qid, {"recall_audit": audit})
        rows.append({"question_id": qid, "audit": audit})

    summary = summarize_audits(audits)
    rec_dist: dict = {}
    for a in audits:
        k = str((a or {}).get("candidate_record") or "-")
        rec_dist[k] = rec_dist.get(k, 0) + 1
    print(
        f"\n对账汇总: audited={summary['audited']} full_recall={summary['full_recall']} "
        f"with_gap={summary['with_gap']} mean_recall={summary['mean_recall']} "
        f"no_machine_gold={summary['no_machine_gold']} audit_error={summary['audit_error']}\n"
        f"候选记录: {rec_dist}"
        + ("  [!] citations_only=召回下界（旧 run 只落了引用分配子集，非候选全集）"
           if rec_dist.get("citations_only") and not rec_dist.get("retrieved_items") else "")
    )
    header = (f"{'question_id':<28} {'unit':<7} {'hit/gold':<9} {'recall':<7} "
              f"{'cand':<5} {'rec_src':<13} {'src':<10} missing…")
    print("\n" + header)
    print("-" * len(header))
    for row in rows:
        a = row["audit"]
        rec_src = {"retrieved_items": "items", "citations_only": "cite-only"}.get(
            a.get("candidate_record"), str(a.get("candidate_record") or "-"))
        if a.get("status") != "ok":
            print(f"{row['question_id']:<28} {str(a.get('unit') or '-'):<7} "
                  f"{a.get('status') or '-':<9} {'-':<7} {a.get('candidates_n', 0):<5} "
                  f"{rec_src:<13} {'-':<10}")
            continue
        missing = ",".join(a.get("missing") or [][: args.show_missing]) if a.get("missing") else "-"
        print(
            f"{row['question_id']:<28} {a.get('unit') or '-':<7} "
            f"{a.get('hit')}/{a.get('gold_total'):<7} {a.get('recall'):<7} "
            f"{a.get('candidates_n', 0):<5} {rec_src:<13} {str(a.get('matter_source') or '-'):<10} {missing}"
        )
    if args.backfill:
        print(f"\n已回写 recall_audit 列（run={run_id}，{len(rows)} 题）")
    if args.json_out:
        Path(args.json_out).write_text(
            json.dumps({"run_id": run_id, "dataset_id": dataset_id, "summary": summary, "rows": rows},
                       ensure_ascii=False, indent=1),
            encoding="utf-8",
        )
        print("->", args.json_out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
