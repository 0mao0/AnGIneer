# -*- coding: utf-8 -*-
"""clause-probe-v1 探针：条款号直达路的路由层+检索层断言（不跑判官、不跑生成）。

用法：
  python scripts/clause_probe.py                  # 跑 data/evals/datasets/clause-probe-v1.json
  python scripts/clause_probe.py --out /tmp/x.json  # 结果落盘
  python scripts/clause_probe.py --dataset <path>   # 指定其它题集

断言面（clause_resolver 契约，89735bb）：
  ① 路由层：clause_direct 项应出现/不应出现——
    公式号屏蔽（mask_formula_number_spans）、上下文门控（第/条/款/表/图/三段裸号）、
    点名限域（P1-1：《规范名》/标准号 → 只出该文档）、主题守卫（P1-2：全零重合判无效）
  ② 检索层：金标条款块整体位次（precise_rank_max）、条款组首位文档（top_clause_docs）

xfail 题为已知缺口（2026-09-28：「式（6.2.8）」括号形态漏屏蔽）：
  行为与预期相反 → XFAIL-OK（缺口仍在）；行为与预期一致 → XPASS（缺口已修，请摘除 xfail 标记）。
退出码：存在 FAIL → 1，否则 0。
"""
import argparse
import json
import os
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent


def _load_env() -> None:
    for line in (REPO / ".env").read_text(encoding="utf-8-sig", errors="replace").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip())
    os.environ.setdefault("KNOWLEDGE_BASE_DIR", str(REPO / "data" / "knowledge_base"))


def _is_clause_item(e: dict) -> bool:
    pol = str(e.get("retrieval_policy") or "")
    md = e.get("metadata") or {}
    if "clause" in pol or str(md.get("source_kind") or "") == "clause_direct":
        return True
    fs = md.get("fusion_sources") or []
    if isinstance(fs, str):
        fs = fs.split(",")
    return "clause" in [str(x).strip() for x in fs]


def _run_item(item: dict, retrieve, top_k: int) -> dict:
    probe = item.get("probe") or {}
    expect_clause = bool(probe.get("expect_clause_direct"))
    xfail = bool(probe.get("xfail"))
    r = retrieve_knowledge_local(item, retrieve, top_k)
    items = r.get("items") or []
    clause_items = [e for e in items if _is_clause_item(e)]
    checks: dict = {}

    # ① 路由层：直达是否按预期出现
    checks["clause_direct"] = "ok" if bool(clause_items) == expect_clause else (
        f"实际={'有' if clause_items else '无'} 期望={'有' if expect_clause else '无'}")

    if clause_items:
        # P1-1 限域：所有直达项必须出自点名文档
        restricted = probe.get("restricted_doc")
        if restricted:
            bad = sorted({str(e.get("doc_id")) for e in clause_items} - {restricted})
            checks["restricted_doc"] = "ok" if not bad else f"混入 {bad}"
        # P0-2 主题加权：条款组首位必须出自期望文档
        top_docs = probe.get("top_clause_docs")
        if top_docs:
            first_doc = str(clause_items[0].get("doc_id"))
            checks["top_clause_doc"] = "ok" if first_doc in top_docs else f"首位 {first_doc} ∉ {top_docs}"
        # ② 检索层：金标条款块整体位次
        gold_num = probe.get("gold_num")
        gold_docs = probe.get("gold_doc_for_num") or []
        if gold_num and gold_docs:
            rank = next(
                (i for i, e in enumerate(items, 1)
                 if _is_clause_item(e) and str(e.get("doc_id")) in gold_docs
                 and gold_num in str(e.get("text") or "")),
                None,
            )
            limit = int(probe.get("precise_rank_max") or 0)
            if rank is None:
                checks["precise_rank"] = f"金标条款块（{gold_num}）未进 top-{len(items)}"
            elif limit and rank > limit:
                checks["precise_rank"] = f"位次 {rank} > 上限 {limit}"
            else:
                checks["precise_rank"] = f"ok(rank={rank})"

    failed = [k for k, v in checks.items()
              if v != "ok" and not str(v).startswith("ok(")]
    if xfail:
        # xfail 语义：checks 挂 = 缺口仍在（XFAIL-OK）；全过 = 缺口已修（XPASS，应摘除 xfail 标记）
        status = "XFAIL-OK" if failed else "XPASS(请摘xfail)"
    else:
        status = "FAIL" if failed else "PASS"
    return {
        "id": item["question_id"],
        "question": str(item.get("question"))[:44],
        "n_clause": len(clause_items),
        "n_items": len(items),
        "checks": checks,
        "failed": failed,
        "status": status,
    }


def retrieve_knowledge_local(item: dict, retrieve, top_k: int) -> dict:
    return retrieve(
        query=str(item.get("question")),
        library_id=str(item.get("library_id") or "default"),
        doc_ids=[],
        top_k=top_k,
        task_type="definition",
        mode="text",
    )


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dataset", default=str(REPO / "data/evals/datasets/clause-probe-v1.json"))
    ap.add_argument("--out", default="")
    ap.add_argument("--top-k", type=int, default=20)
    args = ap.parse_args()

    _load_env()
    sys.path.insert(0, str(REPO / "services" / "docs-core" / "src"))
    from docs_core.step09_query.retrieve_service import retrieve_knowledge  # noqa: E402

    data = json.loads(Path(args.dataset).read_text(encoding="utf-8"))
    rows = [_run_item(it, retrieve_knowledge, args.top_k) for it in data["items"]]

    n_fail = sum(1 for r in rows if r["status"] == "FAIL")
    n_pass = sum(1 for r in rows if r["status"] == "PASS")
    n_xok = sum(1 for r in rows if r["status"] == "XFAIL-OK")
    n_xpass = sum(1 for r in rows if r["status"].startswith("XPASS"))

    for r in rows:
        det = "; ".join(f"{k}:{v}" for k, v in r["checks"].items())
        print(f"[{r['status']:>12}] {r['id']:<26} clause={r['n_clause']:>2}/{r['n_items']:<2} {det}")
    print(f"== 汇总：PASS {n_pass} / XFAIL-OK {n_xok} / XPASS {n_xpass} / FAIL {n_fail}（共 {len(rows)}）")

    if args.out:
        Path(args.out).write_text(json.dumps(rows, ensure_ascii=False, indent=1), encoding="utf-8")
        print("结果已写", args.out)
    return 1 if n_fail else 0


if __name__ == "__main__":
    raise SystemExit(main())
