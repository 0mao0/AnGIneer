"""索引层配置解析"""
import os
from pathlib import Path

from dotenv import load_dotenv

from docs_core.ingest.store.blocks_sql_store import resolve_knowledge_base_dir


load_dotenv()


# 获取字符串环境变量并做空白清洗
def get_env_str(key: str, default: str = "") -> str:
    return str(os.getenv(key, default) or "").strip()


# 解析当前 embedding provider 名称
def get_embedding_provider_name() -> str:
    return get_env_str("DOCS_EMBEDDING_PROVIDER", "dashscope").lower() or "dashscope"


# 解析当前 embedding 模型名
def get_embedding_model_name() -> str:
    return get_env_str("DOCS_EMBEDDING_MODEL", "text-embedding-v4") or "text-embedding-v4"


# 解析当前 embedding API Key
def get_embedding_api_key() -> str:
    return get_env_str("DOCS_EMBEDDING_API_KEY")


# 解析当前 embedding API URL
def get_embedding_api_url() -> str:
    return get_env_str("DOCS_EMBEDDING_API_URL", "https://dashscope.aliyuncs.com/compatible-mode/v1")


# 解析当前 vector store provider 名称
def get_vectorstore_provider_name() -> str:
    return get_env_str("DOCS_VECTORSTORE_PROVIDER", "chroma").lower() or "chroma"


# 解析 Chroma 持久化目录
def resolve_chroma_persist_dir(base_path: Path | None = None) -> Path:
    if base_path is not None:
        return Path(base_path).resolve().parent / "chroma"
    root = resolve_knowledge_base_dir() / "vectorstore" / "chroma"
    root.mkdir(parents=True, exist_ok=True)
    return root


__all__ = [
    "get_embedding_api_key",
    "get_embedding_api_url",
    "get_embedding_model_name",
    "get_embedding_provider_name",
    "get_vectorstore_provider_name",
    "resolve_chroma_persist_dir",
]
