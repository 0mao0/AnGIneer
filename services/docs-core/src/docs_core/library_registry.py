"""库组注册表：``library_id → 组 → 存储位置`` 的唯一真相源（docs/plan-kb-split-groups.md §二）。

设计约束：
- 落独立单文件 ``data/registry.sqlite``——不放任何组内 sqlite（knowledge_index 拆完自身就在
  组文件里，注册表存进去是鸡生蛋）；
- **读穿不缓存**——新库不重启不可见的老病（2026-09-30 启动快照事故），所有读取直查 SQLite；
- 未注册的 ``library_id`` 回退旧默认（``QDRANT_COLLECTION`` / 单文件 knowledge_index），
  行为与注册表出现前完全一致——注册表是增量真相源，不是硬切换。

路径口径：``sqlite_file`` 存**相对 data 根**的 POSIX 相对路径（如 ``knowledge/knowledge_index.sqlite``），
跨机器（开发机 D:\\AI\\AnGIneer ↔ 服务器 /home/runner/AnGIneer）可移植；读取时经
:func:`resolve_index_db_path` 拼回绝对路径。
"""

import os
import re
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
DATA_ROOT_ENV = "ANGINEER_DATA_ROOT"
REGISTRY_DB_NAME = "registry.sqlite"

STATUS_ACTIVE = "active"
STATUS_MIGRATING = "migrating"
STATUS_RETIRED = "retired"
_VALID_STATUS = {STATUS_ACTIVE, STATUS_MIGRATING, STATUS_RETIRED}

DEFAULT_GROUP = "standards"

# 组 → 存储默认。collection 阶段一已拆；sqlite_file 是阶段二目标组文件（注册行在 flip-sqlite
# 前仍挂 _DEFAULT_SQLITE_FILE 单文件）。libraries_dir 供目录归位（阶段二后半）使用。
# 评测 collection 定名 evals_corpus（与成绩库 evals.sqlite 区分，见 plan §九-5）。
GROUP_DEFAULTS: Dict[str, Dict[str, str]] = {
    "standards": {
        "collection": "standards",
        "sqlite_file": "knowledge/groups/standards.sqlite",
        "libraries_dir": "knowledge/libraries",
    },
    "dredgeai": {
        "collection": "dredgeai",
        "sqlite_file": "knowledge/groups/dredgeai.sqlite",
        "libraries_dir": "knowledge/libraries",
    },
    "evals": {
        "collection": "evals_corpus",
        "sqlite_file": "evals/groups/evals_corpus.sqlite",
        "libraries_dir": "evals/corpora/libraries",
    },
}

_DEFAULT_SQLITE_FILE = "knowledge/knowledge_index.sqlite"

# 自定义组名 slug 规则：组名会进文件路径（knowledge/groups/<组>.sqlite）与 qdrant
# collection 名，只许小写字母开头 + 小写/数字/_/-，2–32 位——挡掉路径穿越与中文组名
GROUP_NAME_RE = re.compile(r"^[a-z][a-z0-9_-]{1,31}$")

# 自定义组的派生存储布局（与内置组同口径：组文件 lazy、目录走公共 libraries 目录）
_CUSTOM_GROUP_SQLITE_FILE = "knowledge/groups/{group}.sqlite"
_CUSTOM_GROUP_LIBRARIES_DIR = "knowledge/libraries"

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
CREATE TABLE IF NOT EXISTS library_groups (
    group_name   TEXT PRIMARY KEY,
    display_name TEXT NOT NULL DEFAULT '',
    created_at   TEXT NOT NULL,
    updated_at   TEXT NOT NULL
);
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


@dataclass(frozen=True)
class GroupRecord:
    group_name: str
    display_name: str

    def to_dict(self) -> Dict[str, str]:
        return asdict(self)


def _group_defaults(group_name: str) -> Dict[str, str]:
    """组的存储默认：内置组查注册表；已登记的自定义组按约定派生；其余返回空表（走回退）。"""
    builtin = GROUP_DEFAULTS.get(group_name)
    if builtin is not None:
        return builtin
    if get_custom_group(group_name) is not None:
        return {
            "collection": group_name,
            "sqlite_file": _CUSTOM_GROUP_SQLITE_FILE.format(group=group_name),
            "libraries_dir": _CUSTOM_GROUP_LIBRARIES_DIR,
        }
    return {}


# ---- 路径解析 ----


def resolve_data_root() -> Path:
    """data/ 根目录（registry.sqlite 与 sqlite_file 相对路径的基准）。``ANGINEER_DATA_ROOT`` 可覆盖。"""
    env_override = os.getenv(DATA_ROOT_ENV, "").strip()
    if env_override:
        return Path(env_override).expanduser()
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
    defaults = _group_defaults(group_name)
    # sqlite_file 缺省推导：组文件已存在（flip-sqlite 后）走组文件，否则挂过渡单文件——
    # 新建库自动跟随该组当前实际存储位置，跨翻转窗口不出错
    if sqlite_file is None:
        group_file = defaults.get("sqlite_file")
        if group_file and (resolve_data_root() / group_file).exists():
            file_value = group_file
        else:
            file_value = _DEFAULT_SQLITE_FILE
    else:
        file_value = sqlite_file
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


def set_group(library_id: str, group_name: str) -> LibraryRecord:
    """改组迁移（多库管理 tab）：换组名 + 组默认 collection + sqlite_file 按新组现状重新推导。

    只改注册行，不搬数据——与 register_library 缺省推导同口径：新组组文件已存在则挂组文件，
    否则挂过渡单文件。数据物理搬迁属阶段二 flip，拆组前置条件见 plan-kb-split-groups。
    """
    if group_name not in GROUP_DEFAULTS and get_custom_group(group_name) is None:
        raise ValueError(f"未知库组: {group_name}（合法组 {sorted(GROUP_DEFAULTS)} + 已建自定义组）")
    defaults = _group_defaults(group_name)
    group_file = defaults.get("sqlite_file")
    file_value = group_file if group_file and (resolve_data_root() / group_file).exists() else _DEFAULT_SQLITE_FILE
    collection_value = defaults.get("collection") or group_name
    db_path = ensure_schema()
    now = datetime.now(timezone.utc).isoformat()

    def _write() -> None:
        with _connect() as conn:
            cursor = conn.execute(
                "UPDATE library_registry SET group_name=?, sqlite_file=?, collection=?, updated_at=? "
                "WHERE library_id=?",
                (group_name, file_value, collection_value, now, library_id),
            )
            if cursor.rowcount == 0:
                raise KeyError(f"注册表无此库: {library_id}")

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


# ---- 自定义库组（界面建组；内置三组仍是 GROUP_DEFAULTS 硬编码，不落此表） ----


def create_group(group_name: str, display_name: str = "") -> GroupRecord:
    """建/更新自定义组（幂等 upsert display_name）。组名走 slug 校验，禁止撞内置组名。"""
    if not GROUP_NAME_RE.match(group_name or ""):
        raise ValueError(
            f"非法组名: {group_name!r}（须以小写字母开头，仅小写字母/数字/_/-，2–32 位）"
        )
    if group_name in GROUP_DEFAULTS:
        raise ValueError(f"组名与内置组冲突: {group_name}（内置组不可覆盖）")
    display = (display_name or "").strip() or group_name
    db_path = ensure_schema()
    now = datetime.now(timezone.utc).isoformat()

    def _write() -> None:
        with _connect() as conn:
            conn.execute(
                """
                INSERT INTO library_groups (group_name, display_name, created_at, updated_at)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(group_name) DO UPDATE SET
                    display_name=excluded.display_name,
                    updated_at=excluded.updated_at
                """,
                (group_name, display, now, now),
            )

    run_with_write_lock(db_path, _write)
    record = get_custom_group(group_name)
    assert record is not None
    return record


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


def _groups_table_missing(conn: sqlite3.Connection) -> bool:
    """旧版 registry.sqlite 只有 library_registry 表（library_groups 随建组首写才出现）。
    读路径视「表不存在」= 无自定义组——不得顺手建表（显式初始化契约），
    2026-10-07 发版实踩：直查未建表的生产库让总览 500。"""
    return conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='library_groups'"
    ).fetchone() is None


def get_custom_group(group_name: str) -> Optional[GroupRecord]:
    """读穿查自定义组；注册表未初始化、无 groups 表或无此行返回 None。"""
    if not _registry_exists():
        return None
    with _connect() as conn:
        if _groups_table_missing(conn):
            return None
        row = conn.execute(
            "SELECT group_name, display_name FROM library_groups WHERE group_name=?",
            (group_name,),
        ).fetchone()
    return GroupRecord(group_name=row["group_name"], display_name=row["display_name"]) if row else None


def list_custom_groups() -> List[GroupRecord]:
    """全部自定义组（含尚未挂库的空组）；注册表未初始化或无 groups 表返回空表。"""
    if not _registry_exists():
        return []
    with _connect() as conn:
        if _groups_table_missing(conn):
            return []
        rows = conn.execute(
            "SELECT group_name, display_name FROM library_groups ORDER BY created_at ASC"
        ).fetchall()
    return [GroupRecord(group_name=r["group_name"], display_name=r["display_name"]) for r in rows]


# ---- 存储位置解析（注册表优先，回退旧默认） ----


def resolve_collection(library_id: str) -> str:
    """该库的 qdrant collection；未注册回退 ``QDRANT_COLLECTION`` 全局默认。"""
    record = get_library(library_id)
    if record is not None:
        return record.collection
    return get_qdrant_collection()


def resolve_index_db_path(library_id: str) -> Path:
    """该库的正文/FTS sqlite 绝对路径；未注册或登记为默认单文件时回退 knowledge_index 默认。

    默认单文件（``_DEFAULT_SQLITE_FILE``）走 ``paths.resolve_knowledge_index_db_path``
    （KNOWLEDGE_BASE_DIR 口径）而非 ``resolve_data_root()``：两者在生产同指，但测试用
    KNOWLEDGE_BASE_DIR 隔离实例时不经 ANGINEER_DATA_ROOT（2026-10-03 实踩：
    两套口径分叉致组路由把隔离实例的 default 库写到另一份 tmp 文件）。
    """
    record = get_library(library_id)
    if record is not None and record.sqlite_file != _DEFAULT_SQLITE_FILE:
        return resolve_data_root() / record.sqlite_file
    return resolve_knowledge_index_db_path()


def resolve_libraries_dir(library_id: str) -> Path:
    """该库解析产物根目录（目录归位后按组分目录）。

    组目标目录已在盘上存在（归位 mv 完成）才切过去，否则回退旧布局
    ``knowledge_base/libraries``——搬目录与切代码无先后依赖。
    """
    record = get_library(library_id)
    if record is not None:
        lib_dir = _group_defaults(record.group_name).get("libraries_dir")
        if lib_dir:
            candidate = resolve_data_root() / lib_dir
            if candidate.exists():
                return candidate
    from .paths import resolve_knowledge_base_dir

    return resolve_knowledge_base_dir() / "libraries"


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
    "DATA_ROOT_ENV",
    "GROUP_DEFAULTS",
    "GROUP_NAME_RE",
    "GroupRecord",
    "LibraryRecord",
    "REGISTRY_DB_ENV",
    "STATUS_ACTIVE",
    "STATUS_MIGRATING",
    "STATUS_RETIRED",
    "create_group",
    "ensure_schema",
    "get_custom_group",
    "get_library",
    "list_custom_groups",
    "list_libraries",
    "register_library",
    "resolve_collection",
    "set_group",
    "resolve_data_root",
    "resolve_index_db_path",
    "resolve_libraries_dir",
    "resolve_registry_db_path",
    "seed_from_meta",
    "set_status",
]
