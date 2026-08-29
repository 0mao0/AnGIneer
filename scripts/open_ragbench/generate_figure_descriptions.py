"""为已入库文档的图表生成 VLM 文字描述（独立补跑入口，薄包装 docs-core 模块）。

核心逻辑在 docs_core.step04_structure.figure_describer（解析管线 figure_describe 阶段同源）。
配置走环境变量：FIGURE_DESCRIBE_VLM_URL / FIGURE_DESCRIBE_VLM_API_KEY（或 ANGINEER_CHAT_API_KEY）/
FIGURE_DESCRIBE_VLM_MODEL / FIGURE_DESCRIBE_TIMEOUT。

用法：
    python scripts/open_ragbench/generate_figure_descriptions.py [--library lib-b07ed174] [--doc-ids a,b] [--workers 4]
"""
import argparse
import os
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from open_ragbench import common  # noqa: E402
from docs_core.step04_structure.figure_describer import (  # noqa: E402
    describe_figures_in_graph,
    is_enabled,
)

KNOWLEDGE_INDEX = common.REPO_ROOT / "data" / "knowledge_base" / "knowledge_index.sqlite"


def list_doc_ids(library_id: str) -> list[str]:
    if not KNOWLEDGE_INDEX.exists():
        return []
    conn = sqlite3.connect(KNOWLEDGE_INDEX)
    try:
        rows = conn.execute(
            "SELECT doc_id FROM canonical_documents WHERE library_id=? ORDER BY doc_id",
            (library_id,),
        ).fetchall()
        return [row[0] for row in rows]
    finally:
        conn.close()


def main() -> int:
    parser = argparse.ArgumentParser(description="为已入库文档的图表生成 VLM 描述")
    parser.add_argument("--library", default="lib-b07ed174")
    parser.add_argument("--doc-ids", default="", help="逗号分隔的文档子集（默认库内全部）")
    parser.add_argument("--workers", type=int, default=4, help="文档内并发请求数")
    args = parser.parse_args()

    if not is_enabled():
        print("FIGURE_DESCRIBE_ENABLED=0，已跳过")
        return 0
    if not os.getenv("FIGURE_DESCRIBE_VLM_API_KEY") and not os.getenv("ANGINEER_CHAT_API_KEY"):
        print("缺少 FIGURE_DESCRIBE_VLM_API_KEY（或 ANGINEER_CHAT_API_KEY）")
        return 2

    doc_ids = [d.strip() for d in args.doc_ids.split(",") if d.strip()] or list_doc_ids(args.library)
    total = {"described": 0, "already": 0, "missing_images": 0, "errors": 0}
    failed_docs = []
    for doc_id in doc_ids:
        try:
            stats = describe_figures_in_graph(
                args.library, doc_id, max_workers=args.workers,
            )
            for key in ("described", "already", "missing_images", "errors"):
                total[key] += stats[key]
            print(
                f"[{doc_id}] 新生成 {stats['described']}，已有 {stats['already']}，"
                f"缺图 {stats['missing_images']}，失败 {stats['errors']}",
                flush=True,
            )
        except Exception as exc:  # noqa: BLE001
            failed_docs.append(doc_id)
            print(f"[{doc_id}] 失败: {type(exc).__name__}: {exc}", flush=True)

    print(f"TOTAL: {total}；文档级失败: {len(failed_docs)} {failed_docs}")
    return 1 if failed_docs else 0


if __name__ == "__main__":
    sys.exit(main())
