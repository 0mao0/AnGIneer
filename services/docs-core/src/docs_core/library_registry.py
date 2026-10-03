"""库组注册表：``library_id → 组 → 存储位置`` 的唯一真相源（docs/plan-kb-split-groups.md §二）。

设计约束：
- 落独立单文件 ``data/registry.sqlite``——不放任何组内 sqlite（knowledge_index 拆完自身就在
  组文件里，注册表存进去是鸡生蛋）；
- **读穿不缓存**——新库不重启不可见的老病（2026-09-30 启动快照事故），所有读取直查 SQLite；
- 未注册的 ``library_id`` 回退旧默认（``QDRANT_COLLECTION`` / 单文件 knowledge_index），
  行为与注册表出现前完全一致——注册表是增量真相源，不是硬切换。

路径口径：``sqlite_file`` 存**相对 data 根**的 POSIX 相对路径（如 ``knowledge_base/knowledge_index.sqlite``），
跨机器（开发机 D:\\AI\\AnGIneer ↔ 服务器 /home/runner/AnGIneer）可移植；读取时经
:func:`resolve_index_db_path` 拼回绝对路径。
"""

import os
import sqlite3
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional

from .paths import resolve_knowledge_index_db_path, resolve_repo_root
from .step05_sqlite_fts.store.sqlite_utils import (
    create_connection,
    run_with_write_lock,
)
from .step06_vectors.config import get_qdrant_collection

REGISTRY_DB_ENV = "ANGINEER_REGISTRY_DB"
REGISTRY_DB_NAME = "registry.sqlite"

STATUS_ACTIVE = "active"
STATUS_MIGRATING = "migrating"
STATUS_RETIRED = "retired"
_VALID_STATUS = {STATUS_ACTIVE, STATUS_MIGRATING, STATUS_RETIRED}

DEFAULT_GROUP = "standards"

# 组 → 阶段一存储默认（sqlite 仍是单文件，阶段二再按组拆文件；collection 阶段一即按组拆）。
# 评测 collection 定名 evals_corpus（与成绩库 evals.sqlite 区分，见 plan §九-5）。
GROUP_DEFAULTS: Dict[str, Dict[str, str]] = {
    "standards": {"collection": "standards"},
    "dredgeai": {"collection": "dredgeai"},
    "evals": {"collection": "evals_corpus"},
}

_DEFAULT_SQLITE_FILE = "knowledge_base/knowledge_index.sqlite"

_SCHEMA = """
CREATE TABLE IF NOT EXISTS library_registry (
    library_id  TEXT PRIMARY KEY,
    name        TEXT NOT NULL DEFAULT '',
    description TEXT NOT NULL DEFAULT '',
    group_name  TEXT NOT NULL,
    sqlite_file TEXT NOT NULL,
    collection  TEXT NOT NULL,
    status      TEXT NOT NULL DEFAULT 'active',
    created_at  TEXT NOT NULL,
    updated_at  TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_library_registry_group ON library_registry(group_name);
"""


@dataclass(frozen=True)
class LibraryRecord:
    library_id: str
    name: str
    description: str
    group_name: str
    sqlite_file: str
    collection: str
    status: str

    def to_dict(self) -> Dict[str, str]:
        return asdict(self)


# ---- 路径解析 ----


def resolve_data_root() -> Path:
    """data/ 根目录（registry.sqlite 与 sqlite_file 相对路径的基准）。"""
    return resolve_repo_root() / "data"


def resolve_registry_db_path() -> Path:
    env_override = os.getenv(REGISTRY_DB_ENV, "").strip()
    if env_override:
        return Path(env_override).expanduser()
    return resolve_data_root() / REGISTRY_DB_NAME


# ---- 连接与 schema ----


def _connect() -> sqlite3.Connection:
    return create_connection(resolve_registry_db_path())


def ensure_schema(db_path: Optional[Path] = None) -> Path:
    """建库建表（幂等）。注册表只能显式初始化——纯读取不得顺手建文件（读缺失=回退，非错误）。"""
    path = db_path or resolve_registry_db_path()
    with create_connection(path) as conn:
        conn.executescript(_SCHEMA)
    return path


def _registry_exists() -> bool:
    return resolve_registry_db_path().exists()


# ---- 写入 ----


def register_library(
    library_id: str,
    *,
    name: str = "",
    description: str = "",
    group_name: str = DEFAULT_GROUP,
    sqlite_file: Optional[str] = None,
    collection: Optional[str] = None,
    status: str = STATUS_ACTIVE,
) -> LibraryRecord:
    """登记/更新注册行（幂等 upsert）。sqlite_file/collection 缺省按组默认推导。"""
    if status not in _VALID_STATUS:
        raise ValueError(f"非法注册状态: {status}（合法值 {sorted(_VALID_STATUS)}）")
    defaults = GROUP_DEFAULTS.get(group_name, {})
    file_value = sqlite_file or _DEFAULT_SQLITE_FILE
    collection_value = collection or defaults.get("collection") or group_name
    now = datetime.now(timezone.utc).isoformat()
    db_path = ensure_schema()

    def _write() -> None:
        with _connect() as conn:
            conn.execute(
                """
                INSERT INTO library_registry
                    (library_id, name, description, group_name, sqlite_file, collection, status, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(library_id) DO UPDATE SET
                    name=excluded.name,
                    description=excluded.description,
                    group_name=excluded.group_name,
                    sqlite_file=excluded.sqlite_file,
                    collection=excluded.collection,
                    status=excluded.status,
                    updated_at=excluded.updated_at
                """,
                (
                    library_id,
                    name,
                    description,
                    group_name,
                    file_value,
                    collection_value,
                    status,
                    now,
                    now,
                ),
            )

    run_with_write_lock(db_path, _write)
    record = get_library(library_id)
    assert record is not None
    return record


def set_status(library_id: str, status: str) -> None:
    if status not in _VALID_STATUS:
        raise ValueError(f"非法注册状态: {status}（合法值 {sorted(_VALID_STATUS)}）")
    db_path = ensure_schema()
    now = datetime.now(timezone.utc).isoformat()

    def _write() -> None:
        with _connect() as conn:
            cursor = conn.execute(
                "UPDATE library_registry SET status=?, updated_at=? WHERE library_id=?",
                (status, now, library_id),
            )
            if cursor.rowcount == 0:
                raise KeyError(f"注册表无此库: {library_id}")

    run_with_write_lock(db_path, _write)


# ---- 读取（读穿，不缓存） ----


def _row_to_record(row: sqlite3.Row) -> LibraryRecord:
    return LibraryRecord(
        library_id=row["library_id"],
        name=row["name"],
        description=row["description"],
        group_name=row["group_name"],
        sqlite_file=row["sqlite_file"],
        collection=row["collection"],
        status=row["status"],
    )


def get_library(library_id: str) -> Optional[LibraryRecord]:
    """读穿查单行；注册表未初始化或无此行返回 None（调用方走回退默认）。"""
    if not _registry_exists():
        return None
    with _connect() as conn:
        row = conn.execute(
            "SELECT library_id, name, description, group_name, sqlite_file, collection, status "
            "FROM library_registry WHERE library_id=?",
            (library_id,),
        ).fetchone()
    return _row_to_record(row) if row is not None else None


def list_libraries(*, include_retired: bool = False) -> List[LibraryRecord]:
    """注册表直出全部注册行（/knowledge/libraries 的数据源）；注册表未初始化返回空表。"""
    if not _registry_exists():
        return []
    sql = (
        "SELECT library_id, name, description, group_name, sqlite_file, collection, status "
        "FROM library_registry"
    )
    if not include_retired:
        sql += " WHERE status != 'retired'"
    sql += " ORDER BY created_at ASC"
    with _connect() as conn:
        rows = conn.execute(sql).fetchall()
    return [_row_to_record(row) for row in rows]


# ---- 存储位置解析（注册表优先，回退旧默认） ----


def resolve_collection(library_id: str) -> str:
    """该库的 qdrant collection；未注册回退 ``QDRANT_COLLECTION`` 全局默认。"""
    record = get_library(library_id)
    if record is not None:
        return record.collection
    return get_qdrant_collection()


def resolve_index_db_path(library_id: str) -> Path:
    """该库的正文/FTS sqlite 绝对路径；未注册回退单文件 knowledge_index 默认。"""
    record = get_library(library_id)
    if record is not None:
        return resolve_data_root() / record.sqlite_file
    return resolve_knowledge_index_db_path()


# ---- 种子（从 knowledge_meta libraries 表灌入） ----


def seed_from_meta(
    meta_db_path: Path,
    group_mapping: Dict[str, str],
    *,
    default_group: str = DEFAULT_GROUP,
    collection_override: Optional[str] = None,
) -> List[LibraryRecord]:
    """把 knowledge_meta.sqlite 的 libraries 表灌进注册表。

    ``group_mapping``：library_id → 组名 的显式映射（组归属是业务判断，不猜）；
    映射外的库落 ``default_group``。已注册的行不覆盖（幂等重跑安全）。
    ``collection_override``：零停机种子用法——全部行先指旧全局 collection（路由不变），
    拆桶对账后再翻转组默认（scripts/seed_library_registry.py --flip）。
    """
    seeded: List[LibraryRecord] = []
    with create_connection(Path(meta_db_path)) as conn:
        rows = conn.execute(
            "SELECT id, name, description FROM libraries ORDER BY created_at ASC"
        ).fetchall()
    for row in rows:
        if get_library(row["id"]) is not None:
            continue
        seeded.append(
            register_library(
                row["id"],
                name=row["name"] or "",
                description=row["description"] or "",
                group_name=group_mapping.get(row["id"], default_group),
                collection=collection_override,
            )
        )
    return seeded


__all__ = [
    "DEFAULT_GROUP",
    "GROUP_DEFAULTS",
    "LibraryRecord",
    "REGISTRY_DB_ENV",
    "STATUS_ACTIVE",
    "STATUS_MIGRATING",
    "STATUS_RETIRED",
    "ensure_schema",
    "get_library",
    "list_libraries",
    "register_library",
    "resolve_collection",
    "resolve_data_root",
    "resolve_index_db_path",
    "resolve_registry_db_path",
    "seed_from_meta",
    "set_status",
]
