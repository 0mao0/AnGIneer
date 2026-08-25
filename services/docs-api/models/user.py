"""用户、用户-知识库、会话数据模型（账号密码登录，docs-api / aichat-api 共享同一 DB）。"""
import os
import secrets
import hashlib
import sqlite3
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import List, Optional

DB_PATH = os.environ.get("USERS_DB_PATH", str(
    Path(__file__).resolve().parent.parent.parent.parent
    / "data" / "users.sqlite"
))

SESSION_TTL_DAYS = 7
PBKDF2_ITERATIONS = 200_000
MIN_PASSWORD_LEN = 6


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def hash_password(password: str, iterations: int = PBKDF2_ITERATIONS) -> str:
    salt = secrets.token_hex(16)
    dk = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), bytes.fromhex(salt), iterations)
    return f"pbkdf2${iterations}${salt}${dk.hex()}"


def verify_password(password: str, stored: str) -> bool:
    try:
        _, iter_s, salt_hex, hash_hex = stored.split("$")
        iterations = int(iter_s)
    except (ValueError, AttributeError):
        return False
    dk = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), bytes.fromhex(salt_hex), iterations)
    return secrets.compare_digest(dk.hex(), hash_hex)


@dataclass
class User:
    id: Optional[int] = None
    username: str = ""
    display_name: str = ""
    password_hash: str = ""
    is_active: bool = True
    is_admin: bool = False
    created_at: str = ""
    last_login_at: Optional[str] = None
    library_ids: List[str] = field(default_factory=list)


def _get_conn() -> sqlite3.Connection:
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


def init_db() -> None:
    conn = _get_conn()
    conn.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT NOT NULL UNIQUE,
            display_name TEXT NOT NULL DEFAULT '',
            password_hash TEXT NOT NULL,
            is_active INTEGER NOT NULL DEFAULT 1,
            is_admin INTEGER NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL,
            last_login_at TEXT
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS user_libraries (
            user_id INTEGER NOT NULL,
            library_id TEXT NOT NULL,
            PRIMARY KEY (user_id, library_id),
            FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS sessions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            token_hash TEXT NOT NULL UNIQUE,
            user_id INTEGER NOT NULL,
            created_at TEXT NOT NULL,
            expires_at TEXT NOT NULL,
            FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
        )
    """)
    try:
        conn.execute("ALTER TABLE users ADD COLUMN is_admin INTEGER NOT NULL DEFAULT 0")
    except sqlite3.OperationalError:
        pass  # 已存在该列
    conn.commit()
    conn.close()


def _library_ids_for_user(conn: sqlite3.Connection, user_id: int) -> List[str]:
    rows = conn.execute(
        "SELECT library_id FROM user_libraries WHERE user_id = ? ORDER BY rowid",
        (user_id,),
    ).fetchall()
    return [r["library_id"] for r in rows]


def _row_to_user(row: sqlite3.Row, library_ids: List[str]) -> User:
    return User(
        id=row["id"],
        username=row["username"],
        display_name=row["display_name"],
        password_hash=row["password_hash"],
        is_active=bool(row["is_active"]),
        is_admin=bool(row["is_admin"]),
        created_at=row["created_at"],
        last_login_at=row["last_login_at"],
        library_ids=library_ids,
    )


def get_user_by_username(username: str) -> Optional[User]:
    init_db()
    conn = _get_conn()
    row = conn.execute("SELECT * FROM users WHERE username = ?", (username.strip(),)).fetchone()
    if row is None:
        conn.close()
        return None
    libs = _library_ids_for_user(conn, row["id"])
    user = _row_to_user(row, libs)
    conn.close()
    return user


def get_user_by_id(user_id: int) -> Optional[User]:
    init_db()
    conn = _get_conn()
    row = conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
    if row is None:
        conn.close()
        return None
    libs = _library_ids_for_user(conn, row["id"])
    user = _row_to_user(row, libs)
    conn.close()
    return user


def list_users() -> List[User]:
    init_db()
    conn = _get_conn()
    rows = conn.execute("SELECT * FROM users ORDER BY id").fetchall()
    users = [_row_to_user(r, _library_ids_for_user(conn, r["id"])) for r in rows]
    conn.close()
    return users


def create_user(
    username: str,
    display_name: str = "",
    password: str = "",
    library_ids: Optional[List[str]] = None,
    is_admin: bool = False,
) -> User:
    init_db()
    username = username.strip()
    if not username:
        raise ValueError("用户名不能为空")
    if len(password) < MIN_PASSWORD_LEN:
        raise ValueError(f"密码长度不能少于 {MIN_PASSWORD_LEN} 位")
    conn = _get_conn()
    try:
        dup = conn.execute("SELECT id FROM users WHERE username = ?", (username,)).fetchone()
        if dup:
            raise ValueError("用户名已存在")
        cur = conn.execute(
            "INSERT INTO users (username, display_name, password_hash, is_active, is_admin, created_at) VALUES (?, ?, ?, 1, ?, ?)",
            (username, display_name.strip(), hash_password(password), 1 if is_admin else 0, _now()),
        )
        user_id = cur.lastrowid
        for lid in (library_ids or []):
            conn.execute("INSERT INTO user_libraries (user_id, library_id) VALUES (?, ?)", (user_id, str(lid).strip()))
        conn.commit()
    finally:
        conn.close()
    return get_user_by_id(user_id)


def update_user(user_id: int, display_name: Optional[str] = None, library_ids: Optional[List[str]] = None) -> bool:
    init_db()
    conn = _get_conn()
    try:
        row = conn.execute("SELECT id FROM users WHERE id = ?", (user_id,)).fetchone()
        if row is None:
            return False
        if display_name is not None:
            conn.execute("UPDATE users SET display_name = ? WHERE id = ?", (display_name.strip(), user_id))
        if library_ids is not None:
            conn.execute("DELETE FROM user_libraries WHERE user_id = ?", (user_id,))
            for lid in library_ids:
                conn.execute("INSERT INTO user_libraries (user_id, library_id) VALUES (?, ?)", (user_id, str(lid).strip()))
        conn.commit()
    finally:
        conn.close()
    return True


def set_password(user_id: int, new_password: str) -> bool:
    if len(new_password) < MIN_PASSWORD_LEN:
        raise ValueError(f"密码长度不能少于 {MIN_PASSWORD_LEN} 位")
    init_db()
    conn = _get_conn()
    try:
        cur = conn.execute("UPDATE users SET password_hash = ? WHERE id = ?", (hash_password(new_password), user_id))
        if cur.rowcount == 0:
            return False
        conn.execute("DELETE FROM sessions WHERE user_id = ?", (user_id,))
        conn.commit()
    finally:
        conn.close()
    return True


def set_user_active(user_id: int, active: bool) -> bool:
    init_db()
    conn = _get_conn()
    try:
        cur = conn.execute("UPDATE users SET is_active = ? WHERE id = ?", (1 if active else 0, user_id))
        if cur.rowcount == 0:
            return False
        conn.execute("DELETE FROM sessions WHERE user_id = ?", (user_id,))
        conn.commit()
    finally:
        conn.close()
    return True


def delete_user(user_id: int) -> bool:
    init_db()
    conn = _get_conn()
    try:
        cur = conn.execute("DELETE FROM users WHERE id = ?", (user_id,))
        conn.commit()
    finally:
        conn.close()
    return cur.rowcount > 0


def _hash_token(raw: str) -> str:
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def create_session(user_id: int) -> str:
    init_db()
    raw = secrets.token_urlsafe(32)
    conn = _get_conn()
    try:
        conn.execute(
            "INSERT INTO sessions (token_hash, user_id, created_at, expires_at) VALUES (?, ?, ?, ?)",
            (_hash_token(raw), user_id, _now(), (datetime.now(timezone.utc) + timedelta(days=SESSION_TTL_DAYS)).isoformat()),
        )
        conn.commit()
    finally:
        conn.close()
    return raw


def get_session_user(raw_token: str) -> Optional[User]:
    init_db()
    conn = _get_conn()
    try:
        row = conn.execute(
            "SELECT * FROM sessions WHERE token_hash = ?",
            (_hash_token(raw_token.strip()),),
        ).fetchone()
        if row is None:
            return None
        expires_at = datetime.fromisoformat(row["expires_at"])
        if expires_at <= datetime.now(timezone.utc):
            conn.execute("DELETE FROM sessions WHERE id = ?", (row["id"],))
            conn.commit()
            return None
        # 滑动过期
        conn.execute(
            "UPDATE sessions SET expires_at = ? WHERE id = ?",
            ((datetime.now(timezone.utc) + timedelta(days=SESSION_TTL_DAYS)).isoformat(), row["id"]),
        )
        conn.commit()
        user_row = conn.execute("SELECT * FROM users WHERE id = ?", (row["user_id"],)).fetchone()
        if user_row is None or not bool(user_row["is_active"]):
            return None
        libs = _library_ids_for_user(conn, user_row["id"])
        return _row_to_user(user_row, libs)
    finally:
        conn.close()


def delete_session(raw_token: str) -> bool:
    init_db()
    conn = _get_conn()
    try:
        cur = conn.execute("DELETE FROM sessions WHERE token_hash = ?", (_hash_token(raw_token.strip()),))
        conn.commit()
    finally:
        conn.close()
    return cur.rowcount > 0


def update_last_login(user_id: int) -> None:
    init_db()
    conn = _get_conn()
    try:
        conn.execute("UPDATE users SET last_login_at = ? WHERE id = ?", (_now(), user_id))
        conn.commit()
    finally:
        conn.close()
