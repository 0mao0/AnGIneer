"""结构化结果数据库存储。"""
import json
import sqlite3
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from docs_core.ingest.normalize.structure_builder import StructuredResult


KNOWLEDGE_META_DB_NAME = "knowledge_meta.sqlite"
KNOWLEDGE_INDEX_DB_NAME = "knowledge_index.sqlite"
STRUCTURED_DOC_GRAPH_STRATEGY = "doc_blocks_graph_v1"


# 解析仓库根目录，统一定位到 monorepo 根。
def resolve_repo_root() -> Path:
    current_file = Path(__file__).resolve()
    for candidate in current_file.parents:
        if (candidate / "apps").exists() and (candidate / "services").exists() and (candidate / "package.json").exists():
            return candidate
    return current_file.parents[6]


# 解析仓库根目录并返回 docs-core 统一数据根目录。
def resolve_knowledge_base_dir() -> Path:
    root_dir = resolve_repo_root()
    data_dir = root_dir / "data" / "knowledge_base"
    data_dir.mkdir(parents=True, exist_ok=True)
    return data_dir


# 解析元数据库路径。
def resolve_knowledge_meta_db_path() -> Path:
    return resolve_knowledge_base_dir() / KNOWLEDGE_META_DB_NAME


# 解析索引数据库路径。
def resolve_knowledge_index_db_path() -> Path:
    return resolve_knowledge_base_dir() / KNOWLEDGE_INDEX_DB_NAME


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


# 构造 SQLite 连接并启用 Row 映射。
def create_connection(db_path: Path) -> sqlite3.Connection:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path), timeout=10)
    conn.row_factory = sqlite3.Row
    return conn


class KnowledgeMetaStore:
    """业务元数据数据库访问层。"""

    def __init__(
        self,
        db_path: Optional[Path] = None,
        schema_version: str = "1.0.0",
    ) -> None:
        self.db_path = db_path or resolve_knowledge_meta_db_path()
        self.schema_version = schema_version
        self.init_schema()

    # 打开元数据库连接。
    def connect(self) -> sqlite3.Connection:
        return create_connection(self.db_path)

    # 初始化元数据库 Schema。
    def init_schema(self) -> None:
        with self.connect() as conn:
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
                    parent_id TEXT,
                    visible INTEGER NOT NULL,
                    library_id TEXT NOT NULL,
                    file_path TEXT,
                    status TEXT NOT NULL,
                    sort_order INTEGER NOT NULL DEFAULT 0,
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
                    error TEXT,
                    schema_version TEXT NOT NULL DEFAULT '1.0.0',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )
            conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_nodes_library_parent_sort
                ON nodes (library_id, parent_id, sort_order, created_at)
                """
            )
            conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_parse_tasks_doc_created
                ON parse_tasks (doc_id, created_at DESC)
                """
            )
            conn.commit()

    # 读取所有知识库。
    def list_libraries(self) -> List[sqlite3.Row]:
        with self.connect() as conn:
            return conn.execute(
                "SELECT id, name, description, created_at, updated_at FROM libraries ORDER BY created_at ASC"
            ).fetchall()

    # 读取所有节点。
    def list_nodes(self) -> List[sqlite3.Row]:
        with self.connect() as conn:
            return conn.execute(
                """
                SELECT id, title, type, parent_id, visible, library_id, file_path, status,
                       parse_progress, parse_stage, parse_error, parse_task_id, strategy,
                       schema_version, sort_order, created_at, updated_at
                FROM nodes
                ORDER BY library_id ASC, parent_id ASC, sort_order ASC, created_at ASC
                """
            ).fetchall()

    # 读取所有解析任务。
    def list_parse_tasks(self) -> List[sqlite3.Row]:
        with self.connect() as conn:
            return conn.execute(
                """
                SELECT id, library_id, doc_id, status, progress, stage, error, schema_version, created_at, updated_at
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

    # 持久化节点记录。
    def upsert_node(self, node: Any) -> None:
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO nodes (
                    id, title, type, parent_id, visible, library_id, file_path, status, parse_progress,
                    parse_stage, parse_error, parse_task_id, strategy, schema_version, sort_order, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    title = excluded.title,
                    type = excluded.type,
                    parent_id = excluded.parent_id,
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
                    sort_order = excluded.sort_order,
                    updated_at = excluded.updated_at
                """,
                (
                    node.id,
                    node.title,
                    node.type,
                    node.parent_id,
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
                    node.sort_order,
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
                INSERT INTO parse_tasks (id, library_id, doc_id, status, progress, stage, error, schema_version, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    status = excluded.status,
                    progress = excluded.progress,
                    stage = excluded.stage,
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
                    task.error,
                    task.schema_version,
                    task.created_at.isoformat(),
                    task.updated_at.isoformat(),
                ),
            )
            conn.commit()

    # 删除节点记录。
    def delete_nodes(self, node_ids: List[str]) -> None:
        if not node_ids:
            return
        placeholders = ",".join(["?"] * len(node_ids))
        with self.connect() as conn:
            conn.execute(f"DELETE FROM nodes WHERE id IN ({placeholders})", node_ids)
            conn.commit()

    # 删除指定文档集合的解析任务记录。
    def delete_parse_tasks_by_doc_ids(self, doc_ids: List[str]) -> int:
        if not doc_ids:
            return 0
        placeholders = ",".join(["?"] * len(doc_ids))
        with self.connect() as conn:
            cursor = conn.execute(f"DELETE FROM parse_tasks WHERE doc_id IN ({placeholders})", doc_ids)
            conn.commit()
            return int(cursor.rowcount or 0)


class KnowledgeIndexStore:
    """索引数据库访问层。"""

    def __init__(
        self,
        db_path: Optional[Path] = None,
        schema_version: str = "1.0.0",
    ) -> None:
        self.db_path = db_path or resolve_knowledge_index_db_path()
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

_index_store = KnowledgeIndexStore()


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
        _index_store.clear_doc_blocks(doc_id)
    inserted = _index_store.insert_doc_blocks_base_rows(base_rows) if base_rows else 0
    updated = _index_store.update_doc_blocks_derived_rows(derived_rows) if derived_rows else 0
    return {"inserted": inserted, "updated": updated}


# 查询文档块记录。
def query_doc_blocks(
    doc_id: str,
    block_type: Optional[str] = None,
    derived_level: Optional[int] = None,
    limit: int = 100,
) -> List[Dict[str, Any]]:
    return _index_store.query_doc_blocks(
        doc_id=doc_id,
        block_type=block_type,
        derived_level=derived_level,
        limit=limit,
    )


# 获取文档块统计信息。
def get_doc_blocks_stats(doc_id: str) -> Dict[str, Any]:
    return _index_store.get_doc_blocks_stats(doc_id)


__all__ = [
    "KNOWLEDGE_INDEX_DB_NAME",
    "KNOWLEDGE_META_DB_NAME",
    "KnowledgeIndexStore",
    "KnowledgeMetaStore",
    "create_connection",
    "get_doc_blocks_stats",
    "parse_datetime",
    "persist_doc_blocks",
    "query_doc_blocks",
    "resolve_knowledge_base_dir",
    "resolve_knowledge_index_db_path",
    "resolve_knowledge_meta_db_path",
]
