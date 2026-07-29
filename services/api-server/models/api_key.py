"""API Key 数据模型与持久化操作。"""
import os
import secrets
import hashlib
import sqlite3
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional


DB_PATH = os.environ.get("API_KEYS_DB_PATH", str(
    Path(__file__).resolve().parent.parent.parent.parent
    / "data" / "api_keys.sqlite"
))


@dataclass
class APIKey:
    id: Optional[int] = None
    key_hash: str = ""
    key_prefix: str = ""
    user_name: str = ""
    email: str = ""
    is_active: bool = True
    rate_limit_per_minute: int = 60
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    last_used_at: Optional[str] = None


def _get_conn() -> sqlite3.Connection:
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


def init_db() -> None:
    conn = _get_conn()
    conn.execute("""
        CREATE TABLE IF NOT EXISTS api_keys (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            key_hash TEXT NOT NULL UNIQUE,
            key_prefix TEXT NOT NULL,
            user_name TEXT NOT NULL DEFAULT '',
            email TEXT NOT NULL DEFAULT '',
            is_active INTEGER NOT NULL DEFAULT 1,
            rate_limit_per_minute INTEGER NOT NULL DEFAULT 60,
            created_at TEXT NOT NULL,
            last_used_at TEXT
        )
    """)
    conn.commit()
    conn.close()


def _hash_key(raw_key: str) -> str:
    return hashlib.sha256(raw_key.encode()).hexdigest()


def generate_key(user_name: str, email: str = "", rate_limit_per_minute: int = 60) -> tuple[str, APIKey]:
    """生成新的 API Key，返回 (原始key, APIKey对象)。"""
    init_db()

    prefix = "ag_"
    raw_key = prefix + secrets.token_urlsafe(32)
    key_hash = _hash_key(raw_key)
    key_prefix = raw_key[:4] + "****" + raw_key[-4:]

    now = datetime.now(timezone.utc).isoformat()

    conn = _get_conn()
    conn.execute(
        "INSERT INTO api_keys (key_hash, key_prefix, user_name, email, rate_limit_per_minute, created_at) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (key_hash, key_prefix, user_name, email, rate_limit_per_minute, now),
    )
    conn.commit()
    row_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
    conn.close()

    api_key = APIKey(
        id=row_id,
        key_hash=key_hash,
        key_prefix=key_prefix,
        user_name=user_name,
        email=email,
        rate_limit_per_minute=rate_limit_per_minute,
        created_at=now,
    )
    return raw_key, api_key


def lookup_key(raw_key: str) -> Optional[APIKey]:
    """根据原始 key 查找 APIKey 对象，验证通过则更新 last_used_at。"""
    init_db()

    key_hash = _hash_key(raw_key)
    conn = _get_conn()
    row = conn.execute(
        "SELECT * FROM api_keys WHERE key_hash = ? AND is_active = 1",
        (key_hash,),
    ).fetchone()
    if not row:
        conn.close()
        return None

    now = datetime.now(timezone.utc).isoformat()
    conn.execute("UPDATE api_keys SET last_used_at = ? WHERE id = ?", (now, row["id"]))
    conn.commit()
    conn.close()

    return APIKey(**dict(row))


def list_keys() -> list[dict]:
    """列出所有 Key（不含 hash），供管理页面使用。"""
    init_db()
    conn = _get_conn()
    rows = conn.execute(
        "SELECT id, key_prefix, user_name, is_active, created_at, last_used_at "
        "FROM api_keys ORDER BY id DESC"
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def deactivate_key(key_id: int) -> bool:
    init_db()
    conn = _get_conn()
    conn.execute("UPDATE api_keys SET is_active = 0 WHERE id = ?", (key_id,))
    conn.commit()
    affected = conn.total_changes
    conn.close()
    return affected > 0


def rename_key(key_id: int, new_name: str) -> bool:
    init_db()
    conn = _get_conn()
    conn.execute("UPDATE api_keys SET user_name = ? WHERE id = ?", (new_name, key_id))
    conn.commit()
    affected = conn.total_changes
    conn.close()
    return affected > 0


def reactivate_key(key_id: int) -> bool:
    init_db()
    conn = _get_conn()
    conn.execute("UPDATE api_keys SET is_active = 1 WHERE id = ?", (key_id,))
    conn.commit()
    affected = conn.total_changes
    conn.close()
    return affected > 0


def delete_key(key_id: int) -> bool:
    """永久删除 API Key。"""
    init_db()
    conn = _get_conn()
    conn.execute("DELETE FROM api_keys WHERE id = ?", (key_id,))
    conn.commit()
    affected = conn.total_changes
    conn.close()
    return affected > 0
