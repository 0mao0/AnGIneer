"""知识库服务与仓储门面"""
from datetime import datetime
import logging
import re
from pathlib import Path
from typing import Any, Dict, List, Optional

from pydantic import BaseModel

from tree_core import tree_store

from docs_core.ingest.organize.types import (
    CanonicalBlock,
    CanonicalChunk,
    CanonicalDocument,
    CanonicalTable,
    CitationTarget,
)
from docs_core.ingest.store.canonical_sql_store import CanonicalSQLiteStore
from docs_core.ingest.store.blocks_sql_store import (
    KnowledgeIndexStore,
    KnowledgeMetaStore,
    STRUCTURED_DOC_GRAPH_STRATEGY,
    parse_datetime,
    resolve_knowledge_index_db_path,
    resolve_knowledge_meta_db_path,
)
from docs_core.indexing import (
    ChromaVectorStore,
    SQLiteVectorStore,
    VectorRecord,
    VectorSearchHit,
    get_vectorstore_provider_name,
)


SCHEMA_VERSION = "1.0.0"
logger = logging.getLogger(__name__)


REFERENCE_TARGET_TYPE_MAP = {
    "text": "content",
    "title": "content",
    "heading": "content",
    "paragraph": "content",
    "list": "content",
    "content": "content",
    "table": "table",
    "formula": "formula",
    "equation": "formula",
    "image": "figure",
    "figure": "figure",
}


def _normalize_reference_text(value: str) -> str:
    return (
        str(value or "")
        .replace("（", "(")
        .replace("）", ")")
        .replace("－", "-")
        .replace("_", " ")
        .strip()
        .lower()
    )


def _resolve_reference_target_type(block_type: str) -> str:
    return REFERENCE_TARGET_TYPE_MAP.get(str(block_type or "").strip().lower(), "content")


def _extract_reference_identifier(value: str) -> str:
    normalized = " ".join(str(value or "").split()).strip()
    if not normalized:
        return ""
    patterns = [
        r"(表\s*\d+(?:[.\-]\d+)*)",
        r"(图\s*\d+(?:[.\-]\d+)*)",
        r"(公式\s*\d+(?:[.\-]\d+)*)",
        r"(式\s*\d+(?:[.\-]\d+)*)",
        r"(第\s*\d+(?:\.\d+)*(?:章|节|条|款|项))",
        r"^(\d+(?:\.\d+)*(?:\.\d+)*)",
    ]
    for pattern in patterns:
        matched = re.search(pattern, normalized, flags=re.IGNORECASE)
        if matched:
            return matched.group(1).replace(" ", "")
    return ""


def _build_reference_label(section_path: str, content: str, target_type: str) -> str:
    section_identifier = _extract_reference_identifier(section_path)
    if section_identifier:
        return section_identifier
    content_identifier = _extract_reference_identifier(content)
    if content_identifier:
        return content_identifier
    normalized_section = str(section_path or "").strip()
    if normalized_section:
        segments = [segment.strip() for segment in normalized_section.replace(">", "/").split("/") if segment.strip()]
        if segments:
            return segments[-1][:24]
    fallback_map = {
        "table": "表格条文",
        "formula": "公式条文",
        "figure": "图片条文",
        "content": "正文条文",
    }
    return fallback_map.get(target_type, "知识条文")


def _score_reference_candidate(
    query: str,
    section_path: str,
    content: str,
    *,
    target_type: str,
    current_doc_boost: bool,
) -> float:
    normalized_query = _normalize_reference_text(query)
    normalized_section = _normalize_reference_text(section_path)
    normalized_content = _normalize_reference_text(content)
    score = 0.0
    if not normalized_query:
        return score
    if normalized_query == normalized_section:
        score += 24.0
    elif normalized_query and normalized_query in normalized_section:
        score += 18.0
    if normalized_query and normalized_query in normalized_content:
        score += 14.0
    query_tokens = [token for token in normalized_query.replace("/", " ").split() if len(token) >= 2]
    for token in query_tokens:
        if token in normalized_section:
            score += 4.0
        if token in normalized_content:
            score += 2.5
    if target_type in {"table", "formula", "figure"}:
        score += 1.5
    if current_doc_boost:
        score += 2.0
    return score


class KnowledgeNode(BaseModel):
    """知识库节点。"""

    id: str
    title: str
    type: str
    parent_id: Optional[str] = None
    visible: bool = False
    library_id: str
    file_path: Optional[str] = None
    status: str = "pending"
    parse_progress: int = 0
    parse_stage: Optional[str] = None
    parse_error: Optional[str] = None
    parse_task_id: Optional[str] = None
    strategy: str = STRUCTURED_DOC_GRAPH_STRATEGY
    schema_version: str = SCHEMA_VERSION
    sort_order: int = 0
    created_at: datetime = datetime.now()
    updated_at: datetime = datetime.now()


class KnowledgeLibrary(BaseModel):
    """知识库。"""

    id: str
    name: str
    description: Optional[str] = None
    created_at: datetime = datetime.now()
    updated_at: datetime = datetime.now()


class ParseTask(BaseModel):
    """解析任务。"""

    id: str
    library_id: str
    doc_id: str
    status: str = "queued"
    progress: int = 0
    stage: str = "queued"
    stage_message: Optional[str] = None
    error: Optional[str] = None
    schema_version: str = SCHEMA_VERSION
    created_at: datetime = datetime.now()
    updated_at: datetime = datetime.now()


class KnowledgeService:
    """对外暴露稳定接口的知识库服务。"""

    def __init__(self) -> None:
        self.libraries: List[KnowledgeLibrary] = []
        self.nodes: List[KnowledgeNode] = []
        self.parse_tasks: List[ParseTask] = []
        self.db_path = self._resolve_db_path()
        self.index_db_path = self._resolve_index_db_path()
        self.meta_store = KnowledgeMetaStore(
            db_path=self.db_path,
            schema_version=SCHEMA_VERSION,
        )
        self.index_store = KnowledgeIndexStore(
            db_path=self.index_db_path,
            schema_version=SCHEMA_VERSION,
        )
        self.canonical_store = CanonicalSQLiteStore(db_path=self.index_db_path)
        self.vector_store = self._create_vector_store()
        self._load_from_db()
        if not self.libraries:
            self.create_library("default", "默认知识库", "系统自动创建的默认知识库")

    # 解析元数据库路径
    def _resolve_db_path(self) -> Path:
        return resolve_knowledge_meta_db_path()

    # 解析索引数据库路径
    def _resolve_index_db_path(self) -> Path:
        return resolve_knowledge_index_db_path()

    # 按配置创建当前默认向量存储实现
    def _create_vector_store(self):
        provider_name = get_vectorstore_provider_name()
        if provider_name == "sqlite":
            vector_store = SQLiteVectorStore(db_path=self.index_db_path)
            logger.info("docs_core 启用向量 provider=%s, backend=%s", provider_name, vector_store.__class__.__name__)
            return vector_store
        if provider_name == "chroma":
            try:
                vector_store = ChromaVectorStore()
                logger.info("docs_core 启用向量 provider=%s, backend=%s", provider_name, vector_store.__class__.__name__)
                return vector_store
            except Exception as exc:
                logger.warning("docs_core 初始Chroma 失败，回退SQLiteVectorStore: %s", exc)
                vector_store = SQLiteVectorStore(db_path=self.index_db_path)
                logger.info("docs_core 启用向量 provider=%s, backend=%s", "sqlite(fallback)", vector_store.__class__.__name__)
                return vector_store
        vector_store = SQLiteVectorStore(db_path=self.index_db_path)
        logger.warning("docs_core 遇到未知向量provider=%s，回退%s", provider_name, vector_store.__class__.__name__)
        logger.info("docs_core 启用向量 provider=%s, backend=%s", "sqlite(fallback)", vector_store.__class__.__name__)
        return vector_store

    # 把数据库记录加载为内存对象缓存
    def _load_from_db(self) -> None:
        self.libraries = [
            KnowledgeLibrary(
                id=row["id"],
                name=row["name"],
                description=row["description"],
                created_at=parse_datetime(row["created_at"]),
                updated_at=parse_datetime(row["updated_at"]),
            )
            for row in self.meta_store.list_libraries()
        ]
        self.nodes = [
            KnowledgeNode(
                id=row["id"],
                title=row["title"],
                type=row["type"],
                parent_id=row["parent_id"],
                visible=bool(row["visible"]),
                library_id=row["library_id"],
                file_path=row["file_path"],
                status=row["status"],
                parse_progress=int(row["parse_progress"] or 0),
                parse_stage=row["parse_stage"],
                parse_error=row["parse_error"],
                parse_task_id=row["parse_task_id"],
                strategy=row["strategy"] or STRUCTURED_DOC_GRAPH_STRATEGY,
                schema_version=row["schema_version"] or SCHEMA_VERSION,
                sort_order=int(row["sort_order"] or 0),
                created_at=parse_datetime(row["created_at"]),
                updated_at=parse_datetime(row["updated_at"]),
            )
            for row in self.meta_store.list_nodes()
        ]
        self.parse_tasks = [
            ParseTask(
                id=row["id"],
                library_id=row["library_id"],
                doc_id=row["doc_id"],
                status=row["status"],
                progress=int(row["progress"] or 0),
                stage=row["stage"] or "queued",
                stage_message=row["stage_message"],
                error=row["error"],
                schema_version=row["schema_version"] or SCHEMA_VERSION,
                created_at=parse_datetime(row["created_at"]),
                updated_at=parse_datetime(row["updated_at"]),
            )
            for row in self.meta_store.list_parse_tasks()
        ]

    # 删除指定节点集合
    def _delete_nodes(self, node_ids: List[str]) -> None:
        self.meta_store.delete_nodes(node_ids)

    # 收集节点及其全部后代节点 ID，委托给 tree_store。
    def _collect_subtree_node_ids(self, node_id: str) -> List[str]:
        with self.meta_store.connect() as conn:
            return tree_store._collect_subtree_ids(conn, node_id)

    # 收集指定节点集合中的文档节点
    def _collect_document_nodes(self, node_ids: List[str]) -> List[KnowledgeNode]:
        node_id_set = set(node_ids)
        return [
            node
            for node in self.nodes
            if node.id in node_id_set and node.type == "document"
        ]

    # 清理文档节点关联的存储产物与索引数据
    def _purge_document_artifacts(self, document_nodes: List[KnowledgeNode]) -> None:
        if not document_nodes:
            return
        from docs_core.ingest.store.assets_file_store import file_storage

        doc_ids = [node.id for node in document_nodes]
        self.meta_store.delete_parse_tasks_by_doc_ids(doc_ids)
        self.parse_tasks = [task for task in self.parse_tasks if task.doc_id not in set(doc_ids)]
        for node in document_nodes:
            self.index_store.clear_document_segments(node.id)
            self.index_store.clear_doc_blocks(node.id)
            self.index_store.clear_doc_block_corrections(node.id)
            self.canonical_store.clear_document(node.id)
            self.vector_store.clear_document(node.id)
            file_storage.delete_document(node.library_id, node.id)

    # 生成删除节点前的影响范围预览
    def get_delete_preview(self, node_id: str) -> Optional[Dict[str, Any]]:
        target = self.get_node(node_id)
        if not target:
            return None
        subtree_node_ids = self._collect_subtree_node_ids(node_id)
        subtree_nodes = [node for node in self.nodes if node.id in set(subtree_node_ids)]
        document_nodes = self._collect_document_nodes(subtree_node_ids)
        folder_count = sum(1 for node in subtree_nodes if node.type == "folder")
        document_titles = [node.title for node in document_nodes]
        return {
            "node_id": target.id,
            "node_title": target.title,
            "node_type": target.type,
            "total_nodes": len(subtree_nodes),
            "folder_count": folder_count,
            "document_count": len(document_nodes),
            "doc_ids": [node.id for node in document_nodes],
            "doc_titles": document_titles,
            "sample_doc_titles": document_titles[:5],
        }

    # 对兄弟节点重新排序，委托给 tree_store。
    def _normalize_sibling_orders(self, library_id: str, parent_id: Optional[str]) -> None:
        with self.meta_store.connect() as conn:
            tree_store.normalize_siblings(conn, parent_id, library_id)
        siblings = [node for node in self.nodes if node.library_id == library_id and node.parent_id == parent_id]
        siblings.sort(key=lambda node: (node.sort_order, node.created_at))
        for idx, sibling in enumerate(siblings):
            if sibling.sort_order != idx:
                sibling.sort_order = idx

    # 获取知识库列表
    def list_libraries(self) -> List[KnowledgeLibrary]:
        return self.libraries

    # 创建知识库
    def create_library(self, library_id: str, name: str, description: str = "") -> KnowledgeLibrary:
        library = KnowledgeLibrary(id=library_id, name=name, description=description)
        self.libraries.append(library)
        self.meta_store.upsert_library(library)
        return library

    # 获取知识库
    def get_library(self, library_id: str) -> Optional[KnowledgeLibrary]:
        for library in self.libraries:
            if library.id == library_id:
                return library
        return None

    # 获取知识库节点列表
    def list_nodes(self, library_id: str, visible: bool = False) -> List[KnowledgeNode]:
        nodes = [node for node in self.nodes if node.library_id == library_id]
        if visible:
            nodes = [node for node in nodes if node.visible]
        return sorted(nodes, key=lambda node: (node.sort_order, node.created_at))

    # 创建节点，sort_order 由 tree_store 自动计算。
    def create_node(self, node: KnowledgeNode) -> KnowledgeNode:
        self.nodes.append(node)
        self.meta_store.upsert_node(node)
        with self.meta_store.connect() as conn:
            tree_node = tree_store.get_node(conn, node.id)
            if tree_node:
                node.sort_order = tree_node.get("sort_order", 0)
        return node

    # 按文件路径注册文档节点
    def register_document(
        self,
        library_id: str,
        file_path: str,
        doc_id: Optional[str] = None,
        title: Optional[str] = None,
        parent_id: Optional[str] = None,
    ) -> KnowledgeNode:
        source_path = Path(file_path)
        resolved_doc_id = doc_id or source_path.stem
        existing = self.get_node(resolved_doc_id)
        if existing:
            return existing
        node = KnowledgeNode(
            id=resolved_doc_id,
            title=title or source_path.stem,
            type="document",
            parent_id=parent_id,
            library_id=library_id,
            file_path=str(source_path),
            visible=True,
            status="pending",
        )
        return self.create_node(node)

    # 更新节点，树属性变更委托给 tree_store。
    def update_node(self, node_id: str, **kwargs: Any) -> Optional[KnowledgeNode]:
        for node in self.nodes:
            if node.id != node_id:
                continue
            old_parent_id = node.parent_id
            old_library_id = node.library_id
            for key, value in kwargs.items():
                if hasattr(node, key):
                    setattr(node, key, value)
            tree_updates: Dict[str, Any] = {}
            if "parent_id" in kwargs:
                tree_updates["parent_id"] = kwargs["parent_id"]
            if "library_id" in kwargs:
                tree_updates["scope_id"] = kwargs["library_id"]
            if "sort_order" in kwargs:
                tree_updates["sort_order"] = kwargs["sort_order"]
            if "title" in kwargs:
                tree_updates["title"] = kwargs["title"]
            if tree_updates:
                with self.meta_store.connect() as conn:
                    tree_result = tree_store.update_node(conn, node_id, tree_updates)
                    if tree_result:
                        node.parent_id = tree_result.get("parent_id")
                        node.sort_order = tree_result.get("sort_order", 0)
                        if "scope_id" in tree_updates:
                            node.library_id = tree_result.get("scope_id", node.library_id)
            parent_or_library_changed = old_parent_id != node.parent_id or old_library_id != node.library_id
            if parent_or_library_changed:
                self._normalize_sibling_orders(old_library_id, old_parent_id)
            node.updated_at = datetime.now()
            if node.type != "folder":
                self.meta_store.upsert_node(node)
            return node
        return None

    # 删除节点
    def delete_node(self, node_id: str) -> bool:
        if node_id not in {node.id for node in self.nodes}:
            return False
        target = self.get_node(node_id)
        to_delete = self._collect_subtree_node_ids(node_id)
        document_nodes = self._collect_document_nodes(to_delete)
        self._purge_document_artifacts(document_nodes)
        to_delete_set = set(to_delete)
        self.nodes = [node for node in self.nodes if node.id not in to_delete_set]
        self._delete_nodes(to_delete)
        if target:
            self._normalize_sibling_orders(target.library_id, target.parent_id)
        return True

    # 获取节点
    def get_node(self, node_id: str) -> Optional[KnowledgeNode]:
        for node in self.nodes:
            if node.id == node_id:
                return node
        return None

    # 创建解析任务
    def create_parse_task(self, task_id: str, library_id: str, doc_id: str) -> ParseTask:
        now = datetime.now()
        task = ParseTask(
            id=task_id,
            library_id=library_id,
            doc_id=doc_id,
            status="queued",
            progress=0,
            stage="queued",
            created_at=now,
            updated_at=now,
        )
        self.parse_tasks = [task, *[item for item in self.parse_tasks if item.id != task_id]]
        self.meta_store.upsert_parse_task(task)
        return task

    # 获取解析任务
    def get_parse_task(self, task_id: str) -> Optional[ParseTask]:
        for task in self.parse_tasks:
            if task.id == task_id:
                return task
        return None

    # 更新解析任务
    def update_parse_task(self, task_id: str, **kwargs: Any) -> Optional[ParseTask]:
        task = self.get_parse_task(task_id)
        if not task:
            return None
        for key, value in kwargs.items():
            if hasattr(task, key):
                setattr(task, key, value)
        task.updated_at = datetime.now()
        self.meta_store.upsert_parse_task(task)
        return task

    # 请求取消解析任务
    def request_parse_task_cancel(self, task_id: str, message: str = "用户手动取消任务") -> Optional[ParseTask]:
        task = self.get_parse_task(task_id)
        if not task:
            return None
        return self.update_parse_task(
            task_id,
            status="cancel_requested",
            stage="cancel_requested",
            stage_message=message,
            error=message,
        )

    # 判断解析任务是否已请求取消
    def is_parse_task_cancel_requested(self, task_id: str) -> bool:
        task = self.get_parse_task(task_id)
        if not task:
            return False
        return str(task.status or "").strip() == "cancel_requested"

    # 删除文档结构化片段
    def clear_document_segments(self, doc_id: str, strategy: Optional[str] = None) -> int:
        return self.index_store.clear_document_segments(doc_id, strategy)

    # 保存文档结构化片段
    def save_document_segments(
        self,
        doc_id: str,
        library_id: str,
        strategy: str,
        items: List[Dict[str, Any]],
    ) -> int:
        return self.index_store.save_document_segments(doc_id, library_id, strategy, items)

    # 查询文档结构化片段
    def list_document_segments(
        self,
        doc_id: str,
        strategy: str,
        item_type: Optional[str] = None,
        keyword: Optional[str] = None,
        limit: int = 200,
    ) -> List[Dict[str, Any]]:
        return self.index_store.list_document_segments(
            doc_id=doc_id,
            strategy=strategy,
            item_type=item_type,
            keyword=keyword,
            limit=limit,
        )

    # 统计文档结构化片段
    def get_document_segment_stats(self, doc_id: str) -> Dict[str, Any]:
        return self.index_store.get_document_segment_stats(doc_id)

    # 保存整份 canonical document SQLite 真相源
    def save_canonical_document(self, document: CanonicalDocument) -> Dict[str, int]:
        stats = self.canonical_store.save_document(document)
        self.rebuild_document_indexes(document.doc_id, document)
        return stats

    # 以语义图为唯一真相源重建 canonical 与向量索引
    def save_semantic_graph_projection(
        self,
        library_id: str,
        doc_id: str,
        graph_data: Dict[str, Any],
        *,
        title: str = "",
    ) -> Dict[str, int]:
        from docs_core.indexing import build_vector_records
        from docs_core.ingest.organize.builder import rebuild_canonical_document_from_graph

        canonical_document = rebuild_canonical_document_from_graph(
            library_id=library_id,
            doc_id=doc_id,
            graph_data=graph_data,
            title=title,
        )
        stats = self.canonical_store.save_document(canonical_document)
        self.rebuild_document_indexes(doc_id, canonical_document)
        return stats

    # 统一重建文档 FTS 与向量索引，支持 chunk 级增量刷新
    def rebuild_document_indexes(
        self,
        doc_id: str,
        canonical_document: CanonicalDocument,
        *,
        changed_chunk_ids: Optional[List[str]] = None,
    ) -> None:
        from docs_core.indexing import build_vector_records

        self.canonical_store.rebuild_chunk_fts(doc_id)
        vector_records = build_vector_records(canonical_document, only_chunk_ids=changed_chunk_ids)
        normalized_chunk_ids = [item for item in (changed_chunk_ids or []) if item]
        if normalized_chunk_ids:
            self.vector_store.delete_records(doc_id=doc_id, entity_ids=normalized_chunk_ids)
        else:
            self.vector_store.clear_document(doc_id)
        if vector_records:
            self.vector_store.upsert_records(vector_records)

    # 读取整份 canonical document
    def get_canonical_document(self, doc_id: str) -> Optional[CanonicalDocument]:
        return self.canonical_store.get_document(doc_id)

    # 清理指定文档的向量索引
    def clear_document_vectors(self, doc_id: str, entity_types: Optional[List[str]] = None) -> int:
        return self.vector_store.clear_document(doc_id, entity_types)

    # 保存文档向量索引记录
    def save_document_vectors(self, records: List[VectorRecord]) -> int:
        return self.vector_store.upsert_records(records)

    # 查询向量索引命中
    def search_document_vectors(
        self,
        query_embedding: List[float],
        *,
        doc_ids: Optional[List[str]] = None,
        entity_types: Optional[List[str]] = None,
        top_k: int = 10,
    ) -> List[VectorSearchHit]:
        return self.vector_store.search(
            query_embedding,
            doc_ids=doc_ids,
            entity_types=entity_types,
            top_k=top_k,
        )

    # 获取单文档向量索引统计
    def get_document_vector_stats(self, doc_id: str) -> Dict[str, Any]:
        return self.vector_store.get_document_stats(doc_id)

    # 查询 canonical chunks
    def list_canonical_chunks(
        self,
        doc_id: str,
        chunk_types: Optional[List[str]] = None,
        keyword: Optional[str] = None,
        limit: int = 200,
    ) -> List[CanonicalChunk]:
        return self.canonical_store.list_chunks(
            doc_id=doc_id,
            chunk_types=chunk_types,
            keyword=keyword,
            limit=limit,
        )

    # 查询 canonical blocks
    def list_canonical_blocks(
        self,
        doc_id: str,
        block_types: Optional[List[str]] = None,
        keyword: Optional[str] = None,
        limit: int = 200,
    ) -> List[CanonicalBlock]:
        return self.canonical_store.list_blocks(
            doc_id=doc_id,
            block_types=block_types,
            keyword=keyword,
            limit=limit,
        )

    # 查询图级 citation targets
    def list_citation_targets(self, doc_id: str, limit: int = 200) -> List[Dict[str, Any]]:
        return self.canonical_store.list_citation_targets(doc_id=doc_id, limit=limit)

    # 查询单个 citation target
    def get_citation_target(self, doc_id: str, target_id: str) -> Optional[Dict[str, Any]]:
        return self.canonical_store.get_citation_target(doc_id=doc_id, target_id=target_id)

    # 查询 canonical tables
    def list_canonical_tables(
        self,
        doc_id: str,
        table_types: Optional[List[str]] = None,
        keyword: Optional[str] = None,
        limit: int = 100,
    ) -> List[CanonicalTable]:
        return self.canonical_store.list_tables(
            doc_id=doc_id,
            table_types=table_types,
            keyword=keyword,
            limit=limit,
        )

    # 按 block_uid 列表批量查询富媒体字段。
    def get_blocks_rich_media(self, doc_id: str, block_uids: List[str]) -> Dict[str, Dict[str, Any]]:
        return self.index_store.get_blocks_rich_media(doc_id=doc_id, block_uids=block_uids)

    # 搜索可供 @ 引用的知识候选。
    def search_references(
        self,
        library_id: str,
        query: str,
        *,
        limit: int = 10,
        types: Optional[List[str]] = None,
        current_doc_id: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        normalized_query = str(query or "").strip()
        allowed_types = {
            str(item or "").strip().lower()
            for item in (types or ["content", "table", "formula", "figure"])
            if str(item or "").strip()
        }
        keyword_candidates: List[Optional[str]] = []
        if normalized_query:
            keyword_candidates.append(normalized_query)
            fallback_tokens = [
                token for token in normalized_query.replace("/", " ").replace("-", " ").split()
                if len(token) >= 2
            ]
            keyword_candidates.extend(token for token in fallback_tokens if token not in keyword_candidates)
        else:
            keyword_candidates.append(None)

        nodes = [
            node for node in self.list_nodes(library_id)
            if node.type == "document"
        ]
        candidates: List[Dict[str, Any]] = []
        for node in nodes:
            blocks = []
            for keyword in keyword_candidates:
                blocks = self.list_canonical_blocks(
                    doc_id=node.id,
                    keyword=keyword or None,
                    limit=max(limit * 6, 40),
                )
                if blocks:
                    break
            if not blocks:
                continue
            rich_media_map = self.get_blocks_rich_media(node.id, [block.block_id for block in blocks])
            for block in blocks:
                target_type = _resolve_reference_target_type(block.block_type)
                if target_type not in allowed_types:
                    continue
                block_content = str(block.text or block.text_clean or "").strip()
                score = _score_reference_candidate(
                    normalized_query,
                    block.section_path,
                    block_content,
                    target_type=target_type,
                    current_doc_boost=bool(current_doc_id and current_doc_id == node.id),
                )
                if not normalized_query:
                    score = 1.0 + (2.0 if current_doc_id and current_doc_id == node.id else 0.0)
                if score <= 0:
                    continue
                rich_media = dict(rich_media_map.get(block.block_id, {}) or {})
                source_file_name = self.get_doc_source_file_name(node.id)
                if source_file_name and not rich_media.get("source_file_name"):
                    rich_media["source_file_name"] = source_file_name
                candidates.append({
                    "target_id": block.block_id,
                    "target_type": target_type,
                    "library_id": library_id,
                    "doc_id": node.id,
                    "doc_title": node.title,
                    "page_idx": int(block.page_idx or 0) + 1,
                    "section_path": block.section_path or "",
                    "label": _build_reference_label(block.section_path or "", block_content, target_type),
                    "snippet": block_content[:240],
                    "content": block_content,
                    "content_type": target_type,
                    "score": round(score, 3),
                    "rich_media": rich_media,
                    "source_version": SCHEMA_VERSION,
                })
        candidates.sort(
            key=lambda item: (
                -float(item.get("score", 0.0) or 0.0),
                str(item.get("doc_title") or ""),
                int(item.get("page_idx") or 0),
            )
        )
        deduped: List[Dict[str, Any]] = []
        seen = set()
        for item in candidates:
            key = (
                str(item.get("target_id") or ""),
                str(item.get("doc_id") or ""),
            )
            if key in seen:
                continue
            seen.add(key)
            deduped.append(item)
            if len(deduped) >= max(1, min(limit, 20)):
                break
        return deduped

    # 获取文档节点的源文件名。
    def get_doc_source_file_name(self, doc_id: str) -> str:
        node = self.get_node(doc_id)
        if node and node.file_path:
            return str(node.file_path)
        return ""


_knowledge_service: Optional["KnowledgeService"] = None


def get_knowledge_service() -> "KnowledgeService":
    """获取全局知识库服务实例（懒加载单例）。"""
    global _knowledge_service
    if _knowledge_service is None:
        _knowledge_service = KnowledgeService()
    return _knowledge_service


class _KnowledgeServiceProxy:
    """模块级懒加载代理，使 knowledge_service.xxx 自动触发 get_knowledge_service()。"""

    def __getattr__(self, name):
        return getattr(get_knowledge_service(), name)

    def __bool__(self):
        return True


knowledge_service = _KnowledgeServiceProxy()


__all__ = [
    "KnowledgeLibrary",
    "KnowledgeNode",
    "KnowledgeService",
    "ParseTask",
    "SCHEMA_VERSION",
    "knowledge_service",
    "get_knowledge_service",
    "push_to_graph",
]


def push_to_graph(library_id: str, doc_id: str, graph_db_path: Optional[str] = None) -> Dict[str, Any]:
    """Push a parsed document's blocks to the knowledge graph for entity extraction.

    This is the producer side of the docs-core → knowledge-graph pipeline.
    """
    import sys
    import os as _os

    kg_src = _os.path.join(_os.path.dirname(__file__), "..", "..", "..", "knowledge-graph", "src")
    if kg_src not in sys.path:
        sys.path.insert(0, _os.path.abspath(kg_src))

    try:
        from knowledge_graph.graph_store import GraphStore
        from knowledge_graph.evidence_builder import build_evidence_packets
        from knowledge_graph.graph_orchestrator import GraphOrchestrator

        from docs_core.ingest.store.assets_file_store import file_storage, get_doc_blocks_graph
    except ImportError as e:
        logger.warning("knowledge-graph module not available: %s", e)
        return {"pushed": False, "error": str(e)}

    default_db = _os.path.join(_os.path.dirname(__file__), "..", "..", "..", "..", "data", "knowledge_graph.sqlite")
    db_path = graph_db_path or _os.path.abspath(default_db)

    content = file_storage.read_markdown(library_id, doc_id) or ""
    graph = get_doc_blocks_graph(library_id, doc_id)
    structured_items = graph.get("nodes", []) if graph else []

    packets = build_evidence_packets(
        library_id=library_id,
        doc_id=doc_id,
        doc_title="",
        document_content=content,
        structured_items=structured_items,
        doc_blocks_graph=graph,
    )

    store = GraphStore(db_path)
    orchestrator = GraphOrchestrator(store)
    orchestrator.load_seed_entities()
    result = orchestrator.expand_all_packets(packets)

    return {"pushed": True, **result}
