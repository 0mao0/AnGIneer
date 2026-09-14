"""rebuild_document_vectors / rebuild_document_indexes 静默失败收口回归。

生产实踩（2026-09-14）：某文档 209 个 chunk，rebuild_document_vectors 跑完
返回 None、不抛错，Qdrant 里 0 个点——记录全部因空向量被 upsert_records 静默
跳过，调用方统计为成功。修复后应写 ≠ 实写必须 RuntimeError。
"""
import types
from unittest import mock

import pytest

from docs_core.docs_service import DocsService


class _FakeVectorStore:
    def __init__(self, written: int) -> None:
        self._written = written
        self.cleared = []

    def clear_document(self, doc_id: str) -> int:
        self.cleared.append(doc_id)
        return 0

    def delete_records(self, doc_id: str, entity_ids) -> int:  # noqa: ANN001
        return 0

    def upsert_records(self, records) -> int:  # noqa: ANN001
        return self._written


class _FakeCanonicalStore:
    def rebuild_chunk_fts(self, doc_id: str) -> None:
        return None


_RECORDS = [{"record_id": "a"}, {"record_id": "b"}]
_DOC = types.SimpleNamespace(doc_id="d1", blocks=[], chunks=[])


def _service(written: int) -> DocsService:
    svc = object.__new__(DocsService)
    svc.vector_store = _FakeVectorStore(written)
    svc.canonical_store = _FakeCanonicalStore()
    return svc


def test_rebuild_document_vectors_raises_on_write_gap():
    svc = _service(written=0)
    with mock.patch(
        "docs_core.step06_vectors.build_vector_records", return_value=_RECORDS
    ):
        with pytest.raises(RuntimeError, match="向量写入缺口"):
            svc.rebuild_document_vectors("d1", canonical_document=_DOC)


def test_rebuild_document_vectors_returns_written_count():
    svc = _service(written=2)
    with mock.patch(
        "docs_core.step06_vectors.build_vector_records", return_value=_RECORDS
    ):
        assert svc.rebuild_document_vectors("d1", canonical_document=_DOC) == 2


def test_rebuild_document_vectors_empty_records_ok():
    svc = _service(written=0)
    with mock.patch(
        "docs_core.step06_vectors.build_vector_records", return_value=[]
    ):
        assert svc.rebuild_document_vectors("d1", canonical_document=_DOC) == 0


def test_rebuild_document_indexes_raises_on_write_gap():
    svc = _service(written=1)
    with mock.patch(
        "docs_core.step06_vectors.build_vector_records", return_value=_RECORDS
    ):
        with pytest.raises(RuntimeError, match="向量写入缺口"):
            svc.rebuild_document_indexes("d1", _DOC)
