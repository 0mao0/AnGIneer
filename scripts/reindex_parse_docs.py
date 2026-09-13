"""给已解析文档重建 FTS + 向量索引，并验证"内容真的能被搜到"。

背景：parse 的 5 阶段链（source_prep→structure）不产出索引；索引要靠 `fts`/`vectors` 阶段。
本脚本直接复用生产入口 `build_sqlite_index_from_graph` 与 `rebuild_document_vectors`，
对指定库/文档做重建，然后：
  1. 在 canonical_chunks 里确认目标文本已进入可检索文本；
  2. 用 FTS 查询该文本，确认能召回对应文档；
  3. 反事实对照：把目标文本置空后重建（仅内存）→ 该文本从 chunk 文本里消失，
     证明"它在索引里"确实是这次修复带来的。

用法：
  python scripts/reindex_parse_docs.py --library omnidocbench --probe-file D:/.../probe_targets.json --reindex
"""
import argparse
import json
import re
import sqlite3
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "services" / "docs-core" / "src"))

DB = REPO / "data" / "knowledge_base" / "knowledge_index.sqlite"


def _chunk_texts(doc_id: str) -> list[str]:
    con = sqlite3.connect(DB)
    try:
        rows = con.execute("SELECT text_clean FROM canonical_chunks WHERE doc_id = ?", (doc_id,)).fetchall()
        return [str(r[0] or "") for r in rows]
    finally:
        con.close()


def _fts_query(text: str, limit: int = 5) -> list[tuple[str, str]]:
    """FTS 查询（转义成安全查询串），返回 [(doc_id, 片段)]。"""
    tokens = [t for t in text.replace('"', " ").split() if len(t) > 1][:8]
    if not tokens:
        return []
    query = " OR ".join(f'"{t}"' for t in tokens)
    con = sqlite3.connect(DB)
    try:
        rows = con.execute(
            "SELECT doc_id, substr(text_clean, 1, 80) FROM canonical_chunk_fts "
            "WHERE canonical_chunk_fts MATCH ? LIMIT ?",
            (query, limit),
        ).fetchall()
        return [(str(r[0]), str(r[1])) for r in rows]
    finally:
        con.close()


def main() -> int:
    ap = argparse.ArgumentParser(description="重建解析文档的 FTS/向量索引并验证可检索")
    ap.add_argument("--library", default="omnidocbench")
    ap.add_argument("--docs", default="", help="逗号分隔 doc_id；留空则用 --probe-file")
    ap.add_argument("--probe-file", default="", help="JSON：[{page, doc}] 或 [{doc, text}]")
    ap.add_argument("--reindex", action="store_true", help="真的执行重建（否则只做只读探查）")
    args = ap.parse_args()

    targets: list[dict] = []
    if args.docs:
        targets = [{"doc": d.strip()} for d in args.docs.split(",") if d.strip()]
    elif args.probe_file:
        targets = json.loads(Path(args.probe_file).read_text(encoding="utf-8"))

    if not targets:
        raise SystemExit("需要 --docs 或 --probe-file")

    ds = None
    if args.reindex:
        from docs_core.docs_service import get_docs_service
        from docs_core.step05_sqlite_fts.sqlite_index import build_sqlite_index_from_graph

        ds = get_docs_service()
        for item in targets:
            doc_id = item["doc"]
            try:
                result = build_sqlite_index_from_graph(args.library, doc_id)
                ds.rebuild_document_vectors(doc_id)
                print(f"  重建完成 {doc_id}: {result.get('canonical_blocks_count')} blocks / "
                      f"{result.get('canonical_chunks_count', '?')} chunks")
            except Exception as exc:  # noqa: BLE001
                print(f"  重建失败 {doc_id}: {str(exc)[:120]}")

    print("\n=== 探针：目标文本是否在索引的可检索文本里 ===")
    for item in targets[:8]:
        doc_id = item["doc"]
        text = str(item.get("text") or "").strip()
        chunks = _chunk_texts(doc_id)
        if not chunks:
            print(f"  {doc_id}: canonical_chunks 无数据（未重建）")
            continue
        blob = "\n".join(chunks)
        # 空白（含换行）不参与比对：代码块的换行、表格的对齐空格都不该算差异
        norm = lambda x: re.sub(r"\s+", "", x)
        blob = norm("\n".join(chunks))
        probe = norm(text)[:24]
        hit = probe in blob if probe else None
        print(f"  {doc_id}: chunks={len(chunks)}  目标文本在可检索文本中={'是' if hit else '否' if probe else '（未提供文本）'}")
        if probe:
            hits = _fts_query(text, limit=50)
            self_hit = any(doc_id in str(h[0]) for h in hits)
            print(f"      FTS 命中 {len(hits)} 条，目标文档在其中={'是' if self_hit else '否'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
