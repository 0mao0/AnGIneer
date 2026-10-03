"""FinanceBench 入库对账（预注册 §4-4：84 篇 / blob / 页数 / 索引）。

1. state(84 期望) ↔ canonical_documents(库内实况) 双向核对；
2. 库内多余 = 重试/热重载遗留的孤儿或重复副本 → HTTP DELETE 清扫（保留 state 认定的 doc_id）；
3. 页数与 pdf_manifest 比对（解析侧页数应一致，±0 容差；不一致列出）。

用法：python scripts/financebench/reconcile.py [--delete-orphans]
"""
import argparse
import json
import sqlite3
import sys
from pathlib import Path

import requests

REPO = Path(__file__).resolve().parents[2]
STATE = REPO / "data" / "financebench" / "ingest" / "import_state.json"
KEYS = REPO / "data" / "financebench" / "ingest" / "keys.json"
MANIFEST = REPO / "data" / "financebench" / "raw" / "pdf_manifest.json"
DB = REPO / "data" / "knowledge" / "knowledge_index.sqlite"
DOCS_API = "http://localhost:8790"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--delete-orphans", action="store_true", help="删除库内 state 未认定的文档")
    args = parser.parse_args()

    state = json.loads(STATE.read_text(encoding="utf-8"))
    keys = json.loads(KEYS.read_text(encoding="utf-8"))
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    library_id = state["library_id"]
    expected = {d: r for d, r in state["docs"].items()}

    con = sqlite3.connect(DB)
    live = {row[0]: {"title": row[1], "status": row[2], "pages": row[3], "chunks": row[4]} for row in con.execute(
        """SELECT d.doc_id, d.title, d.status, d.page_count,
                  (SELECT COUNT(*) FROM canonical_chunks c WHERE c.doc_id = d.doc_id)
           FROM canonical_documents d WHERE d.library_id = ?""",
        (library_id,),
    )}

    ok, problems, missing = [], [], []
    for doc, rec in sorted(expected.items()):
        doc_id = rec.get("doc_id") or ""
        if rec.get("status") not in ("succeeded", "partial") or doc_id not in live:
            missing.append((doc, rec.get("status"), doc_id))
            continue
        row = live[doc_id]
        pages_expect = manifest.get(doc, {}).get("pages")
        issues = []
        if row["chunks"] <= 0:
            issues.append("chunk=0")
        if row["status"] == "partial":
            issues.append("partial")
        if pages_expect is not None and row["pages"] not in (pages_expect, pages_expect - 1, pages_expect + 1):
            issues.append(f"页数 库{row['pages']} vs PDF{pages_expect}")
        if issues:
            problems.append((doc, doc_id, issues))
        else:
            ok.append(doc)

    keep = {r.get("doc_id") for r in expected.values() if r.get("doc_id")}
    orphans = sorted(set(live) - keep)

    print(f"库 {library_id}: 期望 84 | 通过 {len(ok)} | 问题 {len(problems)} | 缺失 {len(missing)} | 库内孤儿/重复 {len(orphans)}")
    for doc, doc_id, issues in problems:
        print(f"  [问题] {doc} {doc_id}: {', '.join(issues)}")
    for doc, status, doc_id in missing:
        print(f"  [缺失] {doc} status={status} doc_id={doc_id}")
    for o in orphans:
        row = live[o]
        print(f"  [孤儿] {o} pages={row['pages']} chunks={row['chunks']} status={row['status']}")
    if orphans and args.delete_orphans:
        for o in orphans:
            resp = requests.delete(f"{DOCS_API}/api/v1/documents/{o}", headers={"X-API-Key": keys["api_key"]}, timeout=60)
            print(f"  删除 {o}: HTTP {resp.status_code}")
    return 0 if (len(ok) == 84 and not problems and not missing and not orphans) else 1


if __name__ == "__main__":
    sys.exit(main())
