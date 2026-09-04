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


# 向量索引分批嵌入的并发度（默认 1=串行）。
# 实测 DGX qwen3-embedding 对并发请求排队执行：双并发每对 2.9~5.6s，反而慢于串行
# 两批 ~3.3s，故默认串行；仅当端点真正并行（如多 worker 的本地 TEI）时才调大。
def get_embedding_batch_concurrency() -> int:
    try:
        return max(1, int(get_env_str("DOCS_EMBEDDING_BATCH_CONCURRENCY", "1")))
    except (ValueError, TypeError):
        return 1


# 向量索引单批嵌入文本数（默认 32）。
# 实测 qwen3-embedding 批内亚线性扩展：16 条 103ms/条 → 64 条 59ms/条，
# 调大批次比并发更能稳定提速；DGX 端点建议 64。本地 TEI 类服务有 payload
# 上限（历史上整篇一次提交触发 413），用 TEI 时保持 ≤32。
def get_embedding_batch_size() -> int:
    try:
        return max(1, int(get_env_str("DOCS_EMBEDDING_BATCH_SIZE", "32")))
    except (ValueError, TypeError):
        return 32


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
    "get_embedding_batch_concurrency",
    "get_embedding_batch_size",
    "get_embedding_hash_penalty",
    "get_embedding_provider_name",
    "get_embedding_strict_fallback",
    "get_vectorstore_provider_name",
    "load_embedding_entries",
]
