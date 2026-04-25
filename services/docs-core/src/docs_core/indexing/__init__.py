"""Docs 索引层统一导出。"""

from .chroma_vector_store import ChromaVectorStore
from .config import (
    get_embedding_api_key,
    get_embedding_api_url,
    get_embedding_model_name,
    get_embedding_provider_name,
    get_vectorstore_provider_name,
    resolve_chroma_persist_dir,
)
from .embedding_provider import (
    DashScopeEmbeddingProvider,
    EmbeddingProvider,
    HashEmbeddingProvider,
    build_embedding_terms,
    create_default_embedding_provider,
    default_embedding_provider,
    normalize_embedding_text,
)
from .sqlite_vector_store import SQLiteVectorStore, build_content_hash, dot_similarity
from .vector_indexer import build_vector_records, summarize_vector_records
from .vector_store import VectorRecord, VectorSearchHit, VectorStore

__all__ = [
    "ChromaVectorStore",
    "DashScopeEmbeddingProvider",
    "EmbeddingProvider",
    "HashEmbeddingProvider",
    "SQLiteVectorStore",
    "VectorRecord",
    "VectorSearchHit",
    "VectorStore",
    "build_content_hash",
    "build_embedding_terms",
    "build_vector_records",
    "create_default_embedding_provider",
    "default_embedding_provider",
    "dot_similarity",
    "get_embedding_api_key",
    "get_embedding_api_url",
    "get_embedding_model_name",
    "get_embedding_provider_name",
    "get_vectorstore_provider_name",
    "normalize_embedding_text",
    "resolve_chroma_persist_dir",
    "summarize_vector_records",
]
