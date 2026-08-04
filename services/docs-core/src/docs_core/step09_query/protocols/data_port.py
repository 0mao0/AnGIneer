"""query 层数据访问端口：检索器只依赖协议，不 import 服务实现。

默认实现由 docs_service 提供（default_query_data_port 内部延迟导入，
避免 query 模块级依赖服务层）；测试可注入伪端口。
"""
from typing import Dict, List, Optional, Protocol, runtime_checkable

from docs_core.models.types import (
    CanonicalBlock,
    CanonicalChunk,
    CanonicalDocument,
    CanonicalPage,
    CanonicalTable,
)
from docs_core.step06_vectors.vector_store import VectorSearchHit


@runtime_checkable
class QueryDataPort(Protocol):
    """query 层读取 canonical/索引所需的最小数据面。"""

    def get_canonical_document(self, doc_id: str) -> Optional[CanonicalDocument]: ...

    def search_document_vectors(
        self,
        query_embedding: List[float],
        *,
        doc_ids: Optional[List[str]] = None,
        entity_types: Optional[List[str]] = None,
        top_k: int = 10,
    ) -> List[VectorSearchHit]: ...

    def list_canonical_chunks(
        self,
        doc_id: str,
        chunk_types: Optional[List[str]] = None,
        keyword: Optional[str] = None,
        limit: int = 200,
    ) -> List[CanonicalChunk]: ...

    def list_canonical_blocks(
        self,
        doc_id: str,
        block_types: Optional[List[str]] = None,
        keyword: Optional[str] = None,
        limit: int = 200,
    ) -> List[CanonicalBlock]: ...

    def list_canonical_tables(
        self,
        doc_id: str,
        table_types: Optional[List[str]] = None,
        keyword: Optional[str] = None,
        limit: int = 100,
    ) -> List[CanonicalTable]: ...

    def list_canonical_pages(self, doc_id: str) -> List[CanonicalPage]: ...

    def search_citation_targets(self, doc_id: str, query: str, limit: int = 20) -> List[Dict[str, object]]: ...

    def search_chunk_fts(self, doc_id: str, query: str, limit: int = 20) -> List[Dict[str, object]]: ...

    def list_blocks_by_clause_refs(
        self,
        doc_id: str,
        clause_refs: List[str],
        limit: int = 12,
    ) -> List[Dict[str, object]]: ...


def default_query_data_port() -> QueryDataPort:
    """默认端口：延迟绑定 docs_service 单例。"""
    from docs_core.docs_service import get_docs_service

    return get_docs_service()
