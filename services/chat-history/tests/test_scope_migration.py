"""chat.sqlite 迁移：PK 去 scope_hash 幂等 + 旧数据 seq 重排不丢（路径注入见 conftest.py）。"""
import sqlite3
from pathlib import Path

from chat_history.store.sqlite_store import init_db


def _old_schema_db(path: Path) -> None:
    conn = sqlite3.connect(path)
    conn.executescript("""
        CREATE TABLE chat_sessions (
            owner_key TEXT NOT NULL, session_id TEXT NOT NULL,
            scene TEXT NOT NULL DEFAULT 'qa', library_id TEXT NOT NULL DEFAULT 'default',
            doc_ids_json TEXT NOT NULL DEFAULT '[]', scope_hash TEXT NOT NULL DEFAULT '',
            title TEXT NOT NULL DEFAULT '', created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
            PRIMARY KEY (owner_key, session_id)
        );
        CREATE TABLE chat_messages (
            owner_key TEXT NOT NULL, session_id TEXT NOT NULL,
            scope_hash TEXT NOT NULL DEFAULT '', seq INTEGER NOT NULL,
            role TEXT NOT NULL, content TEXT NOT NULL DEFAULT '',
            meta_json TEXT NOT NULL DEFAULT '{}', created_at TEXT NOT NULL,
            PRIMARY KEY (owner_key, session_id, scope_hash, seq)
        );
    """)
    # 同 session 两个 scope，各自 seq 1..2（旧形态，迁后必须重排为 1..4）
    for scope, base in (("h1", 0), ("h2", 0)):
        for i in (1, 2):
            conn.execute(
                "INSERT INTO chat_messages VALUES (?,?,?,?,?,?,?,?)",
                ("u:1", "s1", scope, i, "user", f"{scope}-m{i}", "{}", "2026-01-01"),
            )
    conn.commit()
    conn.close()


class TestScopeMigration:
    def test_old_schema_migrated_and_renumbered(self, tmp_path):
        db = tmp_path / "chat.sqlite"
        _old_schema_db(db)
        init_db(str(db))
        conn = sqlite3.connect(db)
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT scope_hash, seq, content FROM chat_messages"
            " WHERE owner_key='u:1' AND session_id='s1' ORDER BY seq"
        ).fetchall()
        assert [r["seq"] for r in rows] == [1, 2, 3, 4]
        assert [r["content"] for r in rows] == ["h1-m1", "h1-m2", "h2-m1", "h2-m2"]
        pk_cols = [r["name"] for r in conn.execute("PRAGMA table_info(chat_messages)") if r["pk"] > 0]
        assert pk_cols == ["owner_key", "session_id", "seq"]
        sess_cols = [r["name"] for r in conn.execute("PRAGMA table_info(chat_sessions)")]
        assert "library_ids_json" in sess_cols
        conn.close()

    def test_migration_idempotent(self, tmp_path):
        db = tmp_path / "chat.sqlite"
        _old_schema_db(db)
        init_db(str(db))
        init_db(str(db))  # 第二次不报错、不重排
        conn = sqlite3.connect(db)
        conn.row_factory = sqlite3.Row
        count = conn.execute("SELECT COUNT(*) FROM chat_messages").fetchone()[0]
        assert count == 4
        # 二跑不重排：seq/内容与首跑一致
        rows = conn.execute(
            "SELECT seq, content FROM chat_messages"
            " WHERE owner_key='u:1' AND session_id='s1' ORDER BY seq"
        ).fetchall()
        assert [r["seq"] for r in rows] == [1, 2, 3, 4]
        assert [r["content"] for r in rows] == ["h1-m1", "h1-m2", "h2-m1", "h2-m2"]
        # 重建临时表已 DROP，二跑也无残留
        assert conn.execute("PRAGMA table_info(chat_messages_old)").fetchall() == []
        conn.close()
