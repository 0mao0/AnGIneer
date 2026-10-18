"""语料包 v2 切片：从组级 sqlite / 全局图谱按 library_id 抽出「每库自包含」子库。

- ``build_library_sqlite_slice``  组 sqlite → 单库切片（12 张 doc 键表 + FTS 行，DDL 原样）
- ``build_library_graph_slice``   全局 graph.sqlite → 单库**闭包**切片（F17：跨库实体引用）
- 向量按库快照（临时 collection）见 P1-4

表清单单一真相源 = ``KbMigrator._DOC_TABLES``（勿另声明同步清单）。
"""
from __future__ import annotations

import logging
import sqlite3
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Dict, Iterator, Mapping, Optional

from . import library_registry
from .corpus_package import checkpoint_sqlite, create_snapshot, delete_snapshot
from .kb_migrator import KbMigrator

logger = logging.getLogger(__name__)

# FTS5 虚表的影子表前缀（{fts}_data/_idx/_content/_docsize/_config）——
# 建表时必须跳过：影子表由虚表语句自行创建，手工执行其 DDL 会撞名。
FTS_TABLES = ("canonical_chunk_fts",)

# 图谱全部表（graph_store.py 建表语句的 10 张；切片/合并同用）
GRAPH_TABLES = (
    "graph_entities", "graph_relations", "graph_principles", "principle_entities",
    "graph_examples", "example_entities", "graph_warnings", "warning_entities",
    "graph_frameworks", "graph_entity_deletions",
)

# 实体闭包口径（F17）：本库归属 ∪ 本库关系端点 ∪ 本库 artifact 联结引用实体
# （add_principle 等按 name 联结、端点在库外真实存在——单按 library_id 过滤会留悬空 FK）
_ENTITY_CLOSURE_SQL = """
    library_id = ?
    OR entity_id IN (SELECT source_id FROM srcdb.graph_relations WHERE library_id = ?)
    OR entity_id IN (SELECT target_id FROM srcdb.graph_relations WHERE library_id = ?)
    OR entity_id IN (SELECT je.entity_id FROM srcdb.principle_entities je
                     JOIN srcdb.graph_principles a ON je.principle_id = a.principle_id
                     WHERE a.library_id = ?)
    OR entity_id IN (SELECT je.entity_id FROM srcdb.example_entities je
                     JOIN srcdb.graph_examples a ON je.example_id = a.example_id
                     WHERE a.library_id = ?)
    OR entity_id IN (SELECT je.entity_id FROM srcdb.warning_entities je
                     JOIN srcdb.graph_warnings a ON je.warning_id = a.warning_id
                     WHERE a.library_id = ?)
"""

# 联结表 → 父表（按本库父 id 抽全行；联结行的实体可能属于他库，闭包已拉入）
_GRAPH_JUNCTIONS = (
    ("principle_entities", "principle_id", "graph_principles"),
    ("example_entities", "example_id", "graph_examples"),
    ("warning_entities", "warning_id", "graph_warnings"),
)

_GRAPH_ARTIFACTS = ("graph_principles", "graph_examples", "graph_warnings", "graph_frameworks")


def _cleanup_sqlite_files(path: Path) -> None:
    for suffix in ("", "-journal", "-wal", "-shm"):
        try:
            (path.parent / (path.name + suffix)).unlink(missing_ok=True)
        except OSError:
            pass


def _close_quietly(conn) -> None:
    if conn is None:
        return
    try:
        conn.close()
    except Exception:
        pass


def _copy_ddl(src: sqlite3.Connection, dst: sqlite3.Connection, tables) -> None:
    """按源 sqlite_master 原样重建表（含 FTS 虚表语句）与索引（sql IS NOT NULL=非自动索引）。"""
    for table in tables:
        row = src.execute(
            "SELECT sql FROM sqlite_master WHERE type='table' AND name=?", (table,)
        ).fetchone()
        if not row or not row[0]:
            logger.warning("切片跳过无 DDL 表: %s", table)
            continue
        dst.execute(row[0])
    ph = ",".join("?" for _ in tables)
    for row in src.execute(
        f"SELECT sql FROM sqlite_master WHERE type='index' AND sql IS NOT NULL "
        f"AND tbl_name IN ({ph})", list(tables),
    ):
        dst.execute(row[0])


def _insert_select(dst: sqlite3.Connection, table: str, where: str, params=()) -> int:
    """从 ATTACH 的 srcdb 按 where 拷行（列序取 dst 重建后的 schema）。"""
    cols = [r[1] for r in dst.execute(f'PRAGMA table_info("{table}")')]
    col_list = ", ".join(f'"{c}"' for c in cols)
    cur = dst.execute(
        f'INSERT INTO "{table}" ({col_list}) SELECT {col_list} FROM srcdb."{table}" WHERE {where}',
        params,
    )
    return cur.rowcount if cur.rowcount >= 0 else 0


def build_library_sqlite_slice(data_root: Path, library_row: Mapping[str, Any], out_path: Path) -> Dict[str, Any]:
    """按库切片组 sqlite。

    读侧先 ``checkpoint_sqlite``（WAL 落盘：不 checkpoint 会漏最近写入——与 v1 导包同规）。
    数据过滤：有 ``library_id`` 列 → ``WHERE library_id=?``；有 ``doc_id`` 列 →
    ``doc_id IN (SELECT doc_id FROM canonical_documents WHERE library_id=?)``；
    都没有 → 跳过告警；表在源库缺失 → 跳过（旧库兼容）。

    返回 ``{"docs", "chunks", "bytes", "tables"}``；失败清理半成品（含 WAL 边车）。
    """
    data_root = Path(data_root)
    out_path = Path(out_path)
    group_db = data_root / str(library_row["sqlite_file"])
    library_id = str(library_row["library_id"])

    out_path.parent.mkdir(parents=True, exist_ok=True)
    _cleanup_sqlite_files(out_path)  # 防上次取消的半成品被 connect 复用（旧行混入）

    checkpoint_sqlite(group_db)

    src = sqlite3.connect(str(group_db))
    src.row_factory = sqlite3.Row
    dst = None
    try:
        dst = sqlite3.connect(str(out_path))
        dst.execute("ATTACH DATABASE ? AS srcdb", (str(group_db),))

        existing = {row[0] for row in src.execute(
            "SELECT name FROM sqlite_master WHERE type='table'")}
        shadow_prefixes = tuple(f"{fts}_" for fts in FTS_TABLES)
        tables = [
            t for t in KbMigrator._DOC_TABLES
            if t in existing and not t.startswith(shadow_prefixes)
        ]
        missing = [t for t in KbMigrator._DOC_TABLES if t not in existing]
        if missing:
            logger.info("切片跳过源库缺失表（旧库兼容）: %s", missing)

        # 1) 建表 + 2) 重建索引（DDL 原样）
        _copy_ddl(src, dst, tables)

        # 3) 拷数据（逐表计数）
        counts: Dict[str, int] = {}
        for table in tables:
            cols = [r[1] for r in src.execute(f'PRAGMA table_info("{table}")')]
            if not cols:
                continue
            if "library_id" in cols:
                where, params = "library_id = ?", [library_id]
            elif "doc_id" in cols:
                where, params = (
                    "doc_id IN (SELECT doc_id FROM srcdb.canonical_documents WHERE library_id = ?)",
                    [library_id],
                )
            else:
                logger.warning("切片跳过无 library_id/doc_id 列的表: %s", table)
                continue
            counts[table] = _insert_select(dst, table, where, params)

        # 4) 触发器最后建（拷数据期不触发；定义随库带走）
        ph = ",".join("?" for _ in tables)
        for row in src.execute(
            f"SELECT sql FROM sqlite_master WHERE type='trigger' AND sql IS NOT NULL "
            f"AND tbl_name IN ({ph})", list(tables),
        ):
            dst.execute(row[0])

        dst.commit()
        docs = counts.get("canonical_documents", 0)
        chunks = counts.get("canonical_chunks", 0)
    except Exception:
        _close_quietly(dst)
        _close_quietly(src)
        _cleanup_sqlite_files(out_path)
        raise
    else:
        _close_quietly(dst)
        _close_quietly(src)
        return {"docs": docs, "chunks": chunks, "bytes": out_path.stat().st_size, "tables": counts}


def build_library_graph_slice(graph_db: Path, library_id: str, out_path: Path) -> Dict[str, Any]:
    """全局 graph.sqlite → 单库**闭包**切片（F17）。

    - relations/artifacts/deletions 按 ``library_id`` 过滤；
    - entities = 闭包：本库归属 ∪ 本库关系端点 ∪ 本库联结引用实体
      （允许含归属他库的行——本库引用所致，导入侧 FK 依赖它们在场）；
    - junctions 按本库父 id 抽全行；
    - 写入顺序 entities → artifacts → junctions → deletions → relations（与导入合并同序）；
    - 切片构建连接 FK OFF 纯拷贝：漏闭包以调用方 ``PRAGMA foreign_key_check`` 完整诊断暴露，
      而非中途 abort；返回 ``{"relations", "tables", "fk_violations"}``——fk_violations 为
      切片内**继承自源库**的悬空行计数（P1-7 实采：生产 graph.sqlite 存在实体删除残留的悬空
      relation/junction 436 条，切片忠实镜像并计数上报，导入侧据此区分「切片缺漏 vs 源数据脏」）；
      失败清理半成品。
    """
    graph_db = Path(graph_db)
    out_path = Path(out_path)

    out_path.parent.mkdir(parents=True, exist_ok=True)
    _cleanup_sqlite_files(out_path)

    checkpoint_sqlite(graph_db)

    src = sqlite3.connect(str(graph_db))
    src.row_factory = sqlite3.Row
    dst = None
    try:
        dst = sqlite3.connect(str(out_path))
        dst.execute("ATTACH DATABASE ? AS srcdb", (str(graph_db),))

        existing = {row[0] for row in src.execute(
            "SELECT name FROM sqlite_master WHERE type='table'")}
        tables = [t for t in GRAPH_TABLES if t in existing]
        missing = [t for t in GRAPH_TABLES if t not in existing]
        if missing:
            logger.warning("图谱切片源缺表（旧库）: %s", missing)

        _copy_ddl(src, dst, tables)

        counts: Dict[str, int] = {}
        # 1) 实体闭包
        if "graph_entities" in tables:
            counts["graph_entities"] = _insert_select(
                dst, "graph_entities", _ENTITY_CLOSURE_SQL, [library_id] * 6)
        # 2) artifacts 按库
        for table in _GRAPH_ARTIFACTS:
            if table in tables:
                counts[table] = _insert_select(dst, table, "library_id = ?", [library_id])
        # 3) 联结按本库父 id 抽全行
        for table, parent_col, parent_table in _GRAPH_JUNCTIONS:
            if table in tables and parent_table in tables:
                counts[table] = _insert_select(
                    dst, table,
                    f"{parent_col} IN (SELECT {parent_col} FROM srcdb.{parent_table} "
                    f"WHERE library_id = ?)",
                    [library_id],
                )
        # 4) 删除墓碑按库
        if "graph_entity_deletions" in tables:
            counts["graph_entity_deletions"] = _insert_select(
                dst, "graph_entity_deletions", "library_id = ?", [library_id])
        # 5) 关系按库（闭包实体会随后被端点检索到，顺序须在实体之后）
        if "graph_relations" in tables:
            counts["graph_relations"] = _insert_select(
                dst, "graph_relations", "library_id = ?", [library_id])

        dst.commit()
        relations = counts.get("graph_relations", 0)
        # 计数（不 abort）：悬空行多为源库历史脏数据，切片只做忠实镜像；区分判据留给导入侧
        fk_violations = len(dst.execute("PRAGMA foreign_key_check").fetchall())
    except Exception:
        _close_quietly(dst)
        _close_quietly(src)
        _cleanup_sqlite_files(out_path)
        raise
    else:
        _close_quietly(dst)
        _close_quietly(src)
        return {"relations": relations, "tables": counts, "fk_violations": fk_violations}


# ---------------------------------------------------------------- 向量按库快照（P1-4）

TEMP_COLLECTION_PREFIX = "exp-tmp-"
_SCROLL_BATCH_SIZE = 1024
_UPSERT_BATCH_SIZE = 256


def _qdrant_client():
    """与 QdrantVectorStore 同配置的客户端（惰性导入；trust_env=False 防系统代理劫持本地流量）。"""
    from docs_core.step06_vectors.config import (
        get_qdrant_api_key,
        get_qdrant_timeout,
        get_qdrant_url,
    )
    from qdrant_client import QdrantClient

    return QdrantClient(
        url=get_qdrant_url(),
        api_key=get_qdrant_api_key() or None,
        timeout=get_qdrant_timeout(),
        trust_env=False,
    )


def library_owns_collection_exclusively(library_id: str, collection: str) -> bool:
    """源 collection 是否仅本库独占（无第二个库指向它）。

    含 retired 一起扫：退役库的残留向量仍在源集合里，独占直取会连它一起打包。
    """
    if not collection:
        return False
    peers = [
        r for r in library_registry.list_libraries(include_retired=True)
        if r.collection == collection and r.library_id != library_id
    ]
    return not peers


def cleanup_stale_temp_collections(client=None) -> list:
    """清扫历史导出残留的 ``exp-tmp-*`` 临时集合（导出开始时调用；单飞导出下安全）。"""
    client = client or _qdrant_client()
    removed = []
    for col in client.get_collections().collections:
        name = str(getattr(col, "name", "") or "")
        if not name.startswith(TEMP_COLLECTION_PREFIX):
            continue
        try:
            client.delete_collection(name)
        except Exception as exc:  # noqa: BLE001 — 残留清扫失败不阻断本次导出
            logger.warning("临时集合清扫失败: %s: %s", name, exc)
            continue
        removed.append(name)
    return sorted(removed)


def copy_collection_points(client, source: str, target: str, scroll_filter, *,
                           scroll_batch: int = _SCROLL_BATCH_SIZE,
                           upsert_batch: int = _UPSERT_BATCH_SIZE) -> int:
    """按 filter scroll 源集合、原样 upsert 进目标集合（保 point id + payload + 向量）。

    公共函数：P1-4 快照临时集合与 P2 导入兜底路径（快照 recover 不可用时的复制通道）共用。
    """
    from qdrant_client import models

    total = 0
    offset = None
    while True:
        points, offset = client.scroll(
            collection_name=source,
            scroll_filter=scroll_filter,
            with_payload=True,
            with_vectors=True,
            limit=scroll_batch,
            offset=offset,
        )
        if points:
            structs = [
                models.PointStruct(id=p.id, vector=p.vector, payload=p.payload) for p in points
            ]
            for start in range(0, len(structs), upsert_batch):
                client.upsert(
                    collection_name=target,
                    points=structs[start:start + upsert_batch],
                    wait=True,
                )
            total += len(points)
        if offset is None:
            break
    return total


def _create_collection_like(client, source: str, target: str) -> None:
    """克隆源集合配置建临时集合（dim/metric/量化/HNSW 原样），并补 payload 索引。

    注意：GET 回来的 ``config.hnsw_config`` 是 ``HnswConfig``（全量态），而 create_collection
    的入参要 ``HnswConfigDiff``（P1-7 实采：直接传会 pydantic ValidationError）——按字段名过滤转换。
    quantization 的 GET 与 create 共用同一批类（Scalar/Product/Binary/Turbo），原样传即合法。
    """
    from qdrant_client import models

    info = client.get_collection(source)
    hnsw = info.config.hnsw_config
    hnsw_diff = None
    if hnsw is not None:
        allowed = set(models.HnswConfigDiff.model_fields)
        hnsw_diff = models.HnswConfigDiff(**{
            k: v for k, v in hnsw.model_dump().items() if k in allowed and v is not None
        })
    client.create_collection(
        collection_name=target,
        vectors_config=info.config.params.vectors,
        hnsw_config=hnsw_diff,
        quantization_config=info.config.quantization_config,
        sparse_vectors_config=info.config.params.sparse_vectors,
    )
    for field_name in ("doc_id", "library_id"):
        client.create_payload_index(
            collection_name=target,
            field_name=field_name,
            field_schema=models.PayloadSchemaType.KEYWORD,
        )


def _delete_collection_quietly(client, name: str) -> None:
    try:
        client.delete_collection(name)
    except Exception as exc:  # noqa: BLE001 — 下次导出开局清扫兜底
        logger.warning("临时集合清理失败（下次导出开局清扫兜底）: %s: %s", name, exc)


@contextmanager
def library_vector_snapshot(library_id: str, collection: str, *, exclusive: bool = False,
                            client=None) -> Iterator[Dict[str, Any]]:
    """产本库向量快照，yield ``{collection, snapshot, size, points, temporary}``。

    - 非独占（默认）：建 ``exp-tmp-<lib>-<ts>`` 克隆集合 → 按 library_id 过滤拷点
      （保 id/payload）→ 建快照；
    - ``exclusive=True``（registry 无第二库指向该集合，见 ``library_owns_collection_exclusively``）：
      跳过拷贝直接快照源集合；
    - 退出时删快照（+临时集合）——调用方须在 with 内把快照流进包（``open_snapshot``）。
    """
    client = client or _qdrant_client()
    temporary = not exclusive
    target = collection
    points: Optional[int] = None
    name = ""
    try:
        if temporary:
            target = f"{TEMP_COLLECTION_PREFIX}{library_id}-{int(time.time())}"
            _create_collection_like(client, collection, target)
            from qdrant_client import models

            flt = models.Filter(must=[models.FieldCondition(
                key="library_id", match=models.MatchValue(value=library_id))])
            points = copy_collection_points(client, collection, target, flt)
        name, size = create_snapshot(target)
    except Exception:
        if temporary and target != collection:
            _delete_collection_quietly(client, target)
        raise
    try:
        yield {"collection": target, "snapshot": name, "size": size,
               "points": points, "temporary": temporary}
    finally:
        delete_snapshot(target, name)
        if temporary:
            _delete_collection_quietly(client, target)
