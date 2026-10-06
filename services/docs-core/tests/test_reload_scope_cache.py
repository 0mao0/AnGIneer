def test_reload_scope_cache_refreshes_snapshots(tmp_path, monkeypatch):
    from docs_core.docs_service import DocsService
    ks = DocsService()  # conftest 已隔离 ANGINEER_DATA_ROOT 到 tmp
    ks.create_library("lib-r", "r")
    assert any(l.id == "lib-r" for l in ks.libraries)
    # 绕过 service 直写 meta（模拟迁移器裸改）
    ks.meta_store.delete_library("lib-r")
    assert any(l.id == "lib-r" for l in ks.libraries)  # 内存快照仍是旧的
    ks.reload_scope_cache()
    assert all(l.id != "lib-r" for l in ks.libraries)
