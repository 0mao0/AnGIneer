"""P2-2 apply_import：落位、doc_catalog、图谱合并、冲突与布局闸。"""
import hashlib
import io
import json
import os
import sqlite3
import sys
import tempfile
import unittest
import zipfile
import gc
from contextlib import closing
from pathlib import Path
from unittest import mock

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../../services/docs-core/src")))

from docs_core import corpus_import_apply, library_registry  # noqa: E402
from docs_core.corpus_package import BundleError, apply_import, checkpoint_sqlite  # noqa: E402
from docs_core.step05_sqlite_fts.store.blocks_sql_store import KnowledgeMetaStore  # noqa: E402
from docs_core.step07_graph.graph_store import GraphStore  # noqa: E402


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _build_library_package(
    tmp: Path,
    *,
    lib_id: str = "lib-x",
    source_root: str = "knowledge/libraries/lib-x",
    group_name: str = "system",
    with_vectors: bool = False,
    dangling: bool = False,
) -> Path:
    index = tmp / "index.sqlite"
    conn = sqlite3.connect(index)
    conn.executescript(
        """
        CREATE TABLE canonical_documents(doc_id TEXT PRIMARY KEY, library_id TEXT, title TEXT);
        CREATE TABLE canonical_chunks(chunk_id TEXT PRIMARY KEY, doc_id TEXT, text_clean TEXT);
        CREATE TABLE doc_catalog(doc_id TEXT PRIMARY KEY, library_id TEXT, matter_id TEXT);
        """
    )
    conn.execute("INSERT INTO canonical_documents VALUES ('d1',?, 'X')", (lib_id,))
    conn.execute("INSERT INTO canonical_chunks VALUES ('c1','d1','hello')")
    conn.execute("INSERT INTO doc_catalog VALUES ('d1',?, 'm1')", (lib_id,))
    conn.commit()
    conn.close()

    graph = tmp / "graph.sqlite"
    GraphStore(str(graph)).close()
    g = sqlite3.connect(graph)
    g.execute(
        "INSERT INTO graph_entities(entity_id,name,layer,library_id,created_at,updated_at) "
        "VALUES ('e1','E','concept',?,'t','t')",
        (lib_id,),
    )
    g.execute(
        "INSERT INTO graph_relations(relation_id,source_id,target_id,relation_type,library_id,doc_id,"
        "created_at,updated_at) VALUES ('r1','e1','e1','requires',?,'d1','t','t')",
        (lib_id,),
    )
    if dangling:
        g.execute("PRAGMA foreign_keys=OFF")
        g.execute(
            "INSERT INTO graph_relations(relation_id,source_id,target_id,relation_type,library_id,doc_id,"
            "created_at,updated_at) VALUES ('rd','missing-e','e1','requires',?,'d1','t','t')",
            (lib_id,),
        )
    g.commit()
    g.close()
    checkpoint_sqlite(graph)

    meta_rows = {
        "nodes": [{
            "id": "d1", "title": "X", "type": "document", "visible": 1, "library_id": lib_id,
            "file_path": f"{source_root}/documents/d1/source/a.txt",
            "status": "parsed", "created_at": "t", "updated_at": "t",
        }],
        "tree_nodes": [{"node_id": "d1", "scope_id": lib_id, "title": "X",
                        "tree_type": "knowledge_doc"}],
        "libraries": [{"id": lib_id, "name": "X", "created_at": "t", "updated_at": "t"}],
    }
    reg_rows = {
        "libraries": [{
            "library_id": lib_id, "name": "X", "description": "",
            "group_name": group_name, "sqlite_file": "",
            "collection": lib_id, "status": "active",
        }],
        "groups": [],
    }
    counts = {
        "docs": 1, "chunks": 1, "vectors": 3 if with_vectors else 0,
        "graph_relations": 2 if dangling else 1,
        "graph_tables": {"graph_entities": 1, "graph_relations": 2 if dangling else 1},
    }
    files_manifest = {}
    inner = io.BytesIO()
    with zipfile.ZipFile(inner, "w", zipfile.ZIP_STORED) as z:
        def add(arc: str, data: bytes) -> None:
            z.writestr(zipfile.ZipInfo(arc), data)
            files_manifest[arc] = _sha(data)

        add("registry/rows.json", json.dumps(reg_rows).encode())
        add("meta/rows.json", json.dumps(meta_rows).encode())
        add("index/index.sqlite", index.read_bytes())
        add("graph/graph.sqlite", graph.read_bytes())
        add(f"files/{source_root}/documents/d1/source/a.txt", b"abc")
        if with_vectors:
            add("qdrant/vectors.snapshot", b"SNAP")
        manifest = {
            "kind": "library", "schema_version": 2, "library_id": lib_id, "name": "X",
            "group_name": group_name, "embed_model": "m", "page_base": 0,
            "counts": counts, "files": files_manifest, "warnings": [],
        }
        z.writestr(zipfile.ZipInfo("manifest.json"), json.dumps(manifest))
    inner_bytes = inner.getvalue()

    outer = tmp / "pkg.zip"
    with zipfile.ZipFile(outer, "w", zipfile.ZIP_STORED) as z:
        z.writestr(zipfile.ZipInfo(f"libraries/{lib_id}.zip"), inner_bytes)
        oman = {
            "kind": "bundle", "schema_version": 2, "embed_model": "m", "page_base": 0,
            "libraries": [{
                "library_id": lib_id, "name": "X", "group_name": group_name,
                "entry": f"libraries/{lib_id}.zip", "sha256": _sha(inner_bytes),
                "bytes": len(inner_bytes), "counts": counts,
            }],
            "files": {f"libraries/{lib_id}.zip": _sha(inner_bytes)},
        }
        z.writestr(zipfile.ZipInfo("manifest.json"), json.dumps(oman))
    return outer


class ApplyImportTests(unittest.TestCase):
    def setUp(self):
        self._td = tempfile.TemporaryDirectory()
        self.addCleanup(self._td.cleanup)
        self.tmp = Path(self._td.name)
        self.data = self.tmp / "data"
        self.data.mkdir()
        os.environ["ANGINEER_DATA_ROOT"] = str(self.data)
        os.environ["ANGINEER_REGISTRY_DB"] = str(self.data / "registry.sqlite")
        os.environ["EMBEDDING_CONFIGS"] = json.dumps([{"model": "m"}])
        self.addCleanup(lambda: os.environ.pop("ANGINEER_DATA_ROOT", None))
        self.addCleanup(lambda: os.environ.pop("ANGINEER_REGISTRY_DB", None))
        self.addCleanup(lambda: os.environ.pop("EMBEDDING_CONFIGS", None))
        library_registry.ensure_schema(self.data / "registry.sqlite")
        KnowledgeMetaStore(self.data / "knowledge/knowledge_meta.sqlite").init_schema()
        self.addCleanup(gc.collect)

    def test_apply_writes_all_parts(self):
        pkg = _build_library_package(self.tmp)
        plan = apply_import(str(pkg), data_root=self.data, group_name="system",
                            apply=False, with_vectors=False)
        self.assertEqual(plan["mode"], "dry-run")
        library_root = self.data / "knowledge/libraries/lib-x"
        self.assertFalse(library_root.exists())

        result = apply_import(str(pkg), data_root=self.data, group_name="system",
                              apply=True, with_vectors=False)
        self.assertEqual(result["mode"], "applied")
        self.assertTrue((library_root / "index.sqlite").exists())
        self.assertTrue((library_root / "documents/d1/source/a.txt").exists())

        rec = library_registry.get_library("lib-x")
        self.assertIsNotNone(rec)
        self.assertEqual(rec.sqlite_file, "knowledge/libraries/lib-x/index.sqlite")
        self.assertEqual(rec.collection, "lib-x")

        conn = sqlite3.connect(library_root / "index.sqlite")
        try:
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM doc_catalog").fetchone()[0], 1)
        finally:
            conn.close()
        meta = sqlite3.connect(self.data / "knowledge/knowledge_meta.sqlite")
        try:
            self.assertEqual(meta.execute("SELECT COUNT(*) FROM nodes").fetchone()[0], 1)
        finally:
            meta.close()
        graph = sqlite3.connect(self.data / "knowledge/graph.sqlite")
        try:
            self.assertEqual(graph.execute("SELECT COUNT(*) FROM graph_entities").fetchone()[0], 1)
            self.assertEqual(graph.execute("SELECT COUNT(*) FROM graph_relations").fetchone()[0], 1)
        finally:
            graph.close()

        # 重复导入：index 已存在，冲突闸拒绝
        with self.assertRaises(BundleError):
            apply_import(str(pkg), data_root=self.data, group_name="system",
                         apply=True, with_vectors=False)

    def test_invalid_library_id_rejected(self):
        pkg = _build_library_package(
            self.tmp, lib_id="../x", source_root="knowledge/libraries/../x",
        )
        with self.assertRaises(BundleError):
            apply_import(str(pkg), data_root=self.data, group_name="system",
                         apply=False, with_vectors=False)

    def test_layout_mismatch_rejected(self):
        pkg = _build_library_package(
            self.tmp, lib_id="lib-e", source_root="evals/corpora/libraries/lib-e",
            group_name="evals",
        )
        with self.assertRaises(BundleError):
            apply_import(str(pkg), data_root=self.data, group_name="system",
                         apply=False, with_vectors=False)

    def test_evals_layout_applies(self):
        pkg = _build_library_package(
            self.tmp, lib_id="lib-e", source_root="evals/corpora/libraries/lib-e",
            group_name="evals",
        )
        result = apply_import(str(pkg), data_root=self.data, group_name="evals",
                              apply=True, with_vectors=False)
        self.assertEqual(result["mode"], "applied")
        self.assertTrue((self.data / "evals/corpora/libraries/lib-e/index.sqlite").exists())
        rec = library_registry.get_library("lib-e")
        self.assertEqual(rec.sqlite_file, "evals/corpora/libraries/lib-e/index.sqlite")

    def test_package_dangling_baseline_allowed(self):
        pkg = _build_library_package(self.tmp, dangling=True)
        result = apply_import(str(pkg), data_root=self.data, group_name="system",
                              apply=True, with_vectors=False)
        self.assertEqual(result["mode"], "applied")
        conn = sqlite3.connect(self.data / "knowledge/graph.sqlite")
        try:
            self.assertEqual(len(conn.execute("PRAGMA foreign_key_check").fetchall()), 1)
        finally:
            conn.close()

    def test_vectors_upload_path(self):
        pkg = _build_library_package(self.tmp, with_vectors=True)
        calls = []

        def fake_upload(lib_id: str, snapshot: Path, qdrant_url):
            calls.append((lib_id, snapshot.read_bytes()))

        with mock.patch.object(corpus_import_apply, "_upload_snapshot", side_effect=fake_upload), \
             mock.patch.object(corpus_import_apply, "_list_qdrant_collections", return_value=set()), \
             mock.patch.object(corpus_import_apply, "count_points_filtered", return_value=3):
            result = apply_import(str(pkg), data_root=self.data, group_name="system",
                                  apply=True, with_vectors=True)
        self.assertEqual(result["mode"], "applied")
        self.assertEqual(calls[0][0], "lib-x")
        self.assertEqual(calls[0][1], b"SNAP")


if __name__ == "__main__":
    unittest.main()
