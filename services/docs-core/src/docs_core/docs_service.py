"""知识库服务与仓储门面"""
from datetime import datetime
import logging
import re
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from pydantic import BaseModel

from tree_core import tree_store

from docs_core.models.types import (
    CanonicalBlock,
    CanonicalChunk,
    CanonicalDocument,
    CanonicalPage,
    CanonicalTable,
    CitationTarget,
    SCHEMA_VERSION,
    STRUCTURED_DOC_GRAPH_STRATEGY,
)
from docs_core.step09_query.protocols.contracts import KnowledgeNode
from docs_core.step05_sqlite_fts.store.canonical_sql_store import CanonicalSQLiteStore
from docs_core.step05_sqlite_fts.store.blocks_sql_store import (
    KnowledgeIndexStore,
    KnowledgeMetaStore,
    parse_datetime,
)
from docs_core.paths import (
    resolve_knowledge_index_db_path,
    resolve_knowledge_meta_db_path,
)
from docs_core import library_registry
from docs_core.step06_vectors import (
    ChromaVectorStore,
    QdrantVectorStore,
    SQLiteVectorStore,
    VectorRecord,
    VectorSearchHit,
    get_vectorstore_provider_name,
)

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


def _build_document_candidates(
    library_id: str,
    nodes: List[Any],
    query: str,
    current_doc_id: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """文档级 @ 候选：标题包含即命中（前缀优先），空查询按库内顺序返回全部文档。"""
    normalized = str(query or "").strip().lower()
    items: List[Dict[str, Any]] = []
    for node in nodes:
        title = str(node.title or "").strip()
        if not title:
            continue
        if normalized:
            lowered = title.lower()
            if lowered.startswith(normalized):
                score = 2.0
            elif normalized in lowered:
                score = 1.0
            else:
                continue
        else:
            score = 1.0
        if current_doc_id and current_doc_id == node.id:
            score += 0.5
        # chip 展示去扩展名（与前端 formatCitationDocTitle 的口径一致）
        bare_title = re.sub(r"\.(pdf|docx?|xlsx?|pptx?|md|markdown|txt)$", "", title, flags=re.IGNORECASE)
        label = bare_title if bare_title.startswith("《") else f"《{bare_title}》"
        items.append({
            "target_id": node.id,
            "target_type": "document",
            "library_id": library_id,
            "doc_id": node.id,
            "doc_title": title,
            "page_idx": 0,
            "page_label": None,
            "section_path": "",
            "label": label,
            "snippet": "",
            "content": "",
            "content_type": "document",
            "score": round(score, 3),
            "rich_media": {},
            "source_version": SCHEMA_VERSION,
        })
    return items


def _dedupe_reference_candidates(
    candidates: List[Dict[str, Any]],
    limit: int,
) -> List[Dict[str, Any]]:
    """引用候选统一排序 + 去重 + 截断。"""
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


class KnowledgeLibrary(BaseModel):
    """知识库。"""

    id: str
    name: str
    description: Optional[str] = None
    created_at: datetime = datetime.now()
    updated_at: datetime = datetime.now()
    # 库组注册表字段（plan-kb-split-groups §二）：注册表已初始化时随列表直出；
    # 未注册/注册表缺失时为空串，前端按「未分组」展示
    group_name: str = ""
    collection: str = ""
    status: str = ""


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


class DocsService:
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
        # 组文件 store 缓存（阶段二：path → store；默认文件走 self.canonical_store/index_store 本体）
        self._canonical_stores: Dict[str, CanonicalSQLiteStore] = {}
        self._index_stores: Dict[str, KnowledgeIndexStore] = {}
        self._load_from_db()
        if not self.libraries:
            self.create_library("default", "默认知识库", "系统自动创建的默认知识库")

    # 解析元数据库路径
    def _resolve_db_path(self) -> Path:
        return resolve_knowledge_meta_db_path()

    # 解析索引数据库路径
    def _resolve_index_db_path(self) -> Path:
        return resolve_knowledge_index_db_path()

    # ---- 向量 collection 路由（库组拆分：注册表解析，未注册回退 store 默认） ----

    @staticmethod
    def _collection_for_library(library_id: Optional[str]) -> Optional[str]:
        """library_id → qdrant collection。返回 None = 未注册，走 store 实例默认（旧行为）。"""
        if not library_id:
            return None
        record = library_registry.get_library(library_id)
        return record.collection if record is not None else None

    def _collection_for_doc(self, doc_id: str) -> Optional[str]:
        node = self.get_node(doc_id)
        if node is None:
            return None
        return self._collection_for_library(node.library_id)

    # ---- sqlite 组文件路由（阶段二：library_id 经注册表解析组文件，未注册回退默认单文件） ----

    def _canonical_store_for(self, library_id: Optional[str]) -> CanonicalSQLiteStore:
        default_path = getattr(self, "index_db_path", None)
        if not library_id or default_path is None:
            return self.canonical_store
        # 未注册库回退本服务默认 store（self.index_db_path 是什么就用什么——测试隔离实例
        # 指向 tmp，绝不能经全局解析绕到真盘组文件，2026-10-03 tests/unit 实踩）
        record = library_registry.get_library(library_id)
        if record is None:
            return self.canonical_store
        path = library_registry.resolve_index_db_path(library_id)
        # 组文件缺失时 resolve 回退到全局默认单文件——「默认单文件」对本服务实例就是
        # self.index_db_path（隔离测试里指向 tmp），必须归一到本体 store
        if Path(path) == Path(default_path) or Path(path) == Path(resolve_knowledge_index_db_path()):
            return self.canonical_store
        key = str(path)
        store = self._canonical_stores.get(key)
        if store is None:
            store = CanonicalSQLiteStore(db_path=Path(path))
            self._canonical_stores[key] = store
        return store

    def _index_store_for(self, library_id: Optional[str]) -> KnowledgeIndexStore:
        default_path = getattr(self, "index_db_path", None)
        if not library_id or default_path is None:
            return self.index_store
        record = library_registry.get_library(library_id)
        if record is None:
            return self.index_store
        path = library_registry.resolve_index_db_path(library_id)
        if Path(path) == Path(default_path) or Path(path) == Path(resolve_knowledge_index_db_path()):
            return self.index_store
        key = str(path)
        store = self._index_stores.get(key)
        if store is None:
            store = KnowledgeIndexStore(db_path=Path(path), schema_version=SCHEMA_VERSION)
            self._index_stores[key] = store
        return store

    def _library_of_doc(self, doc_id: str) -> Optional[str]:
        """doc→library 读穿反查（meta nodes 主键命中）。"""
        return self.meta_store.get_node_library_id(doc_id)

    def _canonical_store_for_doc(self, doc_id: str) -> CanonicalSQLiteStore:
        return self._canonical_store_for(self._library_of_doc(doc_id))

    def _index_store_for_doc(self, doc_id: str) -> KnowledgeIndexStore:
        return self._index_store_for(self._library_of_doc(doc_id))

    def _doc_ids_by_store(self, doc_ids: List[str]) -> "Dict[CanonicalSQLiteStore, List[str]]":
        """doc_ids 按所属组文件分桶（key=该组 canonical store 实例）。"""
        groups: Dict[CanonicalSQLiteStore, List[str]] = {}
        for doc_id in doc_ids:
            store = self._canonical_store_for_doc(doc_id)
            groups.setdefault(store, []).append(doc_id)
        return groups

    def _all_canonical_stores(self) -> List[CanonicalSQLiteStore]:
        """全部已知组文件的 store（chunk_id 反查/全局 FTS 的扇出面）：默认文件 + 注册表各组。"""
        stores: Dict[str, CanonicalSQLiteStore] = {str(self.index_db_path): self.canonical_store}
        for record in library_registry.list_libraries():
            key = str(library_registry.resolve_index_db_path(record.library_id))
            if key not in stores:
                stores[key] = self._canonical_store_for(record.library_id)
        return list(stores.values())

    # 按配置创建当前默认向量存储实现
    def _create_vector_store(self):
        provider_name = get_vectorstore_provider_name()
        if provider_name == "sqlite":
            vector_store = SQLiteVectorStore(db_path=self.index_db_path)
            logger.info("docs_core 启用向量 provider=%s, backend=%s", provider_name, vector_store.__class__.__name__)
            return vector_store
        if provider_name == "qdrant":
            vector_store = QdrantVectorStore()
            logger.info("docs_core 启用向量 provider=%s, backend=%s", provider_name, vector_store.__class__.__name__)
            return vector_store
        if provider_name == "chroma":
            # 配置错误/存储不可用一律 fail-fast：静默回退 sqlite 会让进程跑在空库上
            # 继续答检索题（假警报病根），宁可从不起
            vector_store = ChromaVectorStore()
            logger.info("docs_core 启用向量 provider=%s, backend=%s", provider_name, vector_store.__class__.__name__)
            return vector_store
        raise ValueError(
            f"未知向量 provider={provider_name!r}，可选 qdrant/sqlite/chroma"
        )

    # 数据库行 → 领域对象（_load_from_db 与读穿读入口共用同一份字段映射）
    @staticmethod
    def _library_from_row(row: Any) -> KnowledgeLibrary:
        return KnowledgeLibrary(
            id=row["id"],
            name=row["name"],
            description=row["description"],
            created_at=parse_datetime(row["created_at"]),
            updated_at=parse_datetime(row["updated_at"]),
        )

    @staticmethod
    def _node_from_row(row: Any) -> KnowledgeNode:
        return KnowledgeNode(
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
            deleted=bool(row.get("deleted")),
            created_at=parse_datetime(row["created_at"]),
            updated_at=parse_datetime(row["updated_at"]),
        )

    # 把数据库记录加载为内存对象缓存
    def _load_from_db(self) -> None:
        self.libraries = [
            self._library_from_row(row)
            for row in self.meta_store.list_libraries()
        ]
        self.nodes = [
            self._node_from_row(row)
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
        from docs_core.docs_file_io import file_storage

        doc_ids = [node.id for node in document_nodes]
        self.meta_store.delete_parse_tasks_by_doc_ids(doc_ids)
        self.parse_tasks = [task for task in self.parse_tasks if task.doc_id not in set(doc_ids)]
        for node in document_nodes:
            self.meta_store.clear_parse_stages(node.id)
            index_store = self._index_store_for(node.library_id)
            index_store.clear_document_segments(node.id)
            index_store.clear_doc_blocks(node.id)
            index_store.clear_doc_block_corrections(node.id)
            self._canonical_store_for(node.library_id).clear_document(node.id)
            self.vector_store.clear_document(
                node.id, collection=self._collection_for_library(node.library_id)
            )
            file_storage.delete_document(node.library_id, node.id)
            self._delete_document_graph_data(node.id)

    # 清理 knowledge_graph.sqlite 中该文档的图谱产物（entities 为全局共享，保留）。
    def _delete_document_graph_data(self, doc_id: str) -> None:
        try:
            from docs_core.paths import resolve_graph_db_path
            from docs_core.step07_graph.graph_store import GraphStore
            graph_db = resolve_graph_db_path()
            if graph_db.exists():
                GraphStore(str(graph_db)).delete_document(doc_id)
        except Exception as exc:
            logger.warning("清理文档 %s 的图谱数据失败: %s", doc_id, exc)

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

    # 获取知识库列表（读穿：现查 SQLite，跨进程写入的库对运行中的读方进程立即可见——
    # aichat-api 曾因启动快照看不见新建库，导致该库题目检索恒空、全拒答）。
    # 注册表已初始化时用注册行的 组/collection/状态  enrichment（注册表读穿，无缓存）。
    def list_libraries(self) -> List[KnowledgeLibrary]:
        libraries = [self._library_from_row(row) for row in self.meta_store.list_libraries()]
        records = {record.library_id: record for record in library_registry.list_libraries()}
        for library in libraries:
            record = records.get(library.id)
            if record is not None:
                library.group_name = record.group_name
                library.collection = record.collection
                library.status = record.status
        return libraries

    # 创建知识库（group_name 缺省落注册表默认组；注册表写入失败降级为仅 meta 记录，
    # 存储位置解析走回退默认，行为与注册表出现前一致）
    def create_library(self, library_id: str, name: str, description: str = "", group_name: str = "") -> KnowledgeLibrary:
        library = KnowledgeLibrary(id=library_id, name=name, description=description)
        self.libraries.append(library)
        self.meta_store.upsert_library(library)
        try:
            library_registry.register_library(
                library_id,
                name=name,
                description=description or "",
                group_name=group_name or library_registry.DEFAULT_GROUP,
            )
        except Exception as exc:
            logger.warning("注册表登记失败（已回退默认存储位置）: library=%s err=%s", library_id, exc)
        return library

    # 获取知识库（读穿）
    def get_library(self, library_id: str) -> Optional[KnowledgeLibrary]:
        for library in self.list_libraries():
            if library.id == library_id:
                return library
        return None

    # 更新知识库名称/描述
    def update_library(self, library_id: str, name: Optional[str] = None, description: Optional[str] = None) -> Optional[KnowledgeLibrary]:
        library = self.get_library(library_id)
        if library is None:
            return None
        if name is not None:
            library.name = name
        if description is not None:
            library.description = description
        library.updated_at = datetime.now()
        self.meta_store.upsert_library(library)
        return library

    # 删除知识库：级联清理该库全部节点、文档产物、图谱数据与库记录。default 禁止删除。
    def delete_library(self, library_id: str) -> bool:
        if library_id == "default" or self.get_library(library_id) is None:
            return False
        library_nodes = [node for node in self.nodes if node.library_id == library_id]
        library_node_ids = [node.id for node in library_nodes]
        document_nodes = [node for node in library_nodes if node.type == "document"]
        self._purge_document_artifacts(document_nodes)
        self.nodes = [node for node in self.nodes if node.library_id != library_id]
        self.meta_store.delete_nodes(library_node_ids)
        self.libraries = [library for library in self.libraries if library.id != library_id]
        self.meta_store.delete_library(library_id)
        try:
            library_registry.set_status(library_id, library_registry.STATUS_RETIRED)
        except Exception as exc:
            logger.warning("注册表置 retired 失败: library=%s err=%s", library_id, exc)
        try:
            from docs_core.paths import resolve_graph_db_path
            from docs_core.step07_graph.graph_store import GraphStore
            graph_db = resolve_graph_db_path()
            if graph_db.exists():
                GraphStore(str(graph_db)).delete_library(library_id)
        except Exception as exc:
            logger.warning("清理知识库 %s 的图谱数据失败: %s", library_id, exc)
        return True

    # 获取知识库节点列表（读穿：现查 SQLite——新建库/新导文档对运行中的读方进程立即可见；
    # self.nodes 内存列表只服务本进程写入方内部的树操作，不再是读路径的真相源）
    def list_nodes(self, library_id: Optional[str] = None, visible: bool = False) -> List[KnowledgeNode]:
        nodes = [
            self._node_from_row(row)
            for row in self.meta_store.list_nodes(library_id=library_id)
            if not row["deleted"]
        ]
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

    # 软删除节点及子树：仅标记 deleted，节点与文件系统内容保留。
    def soft_delete_node(self, node_id: str) -> bool:
        if node_id not in {node.id for node in self.nodes}:
            return False
        to_delete = self._collect_subtree_node_ids(node_id)
        self.meta_store.mark_nodes_deleted(to_delete, True)
        id_set = set(to_delete)
        for node in self.nodes:
            if node.id in id_set:
                node.deleted = True
        return True

    # 恢复软删除的节点及子树。
    def restore_soft_deleted_node(self, node_id: str) -> bool:
        if node_id not in {node.id for node in self.nodes}:
            return False
        to_restore = self._collect_subtree_node_ids(node_id)
        self.meta_store.mark_nodes_deleted(to_restore, False)
        id_set = set(to_restore)
        for node in self.nodes:
            if node.id in id_set:
                node.deleted = False
        return True

    # 获取节点子树内全部文档节点 ID（供 API 层级联标记解析记录等使用）。
    def get_subtree_document_ids(self, node_id: str) -> List[str]:
        if node_id not in {node.id for node in self.nodes}:
            return []
        subtree_node_ids = self._collect_subtree_node_ids(node_id)
        return [node.id for node in self._collect_document_nodes(subtree_node_ids)]

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

    # 记录解析步骤
    def log_parse_step(self, task_id: str, doc_id: str, stage: str, progress: int, stage_message: Optional[str] = None) -> None:
        self.meta_store.insert_parse_task_step(task_id, doc_id, stage, progress, stage_message)

    # 获取解析步骤历史
    def get_parse_task_steps(self, task_id: str) -> list[dict]:
        return self.meta_store.get_parse_task_steps(task_id)

    # 记录阶段内分析步骤（MinerU 产物 / PoPo 对齐 / 信号注入等）
    def log_stage_step(self, doc_id: str, stage: str, step: str, status: str = "done", detail: str = "") -> None:
        self.meta_store.insert_parse_stage_step(doc_id, stage, step, status, detail)

    # 获取文档各阶段的分析步骤明细
    def list_stage_steps(self, doc_id: str) -> list[dict]:
        return self.meta_store.list_parse_stage_steps(doc_id)

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
        return self._index_store_for_doc(doc_id).clear_document_segments(doc_id, strategy)

    # 保存文档结构化片段
    def save_document_segments(
        self,
        doc_id: str,
        library_id: str,
        strategy: str,
        items: List[Dict[str, Any]],
    ) -> int:
        return self._index_store_for(library_id).save_document_segments(doc_id, library_id, strategy, items)

    # 查询文档结构化片段
    def list_document_segments(
        self,
        doc_id: str,
        strategy: str,
        item_type: Optional[str] = None,
        keyword: Optional[str] = None,
        limit: int = 200,
    ) -> List[Dict[str, Any]]:
        return self._index_store_for_doc(doc_id).list_document_segments(
            doc_id=doc_id,
            strategy=strategy,
            item_type=item_type,
            keyword=keyword,
            limit=limit,
        )

    # 统计文档结构化片段
    def get_document_segment_stats(self, doc_id: str) -> Dict[str, Any]:
        return self._index_store_for_doc(doc_id).get_document_segment_stats(doc_id)

    # 保存整份 canonical document SQLite 真相源
    def save_canonical_document(self, document: CanonicalDocument) -> Dict[str, int]:
        stats = self._canonical_store_for(document.library_id).save_document(document)
        self.rebuild_document_indexes(document.doc_id, document)
        return stats

    # 仅保存 canonical document 不重建向量索引（FTS 由 canonical_store.save_document 内部处理）
    def save_canonical_document_bare(self, document: CanonicalDocument) -> Dict[str, int]:
        return self._canonical_store_for(document.library_id).save_document(document)

    # 仅重建 FTS 索引
    def rebuild_document_fts(self, doc_id: str) -> None:
        self._canonical_store_for_doc(doc_id).rebuild_chunk_fts(doc_id)

    # 仅重建向量索引
    def rebuild_document_vectors(
        self,
        doc_id: str,
        canonical_document: Optional[CanonicalDocument] = None,
        on_step: Optional[Callable[[str, str, str], None]] = None,
    ) -> int:
        from docs_core.step06_vectors import build_vector_records

        document = canonical_document or self._canonical_store_for_doc(doc_id).get_document(doc_id)
        if document is None:
            raise ValueError(f"canonical document 不存在: {doc_id}")
        if on_step is not None:
            on_step("canonical 读取", "done", f"{len(document.blocks)} blocks / {len(document.chunks)} chunks")
        vector_records = build_vector_records(document)
        if on_step is not None:
            on_step("向量记录构建", "done", f"{len(vector_records)} 条")
        collection = self._collection_for_library(getattr(document, "library_id", ""))
        self.vector_store.clear_document(doc_id, collection=collection)
        written = 0
        if vector_records:
            written = self.vector_store.upsert_records(vector_records, collection=collection) or 0
        # 静默失败收口（2026-09-14 生产实踩：209 chunk 文档重建后 0 个点，
        # 全部记录因空向量被 upsert 静默跳过，调用方毫无感知）：应写 ≠ 实写必须炸
        if written != len(vector_records):
            raise RuntimeError(
                f"向量写入缺口: doc_id={doc_id} 应写 {len(vector_records)} 条，"
                f"实写 {written} 条（空向量被静默跳过，检查 embedding provider）"
            )
        if on_step is not None:
            on_step("向量索引落库", "done", f"{written} 条落库")
        return written

    # 以语义图为唯一真相源重建 canonical 与向量索引
    def save_semantic_graph_projection(
        self,
        library_id: str,
        doc_id: str,
        graph_data: Dict[str, Any],
        *,
        title: str = "",
    ) -> Dict[str, int]:
        from docs_core.step06_vectors import build_vector_records
        from docs_core.step05_sqlite_fts.rebuild.graph_rebuilder import rebuild_canonical_document_from_graph

        canonical_document = rebuild_canonical_document_from_graph(
            library_id=library_id,
            doc_id=doc_id,
            graph_data=graph_data,
            title=title,
        )
        stats = self._canonical_store_for(library_id).save_document(canonical_document)
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
        from docs_core.step06_vectors import build_vector_records

        self._canonical_store_for(getattr(canonical_document, "library_id", "") or None).rebuild_chunk_fts(doc_id)
        vector_records = build_vector_records(canonical_document, only_chunk_ids=changed_chunk_ids)
        collection = self._collection_for_library(getattr(canonical_document, "library_id", ""))
        normalized_chunk_ids = [item for item in (changed_chunk_ids or []) if item]
        if normalized_chunk_ids:
            self.vector_store.delete_records(doc_id=doc_id, entity_ids=normalized_chunk_ids, collection=collection)
        else:
            self.vector_store.clear_document(doc_id, collection=collection)
        written = 0
        if vector_records:
            written = self.vector_store.upsert_records(vector_records, collection=collection) or 0
        if written != len(vector_records):
            raise RuntimeError(
                f"向量写入缺口: doc_id={doc_id} 应写 {len(vector_records)} 条，"
                f"实写 {written} 条（空向量被静默跳过，检查 embedding provider）"
            )

    # 读取整份 canonical document
    def get_canonical_document(self, doc_id: str) -> Optional[CanonicalDocument]:
        return self._canonical_store_for_doc(doc_id).get_document(doc_id)

    # 清理指定文档的向量索引
    def clear_document_vectors(self, doc_id: str, entity_types: Optional[List[str]] = None) -> int:
        return self.vector_store.clear_document(
            doc_id, entity_types, collection=self._collection_for_doc(doc_id)
        )

    # 保存文档向量索引记录
    def save_document_vectors(self, records: List[VectorRecord]) -> int:
        collection = self._collection_for_library(records[0].library_id) if records else None
        return self.vector_store.upsert_records(records, collection=collection)

    # 查询向量索引命中
    def search_document_vectors(
        self,
        query_embedding: List[float],
        *,
        doc_ids: Optional[List[str]] = None,
        entity_types: Optional[List[str]] = None,
        top_k: int = 10,
        library_id: Optional[str] = None,
    ) -> List[VectorSearchHit]:
        return self.vector_store.search(
            query_embedding,
            doc_ids=doc_ids,
            entity_types=entity_types,
            top_k=top_k,
            collection=self._collection_for_library(library_id),
        )

    # 获取单文档向量索引统计
    def get_document_vector_stats(self, doc_id: str) -> Dict[str, Any]:
        return self.vector_store.get_document_stats(
            doc_id, collection=self._collection_for_doc(doc_id)
        )

    # 查询 canonical chunks
    def list_canonical_chunks(
        self,
        doc_id: str,
        chunk_types: Optional[List[str]] = None,
        keyword: Optional[str] = None,
        limit: int = 200,
    ) -> List[CanonicalChunk]:
        return self._canonical_store_for_doc(doc_id).list_chunks(
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
        return self._canonical_store_for_doc(doc_id).list_blocks(
            doc_id=doc_id,
            block_types=block_types,
            keyword=keyword,
            limit=limit,
        )

    # 查询图级 citation targets
    def list_citation_targets(self, doc_id: str, limit: int = 200) -> List[Dict[str, Any]]:
        return self._canonical_store_for_doc(doc_id).list_citation_targets(doc_id=doc_id, limit=limit)

    # 查询单个 citation target
    def get_citation_target(self, doc_id: str, target_id: str) -> Optional[Dict[str, Any]]:
        return self._canonical_store_for_doc(doc_id).get_citation_target(doc_id=doc_id, target_id=target_id)

    # 查询 canonical tables
    def list_canonical_tables(
        self,
        doc_id: str,
        table_types: Optional[List[str]] = None,
        keyword: Optional[str] = None,
        limit: int = 100,
    ) -> List[CanonicalTable]:
        return self._canonical_store_for_doc(doc_id).list_tables(
            doc_id=doc_id,
            table_types=table_types,
            keyword=keyword,
            limit=limit,
        )

    # ---- query 层数据端口直通（QueryDataPort）----
    def list_canonical_pages(self, doc_id: str) -> List[CanonicalPage]:
        """列出 canonical pages。"""
        return self._canonical_store_for_doc(doc_id).list_pages(doc_id)

    def search_citation_targets(self, doc_id: str, query: str, limit: int = 20) -> List[Dict[str, object]]:
        """按文本检索引用目标。"""
        return self._canonical_store_for_doc(doc_id).search_citation_targets(doc_id, query, limit)

    def search_chunk_fts(self, doc_id: Optional[str], query: str, limit: int = 20) -> List[Dict[str, object]]:
        """按 FTS 检索 chunk；doc_id 为 None 时全库检索（拆文件后=各组文件扇出按 bm25 重排）。"""
        if doc_id:
            return self._canonical_store_for_doc(doc_id).search_chunk_fts(doc_id, query, limit)
        merged: List[Dict[str, object]] = []
        for store in self._all_canonical_stores():
            merged.extend(store.search_chunk_fts(None, query, limit))
        merged.sort(key=lambda row: (float(row.get("bm25_score") or 0.0), str(row.get("chunk_id") or "")))
        return merged[: max(1, min(200, limit))]

    def list_blocks_by_clause_refs(self, doc_id: str, clause_refs: List[str], limit: int = 12) -> List[Dict[str, object]]:
        """按条款引用精确召回块。"""
        return self._canonical_store_for_doc(doc_id).list_blocks_by_clause_refs(doc_id, clause_refs, limit)

    # ---- 批量取数直通（检索扇出合并，替代逐文档循环）----
    def list_pages_for_docs(self, doc_ids: List[str]) -> List[CanonicalPage]:
        """批量列出多文档 canonical pages（跨组文件自动分桶合并）。"""
        pages: List[CanonicalPage] = []
        for store, bucket in self._doc_ids_by_store(doc_ids).items():
            pages.extend(store.list_pages_for_docs(bucket))
        return pages

    def search_citation_targets_for_docs(
        self, doc_ids: List[str], query: str, per_doc_limit: int = 40
    ) -> List[Dict[str, object]]:
        """批量检索多文档 citation targets（逐文档上限语义不变；跨组分桶合并）。"""
        merged: List[Dict[str, object]] = []
        for store, bucket in self._doc_ids_by_store(doc_ids).items():
            merged.extend(store.search_citation_targets_for_docs(bucket, query, per_doc_limit))
        return merged

    def list_chunks_by_ids(self, chunk_ids: List[str]) -> List[CanonicalChunk]:
        """按 chunk_id 集合批量反查完整 chunk（chunk→doc 无映射，扇出全部已知组文件）。"""
        if not chunk_ids:
            return []
        merged: List[CanonicalChunk] = []
        for store in self._all_canonical_stores():
            merged.extend(store.list_chunks_by_ids(chunk_ids))
        return merged

    def list_chunks_for_docs(
        self, doc_ids: List[str], keyword: Optional[str] = None, per_doc_limit: int = 60
    ) -> List[CanonicalChunk]:
        """批量查询多文档 chunks（逐文档上限语义不变；跨组分桶合并）。"""
        merged: List[CanonicalChunk] = []
        for store, bucket in self._doc_ids_by_store(doc_ids).items():
            merged.extend(store.list_chunks_for_docs(bucket, keyword=keyword, per_doc_limit=per_doc_limit))
        return merged

    def list_blocks_for_docs(
        self,
        doc_ids: List[str],
        block_types: Optional[List[str]] = None,
        keyword: Optional[str] = None,
        per_doc_limit: int = 60,
    ) -> List[CanonicalBlock]:
        """批量查询多文档 blocks（逐文档上限语义不变；跨组分桶合并）。"""
        merged: List[CanonicalBlock] = []
        for store, bucket in self._doc_ids_by_store(doc_ids).items():
            merged.extend(
                store.list_blocks_for_docs(bucket, block_types=block_types, keyword=keyword, per_doc_limit=per_doc_limit)
            )
        return merged

    def list_blocks_in_page_range(self, doc_id: str, page_min: int, page_max: int) -> List[CanonicalBlock]:
        """按页范围取文档 blocks（公式上下文邻近页拉取）。"""
        return self._canonical_store_for_doc(doc_id).list_blocks_in_page_range(doc_id, page_min, page_max)

    # 按 block_uid 列表批量查询富媒体字段。
    def get_blocks_rich_media(self, doc_id: str, block_uids: List[str]) -> Dict[str, Dict[str, Any]]:
        return self._index_store_for_doc(doc_id).get_blocks_rich_media(doc_id=doc_id, block_uids=block_uids)

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
        # document 类型 = 文档级 @ 提及候选（@ 最多到文档，不下探块/章节）；
        # 只请求 document 时跳过块级扫描，避免无谓的 canonical 查询。
        if "document" in allowed_types:
            candidates.extend(
                _build_document_candidates(library_id, nodes, normalized_query, current_doc_id)
            )
        block_types = allowed_types - {"document"}
        if not block_types:
            return _dedupe_reference_candidates(candidates, limit)
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
            page_labels = {
                page.page_idx: page.printed_page_label
                for page in self._canonical_store_for(library_id).list_pages(node.id)
                if page.printed_page_label
            }
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
                    "page_label": page_labels.get(int(block.page_idx or 0)),
                    "section_path": block.section_path or "",
                    "label": _build_reference_label(block.section_path or "", block_content, target_type),
                    "snippet": block_content[:240],
                    "content": block_content,
                    "content_type": target_type,
                    "score": round(score, 3),
                    "rich_media": rich_media,
                    "source_version": SCHEMA_VERSION,
                })
        return _dedupe_reference_candidates(candidates, limit)

    # 获取文档节点的源文件名。
    def get_doc_source_file_name(self, doc_id: str) -> str:
        node = self.get_node(doc_id)
        if node and node.file_path:
            return str(node.file_path)
        return ""


_docs_service: Optional["DocsService"] = None


def get_docs_service() -> "DocsService":
    """获取全局知识库服务实例（懒加载单例）。"""
    global _docs_service
    if _docs_service is None:
        _docs_service = DocsService()
    return _docs_service


class _DocsServiceProxy:
    """模块级懒加载代理，使 docs_service.xxx 自动触发 get_docs_service()。"""

    def __getattr__(self, name):
        return getattr(get_docs_service(), name)

    def __bool__(self):
        return True


docs_service = _DocsServiceProxy()


__all__ = [
    "KnowledgeLibrary",
    "KnowledgeNode",
    "DocsService",
    "ParseTask",
    "SCHEMA_VERSION",
    "docs_service",
    "get_docs_service",
]
