"""Vector store 抽象协议。"""
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


class VectorRecord(BaseModel):
    """统一的向量索引记录。"""

    record_id: str
    doc_id: str
    entity_type: str
    entity_id: str
    content: str = ""
    content_hash: str = ""
    metadata: Dict[str, Any] = Field(default_factory=dict)
    embedding: List[float] = Field(default_factory=list)


class VectorSearchHit(BaseModel):
    """统一的向量检索命中项。"""

    record_id: str
    doc_id: str
    entity_type: str
    entity_id: str
    content: str = ""
    score: float = 0.0
    metadata: Dict[str, Any] = Field(default_factory=dict)


class VectorStore:
    """可替换的向量存储抽象。"""

    # 写入指定文档的一批向量记录。
    def upsert_records(self, records: List[VectorRecord]) -> int:
        raise NotImplementedError("VectorStore.upsert_records must be implemented by subclasses.")

    # 清理指定文档下的向量记录。
    def clear_document(self, doc_id: str, entity_types: Optional[List[str]] = None) -> int:
        raise NotImplementedError("VectorStore.clear_document must be implemented by subclasses.")

    # 执行向量检索并返回 top-k 命中。
    def search(
        self,
        query_embedding: List[float],
        *,
        doc_ids: Optional[List[str]] = None,
        entity_types: Optional[List[str]] = None,
        top_k: int = 10,
    ) -> List[VectorSearchHit]:
        raise NotImplementedError("VectorStore.search must be implemented by subclasses.")

    # 获取指定文档的向量索引统计。
    def get_document_stats(self, doc_id: str) -> Dict[str, Any]:
        raise NotImplementedError("VectorStore.get_document_stats must be implemented by subclasses.")
