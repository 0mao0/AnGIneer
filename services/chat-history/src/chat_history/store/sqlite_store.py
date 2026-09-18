"""聊天历史 sqlite DAO + HistoryStore 实现（docs/plan-chat-history.md §1/§3）。

DAO 形态照 services/shared/src/shared/user_model.py：函数式 DAO + WAL + init_db()。
表结构以计划 §1 为准；`scope_hash` 与引擎池 key 同算法（angineer_core.history_store.scope_hash_for）。

关键语义（计划 D10/D11/§8）：
- ``seq`` 服务端唯一权威：append 在事务内按 (owner_key, session_id, scope_hash) 取 MAX+1 分配；
- append 落库 owner 以 chat_sessions 行**当前归属**为准——claim 改挂后，在跑 run 的
  后续写入自动跟随新 owner，不产生孤儿行（§8「落库 owner 以会话行当前归属为准」）；
- load 只在会话池新建 session 时由组装层调用一次，按 scope_hash 过滤。
"""
import json
import logging
import os
import sqlite3
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from shared.paths import resolve_data_file

from angineer_core.agent_messages import AgentMessage, ToolCall

DB_PATH = resolve_data_file("CHAT_DB_PATH", "chat.sqlite")

logger = logging.getLogger(__name__)


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
    conn = _get_conn(db_path)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS chat_sessions (
            owner_key TEXT NOT NULL,
            session_id TEXT NOT NULL,
            scene TEXT NOT NULL DEFAULT 'qa',
            library_id TEXT NOT NULL DEFAULT 'default',
            doc_ids_json TEXT NOT NULL DEFAULT '[]',
            scope_hash TEXT NOT NULL DEFAULT '',
            title TEXT NOT NULL DEFAULT '',
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            PRIMARY KEY (owner_key, session_id)
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS chat_messages (
            owner_key TEXT NOT NULL,
            session_id TEXT NOT NULL,
            scope_hash TEXT NOT NULL DEFAULT '',
            seq INTEGER NOT NULL,
            role TEXT NOT NULL,
            content TEXT NOT NULL DEFAULT '',
            meta_json TEXT NOT NULL DEFAULT '{}',
            created_at TEXT NOT NULL,
            PRIMARY KEY (owner_key, session_id, scope_hash, seq)
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS chat_runs (
            run_id TEXT PRIMARY KEY,
            owner_key TEXT NOT NULL,
            session_id TEXT NOT NULL,
            model TEXT NOT NULL DEFAULT '',
            latency_ms INTEGER NOT NULL DEFAULT 0,
            status TEXT NOT NULL DEFAULT '',
            error TEXT NOT NULL DEFAULT '',
            created_at TEXT NOT NULL
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS chat_guests (
            guest_id TEXT PRIMARY KEY,
            created_at TEXT NOT NULL,
            last_seen_at TEXT NOT NULL,
            claimed_by_user_id INTEGER
        )
    """)
    conn.commit()
    conn.close()


# ---------------------------------------------------------------- 序列化

def agent_message_to_full_dict(message: AgentMessage) -> Dict[str, Any]:
    """完整序列化（含 meta 与 tool 字段）——落库用，区别于下发 LLM 的 agent_message_to_dict。"""
    data: Dict[str, Any] = {"role": message.role, "content": message.content}
    if message.tool_calls:
        data["tool_calls"] = [
            {"id": c.id, "name": c.name, "arguments": c.arguments} for c in message.tool_calls
        ]
    if message.tool_call_id:
        data["tool_call_id"] = message.tool_call_id
    if message.name:
        data["name"] = message.name
    if message.is_error:
        data["is_error"] = True
    if message.meta:
        data["meta"] = message.meta
    return data


def agent_message_from_dict(data: Dict[str, Any]) -> AgentMessage:
    """从 run_end 帧 payload["messages"] 或库行还原 AgentMessage。"""
    tool_calls = [
        ToolCall(id=c["id"], name=c.get("name", ""), arguments=c.get("arguments") or {})
        for c in (data.get("tool_calls") or [])
    ]
    return AgentMessage(
        role=data.get("role", "user"),
        content=data.get("content", "") or "",
        tool_calls=tool_calls,
        tool_call_id=data.get("tool_call_id"),
        name=data.get("name"),
        is_error=bool(data.get("is_error")),
        meta=dict(data.get("meta") or {}),
    )


def _message_to_meta_json(message: AgentMessage) -> str:
    """tool 字段与 meta 一并进 meta_json（列模型不变，扩展字段全走 JSON）。"""
    extra: Dict[str, Any] = {}
    if message.tool_calls:
        extra["tool_calls"] = [
            {"id": c.id, "name": c.name, "arguments": c.arguments} for c in message.tool_calls
        ]
    if message.tool_call_id:
        extra["tool_call_id"] = message.tool_call_id
    if message.name:
        extra["name"] = message.name
    if message.is_error:
        extra["is_error"] = True
    if message.meta:
        extra["meta"] = message.meta
    return json.dumps(extra, ensure_ascii=False)


def _derive_title(text: str) -> str:
    """会话标题：首条非空用户消息压缩空白截断 30 字（与前端 deriveTitle 同规则，后端复刻）。"""
    collapsed = " ".join((text or "").split())
    if not collapsed:
        return "未命名对话"
    return f"{collapsed[:30]}…" if len(collapsed) > 30 else collapsed


def _row_to_message(row: sqlite3.Row) -> AgentMessage:
    extra = json.loads(row["meta_json"] or "{}")
    return AgentMessage(
        role=row["role"],
        content=row["content"] or "",
        tool_calls=[
            ToolCall(id=c["id"], name=c.get("name", ""), arguments=c.get("arguments") or {})
            for c in (extra.get("tool_calls") or [])
        ],
        tool_call_id=extra.get("tool_call_id"),
        name=extra.get("name"),
        is_error=bool(extra.get("is_error")),
        meta=dict(extra.get("meta") or {}),
    )


class SqliteHistoryStore:
    """HistoryStore 协议实现 + 会话管理/审计/游客/GC 的 DAO 集合。

    所有方法自带连接管理；失败向上抛（组装层决定降级策略）。
    """

    def __init__(self, db_path: Optional[str] = None):
        self._db_path = db_path or DB_PATH
        init_db(self._db_path)

    # ------------------------------------------------------------ HistoryStore 协议

    def load(self, owner: str, session_id: str, scope_hash: str) -> List[AgentMessage]:
        conn = _get_conn(self._db_path)
        try:
            rows = conn.execute(
                "SELECT role, content, meta_json FROM chat_messages"
                " WHERE owner_key=? AND session_id=? AND scope_hash=? ORDER BY seq",
                (owner, session_id, scope_hash),
            ).fetchall()
            return [_row_to_message(r) for r in rows]
        finally:
            conn.close()

    def append(
        self,
        owner: str,
        session_id: str,
        scope_hash: str,
        messages: List[AgentMessage],
        run_meta: Dict[str, Any],
    ) -> List[int]:
        """追加一轮 run 的消息 + 审计行，返回各消息的 seq（D10：服务端唯一权威）。

        落库 owner 以 chat_sessions 行当前归属为准（§8：claim 改挂后跟随新 owner）。
        """
        if not messages:
            return []
        now = _now()
        conn = _get_conn(self._db_path)
        try:
            with conn:
                row = conn.execute(
                    "SELECT owner_key FROM chat_sessions WHERE session_id=? AND scope_hash=?",
                    (session_id, scope_hash),
                ).fetchone()
                eff_owner = row["owner_key"] if row else owner
                if row is None:
                    conn.execute(
                        "INSERT OR IGNORE INTO chat_sessions"
                        " (owner_key, session_id, scene, library_id, doc_ids_json, scope_hash,"
                        " title, created_at, updated_at)"
                        " VALUES (?,?,?,?,?,?,?,?,?)",
                        (eff_owner, session_id, run_meta.get("scene") or "qa",
                         run_meta.get("library_id") or "default",
                         json.dumps(run_meta.get("doc_ids") or [], ensure_ascii=False),
                         scope_hash, "", now, now),
                    )
                base = conn.execute(
                    "SELECT COALESCE(MAX(seq), 0) AS m FROM chat_messages"
                    " WHERE owner_key=? AND session_id=? AND scope_hash=?",
                    (eff_owner, session_id, scope_hash),
                ).fetchone()["m"]
                seqs: List[int] = []
                for i, message in enumerate(messages):
                    seq = base + i + 1
                    seqs.append(seq)
                    conn.execute(
                        "INSERT INTO chat_messages"
                        " (owner_key, session_id, scope_hash, seq, role, content, meta_json, created_at)"
                        " VALUES (?,?,?,?,?,?,?,?)",
                        (eff_owner, session_id, scope_hash, seq, message.role,
                         message.content, _message_to_meta_json(message), now),
                    )
                conn.execute(
                    "UPDATE chat_sessions SET updated_at=? WHERE owner_key=? AND session_id=?",
                    (now, eff_owner, session_id),
                )
                title_row = conn.execute(
                    "SELECT title FROM chat_sessions WHERE owner_key=? AND session_id=?",
                    (eff_owner, session_id),
                ).fetchone()
                if title_row is not None and not title_row["title"]:
                    first_user = next(
                        (m.content for m in messages if m.role == "user" and m.content.strip()), ""
                    )
                    conn.execute(
                        "UPDATE chat_sessions SET title=? WHERE owner_key=? AND session_id=?",
                        (_derive_title(first_user), eff_owner, session_id),
                    )
                conn.execute(
                    "INSERT OR REPLACE INTO chat_runs"
                    " (run_id, owner_key, session_id, model, latency_ms, status, error, created_at)"
                    " VALUES (?,?,?,?,?,?,?,?)",
                    (run_meta.get("run_id") or "", eff_owner, session_id,
                     run_meta.get("model") or "", int(run_meta.get("latency_ms") or 0),
                     run_meta.get("status") or "", run_meta.get("error") or "", now),
                )
            return seqs
        finally:
            conn.close()

    # ------------------------------------------------------------ 会话查询/删除（步 2 路由用）

    def list_sessions(self, owner: str, library_id: Optional[str] = None,
                      limit: int = 50) -> List[Dict[str, Any]]:
        conn = _get_conn(self._db_path)
        try:
            if library_id:
                rows = conn.execute(
                    "SELECT s.*, (SELECT COUNT(*) FROM chat_messages m"
                    " WHERE m.owner_key=s.owner_key AND m.session_id=s.session_id) AS message_count"
                    " FROM chat_sessions s WHERE s.owner_key=? AND s.library_id=?"
                    " ORDER BY s.updated_at DESC LIMIT ?",
                    (owner, library_id, limit),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT s.*, (SELECT COUNT(*) FROM chat_messages m"
                    " WHERE m.owner_key=s.owner_key AND m.session_id=s.session_id) AS message_count"
                    " FROM chat_sessions s WHERE s.owner_key=?"
                    " ORDER BY s.updated_at DESC LIMIT ?",
                    (owner, limit),
                ).fetchall()
            return [dict(r) for r in rows]
        finally:
            conn.close()

    def get_session(self, owner: str, session_id: str) -> Optional[Dict[str, Any]]:
        conn = _get_conn(self._db_path)
        try:
            row = conn.execute(
                "SELECT * FROM chat_sessions WHERE owner_key=? AND session_id=?",
                (owner, session_id),
            ).fetchone()
            return dict(row) if row else None
        finally:
            conn.close()

    def get_messages(self, owner: str, session_id: str) -> List[Dict[str, Any]]:
        """消息全集（含 seq/meta_json 原文，路由层转 AIChatMessage 形状）。"""
        conn = _get_conn(self._db_path)
        try:
            rows = conn.execute(
                "SELECT seq, role, content, meta_json FROM chat_messages"
                " WHERE owner_key=? AND session_id=? ORDER BY scope_hash, seq",
                (owner, session_id),
            ).fetchall()
            return [dict(r) for r in rows]
        finally:
            conn.close()

    def delete_session(self, owner: str, session_id: str) -> bool:
        conn = _get_conn(self._db_path)
        try:
            with conn:
                cur = conn.execute(
                    "DELETE FROM chat_sessions WHERE owner_key=? AND session_id=?",
                    (owner, session_id),
                )
                conn.execute(
                    "DELETE FROM chat_messages WHERE owner_key=? AND session_id=?",
                    (owner, session_id),
                )
            return cur.rowcount > 0
        finally:
            conn.close()

    def delete_sessions_by_library(self, owner: str, library_id: str) -> int:
        conn = _get_conn(self._db_path)
        try:
            with conn:
                ids = [r["session_id"] for r in conn.execute(
                    "SELECT session_id FROM chat_sessions WHERE owner_key=? AND library_id=?",
                    (owner, library_id),
                ).fetchall()]
                for sid in ids:
                    conn.execute(
                        "DELETE FROM chat_messages WHERE owner_key=? AND session_id=?",
                        (owner, sid),
                    )
                conn.execute(
                    "DELETE FROM chat_sessions WHERE owner_key=? AND library_id=?",
                    (owner, library_id),
                )
            return len(ids)
        finally:
            conn.close()

    def patch_meta(self, owner: str, session_id: str,
                   patches: List[Dict[str, Any]]) -> int:
        """客户端快照 PUT（D10）：仅接受服务端已下发的 seq，浅合并 meta_patch 进 meta_json。

        任一条 seq 不存在 → 整体拒绝（ValueError），避免半合并状态。
        """
        conn = _get_conn(self._db_path)
        try:
            with conn:
                for patch in patches:
                    seq = int(patch["msg_seq"])
                    row = conn.execute(
                        "SELECT meta_json, scope_hash FROM chat_messages"
                        " WHERE owner_key=? AND session_id=? AND seq=?",
                        (owner, session_id, seq),
                    ).fetchone()
                    if row is None:
                        raise ValueError(f"unknown msg_seq: {seq}")
                    extra = json.loads(row["meta_json"] or "{}")
                    meta = dict(extra.get("meta") or {})
                    meta.update(patch.get("meta_patch") or {})
                    extra["meta"] = meta
                    conn.execute(
                        "UPDATE chat_messages SET meta_json=?"
                        " WHERE owner_key=? AND session_id=? AND scope_hash=? AND seq=?",
                        (json.dumps(extra, ensure_ascii=False),
                         owner, session_id, row["scope_hash"], seq),
                    )
            return len(patches)
        finally:
            conn.close()

    # ------------------------------------------------------------ claim / 游客（步 2/3）

    def claim_guest(self, guest_owner: str, user_owner: str, user_id: int) -> int:
        """游客桶改挂用户桶（先到先得：已被认领则幂等返回 0，由路由层翻译语义）。

        返回搬移的会话数；消息行随 owner 一起改挂（PK 含 owner_key，UPDATE 主键段）。
        """
        guest_id = guest_owner[2:] if guest_owner.startswith("g:") else guest_owner
        conn = _get_conn(self._db_path)
        try:
            with conn:
                g = conn.execute(
                    "SELECT claimed_by_user_id FROM chat_guests WHERE guest_id=?",
                    (guest_id,),
                ).fetchone()
                if g is not None and g["claimed_by_user_id"] is not None:
                    return 0  # 先到先得：已认领（含被自己认领）
                conn.execute(
                    "UPDATE chat_guests SET claimed_by_user_id=? WHERE guest_id=?",
                    (user_id, guest_id),
                )
                sids = [r["session_id"] for r in conn.execute(
                    "SELECT session_id FROM chat_sessions WHERE owner_key=?",
                    (guest_owner,),
                ).fetchall()]
                for sid in sids:
                    conn.execute(
                        "UPDATE chat_messages SET owner_key=? WHERE owner_key=? AND session_id=?",
                        (user_owner, guest_owner, sid),
                    )
                    conn.execute(
                        "UPDATE chat_sessions SET owner_key=? WHERE owner_key=? AND session_id=?",
                        (user_owner, guest_owner, sid),
                    )
                conn.execute(
                    "UPDATE chat_runs SET owner_key=? WHERE owner_key=?",
                    (user_owner, guest_owner),
                )
            return len(sids)
        finally:
            conn.close()

    def count_user_messages(self, owner: str) -> int:
        """该 owner 桶下的 user 消息数（诊断用；轮闸请用 guest_rounds——一次提问可能
        因检索重试/steer 追加多条 user 消息，按消息数计会把 1 问答算成多轮）。"""
        conn = _get_conn(self._db_path)
        try:
            return conn.execute(
                "SELECT COUNT(*) AS c FROM chat_messages WHERE owner_key=? AND role='user'",
                (owner,),
            ).fetchone()["c"]
        finally:
            conn.close()

    def guest_rounds(self, owner: str) -> int:
        """轮闸计数：1 个 run = 用户提问 1 次（重试/steer 产生的中间 user 消息不重复计）。
        存量导入的 'imported' 审计行不计轮。"""
        conn = _get_conn(self._db_path)
        try:
            return conn.execute(
                "SELECT COUNT(*) AS c FROM chat_runs"
                " WHERE owner_key=? AND status != 'imported'",
                (owner,),
            ).fetchone()["c"]
        finally:
            conn.close()

    def guest_is_claimed(self, guest_id: str) -> bool:
        """该游客身份是否已被某账号认领。登录过即作废：claim 把 g: 桶搬空后，登出再拿
        同一 cookie 会落到空桶计数清零（2026-09-18 实踩可无限对话），故 claimed 身份
        无论轮数直接拦（产品决策：登录后退回应保持登录，不复活游客额度）。"""
        conn = _get_conn(self._db_path)
        try:
            row = conn.execute(
                "SELECT claimed_by_user_id FROM chat_guests WHERE guest_id=?",
                (guest_id,),
            ).fetchone()
            return bool(row and row["claimed_by_user_id"] is not None)
        finally:
            conn.close()

    def touch_guest(self, guest_id: str) -> None:
        now = _now()
        conn = _get_conn(self._db_path)
        try:
            with conn:
                conn.execute(
                    "INSERT INTO chat_guests (guest_id, created_at, last_seen_at)"
                    " VALUES (?,?,?)"
                    " ON CONFLICT(guest_id) DO UPDATE SET last_seen_at=excluded.last_seen_at",
                    (guest_id, now, now),
                )
        finally:
            conn.close()

    # ------------------------------------------------------------ GC（步 4）

    def gc_expired(self, retention_days: int) -> Dict[str, int]:
        """保留期 GC：消息/审计/游客按各自时间戳清；会话随 updated_at 过期清（消息先行）。"""
        cutoff = (datetime.now(timezone.utc) - timedelta(days=retention_days)).isoformat()
        conn = _get_conn(self._db_path)
        try:
            with conn:
                n_msg = conn.execute(
                    "DELETE FROM chat_messages WHERE created_at<?", (cutoff,)
                ).rowcount
                n_run = conn.execute(
                    "DELETE FROM chat_runs WHERE created_at<?", (cutoff,)
                ).rowcount
                n_sess = conn.execute(
                    "DELETE FROM chat_sessions WHERE updated_at<?", (cutoff,)
                ).rowcount
                n_guest = conn.execute(
                    "DELETE FROM chat_guests"
                    " WHERE COALESCE(last_seen_at, created_at)<?", (cutoff,)
                ).rowcount
            return {"messages": n_msg, "runs": n_run, "sessions": n_sess, "guests": n_guest}
        finally:
            conn.close()
