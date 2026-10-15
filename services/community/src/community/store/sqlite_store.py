"""community.sqlite DAO：分类树（复用 tree_core.tree_node）+ 公开绑定 + 投稿池 + 状态位。

设计见 `docs/design-public-eval-sop-pages.md` §8。形态照 chat-history：
每调用开一条连接（WAL + row_factory）、`init_db()` 幂等建表，构造函数即建表。

所有权红线：本文件是 `data/platform/community.sqlite` 的唯一写者；
测试集 / SOP 两个上游库在本模块内**只读**，用户投稿永不写进正式库。
"""
import json
import os
import sqlite3
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Sequence, Tuple

from shared.paths import resolve_data_file
from tree_core import tree_store

from community import models

DB_PATH = resolve_data_file("COMMUNITY_DB_PATH", "platform/community.sqlite")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _get_conn(db_path: Optional[str] = None) -> sqlite3.Connection:
    path = db_path or DB_PATH
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


def init_db(db_path: Optional[str] = None) -> None:
    """建表建索引（幂等）。分类树不自建表，走 tree_core 的通用 tree_node。"""
    conn = _get_conn(db_path)
    try:
        tree_store.init_table(conn)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS community_meta (
                key   TEXT PRIMARY KEY,
                value TEXT NOT NULL DEFAULT '',
                at    TEXT NOT NULL DEFAULT ''
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS community_binding (
                binding_id TEXT PRIMARY KEY,
                scope_id   TEXT NOT NULL,
                kind       TEXT NOT NULL,
                ref_id     TEXT NOT NULL,
                node_id    TEXT NOT NULL,
                sort_order INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL DEFAULT ''
            )
        """)
        conn.execute("""
            CREATE UNIQUE INDEX IF NOT EXISTS idx_binding_ref
            ON community_binding(scope_id, kind, ref_id)
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS community_submission (
                submission_id    TEXT PRIMARY KEY,
                scope_id         TEXT NOT NULL,
                kind             TEXT NOT NULL,
                node_id          TEXT NOT NULL DEFAULT '',
                parent_ref       TEXT NOT NULL DEFAULT '',
                step_ref         TEXT NOT NULL DEFAULT '',
                title            TEXT NOT NULL DEFAULT '',
                payload_json     TEXT NOT NULL DEFAULT '{}',
                author_owner_key TEXT NOT NULL DEFAULT '',
                author_user_id   INTEGER,
                author_label     TEXT NOT NULL DEFAULT '',
                status           TEXT NOT NULL DEFAULT 'received',
                created_at       TEXT NOT NULL DEFAULT '',
                updated_at       TEXT NOT NULL DEFAULT ''
            )
        """)
        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_sub_scope_node
            ON community_submission(scope_id, node_id, kind, created_at)
        """)
        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_sub_parent
            ON community_submission(scope_id, parent_ref, kind)
        """)
        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_sub_author
            ON community_submission(author_owner_key, created_at)
        """)
        conn.commit()
    finally:
        conn.close()


class CommunityStore:
    """投稿池 + 分类树 + 公开绑定 + 状态位的 DAO 门面。"""

    def __init__(self, db_path: Optional[str] = None):
        self._db_path = db_path or DB_PATH
        init_db(self._db_path)

    @property
    def db_path(self) -> str:
        return self._db_path

    # ---- 状态位（自动绑定 marker 等） ----

    def get_meta(self, key: str) -> Optional[str]:
        conn = _get_conn(self._db_path)
        try:
            row = conn.execute("SELECT value FROM community_meta WHERE key=?", (key,)).fetchone()
            return row["value"] if row else None
        finally:
            conn.close()

    def set_meta(self, key: str, value: str) -> None:
        conn = _get_conn(self._db_path)
        try:
            conn.execute(
                "INSERT OR REPLACE INTO community_meta (key, value, at) VALUES (?, ?, ?)",
                (key, value, _now()),
            )
            conn.commit()
        finally:
            conn.close()

    # ---- 分类树（tree_core 通用表） ----

    def ensure_node(
        self,
        node_id: str,
        *,
        scope_id: str,
        title: str,
        parent_id: Optional[str] = None,
        sort_order: int = 0,
    ) -> Dict[str, Any]:
        """只在缺失时建节点；**不覆盖**已有 title/sort_order（后台改过的分类不被发版打回）。"""
        conn = _get_conn(self._db_path)
        try:
            existing = tree_store.get_node(conn, node_id)
            if existing is None:
                existing = tree_store.insert_node(conn, {
                    "node_id": node_id,
                    "tree_type": models.TREE_TYPE,
                    "scope_id": scope_id,
                    "title": title,
                    "parent_id": parent_id,
                    "sort_order": sort_order,
                    "is_folder": 1,
                })
            return existing
        finally:
            conn.close()

    def list_nodes(self, scope_id: str) -> List[Dict[str, Any]]:
        conn = _get_conn(self._db_path)
        try:
            return tree_store.list_nodes_by_scope(conn, models.TREE_TYPE, scope_id)
        finally:
            conn.close()

    def get_node(self, node_id: str) -> Optional[Dict[str, Any]]:
        conn = _get_conn(self._db_path)
        try:
            node = tree_store.get_node(conn, node_id)
            if node and node.get("tree_type") != models.TREE_TYPE:
                return None
            return node
        finally:
            conn.close()

    # ---- 公开绑定（哪些官方内容算公开：人工写入，设计 §9.1） ----

    def bind(
        self,
        *,
        scope_id: str,
        kind: str,
        ref_id: str,
        node_id: str,
        sort_order: int = 0,
    ) -> Dict[str, Any]:
        conn = _get_conn(self._db_path)
        try:
            binding_id = f"bind:{scope_id}:{kind}:{ref_id}"
            conn.execute(
                """INSERT OR REPLACE INTO community_binding
                   (binding_id, scope_id, kind, ref_id, node_id, sort_order, created_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (binding_id, scope_id, kind, ref_id, node_id, sort_order, _now()),
            )
            conn.commit()
            return {
                "binding_id": binding_id, "scope_id": scope_id, "kind": kind,
                "ref_id": ref_id, "node_id": node_id, "sort_order": sort_order,
            }
        finally:
            conn.close()

    def is_bound(self, *, scope_id: str, kind: str, ref_id: str) -> bool:
        conn = _get_conn(self._db_path)
        try:
            row = conn.execute(
                "SELECT 1 FROM community_binding WHERE scope_id=? AND kind=? AND ref_id=?",
                (scope_id, kind, ref_id),
            ).fetchone()
            return row is not None
        finally:
            conn.close()

    def unbind(self, *, scope_id: str, kind: str, ref_id: str) -> bool:
        conn = _get_conn(self._db_path)
        try:
            cur = conn.execute(
                "DELETE FROM community_binding WHERE scope_id=? AND kind=? AND ref_id=?",
                (scope_id, kind, ref_id),
            )
            conn.commit()
            return cur.rowcount > 0
        finally:
            conn.close()

    def list_bindings(self, scope_id: str) -> List[Dict[str, Any]]:
        conn = _get_conn(self._db_path)
        try:
            rows = conn.execute(
                "SELECT * FROM community_binding WHERE scope_id=? ORDER BY sort_order, ref_id",
                (scope_id,),
            ).fetchall()
            return [dict(r) for r in rows]
        finally:
            conn.close()

    def count_bindings(self, scope_id: str) -> int:
        conn = _get_conn(self._db_path)
        try:
            row = conn.execute(
                "SELECT COUNT(*) AS n FROM community_binding WHERE scope_id=?", (scope_id,)
            ).fetchone()
            return int(row["n"]) if row else 0
        finally:
            conn.close()

    # ---- 投稿池 ----

    def insert_submission(
        self,
        *,
        scope_id: str,
        kind: str,
        payload: Dict[str, Any],
        node_id: str = "",
        parent_ref: str = "",
        step_ref: str = "",
        title: str = "",
        author_owner_key: str = "",
        author_user_id: Optional[int] = None,
        author_label: str = "",
    ) -> Dict[str, Any]:
        submission_id = f"sub-{uuid.uuid4().hex[:12]}"
        now = _now()
        conn = _get_conn(self._db_path)
        try:
            conn.execute(
                """INSERT INTO community_submission
                   (submission_id, scope_id, kind, node_id, parent_ref, step_ref, title,
                    payload_json, author_owner_key, author_user_id, author_label,
                    status, created_at, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    submission_id, scope_id, kind, node_id, parent_ref, step_ref, title,
                    json.dumps(payload, ensure_ascii=False), author_owner_key,
                    author_user_id, author_label, models.STATUS_RECEIVED, now, now,
                ),
            )
            conn.commit()
        finally:
            conn.close()
        return {
            "submission_id": submission_id, "scope_id": scope_id, "kind": kind,
            "node_id": node_id, "parent_ref": parent_ref, "step_ref": step_ref,
            "title": title, "payload": payload, "author_label": author_label,
            "status": models.STATUS_RECEIVED, "created_at": now,
        }

    def _rows_to_submissions(self, rows: Sequence[sqlite3.Row]) -> List[Dict[str, Any]]:
        out: List[Dict[str, Any]] = []
        for row in rows:
            item = dict(row)
            try:
                item["payload"] = json.loads(item.get("payload_json") or "{}")
            except (TypeError, ValueError):
                item["payload"] = {}
            out.append(item)
        return out

    def list_submissions(
        self,
        *,
        scope_id: Optional[str] = None,
        kinds: Optional[Sequence[str]] = None,
        node_id: Optional[str] = None,
        parent_ref: Optional[str] = None,
        limit: int = 200,
        offset: int = 0,
    ) -> Tuple[List[Dict[str, Any]], int]:
        """按条件取投稿（新→旧）+ 命中总数。

        只取 `received`：本版没有审核，所以不存在其它态；审核上线后这里改成按可见态过滤。
        """
        where = ["status = ?"]
        args: List[Any] = [models.STATUS_RECEIVED]
        if scope_id:
            where.append("scope_id = ?")
            args.append(scope_id)
        if kinds:
            where.append(f"kind IN ({', '.join('?' for _ in kinds)})")
            args.extend(kinds)
        if node_id is not None:
            where.append("node_id = ?")
            args.append(node_id)
        if parent_ref is not None:
            where.append("parent_ref = ?")
            args.append(parent_ref)
        clause = " AND ".join(where)
        conn = _get_conn(self._db_path)
        try:
            total_row = conn.execute(
                f"SELECT COUNT(*) AS n FROM community_submission WHERE {clause}", args
            ).fetchone()
            rows = conn.execute(
                f"SELECT * FROM community_submission WHERE {clause} "
                f"ORDER BY created_at DESC, submission_id LIMIT ? OFFSET ?",
                [*args, limit, offset],
            ).fetchall()
            return self._rows_to_submissions(rows), int(total_row["n"] if total_row else 0)
        finally:
            conn.close()

    def get_submission(self, submission_id: str) -> Optional[Dict[str, Any]]:
        conn = _get_conn(self._db_path)
        try:
            row = conn.execute(
                "SELECT * FROM community_submission WHERE submission_id=?", (submission_id,)
            ).fetchone()
            rows = self._rows_to_submissions([row]) if row else []
            return rows[0] if rows else None
        finally:
            conn.close()

    def count_submissions_since(self, author_owner_key: str, hours: int = 24) -> int:
        """滚动窗口内该主体的投稿数（日限兜底用）。

        用滚动 24h 而非日历日：避开跨时区口径，也和「清 cookie 换桶」无关——
        主防线是 nginx 按 IP 频控（设计 §6 R5）。
        """
        if not author_owner_key:
            return 0
        since = (datetime.now(timezone.utc) - timedelta(hours=hours)).isoformat()
        conn = _get_conn(self._db_path)
        try:
            row = conn.execute(
                "SELECT COUNT(*) AS n FROM community_submission "
                "WHERE author_owner_key=? AND created_at>=?",
                (author_owner_key, since),
            ).fetchone()
            return int(row["n"]) if row else 0
        finally:
            conn.close()
