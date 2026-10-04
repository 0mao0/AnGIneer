"""ScopeContext 多库集合：library_id 与 library_ids 双向同步。"""
from angineer_core.base_contracts import ScopeContext
from angineer_core.history_store import scope_hash_for


class TestScopeContextLibraryIds:
    def test_legacy_single_construction_unchanged(self):
        scope = ScopeContext(library_id="libA", doc_ids=["d1"])
        assert scope.library_id == "libA"
        assert scope.library_ids == ["libA"]

    def test_multi_sets_primary_from_first(self):
        scope = ScopeContext(library_ids=["libA", "libB"])
        assert scope.library_id == "libA"
        assert scope.library_ids == ["libA", "libB"]

    def test_multi_overrides_conflicting_single(self):
        scope = ScopeContext(library_id="libX", library_ids=["libA", "libB"])
        assert scope.library_id == "libA"

    def test_default(self):
        scope = ScopeContext()
        assert scope.library_ids == ["default"]

    def test_items_are_stripped_and_empty_dropped(self):
        # 质量评审 M1：集合项 strip 去空后统一收敛，library_id 同步取归一后的首项
        scope = ScopeContext(library_id="libX", library_ids=[" libA ", "", "libB"])
        assert scope.library_ids == ["libA", "libB"]
        assert scope.library_id == "libA"


class TestScopeHashForMulti:
    def test_single_string_hash_unchanged(self):
        # 兼容铁律 2：旧调用产出不变（doc_ids 排序后材料串为 "libA|d1|d2"）
        import hashlib
        expected = hashlib.sha1("libA|d1|d2".encode("utf-8")).hexdigest()[:8]
        assert scope_hash_for("libA", ["d2", "d1"]) == expected
        assert scope_hash_for(["libA"], ["d2", "d1"]) == expected

    def test_multi_set_order_insensitive(self):
        assert scope_hash_for(["libB", "libA"], []) == scope_hash_for(["libA", "libB"], [])

    def test_multi_differs_from_single(self):
        assert scope_hash_for(["libA", "libB"], []) != scope_hash_for("libA", [])
