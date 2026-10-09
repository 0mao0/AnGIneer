"""修复「拒答标注前提过期」：open-ragbench 拒答集 6 题的源论文已在库（2026-09-21/09-23
两次语料扩充入库），标注静默过期 18 天——这 6 题在拒答集与主集同时被判「该拒没拒」。
诊断与裁决见 docs/report-refusal-premise-drift-20261009.md（业主 2026-10-09 拍板方案 A）。

动作：
  1) 主集 open-ragbench-subset-v4.1：6 题改回可答题——恢复公开集原始 gold
     （git 167f5820^ 的 refusal-v2 bundle，哨兵化之前的版本）、refusal_expected=false、
     tags 去掉 refusal、question_family 清空；**题不删**（题没错，是标注过期）。
  2) 拒答集（默认 open-ragbench-refusal-v3-39）：6 题整体摘除 → 33 题，保纯拒答语义
     （业主明确：不做「留集改判成混合集」）。
  3) bundle JSON（data/evals/datasets/*.json，git 跟踪、随部署同步到服务器）同改。
  4) eval_1：给 q_003/q_025/q_027 补 premise 元数据（keyword_zero_hit），
     供 nightly 前提对账核「前提词仍 0 命中」。

安全阀：改判前逐题确认源论文**确已在库**（refusal_premise.Sources.doc_present）；
前提仍成立的题拒绝改判——本地开发机语料只到 09-20 批次（117 篇），这 6 篇并不在，
所以本脚本**只该在生产环境落库**（本地仅用于 --bundles-only 同步仓库内 bundle）。

用法：
  # 生产（容器内跑，容器无 git → 由 --gold-file 传入原始 gold）
  python scripts/fix_refusal_premise_stale.py --gold-file /tmp/refusal_v2_orig.json          # dry-run
  python scripts/fix_refusal_premise_stale.py --gold-file /tmp/refusal_v2_orig.json --apply
  # 本地（只同步仓库内 bundle，不动本地库）
  python scripts/fix_refusal_premise_stale.py --bundles-only --open-ragbench force
  # 本地（只补 eval_1 的 premise 到本地库）
  python scripts/fix_refusal_premise_stale.py --skip-open-ragbench --no-bundles --apply
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
STALE_SET = set()  # 下面 STALE_QUESTIONS 装载后填充
for _p in (REPO / "services" / "evals-core" / "src", REPO / "services" / "docs-core" / "src"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

# 诊断报告里逐题核过的 6 道「前提过期」题（源论文已在生产库 lib-b07ed174）
STALE_QUESTIONS = [
    "refusal-516ff3fc-2870-49f1-a1eb-27210bedca0c",
    "refusal-65ff3ae6-47b4-4e31-80c5-7341fc222067",
    "refusal-8b29750f-d1a2-4fcb-be32-d1b88f953c69",
    "refusal-c3f45046-6e15-46fa-bc30-93e3724692d6",
    "refusal-de25d769-c672-4c8a-95c6-b77f9ec5d2a5",
    "refusal-db28bad3-1c66-4cf3-bed3-d7d7d7c3d85f",
]
STALE_SET = set(STALE_QUESTIONS)
MAIN_DATASET = "open-ragbench-subset-v4.1"
REFUSAL_DATASET = "open-ragbench-refusal-v3-39"
ORIGINAL_GOLD_REV = "167f5820^"  # 哨兵化提交的父提交：refusal-v2 bundle 仍带公开集事实答案
ORIGINAL_GOLD_PATH = "data/evals/datasets/open-ragbench-refusal-v2.json"
BUNDLES = REPO / "data" / "evals" / "datasets"

MAIN_NOTE = ("【2026-10-09 标注修正 6 题】refusal-516ff3fc/65ff3ae6/8b29750f/c3f45046/"
             "de25d769/db28bad3 的源论文已入库（09-21/09-23 语料扩充），恢复公开集 gold、"
             "refusal_expected=false（题不删；拒答语义由拒答集承载）。见 "
             "docs/report-refusal-premise-drift-20261009.md。")
REFUSAL_NOTE = ("【2026-10-09】剔除 6 道前提过期题（refusal-516ff3fc/65ff3ae6/8b29750f/"
                "c3f45046/de25d769/db28bad3 源论文已入库，已改判为可答题归主集）→ 39→33，"
                "保纯拒答语义。见 docs/report-refusal-premise-drift-20261009.md。")
EVAL1_PREMISES = {
    "q_003": {"kind": "keyword_zero_hit", "terms": ["引航锚地"]},
    "q_025": {"kind": "keyword_zero_hit", "terms": ["港口工程给水排水设计规范"]},
    "q_027": {"kind": "keyword_zero_hit", "terms": ["引航锚地"]},
}


def load_original_golds(gold_file: str) -> dict:
    """原始公开集答案（question_id -> gold_answer）：优先 --gold-file，其次 git 历史。"""
    if gold_file:
        bundle = json.loads(Path(gold_file).read_text(encoding="utf-8"))
    else:
        try:
            raw = subprocess.check_output(
                ["git", "show", f"{ORIGINAL_GOLD_REV}:{ORIGINAL_GOLD_PATH}"],
                cwd=str(REPO), stderr=subprocess.PIPE)
        except (subprocess.CalledProcessError, FileNotFoundError) as exc:
            raise SystemExit(f"读不到原始 gold（{ORIGINAL_GOLD_REV}:{ORIGINAL_GOLD_PATH}）：{exc}\n"
                             f"容器内无 git 时请用 --gold-file 传入该 bundle。")
        bundle = json.loads(raw.decode("utf-8"))
    out = {}
    for item in bundle.get("items") or []:
        ans = item.get("answer") or {}
        gold = str(ans.get("gold_answer") or "").strip()
        if ans.get("refusal_expected") and gold and "正确行为是拒答" not in gold:
            out[str(item.get("question_id"))] = gold
    return out


def _parse(raw, default):
    if isinstance(raw, (dict, list)):
        return raw
    try:
        return json.loads(raw) if raw else default
    except (TypeError, ValueError):
        return default


def _flip_item(item: dict, gold: str) -> dict:
    ans = dict(item.get("answer") or {})
    ans["gold_answer"] = gold
    ans["refusal_expected"] = False
    item = dict(item)
    item["answer"] = ans
    item["question_family"] = ""
    item["tags"] = [t for t in (item.get("tags") or []) if str(t) != "refusal"]
    return item


def _update_bundles(args, golds: dict, do_main: bool, do_refusal: bool, do_eval1: bool) -> None:
    apply = args.apply
    if do_main:
        mf = BUNDLES / f"{args.main_dataset}.json"
        if mf.exists():
            data = json.loads(mf.read_text(encoding="utf-8"))
            n = 0
            for i, item in enumerate(data.get("items") or []):
                if item.get("question_id") in STALE_SET and (item.get("answer") or {}).get("refusal_expected"):
                    data["items"][i] = _flip_item(item, golds[item["question_id"]])
                    n += 1
            ds = data.setdefault("dataset", {})
            if MAIN_NOTE not in str(ds.get("description") or ""):
                ds["description"] = (str(ds.get("description") or "") + MAIN_NOTE).strip()
            if apply:
                mf.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
            print(f"  bundle {mf.name}: 改判 {n} 题" + ("" if apply else "（dry-run）"))
    if do_refusal and args.refusal_dataset:
        rf = BUNDLES / f"{args.refusal_dataset}.json"
        if rf.exists():
            data = json.loads(rf.read_text(encoding="utf-8"))
            items = [it for it in (data.get("items") or []) if it.get("question_id") not in STALE_SET]
            removed = len(data.get("items") or []) - len(items)
            data["items"] = items
            ds = data.setdefault("dataset", {})
            ds["question_count"] = len(items)
            if REFUSAL_NOTE not in str(ds.get("description") or ""):
                ds["description"] = (str(ds.get("description") or "") + REFUSAL_NOTE).strip()
            if apply:
                rf.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
            print(f"  bundle {rf.name}: 摘除 {removed} 题 → {len(items)} 题" + ("" if apply else "（dry-run）"))
    if do_eval1:
        ef = BUNDLES / "eval_1.json"
        if ef.exists():
            data = json.loads(ef.read_text(encoding="utf-8"))
            n = 0
            for i, item in enumerate(data.get("items") or []):
                prem = EVAL1_PREMISES.get(str(item.get("question_id")))
                ans = item.get("answer") or {}
                if prem and ans.get("refusal_expected") and ans.get("premise") != prem:
                    ans = dict(ans)
                    ans["premise"] = prem
                    item = dict(item)
                    item["answer"] = ans
                    data["items"][i] = item
                    n += 1
            if apply and n:
                ef.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
            print(f"  bundle {ef.name}: 补 premise {n} 题" + ("" if apply else "（dry-run）"))


def main() -> int:
    ap = argparse.ArgumentParser(description="修复拒答标注前提过期（6 题）")
    ap.add_argument("--apply", action="store_true", help="真正写入；缺省只做 dry-run")
    ap.add_argument("--db", default="", help="evals.sqlite 路径；缺省用 result_store 默认")
    ap.add_argument("--gold-file", default="", help="原始 refusal-v2 bundle（容器内无 git 时用）")
    ap.add_argument("--main-dataset", default=MAIN_DATASET)
    ap.add_argument("--refusal-dataset", default=REFUSAL_DATASET)
    ap.add_argument("--skip-eval1", action="store_true")
    ap.add_argument("--open-ragbench", choices=("auto", "skip", "force"), default="auto",
                    help="主集/拒答集的库动作：auto=前置校验不过就中止；skip=只跳这两项；force=跳过校验")
    ap.add_argument("--bundles-only", action="store_true", help="只改 bundle JSON，不碰 DB")
    ap.add_argument("--no-bundles", action="store_true", help="不改 bundle JSON")
    args = ap.parse_args()

    from evals_core.nightly import refusal_premise as rp

    golds = load_original_golds(args.gold_file)
    missing = [q for q in STALE_QUESTIONS if q not in golds]
    if missing:
        raise SystemExit(f"原始 gold 缺 {len(missing)} 题：{missing}")

    db_path = args.db
    if not args.bundles_only and not db_path:
        from evals_core.storage import result_store
        db_path = str(result_store._DB_PATH)
    print(f"模式: {'bundles-only' if args.bundles_only else 'DB+bundles'}"
          f" | open-ragbench={args.open_ragbench} | db={db_path or '—'}"
          f" | bundles={'跳过' if args.no_bundles else BUNDLES}")

    conn = None
    guard_ok = args.open_ragbench == "force"
    if not args.bundles_only:
        import sqlite3
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        if args.open_ragbench != "skip":
            src = rp.Sources()
            rows = conn.execute(
                f"SELECT question_id, library_id, tags, answer_gold FROM eval_question "
                f"WHERE question_id IN ({','.join('?' * len(STALE_QUESTIONS))}) AND dataset_id=?",
                (*STALE_QUESTIONS, args.main_dataset)).fetchall()
            found = {r["question_id"]: dict(r) for r in rows}
            if len(found) != len(STALE_QUESTIONS):
                raise SystemExit(f"{args.main_dataset} 里只找到 {len(found)}/6 题，停止")
            present = {}
            for qid, r in found.items():
                prem = rp.resolve_premises(_parse(r["answer_gold"], {}), _parse(r["tags"], []))
                doc = next((p.get("doc") for p in prem if p.get("kind") == "doc_absent"), "")
                hit = src.doc_present(r["library_id"], doc) if doc else None
                if not hit:
                    print(f"!! {qid} 的源论文（{doc}）不在本环境库——前提仍成立，拒绝对它改判。")
                    print("   生产环境才有这 6 篇（09-21/09-23 扩充）；本地请用 --bundles-only，"
                          "或显式 --open-ragbench skip 只补 eval_1。")
                    raise SystemExit(2)
                present[qid] = hit
            print("前置校验通过：6 题源论文均已在库 →",
                  {q.split('-')[1][:8]: v for q, v in present.items()})
            guard_ok = True

    # ---- 动作 1：主集 6 题改判 ----
    if conn is not None and guard_ok:
        n = 0
        for qid in STALE_QUESTIONS:
            row = conn.execute("SELECT answer_gold, tags FROM eval_question WHERE dataset_id=? "
                               "AND question_id=?", (args.main_dataset, qid)).fetchone()
            gold_raw = _parse(row["answer_gold"], {}) if row else {}
            if not gold_raw.get("refusal_expected"):
                print(f"  [skip] {qid} 已是可答题（幂等）")
                continue
            n += 1
            print(f"  [flip] {qid} → gold=「{golds[qid][:36]}…」refusal_expected=false")
            if args.apply:
                item = _flip_item({"answer": gold_raw, "tags": _parse(row["tags"], [])}, golds[qid])
                conn.execute(
                    "UPDATE eval_question SET answer_gold=?, tags=?, question_family='' "
                    "WHERE dataset_id=? AND question_id=?",
                    (json.dumps(item["answer"], ensure_ascii=False),
                     json.dumps(item["tags"], ensure_ascii=False), args.main_dataset, qid))
        if args.apply and n:
            desc_row = conn.execute("SELECT description FROM eval_dataset WHERE dataset_id=?",
                                    (args.main_dataset,)).fetchone()
            desc = str(desc_row["description"] or "") if desc_row else ""
            if MAIN_NOTE not in desc:
                conn.execute("UPDATE eval_dataset SET description=?, updated_at=datetime('now') "
                             "WHERE dataset_id=?", ((desc + MAIN_NOTE).strip(), args.main_dataset))
            conn.commit()

    # ---- 动作 2：拒答集摘除 6 题 ----
    if conn is not None and guard_ok and args.refusal_dataset:
        before = conn.execute("SELECT COUNT(*) FROM eval_question WHERE dataset_id=?",
                              (args.refusal_dataset,)).fetchone()[0]
        hit = conn.execute(
            f"SELECT COUNT(*) FROM eval_question WHERE dataset_id=? AND question_id IN "
            f"({','.join('?' * len(STALE_QUESTIONS))})",
            (args.refusal_dataset, *STALE_QUESTIONS)).fetchone()[0]
        if before:
            print(f"  拒答集 {args.refusal_dataset}: {before} → {before - hit} 题（命中 6 题中 {hit} 个）")
        if args.apply and hit:
            conn.execute(
                f"DELETE FROM eval_question WHERE dataset_id=? AND question_id IN "
                f"({','.join('?' * len(STALE_QUESTIONS))})",
                (args.refusal_dataset, *STALE_QUESTIONS))
            ds = conn.execute("SELECT description FROM eval_dataset WHERE dataset_id=?",
                              (args.refusal_dataset,)).fetchone()
            desc = str(ds["description"] or "") if ds else ""
            if REFUSAL_NOTE not in desc:
                desc = (desc + REFUSAL_NOTE).strip()
            conn.execute("UPDATE eval_dataset SET title=?, description=?, question_count=?, "
                         "updated_at=datetime('now') WHERE dataset_id=?",
                         (f"拒答 {before - hit} 题", desc, before - hit, args.refusal_dataset))
            conn.commit()

    # ---- 动作 4：eval_1 补 premise ----
    if conn is not None and not args.skip_eval1:
        for qid, prem in EVAL1_PREMISES.items():
            row = conn.execute("SELECT answer_gold FROM eval_question WHERE dataset_id='eval_1' "
                               "AND question_id=?", (qid,)).fetchone()
            if not row:
                continue
            gold = _parse(row["answer_gold"], {})
            if gold.get("premise") == prem:
                print(f"  [skip] eval_1/{qid} premise 已就位（幂等）")
                continue
            if not gold.get("refusal_expected"):
                print(f"  [warn] eval_1/{qid} 非拒答题，跳过")
                continue
            print(f"  [premise] eval_1/{qid} += {prem}")
            if args.apply:
                gold = dict(gold)
                gold["premise"] = prem
                conn.execute("UPDATE eval_question SET answer_gold=? WHERE dataset_id='eval_1' "
                             "AND question_id=?", (json.dumps(gold, ensure_ascii=False), qid))
        if args.apply:
            conn.commit()

    # ---- 动作 3：bundle JSON ----
    if not args.no_bundles:
        if args.bundles_only:
            _update_bundles(args, golds, True, bool(args.refusal_dataset), not args.skip_eval1)
        elif guard_ok or args.open_ragbench == "skip":
            _update_bundles(args, golds, guard_ok, guard_ok and bool(args.refusal_dataset),
                            not args.skip_eval1)

    # ---- 复核 ----
    if conn is not None:
        after_main = conn.execute(
            f"SELECT COUNT(*) FROM eval_question WHERE dataset_id=? AND question_id IN "
            f"({','.join('?' * len(STALE_QUESTIONS))}) AND answer_gold LIKE '%\"refusal_expected\": true%'",
            (args.main_dataset, *STALE_QUESTIONS)).fetchone()[0]
        line = f"复核：主集 6 题仍标拒答 {after_main} 个"
        if args.refusal_dataset:
            left = conn.execute(
                f"SELECT COUNT(*) FROM eval_question WHERE dataset_id=? AND question_id IN "
                f"({','.join('?' * len(STALE_QUESTIONS))})",
                (args.refusal_dataset, *STALE_QUESTIONS)).fetchone()[0]
            total = conn.execute("SELECT COUNT(*) FROM eval_question WHERE dataset_id=?",
                                 (args.refusal_dataset,)).fetchone()[0]
            line += f"；拒答集残留 {left} 个、当前 {total} 题"
        print(line)
        conn.close()
    print("完成（dry-run）" if not args.apply else "已写入")
    return 0


if __name__ == "__main__":
    sys.exit(main())
