"""解析记录统计模型 - 追踪每次解析操作的完整信息。"""
import os
import sqlite3
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

DB_PATH = os.environ.get("PARSE_RECORDS_DB_PATH", str(
    Path(__file__).resolve().parent.parent.parent.parent
    / "data" / "parse_records.sqlite"
))


@dataclass
class ParseRecord:
    id: Optional[int] = None
    doc_id: str = ""
    task_id: str = ""
    uploaded_by: str = ""
    api_key_id: Optional[int] = None
    file_name: str = ""
    file_format: str = ""
    file_size: int = 0
    status: str = "queued"
    error: Optional[str] = None
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


def _get_conn() -> sqlite3.Connection:
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


def init_db() -> None:
    conn = _get_conn()
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
    conn.execute("CREATE INDEX IF NOT EXISTS idx_pr_created ON parse_records(created_at DESC)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_pr_uploaded ON parse_records(uploaded_by)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_pr_status ON parse_records(status)")
    conn.commit()
    conn.close()


def insert_record(record: ParseRecord) -> int:
    init_db()
    conn = _get_conn()
    conn.execute(
        """INSERT INTO parse_records (doc_id, task_id, uploaded_by, api_key_id,
           file_name, file_format, file_size, status, error, created_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (record.doc_id, record.task_id, record.uploaded_by, record.api_key_id,
         record.file_name, record.file_format, record.file_size,
         record.status, record.error, record.created_at),
    )
    conn.commit()
    row_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
    conn.close()
    return row_id


def update_record_status(task_id: str, status: str, error: Optional[str] = None) -> bool:
    init_db()
    conn = _get_conn()
    if error:
        conn.execute("UPDATE parse_records SET status = ?, error = ? WHERE task_id = ?",
                     (status, error, task_id))
    else:
        conn.execute("UPDATE parse_records SET status = ? WHERE task_id = ?",
                     (status, task_id))
    conn.commit()
    affected = conn.total_changes
    conn.close()
    return affected > 0


def list_records(
    status_filter: Optional[str] = None,
    uploaded_by_filter: Optional[str] = None,
    deleted_filter: bool = False,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    limit: int = 500,
    offset: int = 0,
) -> list[dict]:
    init_db()
    conn = _get_conn()
    query = "SELECT * FROM parse_records WHERE 1=1"
    params: list = []
    if status_filter:
        query += " AND status = ?"
        params.append(status_filter)
    if uploaded_by_filter:
        query += " AND uploaded_by = ?"
        params.append(uploaded_by_filter)
    if deleted_filter:
        query += " AND status = 'deleted'"
    if start_date:
        query += " AND created_at >= ?"
        params.append(start_date)
    if end_date:
        query += " AND created_at <= ?"
        params.append(end_date)
    query += " ORDER BY created_at DESC LIMIT ? OFFSET ?"
    params.extend([limit, offset])
    rows = conn.execute(query, params).fetchall()
    records = [dict(r) for r in rows]
    conn.close()

    # 补充 api_key_name
    api_key_ids = {r["api_key_id"] for r in records if r.get("api_key_id")}
    if api_key_ids:
        api_keys_db = os.path.join(os.path.dirname(DB_PATH), "api_keys.sqlite")
        if os.path.exists(api_keys_db):
            try:
                aconn = sqlite3.connect(api_keys_db)
                aconn.row_factory = sqlite3.Row
                placeholders = ",".join("?" for _ in api_key_ids)
                ak_rows = aconn.execute(
                    f"SELECT id, user_name, key_prefix FROM api_keys WHERE id IN ({placeholders})",
                    list(api_key_ids),
                ).fetchall()
                aconn.close()
                ak_map = {r["id"]: f"{r['user_name']} ({r['key_prefix']})" for r in ak_rows}
                for r in records:
                    if r.get("api_key_id") in ak_map:
                        r["api_key_name"] = ak_map[r["api_key_id"]]
            except Exception:
                pass

    return records


def get_statistics(
    start_date: str,
    end_date: str,
    group_by: str = "day",
) -> list[dict]:
    """获取时间范围内的解析统计，按天和上传者分组。"""
    init_db()
    conn = _get_conn()
    if group_by == "day":
        rows = conn.execute("""
            SELECT DATE(created_at) as date, uploaded_by, COUNT(*) as count
            FROM parse_records
            WHERE created_at >= ? AND created_at <= ? AND status = 'completed'
            GROUP BY DATE(created_at), uploaded_by
            ORDER BY date
        """, (start_date, end_date)).fetchall()
    else:
        rows = conn.execute("""
            SELECT uploaded_by, COUNT(*) as count
            FROM parse_records
            WHERE created_at >= ? AND created_at <= ? AND status = 'completed'
            GROUP BY uploaded_by
            ORDER BY count DESC
        """, (start_date, end_date)).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def update_record_task_id(old_task_id: str, new_task_id: str) -> bool:
    """更新记录的 task_id（用于将 pending 的 task_id 替换为真实的 task_id）。"""
    init_db()
    conn = _get_conn()
    conn.execute("UPDATE parse_records SET task_id = ? WHERE task_id = ?",
                 (new_task_id, old_task_id))
    conn.commit()
    affected = conn.total_changes
    conn.close()
    return affected > 0


def update_record_by_doc_id(doc_id: str, new_task_id: str, new_status: str) -> bool:
    """更新指定文档的最新非已删除记录（用于重启时复用原记录），并清理旧重复。"""
    init_db()
    conn = _get_conn()
    now = datetime.now(timezone.utc).isoformat()
    # 只更新最新那条
    conn.execute(
        "UPDATE parse_records SET task_id = ?, status = ?, error = NULL, created_at = ? "
        "WHERE id = (SELECT id FROM parse_records WHERE doc_id = ? AND status != 'deleted' ORDER BY created_at DESC LIMIT 1)",
        (new_task_id, new_status, now, doc_id),
    )
    affected = conn.total_changes
    # 清理同 doc_id 的旧重复记录（保留最新那条）
    conn.execute(
        "DELETE FROM parse_records WHERE id NOT IN "
        "(SELECT id FROM parse_records WHERE doc_id = ? AND status != 'deleted' ORDER BY created_at DESC LIMIT 1) "
        "AND doc_id = ? AND status != 'deleted'",
        (doc_id, doc_id),
    )
    conn.commit()
    conn.close()
    return affected > 0


def soft_delete_record(doc_id: str) -> bool:
    """标记记录为用户已删除。"""
    init_db()
    conn = _get_conn()
    now = datetime.now(timezone.utc).isoformat()
    conn.execute(
        "UPDATE parse_records SET status = 'deleted', error = ? WHERE doc_id = ? AND status != 'deleted'",
        (f"user_deleted_at_{now}", doc_id),
    )
    conn.commit()
    affected = conn.total_changes
    conn.close()
    return affected > 0


def hard_delete_record(record_id: int) -> bool:
    """永久删除（仅status=deleted允许）。"""
    init_db()
    conn = _get_conn()
    conn.execute("DELETE FROM parse_records WHERE id = ? AND status = 'deleted'", (record_id,))
    conn.commit()
    affected = conn.total_changes
    conn.close()
    return affected > 0


def soft_delete_record_by_id(record_id: int) -> bool:
    """按 record_id 标记记录为用户已删除。"""
    init_db()
    conn = _get_conn()
    now = datetime.now(timezone.utc).isoformat()
    conn.execute(
        "UPDATE parse_records SET status = 'deleted', error = ? WHERE id = ? AND status != 'deleted'",
        (f"user_deleted_at_{now}", record_id),
    )
    conn.commit()
    affected = conn.total_changes
    conn.close()
    return affected > 0


def restore_record(record_id: int) -> bool:
    """将已删除的记录恢复到待解析状态。"""
    init_db()
    conn = _get_conn()
    conn.execute(
        "UPDATE parse_records SET status = 'pending', error = NULL WHERE id = ? AND status = 'deleted'",
        (record_id,),
    )
    conn.commit()
    affected = conn.total_changes
    conn.close()
    return affected > 0
