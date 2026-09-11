"""构建 open-ragbench-subset-v3 = v2(487) + refusal-v2(39) 合并题集。

产物（本地与生产同构）：
1. evals.sqlite：eval_dataset + eval_question 行（dataset_id=open-ragbench-subset-v3）
2. data/evals/datasets/open-ragbench-subset-v3.json（eval.bundle 格式，题干摘录来源）
3. data/open_ragbench/subset/subset_manifest_v3.json（题型归属 manifest，含拒答题）

用法（本地或服务器，仓库根目录执行）：python scripts/build_subset_v3.py --apply
"""
import argparse
import json
import sqlite3
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
DB = REPO / "data" / "evals" / "evals.sqlite"
DATASETS_DIR = REPO / "data" / "evals" / "datasets"
MANIFEST_DIR = REPO / "data" / "open_ragbench" / "subset"

SRC_MAIN = "open-ragbench-subset-v2"
SRC_REFUSAL = "open-ragbench-refusal-v2"
DST = "open-ragbench-subset-v3"
SOURCES = {"text", "text-image", "text-table", "text-table-image"}

Q_COLUMNS = [
    "question_id", "dataset_id", "question", "task_type", "intent_level", "difficulty",
    "tags", "library_id", "doc_ids", "question_family", "canonical_question_id",
    "variant_type", "perturbation_tags", "retrieval_gold", "answer_gold", "sql_gold",
    "sop_gold", "sort_order",
]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()

    conn = sqlite3.connect(str(DB))
    conn.row_factory = sqlite3.Row

    # 幂等：先清掉已存在的 v3
    existing = conn.execute("SELECT COUNT(*) FROM eval_question WHERE dataset_id=?", (DST,)).fetchone()[0]
    print(f"existing v3 questions: {existing}")

    main_rows = conn.execute(
        f"SELECT {', '.join(Q_COLUMNS)} FROM eval_question WHERE dataset_id=? ORDER BY sort_order, question_id",
        (SRC_MAIN,),
    ).fetchall()
    refusal_rows = conn.execute(
        f"SELECT {', '.join(Q_COLUMNS)} FROM eval_question WHERE dataset_id=? ORDER BY sort_order, question_id",
        (SRC_REFUSAL,),
    ).fetchall()
    print(f"source main={len(main_rows)} refusal={len(refusal_rows)} total={len(main_rows)+len(refusal_rows)}")
    if len(main_rows) != 487 or len(refusal_rows) != 39:
        print("!! 源题数不符合预期（487/39），中止")
        return 1

    # 校验拒答题都带 refusal_expected
    bad_refusal = []
    for r in refusal_rows:
        gold = json.loads(r["answer_gold"]) if r["answer_gold"] else {}
        if not gold.get("refusal_expected"):
            bad_refusal.append(r["question_id"])
    if bad_refusal:
        print("!! 拒答题缺 refusal_expected:", bad_refusal[:5])
        return 1

    if not args.apply:
        print("DRY RUN：加 --apply 执行写入")
        return 0

    # 1) DB 写入
    conn.execute("DELETE FROM eval_question WHERE dataset_id=?", (DST,))
    conn.execute("DELETE FROM eval_dataset WHERE dataset_id=?", (DST,))
    src_ds = conn.execute("SELECT * FROM eval_dataset WHERE dataset_id=?", (SRC_MAIN,)).fetchone()
    conn.execute(
        """INSERT INTO eval_dataset
           (dataset_id, title, category, description, schema_version, version,
            library_id, question_count, source_file, created_at, updated_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, datetime('now'), datetime('now'))""",
        (
            DST,
            "Open RAG Benchmark 子集 v3（含拒答 39 题）",
            src_ds["category"],
            "v2 487 题 + 拒答题集 v2 39 题合并；拒答题期望系统拒答（refusal_expected），"
            "报告「拒答专项」自动拆分统计，正确拒答计为答对。",
            src_ds["schema_version"],
            "3.0",
            src_ds["library_id"],
            len(main_rows) + len(refusal_rows),
            "",
        ),
    )
    insert_sql = f"INSERT INTO eval_question ({', '.join(Q_COLUMNS)}) VALUES ({', '.join('?' * len(Q_COLUMNS))})"
    for idx, r in enumerate(main_rows):
        values = [r[c] for c in Q_COLUMNS]
        values[1] = DST  # dataset_id
        values[-1] = idx  # sort_order
        conn.execute(insert_sql, values)
    base_order = len(main_rows)
    for idx, r in enumerate(refusal_rows):
        values = [r[c] for c in Q_COLUMNS]
        values[1] = DST
        values[-1] = base_order + idx
        conn.execute(insert_sql, values)
    conn.commit()
    print(f"DB 写入完成：{len(main_rows) + len(refusal_rows)} 题")

    # 2) 数据集 JSON（eval.bundle 格式）
    def _load_items(dataset_id: str):
        data = json.loads((DATASETS_DIR / f"{dataset_id}.json").read_text(encoding="utf-8"))
        return data

    main_json = _load_items(SRC_MAIN)
    refusal_json = _load_items(SRC_REFUSAL)
    merged = {
        "dataset": {
            **main_json["dataset"],
            "dataset_id": DST,
            "title": "Open RAG Benchmark 子集 v3（含拒答 39 题）",
            "description": "v2 487 题 + 拒答题集 v2 39 题合并；拒答题期望系统拒答。",
            "version": "3.0",
            "question_count": len(main_json["items"]) + len(refusal_json["items"]),
        },
        "items": list(main_json["items"]) + list(refusal_json["items"]),
    }
    out_json = DATASETS_DIR / f"{DST}.json"
    out_json.write_text(json.dumps(merged, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"数据集 JSON: {out_json}（{len(merged['items'])} 题）")

    # 3) manifest v3：v2 manifest 原样 + 拒答题条目（source 取 tags[0] 归属题型桶）
    manifest = json.loads((MANIFEST_DIR / "subset_manifest_v2.json").read_text(encoding="utf-8"))
    existing_uuids = {q.get("uuid") for q in manifest.get("questions", [])}
    appended = 0
    for r in refusal_rows:
        qid = r["question_id"]
        if qid in existing_uuids:
            continue
        tags = json.loads(r["tags"]) if r["tags"] else []
        source = tags[0] if tags and tags[0] in SOURCES else "text"
        qtype = tags[1] if len(tags) > 1 else "abstractive"
        gold = json.loads(r["answer_gold"]) if r["answer_gold"] else {}
        manifest["questions"].append({
            "uuid": qid,
            "query": r["question"],
            "type": qtype,
            "source": source,
            "doc_id": "",
            "answer": str(gold.get("gold_answer") or ""),
            "refusal": True,
        })
        appended += 1
    out_manifest = MANIFEST_DIR / "subset_manifest_v3.json"
    out_manifest.write_text(json.dumps(manifest, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"manifest v3: {out_manifest}（原 {len(existing_uuids)} + 新增 {appended} = {len(manifest['questions'])}）")

    conn.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
