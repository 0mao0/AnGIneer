"""按库图谱文件定位与全局→按库一次性拆分（plan-graph-per-library-split）。

目标形态：每库一份 ``graph.sqlite``（``library_root(<lib>)/graph.sqlite``，与
index.sqlite 同构）。全局 ``knowledge/graph.sqlite`` 退化为**迁移源**：启动拆分
成功后改名 ``graph.sqlite.migrated-<ts>`` 留档，业务不再读写。

访问统一走 :func:`resolve_graph_db_for_library`：库文件存在用库文件；否则全局
文件仍在（拆分前/拆分失败）用全局——**读写同源**，拆分窗口不会出现读写分叉；
两者皆缺返回库文件路径（新库就地创建，与旧行为等价）。

拆分保 FK：relations/junction 带 ``REFERENCES graph_entities(entity_id)``，跨库
端点实体随行拷贝进引用方文件（数据仍以自身 library_id 文件为准，拷贝件仅为满足
同文件 FK；跨库共享语义自拆分起终止，与 ``UNIQUE(name, library_id)`` 一致）。
历史悬空行（P1-7：源库本就有 436 条删除残留）忠实落盘不清洗。
"""
import logging
import shutil
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

# 与 corpus_import_apply.GRAPH_ORDER 同序：先实体/工件、后联结、删除、关系。
_SPLIT_ORDER = (
    "graph_entities",
    "graph_principles",
    "graph_examples",
    "graph_warnings",
    "graph_frameworks",
    "principle_entities",
    "example_entities",
    "warning_entities",
    "graph_entity_deletions",
    "graph_relations",
)
_JUNCTION_PARENT = {
    "principle_entities": ("graph_principles", "principle_id"),
    "example_entities": ("graph_examples", "example_id"),
    "warning_entities": ("graph_warnings", "warning_id"),
}
_ARTIFACT_JUNCTION = {
    "graph_principles": "principle_entities",
    "graph_examples": "example_entities",
    "graph_warnings": "warning_entities",
}


def library_graph_db_path(library_id: str, base_dir: Path | str | None = None) -> Path:
    """按库图谱文件：``<库根>/graph.sqlite``（library_root 已含组路由）。"""
    from ..paths import library_root

    return library_root(library_id, base_dir=base_dir) / "graph.sqlite"


def global_graph_db_path(base_dir: Path | str | None = None) -> Path:
    """迁移源（旧全局文件）：``<knowledge 根>/graph.sqlite``。"""
    if base_dir is not None:
        return Path(base_dir) / "graph.sqlite"
    from ..paths import resolve_graph_db_path

    return resolve_graph_db_path()


def resolve_graph_db_for_library(library_id: str, base_dir: Path | str | None = None) -> Path:
    """业务读写唯一入口：库文件 > 全局文件（迁移前/失败回退）> 库文件（新建）。"""
    per_lib = library_graph_db_path(library_id, base_dir=base_dir)
    if per_lib.exists():
        return per_lib
    legacy = global_graph_db_path(base_dir)
    if legacy.exists():
        return legacy
    return per_lib


def iter_library_graph_paths(base_dir: Path | str | None = None) -> List[Tuple[str, Path]]:
    """枚举现存按库图谱文件 ``[(library_id, path)]``。

    注册表库 + 库目录直扫并集（直扫兜住注册表外的幽灵库）；按 library_id 去重。
    """
    roots: List[Path] = []
    if base_dir is not None:
        roots.append(Path(base_dir) / "libraries")
    else:
        from .. import library_registry
        from ..paths import resolve_knowledge_base_dir

        roots.append(resolve_knowledge_base_dir() / "libraries")
        try:
            for rec in library_registry.list_libraries(include_retired=False):
                roots.append(library_registry.resolve_libraries_dir(rec.library_id))
        except Exception:  # noqa: BLE001  注册表不可用时不影响直扫
            logger.warning("枚举库注册表失败，仅按目录直扫图谱文件", exc_info=True)
    found: Dict[str, Path] = {}
    for root in roots:
        if not root.is_dir():
            continue
        for child in sorted(root.iterdir()):
            if not child.is_dir():
                continue
            candidate = child / "graph.sqlite"
            if candidate.exists() and child.name not in found:
                found[child.name] = candidate
    return sorted(found.items())


def find_graph_db_for_entity(
    entity_id: str, base_dir: Path | str | None = None
) -> Optional[Tuple[str, Path]]:
    """按 entity_id 定位所在**自有**库文件（维护/梦境循环按 id 操作用）。

    跨库端点实体会以拷贝件出现在引用方文件，因此优先匹配 ``library_id`` 与
    目录名一致的自有行；自有未命中再退而匹配任意文件（空标行兜底）。
    拆分前全局文件仍在时兜底查全局。
    """
    fallback_hit: Optional[Tuple[str, Path]] = None
    for library_id, path in iter_library_graph_paths(base_dir=base_dir):
        conn = sqlite3.connect(str(path))
        try:
            own = conn.execute(
                "SELECT library_id FROM graph_entities WHERE entity_id = ? AND library_id = ?",
                (entity_id, library_id),
            ).fetchone()
            if own is None and fallback_hit is None:
                any_row = conn.execute(
                    "SELECT library_id FROM graph_entities WHERE entity_id = ?", (entity_id,)
                ).fetchone()
                if any_row is not None:
                    fallback_hit = (str(any_row[0]) if any_row[0] else library_id, path)
        finally:
            conn.close()
        if own is not None:
            return (str(own[0]) if own[0] else library_id, path)
    if fallback_hit is not None:
        return fallback_hit
    legacy = global_graph_db_path(base_dir)
    if legacy.exists():
        conn = sqlite3.connect(str(legacy))
        try:
            row = conn.execute(
                "SELECT library_id FROM graph_entities WHERE entity_id = ?", (entity_id,)
            ).fetchone()
        finally:
            conn.close()
        if row is not None:
            return (str(row[0]) if row[0] else "default", legacy)
    return None


def _table_cols(conn: sqlite3.Connection, table: str) -> List[str]:
    return [r[1] for r in conn.execute(f'PRAGMA table_info("{table}")')]


def _norm_lib(value: object) -> str:
    return str(value or "").strip()


def split_global_graph_if_present(
    base_dir: Path | str | None = None, log: Optional[logging.Logger] = None
) -> Optional[Dict[str, object]]:
    """全局 graph.sqlite → 每库文件一次性拆分（幂等，启动时调用）。

    返回拆分报告；全局文件不存在（已拆/从未有）返回 None。逐表对账不一致即
    raise（源文件不动，业务继续走全局回退）；无法归属库的行跳过并计数、
    从对账分母剔除（历史脏数据不阻断拆分）。
    """
    log = log or logger
    global_db = global_graph_db_path(base_dir)
    if not global_db.exists():
        return None

    src = sqlite3.connect(str(global_db))
    try:
        if "library_id" not in _table_cols(src, "graph_entities"):
            src.close()
            from .graph_store import GraphStore

            GraphStore(str(global_db)).close()  # 触发旧列 → library_id 重建迁移
            import gc

            gc.collect()
            src = sqlite3.connect(str(global_db))
        src.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        table_names = {
            r[0] for r in src.execute("SELECT name FROM sqlite_master WHERE type='table'")
        }
        rows_by_table: Dict[str, List[Dict[str, object]]] = {}
        for table in _SPLIT_ORDER:
            if table not in table_names:
                continue
            cols = _table_cols(src, table)
            rows_by_table[table] = [
                dict(zip(cols, r)) for r in src.execute(f'SELECT {",".join(cols)} FROM "{table}"')
            ]
    finally:
        src.close()

    entity_lib: Dict[str, str] = {
        str(r["entity_id"]): _norm_lib(r.get("library_id")) or "default"
        for r in rows_by_table.get("graph_entities", [])
    }
    # 工件空标 → 经其联结实体归属兜底（联结行本身也无标时留空，走 resolve_lib 兜底链）。
    artifact_lib: Dict[str, str] = {}
    for artifact_table, junction_table in _ARTIFACT_JUNCTION.items():
        key = _JUNCTION_PARENT[junction_table][1]
        for row in rows_by_table.get(junction_table, []):
            entity_owner = entity_lib.get(str(row.get("entity_id")), "")
            if entity_owner:
                artifact_lib.setdefault(str(row.get(key)), entity_owner)

    owner: Dict[str, Dict[str, List[Dict[str, object]]]] = {t: {} for t in _SPLIT_ORDER}
    skipped: Dict[str, int] = {t: 0 for t in _SPLIT_ORDER}

    def resolve_lib(table: str, row: Dict[str, object]) -> str:
        own = _norm_lib(row.get("library_id"))
        if own:
            return own
        if table == "graph_relations":
            return (
                entity_lib.get(str(row.get("source_id")))
                or entity_lib.get(str(row.get("target_id")))
                or ""
            )
        if table in _JUNCTION_PARENT:
            parent_table, parent_key = _JUNCTION_PARENT[table]
            for p in rows_by_table.get(parent_table, []):
                if str(p.get(parent_key)) == str(row.get(parent_key)):
                    plib = _norm_lib(p.get("library_id"))
                    if plib:
                        return plib
            return entity_lib.get(str(row.get("entity_id"))) or ""
        if table in _ARTIFACT_JUNCTION:
            return artifact_lib.get(str(row.get(next(
                k for k in ("principle_id", "example_id", "warning_id") if k in row
            ))), "")
        if table in ("graph_entities", "graph_entity_deletions"):
            return "default"  # 空/缺标归 default（与 schema DEFAULT 一致）
        return ""

    for table in _SPLIT_ORDER:
        for row in rows_by_table.get(table, []):
            lib = resolve_lib(table, row)
            if not lib:
                skipped[table] += 1
                if skipped[table] <= 3:
                    log.warning("图谱拆分：%s 存在无法归属库的行（sample=%s）", table, str(row)[:120])
                continue
            owner[table].setdefault(lib, []).append(row)

    # 每库需在场的实体 = 自有 ∪ 关系端点 ∪ 联结引用（跨库端点随行拷贝保 FK）。
    needed_entities: Dict[str, set] = {}
    for lib, rows in owner["graph_entities"].items():
        needed_entities.setdefault(lib, set()).update(str(r["entity_id"]) for r in rows)
    for row in rows_by_table.get("graph_relations", []):
        lib = resolve_lib("graph_relations", row)
        for key in ("source_id", "target_id"):
            eid = str(row.get(key))
            if lib and eid in entity_lib:
                needed_entities.setdefault(lib, set()).add(eid)
    for table in _JUNCTION_PARENT:
        for row in rows_by_table.get(table, []):
            lib = resolve_lib(table, row)
            eid = str(row.get("entity_id"))
            if lib and eid in entity_lib:
                needed_entities.setdefault(lib, set()).add(eid)

    from .graph_store import GraphStore

    lib_stats: Dict[str, Dict[str, int]] = {}
    for lib in sorted({lib for t in _SPLIT_ORDER for lib in owner[t]}):
        target = library_graph_db_path(lib, base_dir=base_dir)
        target.parent.mkdir(parents=True, exist_ok=True)
        if target.exists():
            target.unlink()
        store = GraphStore(str(target))
        store.close()
        import gc

        gc.collect()  # GraphStore 初始化连接进引用循环；不 gc 会锁住新库文件（Windows）
        dst = sqlite3.connect(str(target))
        try:
            dst.execute("PRAGMA foreign_keys=OFF")
            dst.execute("BEGIN IMMEDIATE")
            for table in _SPLIT_ORDER:
                if table == "graph_entities":
                    ids = needed_entities.get(lib, set())
                    rows = [
                        {**r, "library_id": _norm_lib(r.get("library_id")) or "default"}
                        for r in rows_by_table.get("graph_entities", [])
                        if str(r["entity_id"]) in ids
                    ]
                else:
                    # 空标行归一为解析出的归属库：单库文件必须全表 library_id 自洽
                    # （导出切片/导入对账都按 library_id=? 过滤，空标会漏）
                    rows = [
                        ({**r, "library_id": lib} if "library_id" in r and not _norm_lib(r.get("library_id")) else r)
                        for r in owner.get(table, {}).get(lib, [])
                    ]
                if not rows:
                    continue
                cols = [c for c in _table_cols(dst, table) if c in rows[0]]
                marks = ",".join("?" * len(cols))
                dst.executemany(
                    f'INSERT OR REPLACE INTO "{table}" ({",".join(cols)}) VALUES ({marks})',
                    [tuple(r[c] for c in cols) for r in rows],
                )
                lib_stats.setdefault(lib, {})[table] = len(rows)
            dst.commit()
        finally:
            dst.close()

    # 对账：可归属行必须恰好落一处（实体按自有归属逐库核对）。
    for table in _SPLIT_ORDER:
        if table == "graph_entities":
            for lib, rows in owner["graph_entities"].items():
                conn = sqlite3.connect(str(library_graph_db_path(lib, base_dir=base_dir)))
                try:
                    own = conn.execute(
                        "SELECT COUNT(*) FROM graph_entities WHERE library_id = ?", (lib,)
                    ).fetchone()[0]
                finally:
                    conn.close()
                if own != len(rows):
                    raise RuntimeError(
                        f"图谱拆分对账失败：graph_entities[{lib}] 目标 {own} != 源 {len(rows)}"
                    )
            continue
        source_total = sum(len(v) for v in owner.get(table, {}).values())
        placed = sum(stats.get(table, 0) for stats in lib_stats.values())
        if placed != source_total:
            raise RuntimeError(
                f"图谱拆分对账失败：{table} 落文件合计 {placed} != 源 {source_total}"
            )

    backup = global_db.parent / (
        "graph.sqlite.migrated-" + datetime.now().strftime("%Y%m%d%H%M%S")
    )
    shutil.move(str(global_db), str(backup))
    for suffix in ("-wal", "-shm"):
        stale = global_db.parent / f"graph.sqlite{suffix}"
        if stale.exists():
            stale.unlink()
    counts = {
        t: sum(len(v) for v in owner.get(t, {}).values()) for t in _SPLIT_ORDER
    }
    skipped_total = {t: n for t, n in skipped.items() if n}
    report: Dict[str, object] = {
        "source": str(global_db),
        "backup": str(backup),
        "counts": counts,
        "skipped": skipped_total,
        "libraries": {lib: stats for lib, stats in sorted(lib_stats.items())},
    }
    log.info("图谱按库拆分完成：%s -> 各库文件，备份 %s，counts=%s，skipped=%s",
             global_db, backup, counts, skipped_total)
    return report
