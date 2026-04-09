"""知识库服务与仓储门面。"""
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from pydantic import BaseModel

from docs_core.structured.result_store_db import (
    KnowledgeIndexStore,
    KnowledgeMetaStore,
    parse_datetime,
    resolve_knowledge_index_db_path,
    resolve_knowledge_meta_db_path,
)


SCHEMA_VERSION = "1.0.0"


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
    strategy: str = "A_structured"
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
        self._load_from_db()
        if not self.libraries:
            self.create_library("default", "默认知识库", "系统自动创建的默认知识库")

    # 解析元数据库路径。
    def _resolve_db_path(self) -> Path:
        return resolve_knowledge_meta_db_path()

    # 解析索引数据库路径。
    def _resolve_index_db_path(self) -> Path:
        return resolve_knowledge_index_db_path()

    # 把数据库记录加载为内存对象缓存。
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
                strategy=row["strategy"] or "A_structured",
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
                error=row["error"],
                schema_version=row["schema_version"] or SCHEMA_VERSION,
                created_at=parse_datetime(row["created_at"]),
                updated_at=parse_datetime(row["updated_at"]),
            )
            for row in self.meta_store.list_parse_tasks()
        ]

    # 删除指定节点集合。
    def _delete_nodes(self, node_ids: List[str]) -> None:
        self.meta_store.delete_nodes(node_ids)

    # 收集节点及其全部后代节点 ID。
    def _collect_subtree_node_ids(self, node_id: str) -> List[str]:
        to_delete = {node_id}
        changed = True
        while changed:
            changed = False
            for node in self.nodes:
                if node.parent_id in to_delete and node.id not in to_delete:
                    to_delete.add(node.id)
                    changed = True
        return list(to_delete)

    # 收集指定节点集合中的文档节点。
    def _collect_document_nodes(self, node_ids: List[str]) -> List[KnowledgeNode]:
        node_id_set = set(node_ids)
        return [
            node
            for node in self.nodes
            if node.id in node_id_set and node.type == "document"
        ]

    # 清理文档节点关联的存储产物与索引数据。
    def _purge_document_artifacts(self, document_nodes: List[KnowledgeNode]) -> None:
        if not document_nodes:
            return
        from docs_core.structured.result_store_json import file_storage

        doc_ids = [node.id for node in document_nodes]
        self.meta_store.delete_parse_tasks_by_doc_ids(doc_ids)
        self.parse_tasks = [task for task in self.parse_tasks if task.doc_id not in set(doc_ids)]
        for node in document_nodes:
            self.index_store.clear_document_segments(node.id)
            self.index_store.clear_doc_blocks(node.id)
            self.index_store.clear_doc_block_corrections(node.id)
            file_storage.delete_document(node.library_id, node.id)

    # 生成删除节点前的影响范围预览。
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

    # 对兄弟节点重新排序。
    def _normalize_sibling_orders(self, library_id: str, parent_id: Optional[str]) -> None:
        siblings = sorted(
            [node for node in self.nodes if node.library_id == library_id and node.parent_id == parent_id],
            key=lambda node: (node.sort_order, node.created_at),
        )
        for idx, sibling in enumerate(siblings):
            if sibling.sort_order != idx:
                sibling.sort_order = idx
                sibling.updated_at = datetime.now()
                self.meta_store.upsert_node(sibling)

    # 获取知识库列表。
    def list_libraries(self) -> List[KnowledgeLibrary]:
        return self.libraries

    # 创建知识库。
    def create_library(self, library_id: str, name: str, description: str = "") -> KnowledgeLibrary:
        library = KnowledgeLibrary(id=library_id, name=name, description=description)
        self.libraries.append(library)
        self.meta_store.upsert_library(library)
        return library

    # 获取知识库。
    def get_library(self, library_id: str) -> Optional[KnowledgeLibrary]:
        for library in self.libraries:
            if library.id == library_id:
                return library
        return None

    # 获取知识库节点列表。
    def list_nodes(self, library_id: str, visible: bool = False) -> List[KnowledgeNode]:
        nodes = [node for node in self.nodes if node.library_id == library_id]
        if visible:
            nodes = [node for node in nodes if node.visible]
        return sorted(nodes, key=lambda node: (node.sort_order, node.created_at))

    # 创建节点。
    def create_node(self, node: KnowledgeNode) -> KnowledgeNode:
        sibling_orders = [
            item.sort_order for item in self.nodes if item.library_id == node.library_id and item.parent_id == node.parent_id
        ]
        if node.sort_order < 0:
            node.sort_order = 0
        elif sibling_orders and node.sort_order == 0:
            node.sort_order = max(sibling_orders, default=-1) + 1
        self.nodes.append(node)
        self.meta_store.upsert_node(node)
        return node

    # 按文件路径注册文档节点。
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

    # 更新节点。
    def update_node(self, node_id: str, **kwargs: Any) -> Optional[KnowledgeNode]:
        for node in self.nodes:
            if node.id != node_id:
                continue
            old_parent_id = node.parent_id
            old_library_id = node.library_id
            for key, value in kwargs.items():
                if hasattr(node, key):
                    setattr(node, key, value)
            has_explicit_sort_order = "sort_order" in kwargs
            parent_or_library_changed = old_parent_id != node.parent_id or old_library_id != node.library_id
            if ("parent_id" in kwargs or "library_id" in kwargs) and not has_explicit_sort_order:
                sibling_orders = [
                    item.sort_order
                    for item in self.nodes
                    if item.id != node.id and item.library_id == node.library_id and item.parent_id == node.parent_id
                ]
                node.sort_order = max(sibling_orders, default=-1) + 1
            if parent_or_library_changed:
                self._normalize_sibling_orders(old_library_id, old_parent_id)
                if not has_explicit_sort_order:
                    self._normalize_sibling_orders(node.library_id, node.parent_id)
            node.updated_at = datetime.now()
            self.meta_store.upsert_node(node)
            return node
        return None

    # 删除节点。
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

    # 获取节点。
    def get_node(self, node_id: str) -> Optional[KnowledgeNode]:
        for node in self.nodes:
            if node.id == node_id:
                return node
        return None

    # 创建解析任务。
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

    # 获取解析任务。
    def get_parse_task(self, task_id: str) -> Optional[ParseTask]:
        for task in self.parse_tasks:
            if task.id == task_id:
                return task
        return None

    # 更新解析任务。
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

    # 删除文档结构化片段。
    def clear_document_segments(self, doc_id: str, strategy: Optional[str] = None) -> int:
        return self.index_store.clear_document_segments(doc_id, strategy)

    # 保存文档结构化片段。
    def save_document_segments(
        self,
        doc_id: str,
        library_id: str,
        strategy: str,
        items: List[Dict[str, Any]],
    ) -> int:
        return self.index_store.save_document_segments(doc_id, library_id, strategy, items)

    # 查询文档结构化片段。
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

    # 统计文档结构化片段。
    def get_document_segment_stats(self, doc_id: str) -> Dict[str, Any]:
        return self.index_store.get_document_segment_stats(doc_id)


knowledge_service = KnowledgeService()


__all__ = [
    "KnowledgeLibrary",
    "KnowledgeNode",
    "KnowledgeService",
    "ParseTask",
    "SCHEMA_VERSION",
    "knowledge_service",
]
