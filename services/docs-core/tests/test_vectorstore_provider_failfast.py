"""向量 provider fail-fast：漏配/未知 provider 不再静默回退空库（素材体检向量假警报的回归锁）。"""

from types import SimpleNamespace

import pytest

from docs_core.docs_service import DocsService
from docs_core.step06_vectors.config import get_vectorstore_provider_name


def test_unset_provider_raises(monkeypatch) -> None:
    monkeypatch.delenv("DOCS_VECTORSTORE_PROVIDER", raising=False)
    with pytest.raises(RuntimeError, match="未配置"):
        get_vectorstore_provider_name()


def test_provider_case_insensitive_and_stripped(monkeypatch) -> None:
    monkeypatch.setenv("DOCS_VECTORSTORE_PROVIDER", " Qdrant ")
    assert get_vectorstore_provider_name() == "qdrant"


def test_unknown_provider_factory_raises(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("DOCS_VECTORSTORE_PROVIDER", "qdrant-typo")
    stub = SimpleNamespace(index_db_path=tmp_path / "index.sqlite")
    with pytest.raises(ValueError, match="未知向量 provider"):
        DocsService._create_vector_store(stub)


def test_chroma_failure_no_silent_sqlite(monkeypatch) -> None:
    monkeypatch.setenv("DOCS_VECTORSTORE_PROVIDER", "chroma")

    def _boom() -> None:
        raise RuntimeError("chroma 挂了")

    import docs_core.step06_vectors.chroma_vector_store as chroma_mod

    monkeypatch.setattr(chroma_mod.ChromaVectorStore, "__init__", lambda self: _boom())
    stub = SimpleNamespace(index_db_path="index.sqlite")
    with pytest.raises(RuntimeError, match="chroma 挂了"):
        DocsService._create_vector_store(stub)
