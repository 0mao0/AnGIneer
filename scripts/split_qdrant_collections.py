"""qdrant 按组拆 collection：scroll 源 collection → 按注册表路由 → upsert 目标 collection。

承接 docs/plan-kb-split-groups.md 阶段一（该计划已完结清理、git 历史可查）。特性：
- 向量原样搬运（scroll+upsert），**不重新嵌入**，省 GPU 数小时
- 幂等：point id 确定性（uuid5(record_id)），中断重跑不产生重复（scroll 游标不可持久化，
  重跑=从头全量再扫一遍，计数每跑清零重算；progress 文件仅作崩溃遥测）
- 搬运时给 payload 补上 library_id（组内多库过滤与对账的归属依据）
- 源 collection 不动（回滚窗口）；对账通过后才 --delete-source 清理
- 进度遥测落 <data>/qdrant_split_progress.json（仅 --yes 时写）

前置：先跑 scripts/seed_library_registry.py 落注册表。

用法（本机或 docs-api 容器内，容器内需 -e QDRANT_URL=http://qdrant:6333）：
    python scripts/split_qdrant_collections.py                 # DRY RUN：各组应迁计数预览
    python scripts/split_qdrant_collections.py --yes           # 执行搬运（断点续跑）
    python scripts/split_qdrant_collections.py --verify        # 对账：各组 源剩余+目标 == 源原始
    python scripts/split_qdrant_collections.py --delete-source # 对账通过后清源（回滚窗口终点）
"""
import argparse
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

_SCROLL_BATCH = 1024


def _doc_library_map() -> dict:
    """doc_id → library_id（knowledge_meta nodes 表，document 类型、未删除）。"""
    import sqlite3

    from docs_core.paths import resolve_knowledge_meta_db_path

    meta_path = resolve_knowledge_meta_db_path()
    with sqlite3.connect(f"file:{meta_path}?mode=ro", uri=True) as conn:
        rows = conn.execute(
            "SELECT id, library_id FROM nodes WHERE type = 'document' AND COALESCE(deleted, 0) = 0"
        ).fetchall()
    return {str(doc_id): str(lib) for doc_id, lib in rows}


def _library_collection_map() -> dict:
    """library_id → **目标** collection（按组默认推导，非注册行当前值——
    零停机种子里注册行仍挂旧全局 collection，目标桶必须看组默认）。"""
    from docs_core import library_registry as registry

    return {
        record.library_id: registry.GROUP_DEFAULTS.get(record.group_name, {}).get(
            "collection", record.group_name
        )
        for record in registry.list_libraries()
    }


def _progress_path() -> Path:
    from docs_core import library_registry as registry

    return registry.resolve_data_root() / "qdrant_split_progress.json"


def _load_progress() -> dict:
    path = _progress_path()
    if path.exists():
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {"migrated": {}, "unmapped": 0}


def _save_progress(progress: dict) -> None:
    _progress_path().write_text(
        json.dumps(progress, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def _targets() -> tuple:
    """返回 (doc→collection, doc→library) 两张映射（注册表读穿 + meta nodes）。"""
    doc_lib = _doc_library_map()
    lib_coll = _library_collection_map()
    doc_coll = {}
    for doc_id, library_id in doc_lib.items():
        collection = lib_coll.get(library_id)
        if collection:
            doc_coll[doc_id] = collection
    return doc_coll, doc_lib


def main() -> int:
    parser = argparse.ArgumentParser(description="qdrant 按组拆 collection（DRY RUN 缺省）")
    parser.add_argument("--yes", action="store_true", help="执行搬运（缺省 DRY RUN）")
    parser.add_argument("--verify", action="store_true", help="对账：按组 counts 比对")
    parser.add_argument("--delete-source", action="store_true", help="删除源 collection 中已迁走的点")
    parser.add_argument("--source", default="", help="源 collection（缺省 QDRANT_COLLECTION 全局值）")
    args = parser.parse_args()

    from qdrant_client import models

    from docs_core.step06_vectors.config import get_qdrant_collection
    from docs_core.step06_vectors.qdrant_vector_store import QdrantVectorStore

    store = QdrantVectorStore()
    client = store._get_client()
    source = args.source or get_qdrant_collection()
    doc_coll, doc_lib = _targets()
    if not doc_coll:
        print("[split] 注册表/meta 为空或无映射，先跑 seed_library_registry.py", flush=True)
        return 1

    if args.yes:
        # 目标 collection 预建（维度/payload 索引与源同构，经 store._ensure_collection）
        source_dim = store._collection_dim(source)
        if source_dim <= 0:
            print(f"[split] 源 collection {source} 不存在或无维度，无法推导目标维度", flush=True)
            return 1
        for target in sorted(set(doc_coll.values())):
            store._ensure_collection(source_dim, target)
            print(f"[split] 目标 collection 就绪: {target} (dim={source_dim})", flush=True)

    if args.verify:
        return _verify(client, source, doc_coll)
    if args.delete_source:
        return _delete_source(client, source, doc_coll)

    # 全量 scroll 源 collection，按 doc→collection 路由（单遍扫描，避免 MatchAny 大清单）。
    # 计数语义：scroll 游标无法持久化，中断重跑必然从头扫——幂等靠 point id 确定性 upsert，
    # 因此计数每跑清零重算（progress 文件仅作崩溃遥测，不作断点续跑依据；DRY RUN 不落盘）。
    migrated: dict = {}
    unmapped = 0
    offset = None
    scanned = 0
    pending: dict = {}  # collection → [PointStruct]
    while True:
        points, offset = client.scroll(
            collection_name=source,
            with_payload=True,
            with_vectors=True,
            limit=_SCROLL_BATCH,
            offset=offset,
        )
        for point in points:
            scanned += 1
            payload = point.payload or {}
            target = doc_coll.get(str(payload.get("doc_id") or ""))
            if not target or target == source:
                if not target:
                    unmapped += 1
                continue
            payload["library_id"] = payload.get("library_id") or doc_lib.get(
                str(payload.get("doc_id") or ""), ""
            )
            pending.setdefault(target, []).append(
                models.PointStruct(id=point.id, vector=point.vector, payload=payload)
            )
        # 凑批落盘
        for target, batch in list(pending.items()):
            if len(batch) >= _SCROLL_BATCH:
                if args.yes:
                    client.upsert(collection_name=target, points=batch, wait=True)
                migrated[target] = int(migrated.get(target) or 0) + len(batch)
                pending[target] = []
        if scanned % (_SCROLL_BATCH * 20) == 0:
            print(f"[split] 已扫 {scanned}，已迁 {sum(migrated.values())}，未映射 {unmapped}", flush=True)
            if args.yes:
                _save_progress({"migrated": migrated, "unmapped": unmapped})
        if offset is None:
            break
    for target, batch in pending.items():
        if not batch:
            continue
        if args.yes:
            client.upsert(collection_name=target, points=batch, wait=True)
        migrated[target] = int(migrated.get(target) or 0) + len(batch)
    if args.yes:
        _save_progress({"migrated": migrated, "unmapped": unmapped})

    print(f"[split] 扫描完成：共 {scanned} 点，未映射（留在源）{unmapped}", flush=True)
    for target, count in sorted(migrated.items()):
        print(f"[split]   → {target}: {count}", flush=True)
    if not args.yes:
        print("[split] DRY RUN：以上为应迁计数，加 --yes 才真正写入", flush=True)
        return 2
    print("[split] 搬运完成。跑 --verify 对账，通过后再 --delete-source 清源", flush=True)
    return 0


def _verify(client, source: str, doc_coll: dict) -> int:
    """按 collection 对账：目标桶计数 == 该桶应收 doc 的源原始计数（迁移前快照口径）。

    源 collection 在 delete-source 前仍含全部点：目标 count 应等于「源中属于该组的点数」。
    """
    targets = sorted(set(doc_coll.values()))
    ok = True
    for target in targets:
        doc_ids = [doc for doc, coll in doc_coll.items() if coll == target]
        expected = _count_docs(client, source, doc_ids)
        actual = int(client.count(collection_name=target, exact=True).count) if _exists(client, target) else 0
        match = "OK " if actual == expected else "MISMATCH"
        if actual != expected:
            ok = False
        print(f"[verify] {match} {target}: 目标 {actual} / 源应收 {expected}", flush=True)
    return 0 if ok else 1


def _count_docs(client, collection: str, doc_ids: list) -> int:
    from qdrant_client import models

    total = 0
    for start in range(0, len(doc_ids), 256):
        batch = doc_ids[start : start + 256]
        total += int(
            client.count(
                collection_name=collection,
                count_filter=models.Filter(
                    must=[models.FieldCondition(key="doc_id", match=models.MatchAny(any=batch))]
                ),
                exact=True,
            ).count
        )
    return total


def _exists(client, collection: str) -> bool:
    try:
        client.get_collection(collection)
        return True
    except Exception:
        return False


def _delete_source(client, source: str, doc_coll: dict) -> int:
    """对账通过后清源：按 doc_id 分批删除已迁走的点（回滚窗口终点，不可逆，先确认 --verify 全 OK）。"""
    from qdrant_client import models

    doc_ids = sorted(doc_coll.keys())
    deleted = 0
    for start in range(0, len(doc_ids), 256):
        batch = doc_ids[start : start + 256]
        flt = models.Filter(
            must=[models.FieldCondition(key="doc_id", match=models.MatchAny(any=batch))]
        )
        client.delete(
            collection_name=source,
            points_selector=models.FilterSelector(filter=flt),
            wait=True,
        )
        deleted += len(batch)
        if deleted % 5120 == 0:
            print(f"[delete-source] 已按 {deleted}/{len(doc_ids)} 个 doc 清源", flush=True)
    print(f"[delete-source] 完成：源 {source} 已清除 {len(doc_ids)} 个 doc 的点", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
