"""结构化结果数据库存储。"""
import json
import sqlite3
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

import docs_core.paths as paths
from tree_core import tree_store

from docs_core.step04_structure.solo_engine import StructuredResult
from docs_core.models.types import STRUCTURED_DOC_GRAPH_STRATEGY
from docs_core.step05_sqlite_fts.store.sqlite_utils import create_connection


# 安全解析数据库中的时间字符串。
def parse_datetime(dt_str: Optional[str]) -> datetime:
    if not dt_str:
        return datetime.now()
    try:
        return datetime.fromisoformat(dt_str)
    except (TypeError, ValueError):
        try:
            from dateutil import parser

            return parser.parse(dt_str)
        except Exception:
            return datetime.now()


class KnowledgeMetaStore:
    """业务元数据数据库访问层。"""

    def __init__(
        self,
        db_path: Optional[Path] = None,
        schema_version: str = "1.0.0",
    ) -> None:
        self.db_path = db_path or paths.resolve_knowledge_meta_db_path()
        self.schema_version = schema_version
        self.init_schema()

    # 打开元数据库连接。
    def connect(self) -> sqlite3.Connection:
        return create_connection(self.db_path)

    # 初始化元数据库 Schema，含自动迁移逻辑。
    def init_schema(self) -> None:
        with self.connect() as conn:
            self._migrate_if_needed(conn)
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS libraries (
                    id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    description TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS nodes (
                    id TEXT PRIMARY KEY,
                    title TEXT NOT NULL,
                    type TEXT NOT NULL,
                    visible INTEGER NOT NULL,
                    library_id TEXT NOT NULL,
                    file_path TEXT,
                    status TEXT NOT NULL,
                    parse_progress INTEGER NOT NULL DEFAULT 0,
                    parse_stage TEXT,
                    parse_error TEXT,
                    parse_task_id TEXT,
                    strategy TEXT NOT NULL DEFAULT 'doc_blocks_graph_v1',
                    schema_version TEXT NOT NULL DEFAULT '1.0.0',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS parse_tasks (
                    id TEXT PRIMARY KEY,
                    library_id TEXT NOT NULL,
                    doc_id TEXT NOT NULL,
                    status TEXT NOT NULL,
                    progress INTEGER NOT NULL DEFAULT 0,
                    stage TEXT NOT NULL,
                    stage_message TEXT,
                    error TEXT,
                    schema_version TEXT NOT NULL DEFAULT '1.0.0',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )
            try:
                conn.execute(
                    """
                    ALTER TABLE parse_tasks ADD COLUMN stage_message TEXT
                    """
                )
            except sqlite3.OperationalError:
                pass
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS parse_task_steps (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    task_id TEXT NOT NULL,
                    doc_id TEXT NOT NULL,
                    stage TEXT NOT NULL,
                    progress INTEGER NOT NULL DEFAULT 0,
                    stage_message TEXT,
                    created_at TEXT NOT NULL
                )
                """
            )
            conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_parse_task_steps_task
                ON parse_task_steps (task_id, created_at ASC)
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS parse_stage_steps (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    doc_id TEXT NOT NULL,
                    stage TEXT NOT NULL,
                    step TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'done',
                    detail TEXT DEFAULT '',
                    created_at TEXT NOT NULL
                )
                """
            )
            conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_parse_stage_steps_doc_stage
                ON parse_stage_steps (doc_id, stage, created_at ASC)
                """
            )
            conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_nodes_library_type
                ON nodes (library_id, type, created_at)
                """
            )
            conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_parse_tasks_doc_created
                ON parse_tasks (doc_id, created_at DESC)
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS doc_parse_stages (
                    doc_id TEXT NOT NULL,
                    stage TEXT NOT NULL,
                    status TEXT NOT NULL,
                    message TEXT DEFAULT '',
                    error TEXT DEFAULT '',
                    started_at TEXT,
                    finished_at TEXT,
                    updated_at TEXT NOT NULL,
                    PRIMARY KEY (doc_id, stage)
                )
                """
            )
            try:
                conn.execute("ALTER TABLE doc_parse_stages ADD COLUMN input_summary TEXT DEFAULT ''")
            except sqlite3.OperationalError:
                pass
            try:
                conn.execute("ALTER TABLE doc_parse_stages ADD COLUMN output_summary TEXT DEFAULT ''")
            except sqlite3.OperationalError:
                pass
            try:
                conn.execute("ALTER TABLE doc_parse_stages ADD COLUMN fallback TEXT DEFAULT ''")
            except sqlite3.OperationalError:
                pass
            try:
                conn.execute("ALTER TABLE doc_parse_stages ADD COLUMN page_count INTEGER DEFAULT 0")
            except sqlite3.OperationalError:
                pass
            try:
                conn.execute("ALTER TABLE doc_parse_stages ADD COLUMN is_scanned INTEGER DEFAULT 0")
            except sqlite3.OperationalError:
                pass
            try:
                conn.execute("ALTER TABLE nodes ADD COLUMN deleted INTEGER NOT NULL DEFAULT 0")
            except sqlite3.OperationalError:
                pass
            conn.commit()
            tree_store.init_table(conn)

    # 检测并迁移旧版 nodes 表（含 parent_id/sort_order 列）。
    def _migrate_if_needed(self, conn: sqlite3.Connection) -> None:
        cols = [r[1] for r in conn.execute("PRAGMA table_info(nodes)").fetchall()]
        if "parent_id" not in cols:
            return
        tree_store.init_table(conn)
        rows = conn.execute(
            "SELECT id, title, type, parent_id, sort_order, library_id, visible, file_path, status, created_at, updated_at FROM nodes"
        ).fetchall()
        for row in rows:
            node_id, title, node_type, parent_id, sort_order, library_id, visible, file_path, status, created_at, updated_at = row
            is_folder = node_type == "folder"
            tree_type = "knowledge_folder" if is_folder else "knowledge_doc"
            extra = {}
            if not is_folder:
                extra = {"visible": bool(visible), "file_path": file_path, "status": status}
            tree_store.insert_node(conn, {
                "node_id": node_id,
                "tree_type": tree_type,
                "title": title,
                "parent_id": parent_id,
                "scope_id": library_id,
                "sort_order": sort_order,
                "is_folder": is_folder,
                "extra": extra,
            })
        conn.execute(
            """
            CREATE TABLE nodes_new (
                id TEXT PRIMARY KEY,
                title TEXT NOT NULL,
                type TEXT NOT NULL,
                visible INTEGER NOT NULL,
                library_id TEXT NOT NULL,
                file_path TEXT,
                status TEXT NOT NULL,
                parse_progress INTEGER NOT NULL DEFAULT 0,
                parse_stage TEXT,
                parse_error TEXT,
                parse_task_id TEXT,
                strategy TEXT NOT NULL DEFAULT 'doc_blocks_graph_v1',
                schema_version TEXT NOT NULL DEFAULT '1.0.0',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
            """
        )
        conn.execute(
            """
            INSERT INTO nodes_new (id, title, type, visible, library_id, file_path, status,
                                   parse_progress, parse_stage, parse_error, parse_task_id,
                                   strategy, schema_version, created_at, updated_at)
            SELECT id, title, type, visible, library_id, file_path, status,
                   parse_progress, parse_stage, parse_error, parse_task_id,
                   strategy, schema_version, created_at, updated_at
            FROM nodes
            WHERE type != 'folder'
            """
        )
        conn.execute("DROP TABLE nodes")
        conn.execute("ALTER TABLE nodes_new RENAME TO nodes")
        conn.commit()

    # 读取所有知识库。
    def list_libraries(self) -> List[sqlite3.Row]:
        with self.connect() as conn:
            return conn.execute(
                "SELECT id, name, description, created_at, updated_at FROM libraries ORDER BY created_at ASC"
            ).fetchall()

    # 读取所有节点：folder 从 tree_node 读取，document 从 nodes + tree_node 合并。
    def list_nodes(self) -> List[Dict[str, Any]]:
        with self.connect() as conn:
            result = []
            doc_rows = conn.execute(
                """
                SELECT id, title, type, visible, library_id, file_path, status,
                       parse_progress, parse_stage, parse_error, parse_task_id, strategy,
                       schema_version, deleted, created_at, updated_at
                FROM nodes
                ORDER BY library_id ASC, created_at ASC
                """
            ).fetchall()
            for row in doc_rows:
                item = dict(row)
                tree_node = tree_store.get_node(conn, item["id"])
                if tree_node:
                    item["parent_id"] = tree_node.get("parent_id")
                    item["sort_order"] = tree_node.get("sort_order", 0)
                else:
                    item["parent_id"] = None
                    item["sort_order"] = 0
                result.append(item)
            folder_rows = conn.execute(
                """
                SELECT node_id, title, parent_id, scope_id, sort_order, deleted, created_at, updated_at
                FROM tree_node
                WHERE tree_type = 'knowledge_folder'
                ORDER BY scope_id ASC, sort_order ASC
                """
            ).fetchall()
            for row in folder_rows:
                item = dict(row)
                result.append({
                    "id": item["node_id"],
                    "title": item["title"],
                    "type": "folder",
                    "parent_id": item["parent_id"],
                    "visible": True,
                    "library_id": item["scope_id"],
                    "file_path": None,
                    "status": "completed",
                    "parse_progress": 0,
                    "parse_stage": None,
                    "parse_error": None,
                    "parse_task_id": None,
                    "strategy": STRUCTURED_DOC_GRAPH_STRATEGY,
                    "schema_version": "1.0.0",
                    "sort_order": item["sort_order"],
                    "deleted": bool(item.get("deleted")),
                    "created_at": item["created_at"],
                    "updated_at": item["updated_at"],
                })
            return result

    # 读取所有解析任务。
    def list_parse_tasks(self) -> List[sqlite3.Row]:
        with self.connect() as conn:
            return conn.execute(
                """
                SELECT id, library_id, doc_id, status, progress, stage, stage_message, error, schema_version, created_at, updated_at
                FROM parse_tasks
                ORDER BY created_at DESC
                """
            ).fetchall()

    # 持久化知识库记录。
    def upsert_library(self, library: Any) -> None:
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO libraries (id, name, description, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    name = excluded.name,
                    description = excluded.description,
                    updated_at = excluded.updated_at
                """,
                (
                    library.id,
                    library.name,
                    library.description,
                    library.created_at.isoformat(),
                    library.updated_at.isoformat(),
                ),
            )
            conn.commit()

    # 持久化节点记录：folder 只写 tree_node，document 写 nodes + tree_node。
    def upsert_node(self, node: Any) -> None:
        with self.connect() as conn:
            is_folder = getattr(node, "type", "") == "folder"
            if is_folder:
                tree_store.insert_node(conn, {
                    "node_id": node.id,
                    "tree_type": "knowledge_folder",
                    "title": node.title,
                    "parent_id": node.parent_id,
                    "scope_id": node.library_id,
                    "sort_order": node.sort_order,
                    "is_folder": True,
                })
                conn.commit()
            else:
                tree_store.insert_node(conn, {
                    "node_id": node.id,
                    "tree_type": "knowledge_doc",
                    "title": node.title,
                    "parent_id": node.parent_id,
                    "scope_id": node.library_id,
                    "sort_order": node.sort_order,
                    "is_folder": False,
                    "extra": {
                        "visible": node.visible,
                        "file_path": node.file_path,
                        "status": node.status,
                    },
                })
                conn.execute(
                    """
                    INSERT INTO nodes (
                        id, title, type, visible, library_id, file_path, status, parse_progress,
                        parse_stage, parse_error, parse_task_id, strategy, schema_version, deleted, created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(id) DO UPDATE SET
                        title = excluded.title,
                        type = excluded.type,
                        visible = excluded.visible,
                        library_id = excluded.library_id,
                        file_path = excluded.file_path,
                        status = excluded.status,
                        parse_progress = excluded.parse_progress,
                        parse_stage = excluded.parse_stage,
                        parse_error = excluded.parse_error,
                        parse_task_id = excluded.parse_task_id,
                        strategy = excluded.strategy,
                        schema_version = excluded.schema_version,
                        deleted = excluded.deleted,
                        updated_at = excluded.updated_at
                    """,
                    (
                        node.id,
                        node.title,
                        node.type,
                        1 if node.visible else 0,
                        node.library_id,
                        node.file_path,
                        node.status,
                        node.parse_progress,
                        node.parse_stage,
                        node.parse_error,
                        node.parse_task_id,
                        node.strategy,
                        node.schema_version,
                        1 if getattr(node, "deleted", False) else 0,
                        node.created_at.isoformat(),
                        node.updated_at.isoformat(),
                    ),
                )
                conn.commit()

    # 持久化解析任务记录。
    def upsert_parse_task(self, task: Any) -> None:
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO parse_tasks (id, library_id, doc_id, status, progress, stage, stage_message, error, schema_version, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    status = excluded.status,
                    progress = excluded.progress,
                    stage = excluded.stage,
                    stage_message = excluded.stage_message,
                    error = excluded.error,
                    schema_version = excluded.schema_version,
                    updated_at = excluded.updated_at
                """,
                (
                    task.id,
                    task.library_id,
                    task.doc_id,
                    task.status,
                    task.progress,
                    task.stage,
                    getattr(task, "stage_message", None),
                    task.error,
                    task.schema_version,
                    task.created_at.isoformat(),
                    task.updated_at.isoformat(),
                ),
            )
            conn.commit()

    def insert_parse_task_step(self, task_id: str, doc_id: str, stage: str, progress: int, stage_message: Optional[str] = None) -> None:
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO parse_task_steps (task_id, doc_id, stage, progress, stage_message, created_at)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (task_id, doc_id, stage, progress, stage_message, datetime.now().isoformat()),
            )
            conn.commit()

    def get_parse_task_steps(self, task_id: str) -> list[dict]:
        with self.connect() as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                "SELECT * FROM parse_task_steps WHERE task_id = ? ORDER BY created_at ASC",
                (task_id,),
            ).fetchall()
            return [dict(r) for r in rows]

    def upsert_parse_stage(
        self,
        doc_id: str,
        stage: str,
        *,
        status: str,
        message: str = "",
        error: str = "",
        started_at: Optional[str] = None,
        finished_at: Optional[str] = None,
        input_summary: str = "",
        output_summary: str = "",
        fallback: str = "",
        page_count: int = 0,
        is_scanned: bool = False,
    ) -> None:
        now = datetime.now().isoformat()
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO doc_parse_stages (doc_id, stage, status, message, error, started_at, finished_at, updated_at, input_summary, output_summary, fallback, page_count, is_scanned)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT (doc_id, stage) DO UPDATE SET
                    status = excluded.status,
                    message = excluded.message,
                    error = excluded.error,
                    started_at = COALESCE(excluded.started_at, doc_parse_stages.started_at),
                    finished_at = COALESCE(excluded.finished_at, doc_parse_stages.finished_at),
                    updated_at = excluded.updated_at,
                    input_summary = COALESCE(excluded.input_summary, doc_parse_stages.input_summary),
                    output_summary = COALESCE(excluded.output_summary, doc_parse_stages.output_summary),
                    fallback = COALESCE(excluded.fallback, doc_parse_stages.fallback),
                    page_count = COALESCE(excluded.page_count, doc_parse_stages.page_count),
                    is_scanned = COALESCE(excluded.is_scanned, doc_parse_stages.is_scanned)
                """,
                (doc_id, stage, status, message, error, started_at, finished_at, now, input_summary, output_summary, fallback, int(page_count or 0), 1 if is_scanned else 0),
            )
            conn.commit()

    def list_parse_stages(self, doc_id: str) -> List[dict]:
        with self.connect() as conn:
            rows = conn.execute(
                "SELECT doc_id, stage, status, message, error, started_at, finished_at, updated_at, input_summary, output_summary, fallback, page_count, is_scanned "
                "FROM doc_parse_stages WHERE doc_id = ? ORDER BY updated_at ASC",
                (doc_id,),
            ).fetchall()
        return [dict(row) for row in rows]

    def page_counts_by_doc_ids(self, doc_ids: List[str]) -> Dict[str, int]:
        """批量查询各文档 raw_parse 阶段落库的页数（列表页展示用，缺省返回 0）。"""
        if not doc_ids:
            return {}
        placeholders = ",".join("?" * len(doc_ids))
        with self.connect() as conn:
            rows = conn.execute(
                "SELECT doc_id, MAX(page_count) AS page_count FROM doc_parse_stages "
                f"WHERE doc_id IN ({placeholders}) AND stage = 'raw_parse' GROUP BY doc_id",
                tuple(doc_ids),
            ).fetchall()
        result: Dict[str, int] = {}
        for row in rows:
            item = dict(row)
            result[str(item.get("doc_id") or "")] = int(item.get("page_count") or 0)
        return result

    def clear_parse_stages(self, doc_id: str) -> None:
        with self.connect() as conn:
            conn.execute("DELETE FROM doc_parse_stages WHERE doc_id = ?", (doc_id,))
            conn.commit()

    # 记录阶段内分析步骤（如 MinerU 产物落盘 / PoPo 对齐检查 / 信号注入等），供前端展示条逐项展示
    def insert_parse_stage_step(
        self,
        doc_id: str,
        stage: str,
        step: str,
        status: str = "done",
        detail: str = "",
    ) -> None:
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO parse_stage_steps (doc_id, stage, step, status, detail, created_at)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (doc_id, stage, step, status, detail, datetime.now().isoformat()),
            )
            conn.commit()

    def list_parse_stage_steps(self, doc_id: str) -> List[dict]:
        with self.connect() as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                "SELECT doc_id, stage, step, status, detail, created_at "
                "FROM parse_stage_steps WHERE doc_id = ? ORDER BY created_at ASC, id ASC",
                (doc_id,),
            ).fetchall()
            return [dict(r) for r in rows]

    def clear_parse_stage_steps(self, doc_id: str, stage: Optional[str] = None) -> None:
        with self.connect() as conn:
            if stage:
                conn.execute(
                    "DELETE FROM parse_stage_steps WHERE doc_id = ? AND stage = ?",
                    (doc_id, stage),
                )
            else:
                conn.execute("DELETE FROM parse_stage_steps WHERE doc_id = ?", (doc_id,))
            conn.commit()

    # 标记/取消标记节点软删除状态（nodes 表 + tree_node 表）。
    def mark_nodes_deleted(self, node_ids: List[str], deleted: bool) -> None:
        if not node_ids:
            return
        placeholders = ",".join(["?"] * len(node_ids))
        flag = 1 if deleted else 0
        with self.connect() as conn:
            conn.execute(
                f"UPDATE nodes SET deleted = ? WHERE id IN ({placeholders})",
                [flag, *node_ids],
            )
            for nid in node_ids:
                tree_store.mark_node_deleted(conn, nid, deleted)
            conn.commit()

    # 删除节点记录，同步删除 tree_node。
    def delete_nodes(self, node_ids: List[str]) -> None:
        if not node_ids:
            return
        placeholders = ",".join(["?"] * len(node_ids))
        with self.connect() as conn:
            conn.execute(f"DELETE FROM nodes WHERE id IN ({placeholders})", node_ids)
            for nid in node_ids:
                tree_store.delete_node(conn, nid)
            conn.commit()

    # 删除指定文档集合的解析任务记录（含 parse_task_steps 明细）。
    def delete_parse_tasks_by_doc_ids(self, doc_ids: List[str]) -> int:
        if not doc_ids:
            return 0
        placeholders = ",".join(["?"] * len(doc_ids))
        with self.connect() as conn:
            cursor = conn.execute(f"DELETE FROM parse_tasks WHERE doc_id IN ({placeholders})", doc_ids)
            conn.execute(f"DELETE FROM parse_task_steps WHERE doc_id IN ({placeholders})", doc_ids)
            conn.execute(f"DELETE FROM parse_stage_steps WHERE doc_id IN ({placeholders})", doc_ids)
            conn.commit()
            return int(cursor.rowcount or 0)


class KnowledgeIndexStore:
    """索引数据库访问层。"""

    def __init__(
        self,
        db_path: Optional[Path] = None,
        schema_version: str = "1.0.0",
    ) -> None:
        self.db_path = db_path or paths.resolve_knowledge_index_db_path()
        self.schema_version = schema_version
        self.init_schema()

    # 打开索引数据库连接。
    def connect(self) -> sqlite3.Connection:
        return create_connection(self.db_path)

    # 初始化索引数据库 Schema。
    def init_schema(self) -> None:
        with self.connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS doc_blocks (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    doc_id TEXT NOT NULL,
                    doc_name TEXT,
                    page_idx INTEGER NOT NULL,
                    page_width REAL NOT NULL,
                    page_height REAL NOT NULL,
                    block_seq INTEGER NOT NULL,
                    block_uid TEXT NOT NULL,
                    block_type TEXT NOT NULL,
                    content_json TEXT NOT NULL,
                    plain_text TEXT,
                    bbox_abs_x1 REAL NOT NULL,
                    bbox_abs_y1 REAL NOT NULL,
                    bbox_abs_x2 REAL NOT NULL,
                    bbox_abs_y2 REAL NOT NULL,
                    page_seq INTEGER,
                    sub_type TEXT,
                    bbox_norm_x1 REAL,
                    bbox_norm_y1 REAL,
                    bbox_norm_x2 REAL,
                    bbox_norm_y2 REAL,
                    bbox_source TEXT,
                    raw_title_level INTEGER,
                    derived_title_level INTEGER,
                    title_path TEXT,
                    parent_block_uid TEXT,
                    prev_block_uid TEXT,
                    next_block_uid TEXT,
                    explain_for_block_uid TEXT,
                    explain_type TEXT,
                    table_type TEXT,
                    table_nest_level INTEGER,
                    table_html TEXT,
                    math_type TEXT,
                    math_content TEXT,
                    image_path TEXT,
                    quality_score REAL,
                    derived_confidence REAL,
                    derived_by TEXT,
                    derive_version TEXT,
                    parser_version TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    is_active INTEGER NOT NULL
                )
                """
            )
            conn.execute(
                """
                CREATE UNIQUE INDEX IF NOT EXISTS uq_doc_blocks_block_uid
                ON doc_blocks(block_uid)
                """
            )
            conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_doc_blocks_doc_page_seq
                ON doc_blocks(doc_id, page_idx, block_seq)
                """
            )
            conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_doc_blocks_doc_type
                ON doc_blocks(doc_id, block_type)
                """
            )
            conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_doc_blocks_doc_active
                ON doc_blocks(doc_id, is_active)
                """
            )
            conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_doc_blocks_doc_parent
                ON doc_blocks(doc_id, parent_block_uid)
                """
            )
            conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_doc_blocks_doc_heading
                ON doc_blocks(doc_id, derived_title_level, page_idx)
                """
            )
            conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_doc_blocks_doc_explain
                ON doc_blocks(doc_id, explain_for_block_uid)
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS document_segments (
                    id TEXT PRIMARY KEY,
                    doc_id TEXT NOT NULL,
                    library_id TEXT NOT NULL,
                    strategy TEXT NOT NULL,
                    item_type TEXT NOT NULL,
                    title TEXT,
                    content TEXT NOT NULL,
                    meta_json TEXT,
                    schema_version TEXT NOT NULL DEFAULT '1.0.0',
                    order_index INTEGER NOT NULL DEFAULT 0,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )
            conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_document_segments_doc_strategy
                ON document_segments (doc_id, strategy, item_type, order_index)
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS doc_block_corrections (
                    id TEXT PRIMARY KEY,
                    doc_id TEXT NOT NULL,
                    block_uid TEXT NOT NULL,
                    operation_type TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    created_at TEXT NOT NULL
                )
                """
            )
            conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_doc_block_corrections_doc_block
                ON doc_block_corrections(doc_id, block_uid, created_at)
                """
            )
            conn.commit()

    # 删除指定文档或策略下的片段投影。
    def clear_document_segments(self, doc_id: str, strategy: Optional[str] = None) -> int:
        with self.connect() as conn:
            if strategy:
                cursor = conn.execute(
                    "DELETE FROM document_segments WHERE doc_id = ? AND strategy = ?",
                    (doc_id, strategy),
                )
            else:
                cursor = conn.execute(
                    "DELETE FROM document_segments WHERE doc_id = ?",
                    (doc_id,),
                )
            conn.commit()
            return int(cursor.rowcount or 0)

    # 批量写入文档片段投影。
    def save_document_segments(
        self,
        doc_id: str,
        library_id: str,
        strategy: str,
        items: List[Dict[str, Any]],
    ) -> int:
        now = datetime.now().isoformat()
        self.clear_document_segments(doc_id, strategy)
        rows = []
        for index, item in enumerate(items):
            rows.append(
                (
                    item.get("id") or f"seg-{uuid.uuid4().hex[:12]}",
                    doc_id,
                    library_id,
                    strategy,
                    item.get("item_type", "segment"),
                    item.get("title"),
                    item.get("content", ""),
                    json.dumps(item.get("meta", {}), ensure_ascii=False),
                    item.get("schema_version", self.schema_version),
                    index,
                    now,
                    now,
                )
            )
        if not rows:
            return 0
        with self.connect() as conn:
            conn.executemany(
                """
                INSERT INTO document_segments (
                    id, doc_id, library_id, strategy, item_type, title, content, meta_json, schema_version, order_index, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                rows,
            )
            conn.commit()
            return len(rows)

    # 更新单个文档块的可编辑字段。
    def update_doc_block_fields(self, doc_id: str, block_uid: str, changes: Dict[str, Any]) -> int:
        column_map = {
            "plain_text": "plain_text",
            "table_html": "table_html",
            "math_content": "math_content",
            "title": "title_path",
            "title_path": "title_path",
            "parent_block_uid": "parent_block_uid",
            "derived_title_level": "derived_title_level",
            "is_active": "is_active",
        }
        assignments = []
        values: List[Any] = []
        for key, column in column_map.items():
            if key in changes:
                assignments.append(f"{column} = ?")
                values.append(changes.get(key))
        if not assignments:
            return 0
        assignments.append("updated_at = ?")
        values.append(datetime.now().isoformat())
        values.extend([doc_id, block_uid])
        with self.connect() as conn:
            cursor = conn.execute(
                f"""
                UPDATE doc_blocks
                SET {", ".join(assignments)}
                WHERE doc_id = ? AND block_uid = ?
                """,
                values,
            )
            conn.commit()
            return int(cursor.rowcount or 0)

    # 批量改写指定父节点下的子节点归属。
    def reparent_doc_blocks(self, doc_id: str, source_parent_uid: str, target_parent_uid: Optional[str]) -> int:
        with self.connect() as conn:
            cursor = conn.execute(
                """
                UPDATE doc_blocks
                SET parent_block_uid = ?, updated_at = ?
                WHERE doc_id = ? AND parent_block_uid = ?
                """,
                (target_parent_uid, datetime.now().isoformat(), doc_id, source_parent_uid),
            )
            conn.commit()
            return int(cursor.rowcount or 0)

    # 记录块级结构纠错操作。
    def record_doc_block_correction(
        self,
        doc_id: str,
        block_uid: str,
        operation_type: str,
        payload: Dict[str, Any],
    ) -> str:
        record_id = f"dbcorr-{uuid.uuid4().hex[:16]}"
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO doc_block_corrections (
                    id, doc_id, block_uid, operation_type, payload_json, created_at
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    record_id,
                    doc_id,
                    block_uid,
                    operation_type,
                    json.dumps(payload, ensure_ascii=False),
                    datetime.now().isoformat(),
                ),
            )
            conn.commit()
        return record_id

    # 查询指定文档最新的一条块级结构纠错记录。
    def get_latest_doc_block_correction(
        self,
        doc_id: str,
        operation_type: Optional[str] = None,
    ) -> Optional[Dict[str, Any]]:
        with self.connect() as conn:
            if operation_type:
                cursor = conn.execute(
                    """
                    SELECT id, doc_id, block_uid, operation_type, payload_json, created_at
                    FROM doc_block_corrections
                    WHERE doc_id = ? AND operation_type = ?
                    ORDER BY created_at DESC
                    LIMIT 1
                    """,
                    (doc_id, operation_type),
                )
            else:
                cursor = conn.execute(
                    """
                    SELECT id, doc_id, block_uid, operation_type, payload_json, created_at
                    FROM doc_block_corrections
                    WHERE doc_id = ?
                    ORDER BY created_at DESC
                    LIMIT 1
                    """,
                    (doc_id,),
                )
            row = cursor.fetchone()
        if not row:
            return None
        payload_json = row["payload_json"] if isinstance(row, sqlite3.Row) else row[4]
        try:
            payload = json.loads(payload_json) if payload_json else {}
        except Exception:
            payload = {}
        return {
            "id": row["id"] if isinstance(row, sqlite3.Row) else row[0],
            "doc_id": row["doc_id"] if isinstance(row, sqlite3.Row) else row[1],
            "block_uid": row["block_uid"] if isinstance(row, sqlite3.Row) else row[2],
            "operation_type": row["operation_type"] if isinstance(row, sqlite3.Row) else row[3],
            "payload": payload,
            "created_at": row["created_at"] if isinstance(row, sqlite3.Row) else row[5],
        }

    # 删除指定 ID 的块级结构纠错记录。
    def delete_doc_block_correction(self, record_id: str) -> int:
        with self.connect() as conn:
            cursor = conn.execute(
                "DELETE FROM doc_block_corrections WHERE id = ?",
                (record_id,),
            )
            conn.commit()
            return int(cursor.rowcount or 0)

    # 清空指定文档的块级结构纠错记录。
    def clear_doc_block_corrections(self, doc_id: str) -> int:
        with self.connect() as conn:
            cursor = conn.execute("DELETE FROM doc_block_corrections WHERE doc_id = ?", (doc_id,))
            conn.commit()
            return int(cursor.rowcount or 0)

    # 清空指定文档的块索引。
    def clear_doc_blocks(self, doc_id: str) -> int:
        with self.connect() as conn:
            cursor = conn.execute("DELETE FROM doc_blocks WHERE doc_id = ?", (doc_id,))
            conn.commit()
            return int(cursor.rowcount or 0)

    # 批量写入基础块索引行。
    def insert_doc_blocks_base_rows(self, rows: List[Dict[str, Any]]) -> int:
        inserted = 0
        with self.connect() as conn:
            for row in rows:
                conn.execute(
                    """
                    INSERT INTO doc_blocks (
                        doc_id, doc_name, page_idx, page_width, page_height,
                        block_seq, block_uid, block_type, content_json, plain_text,
                        bbox_abs_x1, bbox_abs_y1, bbox_abs_x2, bbox_abs_y2,
                        created_at, updated_at, is_active
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1)
                    """,
                    (
                        row.get("doc_id"),
                        row.get("doc_name"),
                        row.get("page_idx", 0),
                        row.get("page_width", 0.0),
                        row.get("page_height", 0.0),
                        row.get("block_seq", 0),
                        row.get("block_uid"),
                        row.get("block_type"),
                        json.dumps(row.get("content_json", {}), ensure_ascii=False),
                        row.get("plain_text", ""),
                        row.get("bbox_abs_x1", 0.0),
                        row.get("bbox_abs_y1", 0.0),
                        row.get("bbox_abs_x2", 0.0),
                        row.get("bbox_abs_y2", 0.0),
                        row.get("created_at"),
                        row.get("updated_at"),
                    ),
                )
                inserted += 1
            conn.commit()
        return inserted

    # 批量更新块索引的推导字段。
    def update_doc_blocks_derived_rows(self, rows: List[Dict[str, Any]]) -> int:
        updated = 0
        with self.connect() as conn:
            for row in rows:
                conn.execute(
                    """
                    UPDATE doc_blocks SET
                        page_seq = ?,
                        sub_type = ?,
                        bbox_norm_x1 = ?,
                        bbox_norm_y1 = ?,
                        bbox_norm_x2 = ?,
                        bbox_norm_y2 = ?,
                        bbox_source = ?,
                        raw_title_level = ?,
                        derived_title_level = ?,
                        title_path = ?,
                        parent_block_uid = ?,
                        prev_block_uid = ?,
                        next_block_uid = ?,
                        explain_for_block_uid = ?,
                        explain_type = ?,
                        table_type = ?,
                        table_nest_level = ?,
                        table_html = ?,
                        math_type = ?,
                        math_content = ?,
                        image_path = ?,
                        quality_score = ?,
                        derived_confidence = ?,
                        derived_by = ?,
                        derive_version = ?,
                        parser_version = ?,
                        updated_at = ?
                    WHERE block_uid = ?
                    """,
                    (
                        row.get("page_seq"),
                        row.get("sub_type"),
                        row.get("bbox_norm_x1"),
                        row.get("bbox_norm_y1"),
                        row.get("bbox_norm_x2"),
                        row.get("bbox_norm_y2"),
                        row.get("bbox_source"),
                        row.get("raw_title_level"),
                        row.get("derived_title_level"),
                        row.get("title_path"),
                        row.get("parent_block_uid"),
                        row.get("prev_block_uid"),
                        row.get("next_block_uid"),
                        row.get("explain_for_block_uid"),
                        row.get("explain_type"),
                        row.get("table_type"),
                        row.get("table_nest_level"),
                        row.get("table_html"),
                        row.get("math_type"),
                        row.get("math_content"),
                        row.get("image_path"),
                        row.get("quality_score"),
                        row.get("derived_confidence"),
                        row.get("derived_by"),
                        row.get("derive_version"),
                        row.get("parser_version"),
                        row.get("updated_at"),
                        row.get("block_uid"),
                    ),
                )
                updated += 1
            conn.commit()
        return updated

    # 查询文档块索引。
    def query_doc_blocks(
        self,
        doc_id: str,
        block_type: Optional[str] = None,
        derived_level: Optional[int] = None,
        limit: int = 100,
    ) -> List[Dict[str, Any]]:
        sql = "SELECT * FROM doc_blocks WHERE doc_id = ? AND is_active = 1"
        params: List[Any] = [doc_id]
        if block_type:
            sql += " AND block_type = ?"
            params.append(block_type)
        if derived_level is not None:
            sql += " AND derived_title_level = ?"
            params.append(derived_level)
        sql += " ORDER BY page_idx ASC, block_seq ASC LIMIT ?"
        params.append(max(1, min(1000, limit)))
        with self.connect() as conn:
            rows = conn.execute(sql, params).fetchall()
        return [dict(row) for row in rows]

    # 按 block_uid 列表批量查询富媒体字段。
    def get_blocks_rich_media(self, doc_id: str, block_uids: List[str]) -> Dict[str, Dict[str, Any]]:
        if not block_uids:
            return {}
        placeholders = ",".join(["?"] * len(block_uids))
        sql = f"""
            SELECT block_uid, table_html, math_content, image_path, content_json
            FROM doc_blocks
            WHERE doc_id = ? AND is_active = 1 AND block_uid IN ({placeholders})
        """
        params: List[Any] = [doc_id] + list(block_uids)
        with self.connect() as conn:
            rows = conn.execute(sql, params).fetchall()
        result: Dict[str, Dict[str, Any]] = {}
        for row in rows:
            uid = str(row["block_uid"] or "")
            if not uid:
                continue
            content_json = row["content_json"]
            parsed_json = {}
            if isinstance(content_json, str) and content_json.strip():
                try:
                    import json
                    parsed_json = json.loads(content_json)
                except Exception:
                    pass
            image_paths = []
            if isinstance(parsed_json, dict):
                img_paths = parsed_json.get("image_paths")
                if isinstance(img_paths, list):
                    image_paths = [str(p) for p in img_paths if p]
            rich_media_order = []
            if isinstance(parsed_json, dict):
                rmo = parsed_json.get("rich_media_order")
                if isinstance(rmo, list):
                    rich_media_order = rmo
            result[uid] = {
                "table_html": str(row["table_html"] or ""),
                "math_content": str(row["math_content"] or ""),
                "image_path": str(row["image_path"] or ""),
                "image_paths": image_paths,
                "rich_media_order": rich_media_order,
            }
        return result

    # 统计文档块索引信息。
    def get_doc_blocks_stats(self, doc_id: str) -> Dict[str, Any]:
        with self.connect() as conn:
            total = conn.execute(
                "SELECT COUNT(*) AS cnt FROM doc_blocks WHERE doc_id = ? AND is_active = 1",
                (doc_id,),
            ).fetchone()["cnt"]
            by_type = conn.execute(
                """
                SELECT block_type, COUNT(*) AS cnt
                FROM doc_blocks
                WHERE doc_id = ? AND is_active = 1
                GROUP BY block_type
                """,
                (doc_id,),
            ).fetchall()
            by_level = conn.execute(
                """
                SELECT derived_title_level, COUNT(*) AS cnt
                FROM doc_blocks
                WHERE doc_id = ? AND is_active = 1 AND derived_title_level IS NOT NULL
                GROUP BY derived_title_level
                """,
                (doc_id,),
            ).fetchall()
            titles_without_level = conn.execute(
                """
                SELECT COUNT(*) AS cnt
                FROM doc_blocks
                WHERE doc_id = ? AND is_active = 1 AND block_type = 'title' AND derived_title_level IS NULL
                """,
                (doc_id,),
            ).fetchone()["cnt"]
        return {
            "total": total,
            "by_type": {row["block_type"]: row["cnt"] for row in by_type},
            "by_level": {row["derived_title_level"]: row["cnt"] for row in by_level},
            "titles_without_level": titles_without_level,
        }

    # 查询文档片段投影。
    def list_document_segments(
        self,
        doc_id: str,
        strategy: str,
        item_type: Optional[str] = None,
        keyword: Optional[str] = None,
        limit: int = 200,
    ) -> List[Dict[str, Any]]:
        sql = """
            SELECT id, doc_id, library_id, strategy, item_type, title, content, meta_json, schema_version, order_index, created_at, updated_at
            FROM document_segments
            WHERE doc_id = ? AND strategy = ?
        """
        params: List[Any] = [doc_id, strategy]
        if item_type:
            sql += " AND item_type = ?"
            params.append(item_type)
        if keyword:
            sql += " AND (content LIKE ? OR title LIKE ?)"
            kw = f"%{keyword}%"
            params.extend([kw, kw])
        sql += " ORDER BY order_index ASC, created_at ASC LIMIT ?"
        params.append(max(1, min(1000, limit)))

        with self.connect() as conn:
            rows = conn.execute(sql, params).fetchall()

        return [
            {
                "id": row["id"],
                "doc_id": row["doc_id"],
                "library_id": row["library_id"],
                "strategy": row["strategy"],
                "item_type": row["item_type"],
                "title": row["title"],
                "content": row["content"],
                "meta": json.loads(row["meta_json"] or "{}"),
                "schema_version": row["schema_version"] or self.schema_version,
                "order_index": int(row["order_index"] or 0),
                "created_at": row["created_at"],
                "updated_at": row["updated_at"],
            }
            for row in rows
        ]

    # 统计文档片段投影数量。
    def get_document_segment_stats(self, doc_id: str) -> Dict[str, Any]:
        with self.connect() as conn:
            rows = conn.execute(
                """
                SELECT strategy, item_type, COUNT(*) AS cnt
                FROM document_segments
                WHERE doc_id = ?
                GROUP BY strategy, item_type
                """,
                (doc_id,),
            ).fetchall()
        summary: Dict[str, Dict[str, int]] = {}
        total = 0
        for row in rows:
            strategy = row["strategy"]
            item_type = row["item_type"]
            cnt = int(row["cnt"] or 0)
            total += cnt
            summary.setdefault(strategy, {})[item_type] = cnt
        return {"doc_id": doc_id, "total": total, "strategies": summary}

_index_stores: Dict[str, KnowledgeIndexStore] = {}


def get_index_store() -> KnowledgeIndexStore:
    """索引库访问（按 db 路径懒加载，兼容 KNOWLEDGE_BASE_DIR 隔离）。"""
    db_path = str(paths.resolve_knowledge_index_db_path())
    if db_path not in _index_stores:
        _index_stores[db_path] = KnowledgeIndexStore()
    return _index_stores[db_path]


# 持久化 doc_blocks 主索引。
def persist_doc_blocks(result: StructuredResult) -> Dict[str, int]:
    base_rows = result.stats.get("base_rows", []) or []
    derived_rows = result.stats.get("derived_rows", []) or []
    doc_id = ""
    if base_rows:
        doc_id = str(base_rows[0].get("doc_id") or "")
    elif derived_rows:
        doc_id = str(derived_rows[0].get("doc_id") or "")
    if doc_id:
        get_index_store().clear_doc_blocks(doc_id)
    inserted = get_index_store().insert_doc_blocks_base_rows(base_rows) if base_rows else 0
    updated = get_index_store().update_doc_blocks_derived_rows(derived_rows) if derived_rows else 0
    return {"inserted": inserted, "updated": updated}


# 查询文档块记录。
def query_doc_blocks(
    doc_id: str,
    block_type: Optional[str] = None,
    derived_level: Optional[int] = None,
    limit: int = 100,
) -> List[Dict[str, Any]]:
    return get_index_store().query_doc_blocks(
        doc_id=doc_id,
        block_type=block_type,
        derived_level=derived_level,
        limit=limit,
    )


# 获取文档块统计信息。
def get_doc_blocks_stats(doc_id: str) -> Dict[str, Any]:
    return get_index_store().get_doc_blocks_stats(doc_id)


__all__ = [
    "KnowledgeIndexStore",
    "KnowledgeMetaStore",
    "create_connection",
    "get_doc_blocks_stats",
    "get_index_store",
    "parse_datetime",
    "persist_doc_blocks",
    "query_doc_blocks",
]
