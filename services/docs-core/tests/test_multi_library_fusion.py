"""多库融合：池键基名权重 / 跨库 key 隔离 / prefer 不再砍 20。"""
from docs_core.step09_query.protocols.contracts import RetrievedItem
from docs_core.step09_query.retrieval.hybrid_retriever import (
    build_candidate_key,
    fuse_candidates,
    prefer_non_toc_candidates,
)


def _item(doc_id: str, target_id: str, score: float, library_id: str = "") -> RetrievedItem:
    metadata = {"citation_target_id": target_id}
    if library_id:
        metadata["library_id"] = library_id
    return RetrievedItem(
        item_id=f"{doc_id}:c1", entity_type="content", doc_id=doc_id,
        title="t", text="x", score=score,
        citation_target_id=target_id, retrieval_policy="dense", metadata=metadata,
    )


class TestCandidateKeyLibraryScope:
    def test_same_target_different_libraries_distinct_keys(self):
        a = _item("d1", "T1", 1.0, library_id="libA")
        b = _item("d2", "T1", 1.0, library_id="libB")
        assert build_candidate_key(a) != build_candidate_key(b)

    def test_no_library_tag_key_unchanged(self):
        item = _item("d1", "T1", 1.0)
        assert build_candidate_key(item) == "target:T1"


class TestFusePoolKeyBaseKind:
    def test_at_suffixed_pool_uses_dense_weight_and_hash_guard(self):
        # dense@libA 池 + embedding_fallback 标记 → 权重应降为 _HASH_DENSE_FUSION_WEIGHT
        items = [_item("d1", f"T{i}", 1.0, library_id="libA") for i in range(3)]
        for it in items:
            it.metadata["embedding_fallback"] = True
        _, debug = fuse_candidates({"dense@libA": items}, task_type="content_qa", top_k=10)
        assert debug["sources"]["dense@libA"]["weight"] == 0.05


class TestPreferNonTocCap:
    def test_default_cap_keeps_20_for_legacy_callers(self):
        items = [_item("d1", f"T{i}", 1.0) for i in range(40)]
        out = prefer_non_toc_candidates(items, task_type="content_qa", top_k=40)
        assert len(out) == 20  # 铁律 1：top_k>20 的单库调用方行为不变

    def test_cap_none_allows_full_pool(self):
        items = [_item("d1", f"T{i}", 1.0) for i in range(40)]
        out = prefer_non_toc_candidates(items, task_type="content_qa", top_k=40, cap=None)
        assert len(out) == 40
