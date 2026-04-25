"""Embedding provider 抽象与实现。"""
import hashlib
import logging
import math
import re
from typing import List, Sequence

import requests

from docs_core.indexing.config import (
    get_embedding_api_key,
    get_embedding_api_url,
    get_embedding_model_name,
    get_embedding_provider_name,
)


logger = logging.getLogger(__name__)
TOKEN_PATTERN = re.compile(r"[A-Za-z0-9_.-]+|[\u4e00-\u9fff]")


class EmbeddingProvider:
    """可替换的文本向量化 provider 基类。"""

    name: str = "base"
    dimension: int = 0

    # 将单条文本编码为向量。
    def embed_text(self, text: str) -> List[float]:
        return self.embed_texts([text])[0]

    # 将多条文本批量编码为向量。
    def embed_texts(self, texts: Sequence[str]) -> List[List[float]]:
        raise NotImplementedError("EmbeddingProvider.embed_texts must be implemented by subclasses.")


# 统一清洗文本，减少空白和大小写差异带来的噪声。
def normalize_embedding_text(text: str) -> str:
    return " ".join((text or "").lower().split()).strip()


# 提取中英文混合文本的基础 token。
def extract_tokens(text: str) -> List[str]:
    return TOKEN_PATTERN.findall(normalize_embedding_text(text))


# 为 CJK 文本补充字符 n-gram，提升短问句与规范术语的相似度稳定性。
def build_cjk_ngrams(text: str, min_n: int = 2, max_n: int = 3) -> List[str]:
    compact = "".join(char for char in normalize_embedding_text(text) if "\u4e00" <= char <= "\u9fff")
    if not compact:
        return []
    grams: List[str] = []
    for n in range(min_n, max_n + 1):
        if len(compact) < n:
            continue
        for index in range(len(compact) - n + 1):
            grams.append(compact[index:index + n])
    return grams


# 构造用于哈希向量化的特征项集合。
def build_embedding_terms(text: str) -> List[str]:
    normalized = normalize_embedding_text(text)
    if not normalized:
        return ["__empty__"]
    return [*extract_tokens(normalized), *build_cjk_ngrams(normalized)]


# 把任意特征项稳定映射到固定维度的向量槽位。
def hash_term(term: str, dimension: int) -> tuple[int, float]:
    digest = hashlib.md5(term.encode("utf-8")).digest()
    bucket = int.from_bytes(digest[:4], "big") % max(1, dimension)
    sign = 1.0 if digest[4] % 2 == 0 else -1.0
    return bucket, sign


# 对向量做 L2 归一化，便于后续使用点积近似余弦相似度。
def normalize_vector(values: List[float]) -> List[float]:
    norm = math.sqrt(sum(value * value for value in values))
    if norm <= 0:
        return values
    return [value / norm for value in values]


class HashEmbeddingProvider(EmbeddingProvider):
    """基于哈希特征的本地 embedding provider。"""

    def __init__(self, dimension: int = 256) -> None:
        self.name = "hash_embedding_v1"
        self.dimension = max(64, int(dimension or 256))

    # 将文本批量编码为固定维度向量。
    def embed_texts(self, texts: Sequence[str]) -> List[List[float]]:
        vectors: List[List[float]] = []
        for text in texts:
            vector = [0.0] * self.dimension
            for term in build_embedding_terms(text):
                bucket, sign = hash_term(term, self.dimension)
                vector[bucket] += sign
            vectors.append(normalize_vector(vector))
        return vectors


class DashScopeEmbeddingProvider(EmbeddingProvider):
    """基于 DashScope OpenAI 兼容接口的 embedding provider。"""

    def __init__(self, model: str, api_key: str, api_url: str, fallback_provider: EmbeddingProvider | None = None) -> None:
        self.name = "dashscope_embedding_v1"
        self.dimension = 0
        self.model = model
        self.api_key = api_key
        self.api_url = api_url.rstrip("/")
        self.fallback_provider = fallback_provider or HashEmbeddingProvider()

    # 判断当前 provider 是否具备可调用的配置。
    def is_configured(self) -> bool:
        return bool(self.model and self.api_key and self.api_url)

    # 通过 DashScope 接口批量请求 embedding。
    def embed_texts(self, texts: Sequence[str]) -> List[List[float]]:
        normalized_texts = [str(text or "").strip() for text in texts]
        if not normalized_texts:
            return []
        if not self.is_configured():
            logger.warning("DOCS_EMBEDDING_PROVIDER=dashscope 但缺少配置，回退到 hash embedding。")
            return self.fallback_provider.embed_texts(normalized_texts)
        try:
            response = requests.post(
                f"{self.api_url}/embeddings",
                headers={
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": self.model,
                    "input": normalized_texts,
                    "encoding_format": "float",
                },
                timeout=60,
            )
            response.raise_for_status()
            payload = response.json()
            data = list(payload.get("data") or [])
            embeddings = [list(item.get("embedding") or []) for item in data]
            if len(embeddings) != len(normalized_texts) or not all(embedding for embedding in embeddings):
                raise ValueError("DashScope embedding 返回结果为空或数量不一致")
            self.dimension = len(embeddings[0])
            return embeddings
        except Exception as exc:
            logger.warning("DashScope embedding 调用失败，回退到 hash embedding: %s", exc)
            return self.fallback_provider.embed_texts(normalized_texts)


# 按环境变量解析默认 embedding provider。
def create_default_embedding_provider() -> EmbeddingProvider:
    provider_name = get_embedding_provider_name()
    if provider_name == "hash":
        return HashEmbeddingProvider()
    if provider_name == "dashscope":
        return DashScopeEmbeddingProvider(
            model=get_embedding_model_name(),
            api_key=get_embedding_api_key(),
            api_url=get_embedding_api_url(),
            fallback_provider=HashEmbeddingProvider(),
        )
    logger.warning("未知 DOCS_EMBEDDING_PROVIDER=%s，回退到 hash embedding。", provider_name)
    return HashEmbeddingProvider()


default_embedding_provider = create_default_embedding_provider()


__all__ = [
    "DashScopeEmbeddingProvider",
    "EmbeddingProvider",
    "HashEmbeddingProvider",
    "build_embedding_terms",
    "create_default_embedding_provider",
    "default_embedding_provider",
    "normalize_embedding_text",
]
