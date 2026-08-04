"""SQLite 连接工具（write 层共享）。"""
import sqlite3
from pathlib import Path


# 构造 SQLite 连接并启用 WAL 模式与 Row 映射。
def create_connection(db_path: Path) -> sqlite3.Connection:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path), timeout=10)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    return conn
