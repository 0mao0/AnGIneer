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
    # 库组拆分的 payload 归属字段（plan-kb-split-groups §二）：写入时透传进引擎 payload，
    # 同 collection 内多库过滤与跨组搬运对账都靠它；空串=注册表出现前的存量记录
    library_id: str = ""


class VectorSearchHit(BaseModel):
    """统一的向量检索命中项。"""

    record_id: str
    doc_id: str
    entity_type: str
    entity_id: str
    content: str = ""
    score: float = 0.0
    metadata: Dict[str, Any] = Field(default_factory=dict)
    library_id: str = ""


class VectorStore:
    """可替换的向量存储抽象。"""

    # 写入指定文档的一批向量记录。
    # collection 仅多 collection 引擎（qdrant）使用，单文件引擎（sqlite/chroma）忽略。
    def upsert_records(self, records: List[VectorRecord], collection: Optional[str] = None) -> int:
        raise NotImplementedError("VectorStore.upsert_records must be implemented by subclasses.")

    # 清理指定文档下的向量记录。
    def clear_document(
        self,
        doc_id: str,
        entity_types: Optional[List[str]] = None,
        collection: Optional[str] = None,
    ) -> int:
        raise NotImplementedError("VectorStore.clear_document must be implemented by subclasses.")

    # 按实体 ID 删除指定文档下的一组向量记录。
    def delete_records(
        self,
        doc_id: str,
        entity_ids: List[str],
        collection: Optional[str] = None,
    ) -> int:
        raise NotImplementedError("VectorStore.delete_records must be implemented by subclasses.")

    # 执行向量检索并返回 top-k 命中。
    def search(
        self,
        query_embedding: List[float],
        *,
        doc_ids: Optional[List[str]] = None,
        entity_types: Optional[List[str]] = None,
        top_k: int = 10,
        collection: Optional[str] = None,
    ) -> List[VectorSearchHit]:
        raise NotImplementedError("VectorStore.search must be implemented by subclasses.")

    # 获取指定文档的向量索引统计。
    def get_document_stats(self, doc_id: str, collection: Optional[str] = None) -> Dict[str, Any]:
        raise NotImplementedError("VectorStore.get_document_stats must be implemented by subclasses.")
