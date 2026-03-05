"""知识库管理 API"""
from typing import Optional, List
from pydantic import BaseModel
from datetime import datetime


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
    created_at: datetime = datetime.now()
    updated_at: datetime = datetime.now()


class KnowledgeLibrary(BaseModel):
    """知识库"""
    id: str
    name: str
    description: Optional[str] = None
    created_at: datetime = datetime.now()
    updated_at: datetime = datetime.now()


class KnowledgeService:
    """知识库服务"""

    def __init__(self):
        self.nodes: List[KnowledgeNode] = []
        self.libraries: List[KnowledgeLibrary] = []

    def list_libraries(self) -> List[KnowledgeLibrary]:
        """获取知识库列表"""
        return self.libraries

    def create_library(self, name: str, description: str = '') -> KnowledgeLibrary:
        """创建知识库"""
        library = KnowledgeLibrary(
            id=f'lib-{len(self.libraries) + 1}',
            name=name,
            description=description
        )
        self.libraries.append(library)
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
        return nodes

    def create_node(self, node: KnowledgeNode) -> KnowledgeNode:
        """创建节点"""
        self.nodes.append(node)
        return node

    def update_node(self, node_id: str, **kwargs) -> Optional[KnowledgeNode]:
        """更新节点"""
        for node in self.nodes:
            if node.id == node_id:
                for key, value in kwargs.items():
                    if hasattr(node, key):
                        setattr(node, key, value)
                node.updated_at = datetime.now()
                return node
        return None

    def delete_node(self, node_id: str) -> bool:
        """删除节点"""
        node_ids = {node.id for node in self.nodes}
        if node_id not in node_ids:
            return False
        to_delete = {node_id}
        changed = True
        while changed:
            changed = False
            for node in self.nodes:
                if node.parent_id in to_delete and node.id not in to_delete:
                    to_delete.add(node.id)
                    changed = True
        self.nodes = [node for node in self.nodes if node.id not in to_delete]
        return True

    def get_node(self, node_id: str) -> Optional[KnowledgeNode]:
        """获取节点"""
        for node in self.nodes:
            if node.id == node_id:
                return node
        return None


knowledge_service = KnowledgeService()
