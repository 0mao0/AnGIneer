"""树操作通用契约模型。"""
from typing import Any, Dict, Optional

from pydantic import BaseModel


class TreeNodeData(BaseModel):
    """树节点数据。"""
    node_id: str
    tree_type: str
    title: str = ""
    parent_id: Optional[str] = None
    scope_id: str = ""
    sort_order: int = 0
    is_folder: bool = False
    extra: Dict[str, Any] = {}


class MoveNodeRequest(BaseModel):
    """移动节点请求。"""
    parent_id: Optional[str] = None
    sort_order: int = 0
