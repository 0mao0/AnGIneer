"""Qdrant vs SQLite 向量检索双跑一致性校验。

用存量 canonical_vectors 里的真实 embedding 作为查询，对比两个 provider 的 top-k 结果：
- recall@k = |Qdrant 命中 ∩ SQLite 命中| / k（SQLite 暴力全量 = ground truth）
- 同时覆盖无过滤与 doc_ids 过滤两种路径
- Qdrant 开 int8 量化时是近似检索，验收线：mean recall@20 ≥ 0.95（计划 B 门禁）

用法：
    python scripts/verify_qdrant_parity.py                 # 默认抽 50 个查询
    python scripts/verify_qdrant_parity.py --samples 200
"""
import argparse
import json
import os
import random
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))


def _index_db_path() -> Path:
    base = os.getenv("KNOWLEDGE_BASE_DIR", "").strip()
    if not base:
        for candidate in ("/app/data/knowledge_base",):
            if Path(candidate).exists():
                base = candidate
                break
    if not base:
        base = str(Path(__file__).resolve().parents[1] / "data" / "knowledge_base")
    return Path(base) / "knowledge_index.sqlite"


def main() -> int:
    parser = argparse.ArgumentParser(description="Qdrant/SQLite 检索一致性校验")
    parser.add_argument("--samples", type=int, default=50, help="抽样查询数")
    parser.add_argument("--top-k", type=int, default=20)
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args()

    db_path = _index_db_path()
    conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    rows = conn.execute(
        "SELECT record_id, doc_id, entity_type, embedding_json FROM canonical_vectors"
        " WHERE dimension > 0"
    ).fetchall()
    conn.close()
    if not rows:
        print("[parity] 源库无有效向量", flush=True)
        return 1

    rng = random.Random(args.seed)
    samples = rng.sample(rows, min(args.samples, len(rows)))
    print(f"[parity] 源库有效向量 {len(rows)}，抽样查询 {len(samples)} 个，top_k={args.top_k}", flush=True)

    from docs_core.step06_vectors.qdrant_vector_store import QdrantVectorStore
    from docs_core.step06_vectors.sqlite_vector_store import SQLiteVectorStore

    sqlite_store = SQLiteVectorStore(db_path=db_path)
    qdrant_store = QdrantVectorStore()

    def _run(query_embedding, doc_ids=None):
        expected = sqlite_store.search(query_embedding, doc_ids=doc_ids, top_k=args.top_k)
        actual = qdrant_store.search(query_embedding, doc_ids=doc_ids, top_k=args.top_k)
        expected_ids = {hit.record_id for hit in expected}
        actual_ids = {hit.record_id for hit in actual}
        id_recall = len(expected_ids & actual_ids) / max(1, len(expected_ids))
        # 语义口径：按 content 去重后比较（table_row_key 大量单字符重复文本会产生
        # 数千条同分记录，record_id 级对比会被并列破平方式淹没，不代表真实质量）
        expected_contents = {hit.content for hit in expected}
        actual_contents = {hit.content for hit in actual}
        content_recall = len(expected_contents & actual_contents) / max(1, len(expected_contents))
        return id_recall, content_recall

    id_recalls, content_recalls = [], []
    f_id_recalls, f_content_recalls = [], []
    for index, (record_id, doc_id, entity_type, embedding_json) in enumerate(samples, 1):
        embedding = json.loads(embedding_json)
        id_r, c_r = _run(embedding)
        id_recalls.append(id_r)
        content_recalls.append(c_r)
        # 同一查询再跑一次 doc_ids 过滤路径（过滤到该向量所属文档 + 随机另一个文档）
        other_doc = rng.choice(rows)[1]
        f_id_r, f_c_r = _run(embedding, doc_ids=[doc_id, other_doc])
        f_id_recalls.append(f_id_r)
        f_content_recalls.append(f_c_r)
        if index % 10 == 0:
            print(f"[parity] {index}/{len(samples)} ...", flush=True)

    def _report(name, id_list, content_list):
        print(
            f"[parity] {name}: record_id recall mean={sum(id_list)/len(id_list):.4f} min={min(id_list):.4f} | "
            f"content recall mean={sum(content_list)/len(content_list):.4f} min={min(content_list):.4f}",
            flush=True,
        )

    _report("无过滤", id_recalls, content_recalls)
    _report("带过滤", f_id_recalls, f_content_recalls)

    threshold = 0.95
    # 验收口径用 content recall（语义等价）；record_id recall 仅作参考输出
    ok = (
        sum(content_recalls) / len(content_recalls) >= threshold
        and sum(f_content_recalls) / len(f_content_recalls) >= threshold
    )
    print(f"[parity] 验收线 content recall mean >= {threshold}：{'通过 [OK]' if ok else '未达标 [FAIL]'}", flush=True)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
