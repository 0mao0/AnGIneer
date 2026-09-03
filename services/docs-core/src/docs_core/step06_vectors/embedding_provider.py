"""Embedding provider 抽象与实现。

多端点降级链（dense 语义通道）：
  端点数组（EMBEDDING_CONFIGS，数组顺序=优先级，第一项为默认）-> hash embedding 兜底
未配置 EMBEDDING_CONFIGS 时回退 hash（仅无语义本地）；DOCS_EMBEDDING_PROVIDER=hash
可直接强制纯本地模式。
"""
import hashlib
import logging
import math
import os
import re
from typing import List, Optional, Sequence

import requests

from docs_core.step06_vectors.config import (
    get_embedding_provider_name,
    load_embedding_entries,
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


# 为 CJK 文本补充字符 n-gram，提升短句与规范术语的相似度稳定性。
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


# 把任意特征项稳定映射到固定维度的向量桶位。
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
    """基于哈希特征的本地 embedding provider（最后兜底，无语义）。"""

    def __init__(self, dimension: int = 256) -> None:
        self.name = "hash_embedding_v1"
        # 允许显式对齐到小于 64 的既有集合维度（历史集合可能为低维）。
        self.dimension = max(1, int(dimension or 256))
        self.runtime_flags: List[str] = []

    # 将文本批量编码为固定维度向量。
    def embed_texts(self, texts: Sequence[str]) -> List[List[float]]:
        self.runtime_flags = ["embedding_hash_fallback"]
        vectors: List[List[float]] = []
        for text in texts:
            vector = [0.0] * self.dimension
            for term in build_embedding_terms(text):
                bucket, sign = hash_term(term, self.dimension)
                vector[bucket] += sign
            vectors.append(normalize_vector(vector))
        return vectors


def _build_openai_compat_provider(
    *,
    model: str,
    api_key: str,
    api_url: str,
) -> Optional["DashScopeEmbeddingProvider"]:
    """按配置构造 OpenAI 兼容 embedding provider；配置不完整时返回 None（跳过该档）。"""
    if not (model and api_key and api_url):
        return None
    return DashScopeEmbeddingProvider(
        model=model,
        api_key=api_key,
        api_url=api_url,
        fallback_provider=None,
    )


class DashScopeEmbeddingProvider(EmbeddingProvider):
    """基于 OpenAI 兼容接口的 embedding provider（dashscope / bge-m3 等均走它）。"""

    def __init__(self, model: str, api_key: str, api_url: str, fallback_provider: Optional[EmbeddingProvider] = None, strict_fallback: Optional[bool] = None) -> None:
        self.name = "dashscope_embedding_v1"
        self.dimension = 0
        self.model = model
        self.api_key = api_key
        self.api_url = api_url.rstrip("/")
        self.fallback_provider = fallback_provider
        self.runtime_flags: List[str] = []
        from docs_core.step06_vectors.config import get_embedding_strict_fallback
        self._strict_fallback = get_embedding_strict_fallback() if strict_fallback is None else strict_fallback

    # 判断当前 provider 是否具备可调用的配置。
    def is_configured(self) -> bool:
        return bool(self.model and self.api_key and self.api_url)

    # 通过 OpenAI 兼容接口批量请求 embedding。
    def embed_texts(self, texts: Sequence[str]) -> List[List[float]]:
        normalized_texts = [str(text or "").strip() for text in texts]
        self.runtime_flags = []
        if not normalized_texts:
            return []
        if not self.is_configured():
            return self._degrade(normalized_texts, "EMBEDDING_CONFIGS 端点配置缺失")
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
                raise ValueError("embedding 返回结果为空或数量不一致")
            self.dimension = len(embeddings[0])
            return embeddings
        except Exception as exc:
            return self._degrade(normalized_texts, str(exc))

    # 本档失败：严格模式直接抛错；否则交给下一档（fallback_provider）并传播其降级标记。
    def _degrade(self, texts: List[str], reason: str) -> List[List[float]]:
        if self._strict_fallback:
            raise RuntimeError(f"embedding 调用失败且启用严格模式，禁止降级: {reason}")
        if self.fallback_provider is None:
            raise RuntimeError(f"embedding 调用失败且无兜底档: {reason}")
        logger.warning("embedding 调用失败，降级到下一档: %s", reason)
        embeddings = self.fallback_provider.embed_texts(texts)
        self.runtime_flags = list(getattr(self.fallback_provider, "runtime_flags", []) or [])
        if embeddings:
            self.dimension = len(embeddings[0])
        return embeddings


class ChainedEmbeddingProvider(EmbeddingProvider):
    """多 provider 自动降级链：按顺序尝试，全部失败抛错；name 沿用首档保持兼容。"""

    def __init__(self, providers: Sequence[Optional[EmbeddingProvider]], expected_dimension: int = 0, strict_fallback: bool = False) -> None:
        self.providers = [provider for provider in providers if provider is not None]
        self.name = self.providers[0].name if self.providers else "empty_embedding_v1"
        self.model = str(getattr(self.providers[0], "model", "") or "") if self.providers else ""
        self.dimension = 0
        self.expected_dimension = max(0, int(expected_dimension or 0))
        self._strict_fallback = strict_fallback
        self.runtime_flags: List[str] = []

    def embed_texts(self, texts: Sequence[str]) -> List[List[float]]:
        normalized = [str(text or "").strip() for text in texts]
        self.runtime_flags = []
        if not normalized:
            return []
        last_error: Optional[Exception] = None
        for index, provider in enumerate(self.providers):
            if self._strict_fallback and index > 0:
                raise RuntimeError(f"启用严格模式，仅允许首档 embedding provider: {last_error}")
            try:
                embeddings = provider.embed_texts(normalized)
            except Exception as exc:  # noqa: BLE001
                last_error = exc
                logger.warning("embedding 第 %d 档失败，继续降级: %s", index + 1, exc)
                continue
            if not embeddings:
                last_error = RuntimeError("embedding 返回空")
                logger.warning("embedding 第 %d 档返回空，继续降级", index + 1)
                continue
            dimension = len(embeddings[0])
            if self.expected_dimension and dimension != self.expected_dimension:
                last_error = RuntimeError(f"embedding 维度 {dimension} 与向量库 {self.expected_dimension} 不一致")
                logger.warning("embedding 第 %d 档维度不匹配，继续降级: %s", index + 1, last_error)
                continue
            self.dimension = dimension
            self.runtime_flags = list(getattr(provider, "runtime_flags", []) or [])
            return embeddings
        raise RuntimeError(f"所有 embedding provider 均失败: {last_error}") from last_error


# 检测已有向量库的维度，用于 fallback 时对齐。
def _detect_existing_vector_dimension() -> int:
    try:
        from docs_core.step06_vectors import get_vectorstore_provider_name
        from docs_core.step06_vectors.chroma_vector_store import ChromaVectorStore
        from docs_core.step06_vectors.sqlite_vector_store import SQLiteVectorStore

        if get_vectorstore_provider_name() == "sqlite":
            store = SQLiteVectorStore()
        else:
            store = ChromaVectorStore()
        return store.get_existing_dimension()
    except Exception:
        return 0


# 按 EMBEDDING_CONFIGS 解析默认 embedding provider（多端点降级链）。
# DOCS_EMBEDDING_PROVIDER=hash 时直接返回纯本地 hash（无语义模式）；
# 否则按 EMBEDDING_CONFIGS 数组顺序构造在线端点，链尾自动补 hash 档兜底。
def create_default_embedding_provider() -> EmbeddingProvider:
    from docs_core.step06_vectors.config import get_embedding_strict_fallback

    provider_name = get_embedding_provider_name()
    existing_dim = _detect_existing_vector_dimension()
    hash_provider = HashEmbeddingProvider(dimension=existing_dim if existing_dim > 0 else 256)
    if provider_name == "hash":
        return hash_provider
    entries = load_embedding_entries()
    if not entries:
        logger.warning("未配置 EMBEDDING_CONFIGS，回退到 hash embedding。")
        return hash_provider
    tiers: List[Optional[EmbeddingProvider]] = []
    for idx, entry in enumerate(entries):
        provider = _build_openai_compat_provider(
            model=entry.get("model", ""),
            api_key=entry.get("api_key", ""),
            api_url=entry.get("api_url", ""),
        )
        if provider is None:
            logger.warning("embedding 第 %d 档配置不完整，跳过: %s", idx + 1, entry.get("name", ""))
            continue
        tiers.append(provider)
    tiers.append(hash_provider)
    return ChainedEmbeddingProvider(
        tiers,
        expected_dimension=existing_dim,
        strict_fallback=get_embedding_strict_fallback(),
    )


default_embedding_provider = create_default_embedding_provider()


__all__ = [
    "ChainedEmbeddingProvider",
    "DashScopeEmbeddingProvider",
    "EmbeddingProvider",
    "HashEmbeddingProvider",
    "build_embedding_terms",
    "create_default_embedding_provider",
    "default_embedding_provider",
    "normalize_embedding_text",
]
