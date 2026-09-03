"""索引层配置解析"""
import json
import os
from typing import Dict, List

from dotenv import load_dotenv


load_dotenv()


# 获取字符串环境变量并做空白清洗
def get_env_str(key: str, default: str = "") -> str:
    return str(os.getenv(key, default) or "").strip()


# 解析当前 embedding provider 名称
def get_embedding_provider_name() -> str:
    return get_env_str("DOCS_EMBEDDING_PROVIDER", "dashscope").lower() or "dashscope"


# 解析当前 vector store provider 名称
def get_vectorstore_provider_name() -> str:
    return get_env_str("DOCS_VECTORSTORE_PROVIDER", "chroma").lower() or "chroma"


# 解析 embedding strict fallback 模式
def get_embedding_strict_fallback() -> bool:
    return os.getenv("DOCS_EMBEDDING_STRICT_FALLBACK", "false").lower() in ("true", "1", "yes", "on")


# 解析 hash fallback 时的 dense 分数降权系数
_DEFAULT_HASH_PENALTY = 0.35

def get_embedding_hash_penalty() -> float:
    try:
        return max(0.0, min(1.0, float(os.getenv("DOCS_EMBEDDING_HASH_PENALTY", str(_DEFAULT_HASH_PENALTY)))))
    except (ValueError, TypeError):
        return _DEFAULT_HASH_PENALTY


# 解析 embedding 端点数组：EMBEDDING_CONFIGS (JSON, 数组顺序=优先级, 第一项为默认)。
# 未配置时返回空数组（由调用方回退 hash 并告警）。
def load_embedding_entries() -> List[Dict[str, str]]:
    raw = get_env_str("EMBEDDING_CONFIGS")
    if not raw:
        return []
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return []
    if not isinstance(data, list):
        return []
    entries: List[Dict[str, str]] = []
    for idx, item in enumerate(data):
        if not isinstance(item, dict):
            continue
        model = str(item.get("model") or "").strip()
        api_key = str(item.get("api_key") or item.get("key") or "").strip()
        api_url = str(item.get("api_url") or item.get("url") or "").strip()
        if not (model and api_key and api_url):
            continue
        entries.append({
            "name": str(item.get("name") or f"endpoint-{idx + 1}"),
            "model": model,
            "api_key": api_key,
            "api_url": api_url,
        })
    return entries


__all__ = [
    "get_embedding_hash_penalty",
    "get_embedding_provider_name",
    "get_embedding_strict_fallback",
    "get_vectorstore_provider_name",
    "load_embedding_entries",
]
