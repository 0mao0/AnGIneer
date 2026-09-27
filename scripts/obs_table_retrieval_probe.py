"""表格检索段微基准探针（观测专用，只读，不改产品代码）。

针对 docs/req-table-retrieval-latency.md 的「动刀前先补观测」：
把 TableRetriever.retrieve 单次调用（即分段计时里的 table= 段）分解为——

  wall        retrieve() 总耗时
  sql         list_canonical_tables 合计（SQL 执行 + JSON 反序列化为 CanonicalTable）
  text_build  build_full_table_text 合计（候选整表文本重建，重复劳动项；含调用次数/去重表数）
  score       其余（逐行纯 Python 打分 + 排序截断）= wall - sql - text_build
  candidates  产出候选条数（build_table_item 调用数）

只读三处数据源：knowledge_meta.sqlite（文档节点）、knowledge_index.sqlite（canonical 表），
不连向量库、不起后端。库与文档圈定口径复刻 aichat-api/chat_agent.py::_load_doc_nodes。

用法：
  python scripts/obs_table_retrieval_probe.py                 # 默认 3 条实测题 × 3 轮
  python scripts/obs_table_retrieval_probe.py --rounds 1 --library default
  python scripts/obs_table_retrieval_probe.py --json data/ops/table-probe-xxx.json
"""
import argparse
import importlib
import json
import sqlite3
import sys
import time
from datetime import datetime
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "services" / "docs-core" / "src"))

from docs_core.paths import resolve_knowledge_index_db_path, resolve_knowledge_meta_db_path  # noqa: E402
from docs_core.step05_sqlite_fts.store.canonical_sql_store import CanonicalSQLiteStore  # noqa: E402
from docs_core.step09_query.protocols.contracts import KnowledgeNode, KnowledgeQueryRequest  # noqa: E402
# retrieval/__init__ 以同名导出 TableRetriever 实例，直接 from-import 会拿到实例而非模块
tr = importlib.import_module("docs_core.step09_query.retrieval.table_retriever")

# 2026-09-26 晚 logs/p0-retest.log 三条实锤题（table= 27.82 / 14.16 / 10.84s）
DEFAULT_QUERIES = [
    "依据《海港总体设计规范》确定5万吨级散货船的设计船型尺度",
    "某5万吨级散货船，设计船型总长L=230m，型宽B=32m，满载吃水T=12.8m，试计算码头前沿水深",
    "码头前沿水深富裕高度 散货船 5万吨级 规范",
]

TOP_K = 20  # 与实测日志 items=20 口径一致 → 每文档拉表 limit=max(30, 160)=160


def load_doc_nodes(library_id: str) -> list[KnowledgeNode]:
    """复刻 _load_doc_nodes 的圈定口径（deleted=0 + type=document + 按 library 过滤）。"""
    conn = sqlite3.connect(f"file:{resolve_knowledge_meta_db_path()}?mode=ro", uri=True)
    try:
        rows = conn.execute(
            "SELECT id, title FROM nodes WHERE deleted=0 AND type='document' AND library_id=? ORDER BY id",
            (library_id,),
        ).fetchall()
    finally:
        conn.close()
    return [
        KnowledgeNode(id=doc_id, title=title or doc_id, type="document", library_id=library_id)
        for doc_id, title in rows
    ]


class TimedPort:
    """只包 list_canonical_tables 的计时代理，其余属性直透。"""

    def __init__(self, store: CanonicalSQLiteStore) -> None:
        self._store = store
        self.t_sql = 0.0
        self.calls = 0
        self.tables_fetched = 0
        self.max_per_doc = 0

    def list_canonical_tables(self, **kwargs):
        t0 = time.perf_counter()
        out = self._store.list_tables(**kwargs)
        self.t_sql += time.perf_counter() - t0
        self.calls += 1
        self.tables_fetched += len(out)
        self.max_per_doc = max(self.max_per_doc, len(out))
        return out

    def __getattr__(self, name):
        return getattr(self._store, name)


def run_probe(queries: list[str], rounds: int, library_id: str, gc_off: bool = False) -> list[dict]:
    doc_nodes = load_doc_nodes(library_id)
    print(f"library={library_id} 文档节点={len(doc_nodes)} 篇 gc_off={gc_off}")
    store = CanonicalSQLiteStore(db_path=resolve_knowledge_index_db_path())

    results: list[dict] = []
    for query in queries:
        for round_no in range(1, rounds + 1):
            port = TimedPort(store)
            retriever = tr.TableRetriever(port=port)

            t_build = 0.0
            build_calls = 0
            build_tables: set[str] = set()
            orig_build = tr.build_full_table_text

            def timed_build(table, _orig=orig_build, _acc=None):
                nonlocal t_build, build_calls
                t0 = time.perf_counter()
                out = _orig(table)
                t_build += time.perf_counter() - t0
                build_calls += 1
                build_tables.add(table.table_id)
                return out

            cand_calls = 0
            orig_item = tr.build_table_item

            def counting_item(**kwargs):
                nonlocal cand_calls
                cand_calls += 1
                return orig_item(**kwargs)

            tr.build_full_table_text = timed_build
            tr.build_table_item = counting_item
            if gc_off:
                import gc

                gc.disable()
            try:
                request = KnowledgeQueryRequest(
                    query=query, library_id=library_id, doc_ids=[], top_k=TOP_K, filters=None
                )
                t0 = time.perf_counter()
                items = retriever.retrieve(request, doc_nodes)
                wall = time.perf_counter() - t0
            finally:
                tr.build_full_table_text = orig_build
                tr.build_table_item = orig_item
                if gc_off:
                    import gc

                    gc.enable()

            row = {
                "query": query,
                "round": round_no,
                "wall_s": round(wall, 3),
                "sql_s": round(port.t_sql, 3),
                "sql_calls": port.calls,
                "tables_fetched": port.tables_fetched,
                "text_build_s": round(t_build, 3),
                "text_build_calls": build_calls,
                "text_build_tables": len(build_tables),
                "score_s": round(wall - port.t_sql - t_build, 3),
                "candidates": cand_calls,
                "returned": len(items),
            }
            results.append(row)
            print(
                f"  r{round_no} wall={row['wall_s']:6.2f}s sql={row['sql_s']:6.2f}s "
                f"text_build={row['text_build_s']:5.2f}s({build_calls:3d}次/{len(build_tables):3d}表) "
                f"score={row['score_s']:6.2f}s cand={cand_calls:4d} fetched={port.tables_fetched}"
            )
    return results


def sql_vs_deserialize(library_id: str) -> dict:
    """单文档级补充探针：list_tables 内 SQL fetchall 与 Python 反序列化各占多少。"""
    idx = sqlite3.connect(f"file:{resolve_knowledge_index_db_path()}?mode=ro", uri=True)
    meta = sqlite3.connect(f"file:{resolve_knowledge_meta_db_path()}?mode=ro", uri=True)
    doc_ids = [r[0] for r in meta.execute(
        "SELECT id FROM nodes WHERE deleted=0 AND type='document' AND library_id=?", (library_id,)
    )]
    placeholders = ",".join("?" * len(doc_ids))
    biggest, biggest_n = None, -1
    for doc_id, n in idx.execute(
        f"SELECT doc_id, COUNT(*) FROM canonical_tables WHERE doc_id IN ({placeholders}) GROUP BY doc_id",
        doc_ids,
    ):
        if n > biggest_n:
            biggest, biggest_n = doc_id, n

    sql = """
        SELECT table_id, doc_id, page_start, page_end, title, caption, bbox_json,
               page_bboxes_json, table_type, header_rows_json, body_rows_json, units_json,
               row_count, col_count, source_block_ids_json, summary, row_keys_json,
               text_chunks_json, version
        FROM canonical_tables WHERE doc_id = ?
        ORDER BY page_start ASC, table_id ASC LIMIT 160
    """
    t0 = time.perf_counter()
    rows = idx.execute(sql, (biggest,)).fetchall()
    t_fetch = time.perf_counter() - t0
    t0 = time.perf_counter()
    store = CanonicalSQLiteStore(db_path=resolve_knowledge_index_db_path())
    tables = store.list_tables(doc_id=biggest, keyword=None, limit=160)
    t_store = time.perf_counter() - t0
    idx.close()
    meta.close()
    return {
        "biggest_doc": biggest,
        "tables": biggest_n,
        "raw_fetchall_s": round(t_fetch, 3),
        "store_call_s": round(t_store, 3),
        "deserialize_s": round(t_store - t_fetch, 3),
        "note": "raw 与 store 各自独立执行，页缓存已热，deserialize_s ≈ store_call - fetchall 仅为量级参考",
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--library", default="default")
    parser.add_argument("--rounds", type=int, default=3)
    parser.add_argument("--gc-off", action="store_true", help="探针期间禁用 GC（对照大堆进程的 GC 开销）")
    parser.add_argument("--inflate-mb", type=int, default=0, help="探针前预分配 N MB 杂散对象（模拟后端大堆脏 allocator）")
    parser.add_argument("--json", dest="json_path", default=None)
    args = parser.parse_args()

    if args.inflate_mb > 0:
        ballast = []
        chunk = [{"k": i, "v": "x" * 64, "t": (i, i + 1)} for i in range(20000)]
        while True:
            ballast.append(chunk)
            import sys as _sys

            if _sys.getsizeof(ballast) + len(ballast) * len(chunk) * 200 > args.inflate_mb * 1024 * 1024:
                break
        print(f"已预分配 ~{args.inflate_mb}MB 堆球囊（{len(ballast)} 组）")

    results = run_probe(DEFAULT_QUERIES, args.rounds, args.library, gc_off=args.gc_off)
    extra = sql_vs_deserialize(args.library)
    print("\n单文档 SQL/反序列化分解:", json.dumps(extra, ensure_ascii=False))

    payload = {
        "probed_at": datetime.now().isoformat(timespec="seconds"),
        "library": args.library,
        "rounds": args.rounds,
        "results": results,
        "sql_vs_deserialize": extra,
    }
    if args.json_path:
        Path(args.json_path).write_text(
            json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        print(f"结果已写 {args.json_path}")


if __name__ == "__main__":
    main()
