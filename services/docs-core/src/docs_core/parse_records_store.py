"""解析记录表（parse_records.sqlite）的表结构与同步逻辑——单一真相源。

为什么要放 docs-core：这张表是管理端「日常维护」页的数据源，而它的写入此前只发生在
docs-api 注入的 `record_updater` 里（`docs-api/orchestrator.py`）。脚本 / 进程内路径直接
`ParseOrchestrator()` 时没有注入，文档就只进 `knowledge_meta.nodes`、不进 parse_records，
管理端整篇看不见（2026-09-14 实测：盘上 295 篇文档有 189 篇不在流水——lib-b07ed174 117 篇
只显示 2 篇、lawbench 60 篇一篇不显示）。表结构放这里后 `ParseOrchestrator` 默认就能写流水，
所有入库路径统一，不再依赖"记得注入"。

写入语义（沿用 docs-api 原实现，勿单独改一处）：
- `processing`：先把 `pending-<doc_id>` 占位记录改名成真实 task_id；没有占位记录就复用同 doc
  最新一条；都没有才新建一条（此时才需要 actor 兜底）。
- 其他状态：按 task_id 更新状态与错误。
"""
from __future__ import annotations

import logging
import os
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

logger = logging.getLogger("docs_core.parse_records_store")

DB_NAME = "parse_records.sqlite"


def db_path() -> str:
    """记录库路径：`PARSE_RECORDS_DB_PATH` 优先（测试/多环境），否则仓库 data 目录。

    每次调用都读环境变量（不在导入期固化），测试里改环境变量后无需重载模块。
    """
    override = os.environ.get("PARSE_RECORDS_DB_PATH")
    if override:
        return override
    from docs_core.paths import resolve_repo_root

    return str(resolve_repo_root() / "data" / DB_NAME)


def connect() -> sqlite3.Connection:
    os.makedirs(os.path.dirname(db_path()), exist_ok=True)
    conn = sqlite3.connect(db_path())
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


def init_schema(conn: sqlite3.Connection) -> None:
    """建表 + 补列 + 建索引（幂等）。docs-api 侧同名函数复用本实现，避免两处 DDL 漂移。"""
    conn.execute("""
        CREATE TABLE IF NOT EXISTS parse_records (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            doc_id TEXT NOT NULL,
            task_id TEXT NOT NULL,
            uploaded_by TEXT NOT NULL DEFAULT '',
            api_key_id INTEGER,
            file_name TEXT NOT NULL DEFAULT '',
            file_format TEXT NOT NULL DEFAULT '',
            file_size INTEGER NOT NULL DEFAULT 0,
            status TEXT NOT NULL DEFAULT 'queued',
            error TEXT,
            created_at TEXT NOT NULL
        )
    """)
    columns = {row[1] for row in conn.execute("PRAGMA table_info(parse_records)")}
    if "library_id" not in columns:
        conn.execute("ALTER TABLE parse_records ADD COLUMN library_id TEXT NOT NULL DEFAULT 'default'")
    if "stages" not in columns:
        conn.execute("ALTER TABLE parse_records ADD COLUMN stages TEXT NOT NULL DEFAULT ''")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_pr_created ON parse_records(created_at DESC)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_pr_uploaded ON parse_records(uploaded_by)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_pr_status ON parse_records(status)")
    conn.commit()


def insert_record(*, doc_id: str, task_id: str, uploaded_by: str = "", file_name: str = "",
                  file_format: str = "", file_size: int = 0, status: str = "queued",
                  error: Optional[str] = None, library_id: str = "default", stages: str = "",
                  created_at: Optional[str] = None) -> int:
    conn = connect()
    try:
        init_schema(conn)
        conn.execute(
            """INSERT INTO parse_records (doc_id, task_id, uploaded_by, api_key_id,
               file_name, file_format, file_size, status, error, created_at, library_id, stages)
               VALUES (?, ?, ?, NULL, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (doc_id, task_id, uploaded_by, file_name, file_format, file_size, status, error,
             created_at or datetime.now(timezone.utc).isoformat(), library_id, stages),
        )
        conn.commit()
        return int(conn.execute("SELECT last_insert_rowid()").fetchone()[0])
    finally:
        conn.close()


def update_status(task_id: str, status: str, error: Optional[str] = None) -> bool:
    conn = connect()
    try:
        init_schema(conn)
        if error:
            conn.execute("UPDATE parse_records SET status = ?, error = ? WHERE task_id = ?",
                         (status, error, task_id))
        else:
            conn.execute("UPDATE parse_records SET status = ? WHERE task_id = ?", (status, task_id))
        conn.commit()
        affected = conn.total_changes
        return affected > 0
    finally:
        conn.close()


def update_task_id(old_task_id: str, new_task_id: str) -> bool:
    conn = connect()
    try:
        init_schema(conn)
        conn.execute("UPDATE parse_records SET task_id = ? WHERE task_id = ?", (new_task_id, old_task_id))
        conn.commit()
        affected = conn.total_changes
        return affected > 0
    finally:
        conn.close()


def update_by_doc_id(doc_id: str, new_task_id: str, new_status: str) -> bool:
    """复用该文档最新一条非删除记录，并清掉同 doc 的旧重复（保留最新）。"""
    conn = connect()
    try:
        init_schema(conn)
        # 只更新最新那条；不动 created_at，避免重新解析后条目被顶到列表最前
        conn.execute(
            "UPDATE parse_records SET task_id = ?, status = ?, error = NULL "
            "WHERE id = (SELECT id FROM parse_records WHERE doc_id = ? AND status != 'deleted' "
            "ORDER BY created_at DESC LIMIT 1)",
            (new_task_id, new_status, doc_id),
        )
        affected = conn.total_changes
        conn.execute(
            "DELETE FROM parse_records WHERE id NOT IN "
            "(SELECT id FROM parse_records WHERE doc_id = ? AND status != 'deleted' "
            "ORDER BY created_at DESC LIMIT 1) AND doc_id = ? AND status != 'deleted'",
            (doc_id, doc_id),
        )
        conn.commit()
        return affected > 0
    finally:
        conn.close()


def _file_name_of(path: str) -> str:
    """按分隔符拆出文件名；迁移遗留的 Windows 路径（Linux 上 os.path 不认 '\'）不能整串当名字。"""
    if path and "\\" in path and "/" not in path:
        return path.rsplit("\\", 1)[-1]
    return os.path.basename(path)


def _document_meta(doc_id: str) -> dict:
    """从知识库节点补文件元信息（名称/格式/大小/所属库）——管理端表格要显示这些列。"""
    meta: dict = {"library_id": "default", "file_name": "", "file_format": "", "file_size": 0}
    try:
        from docs_core.docs_service import get_docs_service

        node = get_docs_service().get_node(doc_id)
    except Exception:  # noqa: BLE001 查不到节点不该影响流水写入
        return meta
    if node is None:
        return meta
    meta["library_id"] = node.library_id or "default"
    path = node.file_path or ""
    meta["file_name"] = _file_name_of(path) or (node.title or "")
    if path:
        meta["file_format"] = os.path.splitext(path)[1].lstrip(".").lower()
        try:
            meta["file_size"] = os.path.getsize(path)
        except OSError:
            pass
    return meta


def _backfill_file_meta_if_empty(task_id: str, doc_id: str) -> None:
    """终态更新时，若流水行文件元信息为空（建 row 时节点查失败的历史形态），从节点补一次。

    只填空列，绝不覆盖已有值；节点仍查不到则保持空，等待下一次状态变化再补。
    """
    conn = connect()
    try:
        init_schema(conn)
        row = conn.execute(
            "SELECT file_name FROM parse_records WHERE task_id = ?", (task_id,)
        ).fetchone()
        if row is None or (row["file_name"] or ""):
            return
        meta = _document_meta(doc_id)
        if not meta["file_name"]:
            return
        conn.execute(
            "UPDATE parse_records SET file_name = ?, file_format = ?, file_size = ? "
            "WHERE task_id = ? AND file_name = ''",
            (meta["file_name"], meta["file_format"], meta["file_size"], task_id),
        )
        conn.commit()
    finally:
        conn.close()


def sync_record_for_task(task_id: str, doc_id: str, status: str, error: Optional[str] = None,
                         *, actor: str = "管理员") -> None:
    """解析编排器的记录同步钩子：`record_updater(task_id, doc_id, status, error)`。

    由 `ParseOrchestrator` 默认使用（脚本/进程内路径），docs-api 侧同签名复用。
    `actor` 只在"需要新建记录"时作为 uploaded_by 兜底，用于区分来源
    （界面/API=管理员，脚本=system:*）。
    """
    try:
        if status == "processing":
            # 占位记录改名 → 复用同 doc 最新一条 → 都没有才新建
            if update_task_id(f"pending-{doc_id}", task_id):
                update_status(task_id, "processing")
            elif not update_by_doc_id(doc_id, task_id, "processing"):
                meta = _document_meta(doc_id)
                insert_record(doc_id=doc_id, task_id=task_id, uploaded_by=actor, status="processing",
                              library_id=meta["library_id"], file_name=meta["file_name"],
                              file_format=meta["file_format"], file_size=meta["file_size"])
        else:
            update_status(task_id, status, error)
            if status in ("completed", "failed"):
                _backfill_file_meta_if_empty(task_id, doc_id)
    except Exception as exc:  # noqa: BLE001 记录同步失败不该打断解析
        logger.warning("同步解析记录失败 task=%s doc=%s: %s", task_id, doc_id, exc)
