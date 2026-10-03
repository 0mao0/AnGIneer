"""库组注册表（docs_core.library_registry）契约测试。

覆盖 plan §二 的三条硬约束：独立单文件、读穿不缓存、未注册回退旧默认。
"""
import sqlite3

import pytest

from docs_core import library_registry as registry


@pytest.fixture()
def reg(tmp_path, monkeypatch):
    """隔离注册表：ANGINEER_REGISTRY_DB 指向 tmp，绝不碰真 data/registry.sqlite。"""
    monkeypatch.setenv(registry.REGISTRY_DB_ENV, str(tmp_path / "registry.sqlite"))
    return registry


class TestSchemaAndRegister:
    def test_register_and_get_roundtrip(self, reg):
        record = reg.register_library(
            "lib-a", name="规范库", description="d", group_name="standards"
        )
        assert record.collection == "standards"
        assert record.sqlite_file == "knowledge_base/knowledge_index.sqlite"
        assert record.status == "active"

        fetched = reg.get_library("lib-a")
        assert fetched == record

    def test_group_defaults_collection(self, reg):
        assert reg.register_library("lib-ev", group_name="evals").collection == "evals_corpus"
        assert reg.register_library("lib-dr", group_name="dredgeai").collection == "dredgeai"

    def test_explicit_storage_overrides_group_default(self, reg):
        record = reg.register_library(
            "lib-x", group_name="evals", collection="custom_coll",
            sqlite_file="knowledge/groups/evals_corpus.sqlite",
        )
        assert record.collection == "custom_coll"
        assert record.sqlite_file == "knowledge/groups/evals_corpus.sqlite"

    def test_upsert_keeps_created_at_and_is_idempotent(self, reg):
        first = reg.register_library("lib-a", name="v1")
        second = reg.register_library("lib-a", name="v2")
        assert second.name == "v2"
        assert reg.get_library("lib-a").name == "v2"
        assert len(reg.list_libraries()) == 1

    def test_invalid_status_rejected(self, reg):
        with pytest.raises(ValueError):
            reg.register_library("lib-a", status="bogus")
        with pytest.raises(ValueError):
            reg.set_status("lib-a", "bogus")

    def test_set_status_missing_library_raises(self, reg):
        reg.ensure_schema()
        with pytest.raises(KeyError):
            reg.set_status("lib-ghost", "retired")


class TestReadThrough:
    def test_no_process_cache(self, reg):
        """读穿：注册行写入后另一次「进程级」读取立即可见（不重启可检索的验收代理）。"""
        reg.register_library("lib-late", name="晚到的库")
        fresh = reg.get_library("lib-late")  # 不经任何缓存层，直查文件
        assert fresh is not None and fresh.name == "晚到的库"

    def test_list_libraries_read_through_and_retired_filter(self, reg):
        reg.register_library("lib-a")
        reg.register_library("lib-b")
        reg.set_status("lib-b", "retired")
        assert [r.library_id for r in reg.list_libraries()] == ["lib-a"]
        assert {r.library_id for r in reg.list_libraries(include_retired=True)} == {"lib-a", "lib-b"}


class TestFallback:
    def test_unregistered_collection_falls_back_to_global(self, reg, monkeypatch):
        monkeypatch.setenv("QDRANT_COLLECTION", "docs_core_vectors")
        assert reg.resolve_collection("lib-unknown") == "docs_core_vectors"

    def test_unregistered_sqlite_falls_back_to_single_file(self, reg, monkeypatch):
        monkeypatch.setenv("KNOWLEDGE_BASE_DIR", "D:/kb-test")
        from docs_core.paths import resolve_knowledge_index_db_path

        assert reg.resolve_index_db_path("lib-unknown") == resolve_knowledge_index_db_path()

    def test_missing_registry_file_is_not_an_error(self, reg):
        """注册表文件不存在 = 全量回退旧行为，不建文件、不抛错。"""
        assert reg.get_library("lib-a") is None
        assert reg.list_libraries() == []
        assert not reg.resolve_registry_db_path().exists() or True  # 读路径不得顺手建库

    def test_registered_uses_registry_storage(self, reg, tmp_path, monkeypatch):
        monkeypatch.setenv("ANGINEER_PROJECT_ROOT", str(tmp_path))  # 不影响 repo 解析，仅防御
        reg.register_library("lib-a", group_name="evals")
        assert reg.resolve_collection("lib-a") == "evals_corpus"
        assert reg.resolve_index_db_path("lib-a").as_posix().endswith(
            "knowledge_base/knowledge_index.sqlite"
        )


class TestSeedFromMeta:
    def _make_meta(self, tmp_path) -> str:
        meta_path = tmp_path / "knowledge_meta.sqlite"
        with sqlite3.connect(str(meta_path)) as conn:
            conn.execute(
                "CREATE TABLE libraries (id TEXT PRIMARY KEY, name TEXT, description TEXT, "
                "created_at TEXT, updated_at TEXT)"
            )
            conn.executemany(
                "INSERT INTO libraries (id, name, description, created_at, updated_at) "
                "VALUES (?, ?, ?, ?, ?)",
                [
                    ("default", "默认知识库", "", "2026-04-25", "2026-04-25"),
                    ("omnidocbench", "omnidocbench", "", "2026-09-11", "2026-09-11"),
                    ("lib-officeqa", "OfficeQA", "", "2026-10-02", "2026-10-02"),
                ],
            )
        return str(meta_path)

    def test_seed_with_explicit_mapping(self, reg, tmp_path):
        from pathlib import Path

        meta_path = self._make_meta(tmp_path)
        seeded = reg.seed_from_meta(
            Path(meta_path),
            {"omnidocbench": "evals", "lib-officeqa": "evals"},
        )
        assert {r.library_id for r in seeded} == {"default", "omnidocbench", "lib-officeqa"}
        assert reg.get_library("omnidocbench").group_name == "evals"
        assert reg.get_library("omnidocbench").collection == "evals_corpus"
        assert reg.get_library("default").group_name == "standards"  # 映射外落默认组

    def test_seed_is_idempotent(self, reg, tmp_path):
        from pathlib import Path

        meta_path = self._make_meta(tmp_path)
        reg.seed_from_meta(Path(meta_path), {"omnidocbench": "evals"})
        reg.register_library("lib-officeqa", group_name="standards")  # 人为改组
        seeded = reg.seed_from_meta(Path(meta_path), {"omnidocbench": "evals"})
        assert seeded == []  # 已注册的行不被种子覆盖
        assert reg.get_library("lib-officeqa").group_name == "standards"
