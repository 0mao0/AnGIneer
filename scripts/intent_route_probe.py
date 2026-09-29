# -*- coding: utf-8 -*-
"""intent-router-v1 探针：意图分类路由层的断言（不跑检索、不跑生成、不跑判官）。

用法：
  python scripts/intent_route_probe.py                     # 跑 data/evals/datasets/intent-router-v1.json
  python scripts/intent_route_probe.py --tag run2          # 结果落盘 out.intent-router-v1.<tag>.json
  python scripts/intent_route_probe.py --dataset <path>    # 指定其它题集
  python scripts/intent_route_probe.py --model-only        # 只看「进分类模型」那批（排除规则前置题）

断言面（意图路由契约，见 evals_core.runner.intent_eval 模块头）：
  ① route【致命】—— 生产路由桶命中（agent_policy.build_attempts 实际优先级）
  ② level / mode  —— 记录项；仅当金标 strict_level / strict_mode=true 才致命
     route 由 (level, mode) 派生，同桶的 L3↔L4 混淆不改注入工具，故默认不记错。

分类器走生产同一条链（angineer_core.IntentClassifier + sop_core.SopLoader 算例），
断言逻辑复用 evals_core.runner.intent_eval（与 UI 运行链路同一真相源）。
退出码：存在 FAIL → 1，否则 0。
"""
import argparse
import json
import os
import statistics
import sys
from collections import Counter, defaultdict
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent


def _load_env() -> None:
    for line in (REPO / ".env").read_text(encoding="utf-8-sig", errors="replace").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip())


for _p in ("evals-core", "angineer-core", "ai-inference", "sop-core"):
    sys.path.insert(0, str(REPO / "services" / _p / "src"))

from evals_core.runner.intent_eval import run_intent_item  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dataset", default=str(REPO / "data/evals/datasets/intent-router-v1.json"))
    ap.add_argument("--out", default="")
    ap.add_argument("--tag", default="")
    ap.add_argument("--model-only", action="store_true",
                    help="只统计 rule_hit=model 的题（真正会进分类模型的那批）")
    args = ap.parse_args()

    _load_env()
    os.environ.setdefault("SOP_DATA_DIR", str(REPO / "data" / "sops"))
    from angineer_core import IntentClassifier  # noqa: E402
    from sop_core.sop_loader import SopLoader  # noqa: E402

    bundle = json.loads(Path(args.dataset).read_text(encoding="utf-8"))
    items = bundle["items"]
    dataset_id = bundle.get("dataset", {}).get("dataset_id", "intent-router-v1")

    sops = SopLoader(os.environ["SOP_DATA_DIR"]).load_all()
    classifier = IntentClassifier(sops)

    rows = []
    for it in items:
        if args.model_only and (it.get("intent") or {}).get("rule_hit") != "model":
            continue
        res = classifier.classify_intent(str(it.get("question") or ""), mode="instruct")
        predicted = {
            "level": getattr(res, "intent_level", None),
            "mode": getattr(res, "service_mode", None),
        }
        outcome = run_intent_item(it, predicted)
        rows.append({
            "id": it["question_id"],
            "question": str(it.get("question"))[:44],
            "family": outcome["family"],
            "trap": outcome["trap"],
            "rule_hit": (it.get("intent") or {}).get("rule_hit", ""),
            "gold_route": outcome["gold_route"],
            "got_route": outcome["got_route"],
            "level": outcome["checks"]["level"],
            "mode": outcome["checks"]["mode"],
            "checks": outcome["checks"],
            "failed": outcome["failed"],
            "status": outcome["status"],
        })

    n = len(rows)
    n_pass = sum(1 for r in rows if r["status"] == "PASS")
    n_xok = sum(1 for r in rows if r["status"] == "XFAIL-OK")
    n_xpass = sum(1 for r in rows if r["status"].startswith("XPASS"))
    n_fail = sum(1 for r in rows if r["status"] == "FAIL")
    route_ok = sum(1 for r in rows if r["checks"]["route"] == "ok")
    level_ok = sum(1 for r in rows if r["checks"]["level"] == "ok")
    mode_ok = sum(1 for r in rows if r["checks"]["mode"] == "ok")

    print(f"== {dataset_id}{'（仅 model 段）' if args.model_only else ''}：{n} 题")
    print(f"   route 正确 {route_ok}/{n} ({100*route_ok/max(n,1):.0f}%)  "
          f"level {level_ok}/{n}  mode {mode_ok}/{n}")
    print(f"   PASS {n_pass} / XFAIL-OK {n_xok} / XPASS {n_xpass} / FAIL {n_fail}")

    by_route = Counter((r["gold_route"], r["checks"]["route"] == "ok") for r in rows)
    print("\n   分 route 桶（正确/总数）:")
    for bucket in ("L0", "L1", "meta", "L2", "complex"):
        tot = sum(c for (b, _), c in by_route.items() if b == bucket)
        ok = sum(c for (b, good), c in by_route.items() if b == bucket and good)
        if tot:
            print(f"     {bucket:<8} {ok}/{tot}")

    fam_tot: Dict[str, list] = {}
    fam: dict = defaultdict(lambda: [0, 0])
    for r in rows:
        fam[r["family"]][1] += 1
        if r["checks"]["route"] == "ok":
            fam[r["family"]][0] += 1
    fam_tot = dict(fam)
    bad = {k: v for k, v in fam_tot.items() if v[0] < v[1]}
    if bad:
        print("\n   有失分的陷阱族:")
        for k, (ok, tot) in sorted(bad.items(), key=lambda kv: kv[1][0] - kv[1][1]):
            print(f"     {k:<22} {ok}/{tot}")

    if n_fail:
        print("\n   失败题明细:")
        for r in rows:
            if r["status"] == "FAIL":
                print(f"     [{r['family']:<20}] {r['id']:<18} gold={r['gold_route']} got={r['got_route']} "
                      f"| {r['checks']['route']} | {r['question']}")

    if args.out or args.tag:
        # 默认落 data/evals/probes/（data/ 不入 git，观测随卷留存；写仓库根会变 git 噪音）
        out = args.out or str(
            REPO / "data" / "evals" / "probes"
            / f"out.{dataset_id}{('.' + args.tag) if args.tag else ''}.json"
        )
        Path(out).parent.mkdir(parents=True, exist_ok=True)
        Path(out).write_text(json.dumps(rows, ensure_ascii=False, indent=1), encoding="utf-8")
        print("\n结果已写", out)
    return 1 if n_fail else 0


if __name__ == "__main__":
    raise SystemExit(main())
