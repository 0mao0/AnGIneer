import pytest
from docs_core import library_registry
from docs_core.kb_migrator import LibraryMigratingError, assert_library_not_migrating


def test_assert_raises_for_migrating(tmp_path):
    library_registry.register_library("lib-g", name="g", group_name="g1")
    library_registry.set_status("lib-g", "migrating")
    with pytest.raises(LibraryMigratingError):
        assert_library_not_migrating("lib-g")
    library_registry.set_status("lib-g", "active")
    assert_library_not_migrating("lib-g")  # 不抛


def test_assert_passes_for_unknown_and_none():
    assert_library_not_migrating(None)
    assert_library_not_migrating("lib-not-registered")


def test_service_write_paths_gate_migrating_library():
    """计划 Step 2：assert 在 Task 6 已建，本用例验证 service 层真正接线（create_parse_task）。"""
    from docs_core.docs_service import get_docs_service
    library_registry.register_library("lib-gate", name="gate", group_name="g1")
    library_registry.set_status("lib-gate", "migrating")
    with pytest.raises(LibraryMigratingError):
        get_docs_service().create_parse_task("t-gate", "lib-gate", "doc-x")
    library_registry.set_status("lib-gate", "active")
    get_docs_service().create_parse_task("t-gate2", "lib-gate", "doc-x")  # 放行
