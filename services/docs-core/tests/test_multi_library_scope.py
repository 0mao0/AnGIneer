"""多库集合契约：normalize_library_ids + KnowledgeQueryRequest.library_ids。"""
from docs_core.step09_query.protocols.contracts import (
    KnowledgeQueryRequest,
    normalize_library_ids,
)


class TestNormalizeLibraryIds:
    def test_empty_falls_back_to_library_id(self):
        assert normalize_library_ids(None, "libA") == ["libA"]
        assert normalize_library_ids([], "libA") == ["libA"]

    def test_empty_and_empty_id_falls_back_default(self):
        assert normalize_library_ids(None, "") == ["default"]

    def test_dedup_keeps_first_seen_order(self):
        assert normalize_library_ids(["a", "b", "a", "b"], "") == ["a", "b"]

    def test_strips_blank_entries(self):
        assert normalize_library_ids([" a ", "", None, "b"], "") == ["a", "b"]


class TestKnowledgeQueryRequest:
    def test_default_empty_list(self):
        req = KnowledgeQueryRequest(query="q", library_id="libA")
        assert req.library_ids == []

    def test_accepts_multi(self):
        req = KnowledgeQueryRequest(query="q", library_id="a", library_ids=["a", "b"])
        assert req.library_ids == ["a", "b"]


# 铁律 1 守卫（单库池键无 @ 后缀、无 library_id 标签）位于
# tests/test_multi_library_retrieve.py::TestRetrieveMultiLibrary::test_single_library_unchanged_pool_keys，
# 本文件不再重复（评审 Minor-7 去重）。
