"""P4-0 批量删库：共享桶保留容器、独立桶删容器、doc_catalog 清行。"""
from __future__ import annotations

import sqlite3
from pathlib import Path
from types import SimpleNamespace

from docs_core import library_registry
from docs_core.library_delete import delete_library_data


class _FakeVectorStore:
    def __init__(self) -> None:
        self.cleared: list[str] = []

    def clear_document(self, doc_id: str, collection=None) -> None:
        self.cleared.append(doc_id)


class _FakeService:
    def __init__(self, meta_db: Path, library_ids: list[str], node_ids: list[str]) -> None:
        self.nodes = [
            SimpleNamespace(id=node_id, library_id=node_id.replace("doc-", "lib-"))
            for node_id in node_ids
        ]
        self.libraries = [SimpleNamespace(id=library_id) for library_id in library_ids]
        self.meta_store = SimpleNamespace(db_path=meta_db)
        self.vector_store = _FakeVectorStore()
        self.reloaded = False
        self._library_ids = set(library_ids)

    def get_library(self, library_id: str):
        return object() if library_id in self._library_ids else None

    def reload_scope_cache(self) -> None:
        self.reloaded = True


def _make_index_db(path: Path, rows: list[tuple[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.executescript(
        """
        CREATE TABLE canonical_documents(doc_id TEXT PRIMARY KEY, library_id TEXT);
        CREATE TABLE doc_blocks(doc_id TEXT, block_id TEXT);
        CREATE TABLE doc_catalog(doc_id TEXT PRIMARY KEY, library_id TEXT, matter_id TEXT);
        """
    )
    for doc_id, library_id in rows:
        conn.execute("INSERT INTO canonical_documents VALUES (?, ?)", (doc_id, library_id))
        conn.execute("INSERT INTO doc_blocks VALUES (?, ?)", (doc_id, doc_id + "-block"))
        conn.execute("INSERT INTO doc_catalog VALUES (?, ?, ?)", (doc_id, library_id, "m-" + library_id))
    conn.commit()
    conn.close()


def _make_meta_db(path: Path, rows: list[tuple[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.executescript(
        """
        CREATE TABLE nodes(id TEXT PRIMARY KEY, library_id TEXT);
        CREATE TABLE tree_node(node_id TEXT PRIMARY KEY, scope_id TEXT);
        CREATE TABLE libraries(id TEXT PRIMARY KEY, name TEXT);
        """
    )
    for doc_id, library_id in rows:
        conn.execute("INSERT INTO nodes VALUES (?, ?)", (doc_id, library_id))
        conn.execute("INSERT INTO tree_node VALUES (?, ?)", (doc_id, library_id))
    for library_id in {row[1] for row in rows}:
        conn.execute("INSERT INTO libraries VALUES (?, ?)", (library_id, library_id))
    conn.commit()
    conn.close()


def test_shared_bucket_keeps_container_and_clears_catalog(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("ANGINEER_DATA_ROOT", str(tmp_path / "data"))
    monkeypatch.setenv("ANGINEER_REGISTRY_DB", str(tmp_path / "registry.sqlite"))
    monkeypatch.setenv("KNOWLEDGE_BASE_DIR", str(tmp_path / "kb"))

    library_registry.register_library(
        "lib-a", name="A", group_name="system",
        sqlite_file="knowledge/groups/shared.sqlite", collection="shared",
    )
    library_registry.register_library(
        "lib-b", name="B", group_name="system",
        sqlite_file="knowledge/groups/shared.sqlite", collection="shared",
    )
    db = tmp_path / "data/knowledge/groups/shared.sqlite"
    _make_index_db(db, [("doc-a", "lib-a"), ("doc-b", "lib-b")])
    meta = tmp_path / "data/knowledge/knowledge_meta.sqlite"
    _make_meta_db(meta, [("doc-a", "lib-a"), ("doc-b", "lib-b")])
    pr = tmp_path / "data/knowledge/parse_records.sqlite"
    pr.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(pr) as conn:
        conn.execute("CREATE TABLE parse_records (doc_id TEXT, library_id TEXT, status TEXT)")
        conn.executemany("INSERT INTO parse_records VALUES (?,?,?)",
                         [("doc-a", "lib-a", "completed"), ("doc-b", "lib-b", "completed")])

    lib_root = tmp_path / "data/knowledge/libraries/lib-a/documents/doc-a/source"
    lib_root.mkdir(parents=True)
    (lib_root / "x.pdf").write_bytes(b"x")

    service = _FakeService(meta, ["lib-a", "lib-b"], ["doc-a", "doc-b"])
    result = delete_library_data(service, "lib-a")

    assert result == {"docs": 1, "container_deleted": False}
    assert db.exists()  # 共享容器保留
    assert library_registry.get_library("lib-a").status == "retired"
    assert library_registry.get_library("lib-b").status == "active"

    conn = sqlite3.connect(db)
    try:
        assert conn.execute("SELECT doc_id FROM canonical_documents").fetchall() == [("doc-b",)]
        assert conn.execute("SELECT doc_id FROM doc_blocks").fetchall() == [("doc-b",)]
        assert conn.execute("SELECT doc_id FROM doc_catalog").fetchall() == [("doc-b",)]
    finally:
        conn.close()
    assert not (tmp_path / "data/knowledge/libraries/lib-a").exists()
    assert (tmp_path / "data/knowledge/libraries/lib-b").parent.exists()
    assert service.vector_store.cleared == ["doc-a"]
    assert service.reloaded is True
    with sqlite3.connect(pr) as conn:
        assert conn.execute("SELECT doc_id FROM parse_records ORDER BY doc_id").fetchall() == [("doc-b",)]


def test_independent_bucket_deletes_container(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("ANGINEER_DATA_ROOT", str(tmp_path / "data"))
    monkeypatch.setenv("ANGINEER_REGISTRY_DB", str(tmp_path / "registry.sqlite"))
    monkeypatch.setenv("KNOWLEDGE_BASE_DIR", str(tmp_path / "kb"))

    library_registry.register_library(
        "lib-solo", name="Solo", group_name="system",
        sqlite_file="knowledge/groups/solo.sqlite", collection="solo",
    )
    db = tmp_path / "data/knowledge/groups/solo.sqlite"
    _make_index_db(db, [("doc-s", "lib-solo")])
    meta = tmp_path / "data/knowledge/knowledge_meta.sqlite"
    _make_meta_db(meta, [("doc-s", "lib-solo")])

    service = _FakeService(meta, ["lib-solo"], ["doc-s"])
    result = delete_library_data(service, "lib-solo")

    assert result == {"docs": 1, "container_deleted": True}
    assert not db.exists()
    assert library_registry.get_library("lib-solo").status == "retired"


def test_delete_retries_when_meta_snapshot_missing(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("ANGINEER_DATA_ROOT", str(tmp_path / "data"))
    monkeypatch.setenv("ANGINEER_REGISTRY_DB", str(tmp_path / "registry.sqlite"))
    monkeypatch.setenv("KNOWLEDGE_BASE_DIR", str(tmp_path / "kb"))
    library_registry.register_library(
        "lib-orphan", name="Orphan", group_name="system",
        sqlite_file="knowledge/libraries/lib-orphan/index.sqlite", collection="lib-orphan",
        status=library_registry.STATUS_DELETING,
    )
    meta = tmp_path / "data/knowledge/knowledge_meta.sqlite"
    _make_meta_db(meta, [("doc-other", "lib-other")])
    service = _FakeService(meta, [], [])
    result = delete_library_data(service, "lib-orphan")
    assert result["docs"] == 0
    assert library_registry.get_library("lib-orphan").status == "retired"


def test_independent_bucket_kept_when_retired_row_references_it(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("ANGINEER_DATA_ROOT", str(tmp_path / "data"))
    monkeypatch.setenv("ANGINEER_REGISTRY_DB", str(tmp_path / "registry.sqlite"))
    monkeypatch.setenv("KNOWLEDGE_BASE_DIR", str(tmp_path / "kb"))

    library_registry.register_library(
        "lib-solo", name="Solo", group_name="system",
        sqlite_file="knowledge/groups/solo.sqlite", collection="solo",
    )
    library_registry.register_library(
        "lib-old", name="Old", group_name="system",
        sqlite_file="knowledge/groups/solo.sqlite", collection="solo",
        status=library_registry.STATUS_RETIRED,
    )
    db = tmp_path / "data/knowledge/groups/solo.sqlite"
    _make_index_db(db, [("doc-s", "lib-solo")])
    meta = tmp_path / "data/knowledge/knowledge_meta.sqlite"
    _make_meta_db(meta, [("doc-s", "lib-solo")])

    service = _FakeService(meta, ["lib-solo"], ["doc-s"])
    result = delete_library_data(service, "lib-solo")

    assert result == {"docs": 1, "container_deleted": False}
    assert db.exists()  # retired 行仍引用，容器不删


def test_builtin_group_bucket_not_deleted(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("ANGINEER_DATA_ROOT", str(tmp_path / "data"))
    monkeypatch.setenv("ANGINEER_REGISTRY_DB", str(tmp_path / "registry.sqlite"))
    monkeypatch.setenv("KNOWLEDGE_BASE_DIR", str(tmp_path / "kb"))

    library_registry.register_library(
        "lib-sys", name="Sys", group_name="system",
        sqlite_file="knowledge/groups/system.sqlite", collection="system",
    )
    db = tmp_path / "data/knowledge/groups/system.sqlite"
    _make_index_db(db, [("doc-s", "lib-sys")])
    meta = tmp_path / "data/knowledge/knowledge_meta.sqlite"
    _make_meta_db(meta, [("doc-s", "lib-sys")])

    service = _FakeService(meta, ["lib-sys"], ["doc-s"])
    result = delete_library_data(service, "lib-sys")

    assert result == {"docs": 1, "container_deleted": False}
    assert db.exists()  # 内置组桶不删

