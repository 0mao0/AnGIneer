"""向量索引全量重建（dense 回填）。

适用场景：切换 embedding 模型（维度变化）或切换向量库 provider 后，把全部已完成文档
重新向量化到当前 sqlite 向量库。逐文档幂等（clear + upsert），进度落盘，中断可续跑。

关键前置：本脚本**第一步先清空 canonical_vectors**，且必须发生在任何 docs_core 导入之前——
embedding provider 在 import 时按库里已有向量的维度锁定 expected_dimension，
残留旧维度向量会让新模型输出被维度守卫拒收并走降级链（回填全白跑）。

用法（docs-api 容器内）：
    python /app/scripts/rebuild_vectors.py --yes                    # 全库回填
    python /app/scripts/rebuild_vectors.py --yes --doc-id doc-xxx   # 单篇
    python /app/scripts/rebuild_vectors.py --yes --library default

进度文件：<knowledge_base>/vector_rebuild_progress.json（与数据库同目录，容器重启不丢）。
"""
import argparse
import json
import os
import sqlite3
import sys
import time
from pathlib import Path


def _index_db_path() -> Path:
    """不依赖 docs_core 导入的路径解析（与 docs_core.paths 口径一致）。"""
    base = os.getenv("KNOWLEDGE_BASE_DIR", "").strip()
    if not base:
        # 容器内默认 /app/data/knowledge_base；本地仓默认 <repo>/data/knowledge_base
        for candidate in ("/app/data/knowledge_base",):
            if Path(candidate).exists():
                base = candidate
                break
    if not base:
        base = str(Path(__file__).resolve().parents[1] / "data" / "knowledge_base")
    return Path(base) / "knowledge_index.sqlite"


def _clear_vectors(db_path: Path) -> int:
    conn = sqlite3.connect(str(db_path))
    try:
        cur = conn.execute("DELETE FROM canonical_vectors")
        conn.commit()
        return int(cur.rowcount or 0)
    finally:
        conn.close()


def main() -> int:
    parser = argparse.ArgumentParser(description="向量索引全量重建")
    parser.add_argument("--yes", action="store_true", help="确认执行（会先清空 canonical_vectors）")
    parser.add_argument("--library", default=None, help="限定知识库 id（默认全部库）")
    parser.add_argument("--doc-id", default=None, help="限定单篇文档")
    args = parser.parse_args()
    if not args.yes:
        print("DRY RUN：加 --yes 才会真正执行（会先清空 canonical_vectors）")
        return 2

    db_path = _index_db_path()
    progress_path = db_path.parent / "vector_rebuild_progress.json"

    removed = _clear_vectors(db_path)
    print(f"[rebuild] 已清空 canonical_vectors（删除 {removed} 条旧向量），db={db_path}", flush=True)

    # 清空之后才允许导入 docs_core（embedding provider 在 import 时锁定维度）
    from docs_core.docs_service import get_docs_service

    kp = get_docs_service()
    library_ids = [args.library] if args.library else [lib.id for lib in kp.list_libraries()]
    doc_nodes = []
    for library_id in library_ids:
        for node in kp.list_nodes(library_id):
            if getattr(node, "type", "") != "document" or getattr(node, "deleted", False):
                continue
            if args.doc_id and node.id != args.doc_id:
                continue
            doc_nodes.append(node)
    print(f"[rebuild] 待重建文档 {len(doc_nodes)} 篇", flush=True)

    done: dict = {}
    if progress_path.exists():
        try:
            done = json.loads(progress_path.read_text(encoding="utf-8"))
        except Exception:
            done = {}

    ok, failed, skipped = 0, 0, 0
    for index, node in enumerate(doc_nodes, 1):
        doc_id = node.id
        if doc_id in done and not args.doc_id:
            skipped += 1
            continue
        started = time.perf_counter()
        try:
            kp.rebuild_document_vectors(doc_id)
        except Exception as exc:  # noqa: BLE001
            failed += 1
            print(f"[rebuild] [{index}/{len(doc_nodes)}] {doc_id} 失败: {exc}", flush=True)
            continue
        elapsed = time.perf_counter() - started
        stats = kp.get_document_vector_stats(doc_id)
        total = stats.get("total_count", "?")
        done[doc_id] = {"vectors": total, "elapsed_s": round(elapsed, 1)}
        progress_path.write_text(json.dumps(done, ensure_ascii=False, indent=1), encoding="utf-8")
        ok += 1
        print(
            f"[rebuild] [{index}/{len(doc_nodes)}] {doc_id} 完成：{total} 条向量，耗时 {elapsed:.1f}s",
            flush=True,
        )

    print(f"[rebuild] 全部结束：成功 {ok}，失败 {failed}，跳过（已有进度）{skipped}", flush=True)
    print("[rebuild] 下一步：随便问一个问题触发 aichat-api 重建矩阵缓存，观察日志 '向量矩阵缓存已构建'", flush=True)
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
