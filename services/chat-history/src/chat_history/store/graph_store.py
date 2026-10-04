"""对话黑板图存储（M1）：schema + 连接级 DAO + 级联。

设计真相源：``docs/req-blackboard-conversation-mode.md`` §5 / §5.1。

纪律：
- **建表进 ``chat_history.store.init_db``**（本模块导出 ``init_graph_schema(conn)``），
  不另起第二套建表入口——这个库的迁移就是「init_db 内联建表/重建」；
- **键 = (owner_key, session_id)**：阶段三 D6 后会话身份即此两列；``scope_hash`` /
  ``library_ids_json`` 只作**来源列**（不进主键，BB §5 2026-10-04 定版）；
- **append-only 为主**：节点 upsert 只前进 ``last_run``、合并 markers，不删旧；
- **幂等**：``conv_graph_version`` 主键 (owner_key, session_id, run_id)，重复 run 直接跳过；
- **级联五处**：``delete_session`` / ``delete_sessions_by_library`` / ``claim_guest`` /
  ``gc_expired`` / （阶段四库拆·合·退役）——retire ≠ delete，退役只让指针悬空、不删图。

连接口径：本模块所有函数**接收调用方的 conn**，自己不开新连接——与 chat-history 其它 DAO
共用同一个短事务，避免「第二个写入方」把 SQLITE_BUSY 变成偶发丢图（BB §5 双写并发）。
"""
from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from typing import Any, Dict, Iterable, List, Optional, Sequence

from angineer_core.conv_graph import Edge, Graph, Node

_GRAPH_TABLES = ("conv_graph_node", "conv_graph_edge", "conv_graph_version", "conv_graph_state")

SCHEMA: Sequence[str] = (
    # 图本体（当前态）。会话身份 = (owner_key, session_id)；来源两列随身携带
    """
    CREATE TABLE IF NOT EXISTS conv_graph_node (
        owner_key TEXT NOT NULL,
        session_id TEXT NOT NULL,
        node_id TEXT NOT NULL,
        type TEXT NOT NULL,
        key TEXT NOT NULL DEFAULT '',
        value_json TEXT NOT NULL DEFAULT '{}',
        scope_hash TEXT NOT NULL DEFAULT '',
        library_ids_json TEXT NOT NULL DEFAULT '[]',
        first_run TEXT NOT NULL DEFAULT '',
        last_run TEXT NOT NULL DEFAULT '',
        status TEXT NOT NULL DEFAULT 'open',
        PRIMARY KEY (owner_key, session_id, node_id)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS conv_graph_edge (
        owner_key TEXT NOT NULL,
        session_id TEXT NOT NULL,
        edge_id TEXT NOT NULL,
        type TEXT NOT NULL,
        src TEXT NOT NULL,
        dst TEXT NOT NULL,
        meta_json TEXT NOT NULL DEFAULT '{}',
        run_id TEXT NOT NULL DEFAULT '',
        scope_hash TEXT NOT NULL DEFAULT '',
        library_ids_json TEXT NOT NULL DEFAULT '[]',
        PRIMARY KEY (owner_key, session_id, edge_id)
    )
    """,
    # 版本台账：归因 / 回放 / 重建；同时是幂等闸（同一 run 只进图一次）
    """
    CREATE TABLE IF NOT EXISTS conv_graph_version (
        owner_key TEXT NOT NULL,
        session_id TEXT NOT NULL,
        run_id TEXT NOT NULL,
        ops_json TEXT NOT NULL DEFAULT '[]',
        rejected_json TEXT NOT NULL DEFAULT '[]',
        created_at TEXT NOT NULL,
        PRIMARY KEY (owner_key, session_id, run_id)
    )
    """,
    # 水位：进程重启 / 任务被杀后的补跑依据
    """
    CREATE TABLE IF NOT EXISTS conv_graph_state (
        owner_key TEXT NOT NULL,
        session_id TEXT NOT NULL,
        last_run_id TEXT NOT NULL DEFAULT '',
        last_seq INTEGER NOT NULL DEFAULT 0,
        status TEXT NOT NULL DEFAULT '',
        updated_at TEXT NOT NULL,
        PRIMARY KEY (owner_key, session_id)
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_conv_graph_node_run ON conv_graph_node (owner_key, session_id, last_run)",
    "CREATE INDEX IF NOT EXISTS idx_conv_graph_edge_run ON conv_graph_edge (owner_key, session_id, run_id)",
)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def init_graph_schema(conn: sqlite3.Connection) -> None:
    """建图四表 + 索引（由 chat-history ``init_db`` 调用；幂等）。"""
    for statement in SCHEMA:
        conn.execute(statement)


def _libs_json(library_ids: Optional[Iterable[str]]) -> str:
    return json.dumps([str(x) for x in (library_ids or [])], ensure_ascii=False)


def apply_ops(conn: sqlite3.Connection, owner_key: str, session_id: str, run_id: Any,
              ops: Sequence[Dict[str, Any]], *, scope_hash: str = "",
              library_ids: Optional[Iterable[str]] = None) -> bool:
    """把一批（已校验的）op 合并进图，并推进水位。幂等：同一 run 二次调用返回 False。"""
    rid = str(run_id)
    if conn.execute(
        "SELECT 1 FROM conv_graph_version WHERE owner_key=? AND session_id=? AND run_id=?",
        (owner_key, session_id, rid),
    ).fetchone():
        return False
    libs = _libs_json(library_ids)
    now = _now()
    with conn:  # 单批 op 一个短事务（BB §5）
        for op in ops:
            kind = op.get("op")
            if kind == "add_node":
                _upsert_node(conn, owner_key, session_id, rid, op, scope_hash, libs)
            elif kind == "add_edge":
                conn.execute(
                    "INSERT OR REPLACE INTO conv_graph_edge"
                    " (owner_key, session_id, edge_id, type, src, dst, meta_json, run_id,"
                    "  scope_hash, library_ids_json) VALUES (?,?,?,?,?,?,?,?,?,?)",
                    (owner_key, session_id, op.get("edge_id") or f"edge:{rid}:{op.get('dst')}",
                     op.get("type") or "", op.get("src") or "", op.get("dst") or "",
                     json.dumps(op.get("meta") or {}, ensure_ascii=False), rid,
                     scope_hash, libs),
                )
            elif kind == "update_value":
                conn.execute(
                    "UPDATE conv_graph_node SET value_json=?, last_run=?, status='open'"
                    " WHERE owner_key=? AND session_id=? AND node_id=?",
                    (json.dumps(op, ensure_ascii=False), rid, owner_key, session_id,
                     op.get("node_id") or ""),
                )
            elif kind == "mark_resolved":
                conn.execute(
                    "UPDATE conv_graph_node SET status='resolved', last_run=?"
                    " WHERE owner_key=? AND session_id=? AND node_id=?",
                    (rid, owner_key, session_id, op.get("node_id") or ""),
                )
        conn.execute(
            "INSERT OR REPLACE INTO conv_graph_version"
            " (owner_key, session_id, run_id, ops_json, rejected_json, created_at)"
            " VALUES (?,?,?,?,?,?)",
            (owner_key, session_id, rid, json.dumps(list(ops), ensure_ascii=False), "[]", now),
        )
        conn.execute(
            "INSERT INTO conv_graph_state"
            " (owner_key, session_id, last_run_id, last_seq, status, updated_at)"
            " VALUES (?,?,?,?,?,?)"
            " ON CONFLICT(owner_key, session_id) DO UPDATE SET"
            " last_run_id=excluded.last_run_id, status=excluded.status,"
            " updated_at=excluded.updated_at",
            (owner_key, session_id, rid, 0, "ok", now),
        )
    return True


def _upsert_node(conn: sqlite3.Connection, owner_key: str, session_id: str, run_id: str,
                 op: Dict[str, Any], scope_hash: str, libs: str) -> None:
    node_id = op.get("node_id") or ""
    payload = {k: v for k, v in op.items() if k not in ("op", "node_id", "run")}
    row = conn.execute(
        "SELECT value_json FROM conv_graph_node WHERE owner_key=? AND session_id=? AND node_id=?",
        (owner_key, session_id, node_id),
    ).fetchone()
    if row is None:
        marker = op.get("marker")
        if marker:
            payload["markers"] = [marker]
        conn.execute(
            "INSERT INTO conv_graph_node"
            " (owner_key, session_id, node_id, type, key, value_json, scope_hash,"
            "  library_ids_json, first_run, last_run, status) VALUES (?,?,?,?,?,?,?,?,?,?,'open')",
            (owner_key, session_id, node_id, op.get("kind") or "clause", op.get("key") or "",
             json.dumps(payload, ensure_ascii=False), scope_hash, libs, run_id, run_id),
        )
        return
    # 已存在：合并 markers（保序去重），只前进 last_run
    try:
        previous = json.loads(row["value_json"] or "{}")
    except Exception:
        previous = {}
    markers = list(previous.get("markers") or [])
    marker = op.get("marker")
    if marker and marker not in markers:
        markers.append(marker)
    if markers:
        payload["markers"] = markers
    conn.execute(
        "UPDATE conv_graph_node SET value_json=?, last_run=?, library_ids_json=?,"
        " status=CASE WHEN status='resolved' THEN 'resolved' ELSE 'open' END"
        " WHERE owner_key=? AND session_id=? AND node_id=?",
        (json.dumps(payload, ensure_ascii=False), run_id, libs, owner_key, session_id, node_id),
    )


def record_rejected(conn: sqlite3.Connection, owner_key: str, session_id: str, run_id: Any,
                    ops: Sequence[Dict[str, Any]], rejected: Sequence[str], *,
                    scope_hash: str = "", library_ids: Optional[Iterable[str]] = None) -> None:
    """整批拒收时留痕（进 version 台账，不进图）——漂移可逐轮定位（BB §3.3/§9）。"""
    rid = str(run_id)
    if conn.execute(
        "SELECT 1 FROM conv_graph_version WHERE owner_key=? AND session_id=? AND run_id=?",
        (owner_key, session_id, rid),
    ).fetchone():
        return
    with conn:
        conn.execute(
            "INSERT OR REPLACE INTO conv_graph_version"
            " (owner_key, session_id, run_id, ops_json, rejected_json, created_at)"
            " VALUES (?,?,?,?,?,?)",
            (owner_key, session_id, rid, json.dumps(list(ops), ensure_ascii=False),
             json.dumps(list(rejected), ensure_ascii=False), _now()),
        )
        conn.execute(
            "INSERT INTO conv_graph_state"
            " (owner_key, session_id, last_run_id, last_seq, status, updated_at)"
            " VALUES (?,?,?,?,?,?)"
            " ON CONFLICT(owner_key, session_id) DO UPDATE SET"
            " status=excluded.status, updated_at=excluded.updated_at",
            (owner_key, session_id, rid, 0, "rejected", _now()),
        )


def load_graph(conn: sqlite3.Connection, owner_key: str, session_id: str) -> Graph:
    """把图载入内存态（读路径用）。

    ``run_id`` 生产是 uuid hex，而内存态图/渲染段要的是**轮次序号**（「第 N 轮引用」）——
    故按 ``conv_graph_version.created_at`` 顺序把 run_id 映射成 1-based 轮次；
    ``run_cites`` 由 cites 边按轮次重建（序数消解要用）。
    """
    graph = Graph()
    ordinal_by_run: Dict[str, int] = {}
    for index, row in enumerate(conn.execute(
        "SELECT run_id FROM conv_graph_version WHERE owner_key=? AND session_id=?"
        " ORDER BY created_at, rowid",
        (owner_key, session_id),
    ).fetchall(), start=1):
        ordinal_by_run[row["run_id"]] = index

    def _ordinal(run_id: Any) -> int:
        text = str(run_id or "").strip()
        if text.isdigit():                     # 离线/单测直接用数字轮次
            return int(text)
        return ordinal_by_run.get(text, 0)

    rows = conn.execute(
        "SELECT node_id, type, key, value_json, first_run, last_run, status"
        " FROM conv_graph_node WHERE owner_key=? AND session_id=? ORDER BY rowid",
        (owner_key, session_id),
    ).fetchall()
    for row in rows:
        try:
            payload = json.loads(row["value_json"] or "{}")
        except Exception:
            payload = {}
        node = Node(
            node_id=row["node_id"], kind=row["type"], key=row["key"],
            doc_id=payload.get("doc_id", ""), library_id=payload.get("library_id", ""),
            locator=payload.get("locator", ""), doc_title=payload.get("doc_title", ""),
            value=payload.get("value", ""), unit=payload.get("unit", ""),
            first_run=_ordinal(row["first_run"]), last_run=_ordinal(row["last_run"]),
            status=row["status"] or "open", markers=list(payload.get("markers") or []),
        )
        graph.nodes[node.node_id] = node
    edge_rows = conn.execute(
        "SELECT type, src, dst, run_id, meta_json FROM conv_graph_edge"
        " WHERE owner_key=? AND session_id=? ORDER BY rowid",
        (owner_key, session_id),
    ).fetchall()
    for row in edge_rows:
        run = _ordinal(row["run_id"])
        meta = {}
        try:
            meta = json.loads(row["meta_json"] or "{}")
        except Exception:
            meta = {}
        graph.edges.append(Edge(kind=row["type"], src=row["src"], dst=row["dst"], run=run,
                                marker=meta.get("marker", "")))
        if row["type"] == "cites":
            if run not in graph.runs:
                graph.runs.append(run)
            bucket = graph.run_cites.setdefault(run, [])
            if row["dst"] not in bucket:
                bucket.append(row["dst"])
    graph.runs.sort()
    return graph


def last_run(conn: sqlite3.Connection, owner_key: str, session_id: str) -> str:
    row = conn.execute(
        "SELECT last_run_id FROM conv_graph_state WHERE owner_key=? AND session_id=?",
        (owner_key, session_id),
    ).fetchone()
    return (row["last_run_id"] if row else "") or ""


def missing_runs(conn: sqlite3.Connection, owner_key: str, session_id: str) -> List[str]:
    """已落库但未进图的 run（水位补跑依据，BB §3.4）：chat_runs 差集 conv_graph_version。"""
    rows = conn.execute(
        "SELECT r.run_id FROM chat_runs r WHERE r.owner_key=? AND r.session_id=?"
        " AND NOT EXISTS (SELECT 1 FROM conv_graph_version v"
        "  WHERE v.owner_key=r.owner_key AND v.session_id=r.session_id AND v.run_id=r.run_id)"
        " ORDER BY r.created_at",
        (owner_key, session_id),
    ).fetchall()
    return [r["run_id"] for r in rows]


# ——————————————————————————— 级联（BB §5.1 五处） ———————————————————————————

def delete_graph(conn: sqlite3.Connection, owner_key: str, session_id: str) -> int:
    """整会话连带删图。"""
    removed = 0
    with conn:
        for table in _GRAPH_TABLES:
            cur = conn.execute(f"DELETE FROM {table} WHERE owner_key=? AND session_id=?",
                               (owner_key, session_id))
            removed += cur.rowcount or 0
    return removed


def reassign_owner(conn: sqlite3.Connection, old_owner: str, new_owner: str) -> int:
    """owner 改挂（``claim_guest``）：图行一并 UPDATE，否则按 owner 查询漏图。"""
    moved = 0
    with conn:
        for table in _GRAPH_TABLES:
            cur = conn.execute(f"UPDATE {table} SET owner_key=? WHERE owner_key=?",
                               (new_owner, old_owner))
            moved += cur.rowcount or 0
    return moved


def sweep_orphans(conn: sqlite3.Connection) -> int:
    """清孤儿图：会话行已不存在（gc 的「消息先删、会话后删」窗口）时的残留（BB §5.1）。"""
    removed = 0
    with conn:
        for table in _GRAPH_TABLES:
            cur = conn.execute(
                f"DELETE FROM {table} WHERE NOT EXISTS ("
                " SELECT 1 FROM chat_sessions s WHERE s.owner_key={0}.owner_key"
                " AND s.session_id={0}.session_id)".format(table)
            )
            removed += cur.rowcount or 0
    return removed


def stats(conn: sqlite3.Connection, owner_key: str, session_id: str) -> Dict[str, int]:
    """按会话统计（调试版 tab / 影子期观测用）。"""
    out: Dict[str, int] = {}
    for table in _GRAPH_TABLES:
        out[table] = conn.execute(
            f"SELECT COUNT(*) AS c FROM {table} WHERE owner_key=? AND session_id=?",
            (owner_key, session_id),
        ).fetchone()["c"]
    return out


class ConvGraphStore:
    """图存储适配器（aichat-api 组装注入；引擎只认 apply_ops/record_rejected/load_graph 三个方法）。

    路径口径与 ``chat_history.store.sqlite_store.DB_PATH`` **同源同值**
    （``resolve_data_file("CHAT_DB_PATH", "platform/chat.sqlite")``）——不在本模块 import
    sqlite_store，避免与它的 ``from .graph_store import ...`` 形成循环。
    """

    def __init__(self, db_path: Optional[str] = None) -> None:
        if db_path:
            self._db_path = db_path
        else:
            from shared.paths import resolve_data_file

            self._db_path = resolve_data_file("CHAT_DB_PATH", "platform/chat.sqlite")

    @property
    def db_path(self) -> str:
        return self._db_path

    def _conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self._db_path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA busy_timeout=5000")
        return conn

    def init(self) -> None:
        conn = self._conn()
        try:
            with conn:
                init_graph_schema(conn)
        finally:
            conn.close()

    def apply_ops(self, owner_key: str, session_id: str, run_id: Any,
                  ops: Sequence[Dict[str, Any]], *, scope_hash: str = "",
                  library_ids: Optional[Iterable[str]] = None) -> bool:
        conn = self._conn()
        try:
            return apply_ops(conn, owner_key, session_id, run_id, ops,
                             scope_hash=scope_hash, library_ids=library_ids)
        finally:
            conn.close()

    def record_rejected(self, owner_key: str, session_id: str, run_id: Any,
                        ops: Sequence[Dict[str, Any]], rejected: Sequence[str], *,
                        scope_hash: str = "",
                        library_ids: Optional[Iterable[str]] = None) -> None:
        conn = self._conn()
        try:
            record_rejected(conn, owner_key, session_id, run_id, ops, rejected,
                            scope_hash=scope_hash, library_ids=library_ids)
        finally:
            conn.close()

    def load_graph(self, owner_key: str, session_id: str) -> Graph:
        conn = self._conn()
        try:
            return load_graph(conn, owner_key, session_id)
        finally:
            conn.close()

    def last_run(self, owner_key: str, session_id: str) -> str:
        conn = self._conn()
        try:
            return last_run(conn, owner_key, session_id)
        finally:
            conn.close()

    def missing_runs(self, owner_key: str, session_id: str) -> List[str]:
        conn = self._conn()
        try:
            return missing_runs(conn, owner_key, session_id)
        finally:
            conn.close()

    def stats(self, owner_key: str, session_id: str) -> Dict[str, int]:
        conn = self._conn()
        try:
            return stats(conn, owner_key, session_id)
        finally:
            conn.close()
