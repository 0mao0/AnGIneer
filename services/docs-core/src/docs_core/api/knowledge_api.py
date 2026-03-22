"""知识库管理 API"""
import json
import uuid
from typing import Optional, List, Dict, Any
from pydantic import BaseModel
from datetime import datetime
import sqlite3
from pathlib import Path


# 当前文档解析 Schema 版本
# 当解析产物结构发生重大变化时，应提升此版本号
SCHEMA_VERSION = "1.0.0"


class KnowledgeNode(BaseModel):
    """知识库节点"""
    id: str
    title: str
    type: str  # 'folder' | 'document'
    parent_id: Optional[str] = None
    visible: bool = False
    library_id: str
    file_path: Optional[str] = None
    status: str = 'pending'  # pending | processing | completed | failed
    parse_progress: int = 0
    parse_stage: Optional[str] = None
    parse_error: Optional[str] = None
    parse_task_id: Optional[str] = None
    strategy: str = 'A_structured'
    schema_version: str = SCHEMA_VERSION
    sort_order: int = 0
    created_at: datetime = datetime.now()
    updated_at: datetime = datetime.now()


class KnowledgeLibrary(BaseModel):
    """知识库"""
    id: str
    name: str
    description: Optional[str] = None
    created_at: datetime = datetime.now()
    updated_at: datetime = datetime.now()


class ParseTask(BaseModel):
    """解析任务"""
    id: str
    library_id: str
    doc_id: str
    status: str = 'queued'  # queued | processing | completed | failed
    progress: int = 0
    stage: str = 'queued'
    error: Optional[str] = None
    schema_version: str = SCHEMA_VERSION
    created_at: datetime = datetime.now()
    updated_at: datetime = datetime.now()


class KnowledgeService:
    """知识库服务"""

    def __init__(self):
        self.nodes: List[KnowledgeNode] = []
        self.libraries: List[KnowledgeLibrary] = []
        self.parse_tasks: List[ParseTask] = []
        self.db_path = self._resolve_db_path()
        self._init_db()
        self._load_from_db()
        if not self.libraries:
            self.create_library('default', '默认知识库', '系统自动创建的默认知识库')

    def _resolve_db_path(self) -> Path:
        root_dir = Path(__file__).resolve().parents[5]
        data_dir = root_dir / 'data'
        data_dir.mkdir(parents=True, exist_ok=True)
        return data_dir / 'knowledge.sqlite3'

    def _get_conn(self) -> sqlite3.Connection:
        try:
            conn = sqlite3.connect(str(self.db_path), timeout=10)
            conn.row_factory = sqlite3.Row
            return conn
        except sqlite3.Error as e:
            print(f"Database connection error: {e}")
            raise

    def _init_db(self) -> None:
        try:
            with self._get_conn() as conn:
                conn.execute(
                    '''
                    CREATE TABLE IF NOT EXISTS libraries (
                        id TEXT PRIMARY KEY,
                        name TEXT NOT NULL,
                        description TEXT,
                        created_at TEXT NOT NULL,
                        updated_at TEXT NOT NULL
                    )
                    '''
                )
                conn.execute(
                    '''
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
                        created_at TEXT NOT NULL,
                        updated_at TEXT NOT NULL
                    )
                    '''
                )
                node_columns = {row['name'] for row in conn.execute("PRAGMA table_info(nodes)").fetchall()}
                if 'parse_progress' not in node_columns:
                    conn.execute("ALTER TABLE nodes ADD COLUMN parse_progress INTEGER NOT NULL DEFAULT 0")
                if 'parse_stage' not in node_columns:
                    conn.execute("ALTER TABLE nodes ADD COLUMN parse_stage TEXT")
                if 'parse_error' not in node_columns:
                    conn.execute("ALTER TABLE nodes ADD COLUMN parse_error TEXT")
                if 'parse_task_id' not in node_columns:
                    conn.execute("ALTER TABLE nodes ADD COLUMN parse_task_id TEXT")
                if 'strategy' not in node_columns:
                    conn.execute("ALTER TABLE nodes ADD COLUMN strategy TEXT NOT NULL DEFAULT 'A_structured'")
                if 'schema_version' not in node_columns:
                    conn.execute(f"ALTER TABLE nodes ADD COLUMN schema_version TEXT NOT NULL DEFAULT '{SCHEMA_VERSION}'")

                conn.execute(
                    '''
                    CREATE TABLE IF NOT EXISTS parse_tasks (
                        id TEXT PRIMARY KEY,
                        library_id TEXT NOT NULL,
                        doc_id TEXT NOT NULL,
                        status TEXT NOT NULL,
                        progress INTEGER NOT NULL DEFAULT 0,
                        stage TEXT NOT NULL,
                        error TEXT,
                        schema_version TEXT NOT NULL DEFAULT '0.0.0',
                        created_at TEXT NOT NULL,
                        updated_at TEXT NOT NULL
                    )
                    '''
                )
                task_columns = {row['name'] for row in conn.execute("PRAGMA table_info(parse_tasks)").fetchall()}
                if 'schema_version' not in task_columns:
                    conn.execute(f"ALTER TABLE parse_tasks ADD COLUMN schema_version TEXT NOT NULL DEFAULT '{SCHEMA_VERSION}'")

                conn.execute(
                    '''
                    CREATE TABLE IF NOT EXISTS document_segments (
                        id TEXT PRIMARY KEY,
                        doc_id TEXT NOT NULL,
                        library_id TEXT NOT NULL,
                        strategy TEXT NOT NULL,
                        item_type TEXT NOT NULL,
                        title TEXT,
                        content TEXT NOT NULL,
                        meta_json TEXT,
                        schema_version TEXT NOT NULL DEFAULT '0.0.0',
                        order_index INTEGER NOT NULL DEFAULT 0,
                        created_at TEXT NOT NULL,
                        updated_at TEXT NOT NULL
                    )
                    '''
                )
                seg_columns = {row['name'] for row in conn.execute("PRAGMA table_info(document_segments)").fetchall()}
                if 'schema_version' not in seg_columns:
                    conn.execute(f"ALTER TABLE document_segments ADD COLUMN schema_version TEXT NOT NULL DEFAULT '{SCHEMA_VERSION}'")
                conn.execute(
                    '''
                    CREATE INDEX IF NOT EXISTS idx_document_segments_doc_strategy
                    ON document_segments (doc_id, strategy, item_type, order_index)
                    '''
                )
                conn.commit()
        except sqlite3.Error as e:
            print(f"Database initialization error: {e}")
            raise

    def _parse_datetime(self, dt_str: Optional[str]) -> datetime:
        """安全解析日期字符串"""
        if not dt_str:
            return datetime.now()
        try:
            return datetime.fromisoformat(dt_str)
        except (ValueError, TypeError):
            # 兼容旧格式或不规范格式
            try:
                # 尝试常见的其他格式，或者回退到当前时间
                from dateutil import parser
                return parser.parse(dt_str)
            except Exception:
                return datetime.now()

    def _load_from_db(self) -> None:
        with self._get_conn() as conn:
            lib_rows = conn.execute(
                'SELECT id, name, description, created_at, updated_at FROM libraries ORDER BY created_at ASC'
            ).fetchall()
            node_rows = conn.execute(
                '''
                SELECT id, title, type, parent_id, visible, library_id, file_path, status,
                       parse_progress, parse_stage, parse_error, parse_task_id, strategy,
                       schema_version, sort_order, created_at, updated_at
                FROM nodes
                ORDER BY library_id ASC, parent_id ASC, sort_order ASC, created_at ASC
                '''
            ).fetchall()
            task_rows = conn.execute(
                '''
                SELECT id, library_id, doc_id, status, progress, stage, error, schema_version, created_at, updated_at
                FROM parse_tasks
                ORDER BY created_at DESC
                '''
            ).fetchall()
        self.libraries = [
            KnowledgeLibrary(
                id=row['id'],
                name=row['name'],
                description=row['description'],
                created_at=self._parse_datetime(row['created_at']),
                updated_at=self._parse_datetime(row['updated_at'])
            )
            for row in lib_rows
        ]
        self.nodes = [
            KnowledgeNode(
                id=row['id'],
                title=row['title'],
                type=row['type'],
                parent_id=row['parent_id'],
                visible=bool(row['visible']),
                library_id=row['library_id'],
                file_path=row['file_path'],
                status=row['status'],
                parse_progress=int(row['parse_progress'] or 0),
                parse_stage=row['parse_stage'],
                parse_error=row['parse_error'],
                parse_task_id=row['parse_task_id'],
                strategy=row['strategy'] or 'A_structured',
                schema_version=row['schema_version'] or '0.0.0',
                sort_order=int(row['sort_order'] or 0),
                created_at=self._parse_datetime(row['created_at']),
                updated_at=self._parse_datetime(row['updated_at'])
            )
            for row in node_rows
        ]
        self.parse_tasks = [
            ParseTask(
                id=row['id'],
                library_id=row['library_id'],
                doc_id=row['doc_id'],
                status=row['status'],
                progress=int(row['progress'] or 0),
                stage=row['stage'] or 'queued',
                error=row['error'],
                schema_version=row['schema_version'] or '0.0.0',
                created_at=self._parse_datetime(row['created_at']),
                updated_at=self._parse_datetime(row['updated_at'])
            )
            for row in task_rows
        ]

    def _upsert_library(self, library: KnowledgeLibrary) -> None:
        with self._get_conn() as conn:
            conn.execute(
                '''
                INSERT INTO libraries (id, name, description, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    name=excluded.name,
                    description=excluded.description,
                    updated_at=excluded.updated_at
                ''',
                (
                    library.id,
                    library.name,
                    library.description,
                    library.created_at.isoformat(),
                    library.updated_at.isoformat()
                )
            )
            conn.commit()

    def _upsert_node(self, node: KnowledgeNode) -> None:
        with self._get_conn() as conn:
            conn.execute(
                '''
                INSERT INTO nodes (id, title, type, parent_id, visible, library_id, file_path, status, parse_progress, parse_stage, parse_error, parse_task_id, strategy, schema_version, sort_order, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    title=excluded.title,
                    type=excluded.type,
                    parent_id=excluded.parent_id,
                    visible=excluded.visible,
                    library_id=excluded.library_id,
                    file_path=excluded.file_path,
                    status=excluded.status,
                    parse_progress=excluded.parse_progress,
                    parse_stage=excluded.parse_stage,
                    parse_error=excluded.parse_error,
                    parse_task_id=excluded.parse_task_id,
                    strategy=excluded.strategy,
                    schema_version=excluded.schema_version,
                    sort_order=excluded.sort_order,
                    updated_at=excluded.updated_at
                ''',
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
                    node.updated_at.isoformat()
                )
            )
            conn.commit()

    def _upsert_parse_task(self, task: ParseTask) -> None:
        with self._get_conn() as conn:
            conn.execute(
                '''
                INSERT INTO parse_tasks (id, library_id, doc_id, status, progress, stage, error, schema_version, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    status=excluded.status,
                    progress=excluded.progress,
                    stage=excluded.stage,
                    error=excluded.error,
                    schema_version=excluded.schema_version,
                    updated_at=excluded.updated_at
                ''',
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
                    task.updated_at.isoformat()
                )
            )
            conn.commit()

    def _delete_nodes(self, node_ids: List[str]) -> None:
        if not node_ids:
            return
        placeholders = ','.join(['?'] * len(node_ids))
        with self._get_conn() as conn:
            conn.execute(f'DELETE FROM nodes WHERE id IN ({placeholders})', node_ids)
            conn.commit()

    def list_libraries(self) -> List[KnowledgeLibrary]:
        """获取知识库列表"""
        return self.libraries

    def create_library(self, library_id: str, name: str, description: str = '') -> KnowledgeLibrary:
        """创建知识库"""
        library = KnowledgeLibrary(
            id=library_id,
            name=name,
            description=description
        )
        self.libraries.append(library)
        self._upsert_library(library)
        return library

    def get_library(self, library_id: str) -> Optional[KnowledgeLibrary]:
        """获取知识库"""
        for lib in self.libraries:
            if lib.id == library_id:
                return lib
        return None

    def list_nodes(self, library_id: str, visible: bool = False) -> List[KnowledgeNode]:
        """获取知识库节点列表"""
        nodes = [n for n in self.nodes if n.library_id == library_id]
        if visible:
            nodes = [n for n in nodes if n.visible]
        return sorted(nodes, key=lambda n: (n.sort_order, n.created_at))

    def create_node(self, node: KnowledgeNode) -> KnowledgeNode:
        """创建节点"""
        sibling_orders = [
            n.sort_order for n in self.nodes
            if n.library_id == node.library_id and n.parent_id == node.parent_id
        ]
        if node.sort_order < 0:
            node.sort_order = 0
        if not sibling_orders and node.sort_order == 0:
            pass
        elif node.sort_order == 0:
            node.sort_order = max(sibling_orders, default=-1) + 1
        self.nodes.append(node)
        self._upsert_node(node)
        return node

    def update_node(self, node_id: str, **kwargs) -> Optional[KnowledgeNode]:
        """更新节点"""
        for node in self.nodes:
            if node.id == node_id:
                old_parent_id = node.parent_id
                old_library_id = node.library_id
                for key, value in kwargs.items():
                    if hasattr(node, key):
                        setattr(node, key, value)
                has_explicit_sort_order = 'sort_order' in kwargs
                parent_or_library_changed = (
                    old_parent_id != node.parent_id or old_library_id != node.library_id
                )
                if ('parent_id' in kwargs or 'library_id' in kwargs) and not has_explicit_sort_order:
                    sibling_orders = [
                        n.sort_order for n in self.nodes
                        if n.id != node.id and n.library_id == node.library_id and n.parent_id == node.parent_id
                    ]
                    node.sort_order = max(sibling_orders, default=-1) + 1
                if parent_or_library_changed:
                    self._normalize_sibling_orders(old_library_id, old_parent_id)
                    if not has_explicit_sort_order:
                        self._normalize_sibling_orders(node.library_id, node.parent_id)
                node.updated_at = datetime.now()
                self._upsert_node(node)
                return node
        return None

    def delete_node(self, node_id: str) -> bool:
        """删除节点"""
        node_ids = {node.id for node in self.nodes}
        if node_id not in node_ids:
            return False
        target = self.get_node(node_id)
        to_delete = {node_id}
        changed = True
        while changed:
            changed = False
            for node in self.nodes:
                if node.parent_id in to_delete and node.id not in to_delete:
                    to_delete.add(node.id)
                    changed = True
        self.nodes = [node for node in self.nodes if node.id not in to_delete]
        self._delete_nodes(list(to_delete))
        if target:
            self._normalize_sibling_orders(target.library_id, target.parent_id)
        return True

    def get_node(self, node_id: str) -> Optional[KnowledgeNode]:
        """获取节点"""
        for node in self.nodes:
            if node.id == node_id:
                return node
        return None

    def create_parse_task(self, task_id: str, library_id: str, doc_id: str) -> ParseTask:
        """创建解析任务"""
        now = datetime.now()
        task = ParseTask(
            id=task_id,
            library_id=library_id,
            doc_id=doc_id,
            status='queued',
            progress=0,
            stage='queued',
            created_at=now,
            updated_at=now
        )
        self.parse_tasks = [task, *[t for t in self.parse_tasks if t.id != task_id]]
        self._upsert_parse_task(task)
        return task

    def get_parse_task(self, task_id: str) -> Optional[ParseTask]:
        """获取解析任务"""
        for task in self.parse_tasks:
            if task.id == task_id:
                return task
        return None

    def update_parse_task(self, task_id: str, **kwargs) -> Optional[ParseTask]:
        """更新解析任务"""
        task = self.get_parse_task(task_id)
        if not task:
            return None
        for key, value in kwargs.items():
            if hasattr(task, key):
                setattr(task, key, value)
        task.updated_at = datetime.now()
        self._upsert_parse_task(task)
        return task

    def _normalize_sibling_orders(self, library_id: str, parent_id: Optional[str]) -> None:
        siblings = sorted(
            [n for n in self.nodes if n.library_id == library_id and n.parent_id == parent_id],
            key=lambda n: (n.sort_order, n.created_at)
        )
        for idx, sibling in enumerate(siblings):
            if sibling.sort_order != idx:
                sibling.sort_order = idx
                sibling.updated_at = datetime.now()
                self._upsert_node(sibling)

    def clear_document_segments(self, doc_id: str, strategy: Optional[str] = None) -> int:
        """删除文档结构化片段"""
        with self._get_conn() as conn:
            if strategy:
                cursor = conn.execute(
                    'DELETE FROM document_segments WHERE doc_id = ? AND strategy = ?',
                    (doc_id, strategy)
                )
            else:
                cursor = conn.execute(
                    'DELETE FROM document_segments WHERE doc_id = ?',
                    (doc_id,)
                )
            conn.commit()
            return int(cursor.rowcount or 0)

    def save_document_segments(
        self,
        doc_id: str,
        library_id: str,
        strategy: str,
        items: List[Dict[str, Any]]
    ) -> int:
        """保存文档结构化片段"""
        now = datetime.now().isoformat()
        self.clear_document_segments(doc_id, strategy)
        rows = []
        for index, item in enumerate(items):
            rows.append(
                (
                    item.get('id') or f"seg-{uuid.uuid4().hex[:12]}",
                    doc_id,
                    library_id,
                    strategy,
                    item.get('item_type', 'segment'),
                    item.get('title'),
                    item.get('content', ''),
                    json.dumps(item.get('meta', {}), ensure_ascii=False),
                    item.get('schema_version', SCHEMA_VERSION),
                    index,
                    now,
                    now
                )
            )

        if not rows:
            return 0

        with self._get_conn() as conn:
            conn.executemany(
                '''
                INSERT INTO document_segments (
                    id, doc_id, library_id, strategy, item_type, title, content, meta_json, schema_version, order_index, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ''',
                rows
            )
            conn.commit()
            return len(rows)

    def list_document_segments(
        self,
        doc_id: str,
        strategy: str,
        item_type: Optional[str] = None,
        keyword: Optional[str] = None,
        limit: int = 200
    ) -> List[Dict[str, Any]]:
        """查询文档结构化片段"""
        sql = '''
            SELECT id, doc_id, library_id, strategy, item_type, title, content, meta_json, schema_version, order_index, created_at, updated_at
            FROM document_segments
            WHERE doc_id = ? AND strategy = ?
        '''
        params: List[Any] = [doc_id, strategy]
        if item_type:
            sql += ' AND item_type = ?'
            params.append(item_type)
        if keyword:
            sql += ' AND (content LIKE ? OR title LIKE ?)'
            kw = f'%{keyword}%'
            params.extend([kw, kw])
        sql += ' ORDER BY order_index ASC, created_at ASC LIMIT ?'
        params.append(max(1, min(1000, limit)))
        with self._get_conn() as conn:
            rows = conn.execute(sql, params).fetchall()
        result: List[Dict[str, Any]] = []
        for row in rows:
            result.append(
                {
                    'id': row['id'],
                    'doc_id': row['doc_id'],
                    'library_id': row['library_id'],
                    'strategy': row['strategy'],
                    'item_type': row['item_type'],
                    'title': row['title'],
                    'content': row['content'],
                    'meta': json.loads(row['meta_json'] or '{}'),
                    'schema_version': row['schema_version'] or '0.0.0',
                    'order_index': int(row['order_index'] or 0),
                    'created_at': row['created_at'],
                    'updated_at': row['updated_at']
                }
            )
        return result

    def get_document_segment_stats(self, doc_id: str) -> Dict[str, Any]:
        """统计文档结构化片段"""
        with self._get_conn() as conn:
            rows = conn.execute(
                '''
                SELECT strategy, item_type, COUNT(*) AS cnt
                FROM document_segments
                WHERE doc_id = ?
                GROUP BY strategy, item_type
                ''',
                (doc_id,)
            ).fetchall()
        summary: Dict[str, Dict[str, int]] = {}
        total = 0
        for row in rows:
            strategy = row['strategy']
            item_type = row['item_type']
            cnt = int(row['cnt'] or 0)
            total += cnt
            if strategy not in summary:
                summary[strategy] = {}
            summary[strategy][item_type] = cnt
        return {'doc_id': doc_id, 'total': total, 'strategies': summary}


knowledge_service = KnowledgeService()
