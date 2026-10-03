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

2026-09-29：断言逻辑收口进 evals_core.runner.probe_eval（UI 运行链路共用同一真相源），
本脚本只保留 CLI 外壳与进程内直调 docs_core 检索（题集仍读磁盘文件）。
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
    os.environ.setdefault("KNOWLEDGE_BASE_DIR", str(REPO / "data" / "knowledge"))


sys.path.insert(0, str(REPO / "services" / "evals-core" / "src"))
from evals_core.runner.probe_eval import run_probe_item  # noqa: E402


def _run_item(item: dict, retrieve, top_k: int) -> dict:
    """CLI 外壳：进程内直调检索后，断言全部交给 evals_core（与 UI 运行同一真相源）。"""
    r = retrieve_knowledge_local(item, retrieve, top_k)
    items = r.get("items") or []
    outcome = run_probe_item(item, items)
    return {
        "id": item["question_id"],
        "question": str(item.get("question"))[:44],
        "n_clause": outcome["n_clause"],
        "n_items": outcome["n_items"],
        "checks": outcome["checks"],
        "failed": outcome["failed"],
        "status": outcome["status"],
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
