# -*- coding: utf-8 -*-
"""表型回归集 · 语料对账：夹具快照 vs 现库（重解析后夹具是否过期）。

用法: python services/angineer-core/tests/fixtures/check_table_type_regression_drift.py
输出: 每表 OK / DIFF（DIFF 时打印首个差异字段），末尾汇总。
"""
import os
import sys
import json

ROOT = "D:/AI/AnGIneer"
os.chdir(ROOT)
os.environ.setdefault("ANGINEER_DATA_ROOT", ROOT + "/data")
sys.path[:0] = [f"{ROOT}/services/{p}/src" for p in
                ("angineer-core", "docs-core", "sop-core", "engtools", "ai-inference")]

from docs_core.docs_service import docs_service

FIXTURE = "services/angineer-core/tests/fixtures/table_type_regression_v1.json"
LIB = "std-water"

fx = json.load(open(FIXTURE, encoding="utf-8"))
store = docs_service._canonical_store_for(LIB)

ok = diff = missing = 0
for t in fx["tables"]:
    doc_id = t["doc_id"]
    cur = next((x for x in store.list_tables(doc_id, limit=500) if x.table_id == t["table_id"]), None)
    if cur is None:
        missing += 1
        print(f"[MISSING] {t['table_id']} {t['title'][:50]} —— 库里已无此表（重解析换 id？）")
        continue
    problems = []
    for field, now in (("title", cur.title), ("header_rows", cur.header_rows), ("body_rows", cur.body_rows)):
        old = t[field]
        if json.dumps(old, ensure_ascii=False, sort_keys=True) != json.dumps(now, ensure_ascii=False, sort_keys=True):
            problems.append(field)
    if problems:
        diff += 1
        print(f"[DIFF] {t['table_id']} 差异字段: {problems}")
        for f in problems[:1]:
            print("   夹具:", json.dumps(t[f], ensure_ascii=False)[:200])
            print("   现库:", json.dumps(getattr(cur, f), ensure_ascii=False)[:200])
    else:
        ok += 1
        print(f"[OK]   {t['table_id']} {t['title'][:50]}")

print(f"\n合计 {len(fx['tables'])} 表：OK={ok} DIFF={diff} MISSING={missing}")
if diff or missing:
    print("→ 夹具过期：重跑 services/angineer-core/tests/fixtures/build_table_type_regression.py 前先核 baseline 是否仍是当前行为。")
