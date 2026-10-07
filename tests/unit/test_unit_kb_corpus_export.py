import json
import os
import sqlite3
import sys
import unittest
from contextlib import closing
from pathlib import Path

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../../scripts")))

import kb_corpus_export  # noqa: E402


def _fake_data_root(tmp: Path) -> Path:
    root = tmp / "data"
    root.mkdir(parents=True)
    reg = root / "registry.sqlite"
    with closing(sqlite3.connect(reg)) as conn:
        conn.executescript(
            """
            CREATE TABLE library_registry (
                library_id TEXT PRIMARY KEY, name TEXT NOT NULL DEFAULT '',
                description TEXT NOT NULL DEFAULT '', group_name TEXT NOT NULL,
                sqlite_file TEXT NOT NULL, collection TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'active',
                created_at TEXT NOT NULL, updated_at TEXT NOT NULL);
            CREATE TABLE library_groups (
                group_name TEXT PRIMARY KEY, display_name TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL, updated_at TEXT NOT NULL);
            """
        )
        conn.execute(
            "INSERT INTO library_registry VALUES ('lib-std-road','公路库','','standards',"
            "'knowledge/groups/standards.sqlite','standards','active','t','t')"
        )
        conn.execute("INSERT INTO library_groups VALUES ('standards','规范','','t')")
        conn.commit()
    grp = root / "knowledge" / "groups"
    grp.mkdir(parents=True)
    with closing(sqlite3.connect(grp / "standards.sqlite")) as conn:  # 组文件必须是真 sqlite（脚本会 checkpoint）
        conn.execute("CREATE TABLE canonical_documents (doc_id TEXT PRIMARY KEY)")
        conn.execute("INSERT INTO canonical_documents VALUES ('d1')")
        conn.commit()
    meta = root / "knowledge" / "knowledge_meta.sqlite"
    with closing(sqlite3.connect(meta)) as conn:
        conn.execute("CREATE TABLE nodes (id TEXT PRIMARY KEY, library_id TEXT, file_path TEXT)")
        conn.execute("INSERT INTO nodes VALUES ('d1','lib-std-road','knowledge/libraries/lib-std-road/documents/d1/source/a.pdf')")
        conn.execute("INSERT INTO nodes VALUES ('d9','lib-other','knowledge/libraries/lib-other/documents/d9/source/b.pdf')")
        conn.execute("CREATE TABLE tree_node (node_id TEXT PRIMARY KEY, scope_id TEXT, extra_json TEXT)")
        conn.execute("INSERT INTO tree_node VALUES ('d1','lib-std-road','{}')")
        conn.commit()
    src = root / "knowledge" / "libraries" / "lib-std-road" / "documents" / "d1" / "source"
    src.mkdir(parents=True)
    (src / "a.pdf").write_bytes(b"%PDF-1.5 fake")
    return root


class KbCorpusExportTests(unittest.TestCase):
    def test_build_package_layout_and_manifest(self):
        import tempfile

        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            root = _fake_data_root(tmp)
            os.environ["ANGINEER_DATA_ROOT"] = str(root)
            os.environ["EMBEDDING_CONFIGS"] = json.dumps([{"model": "qwen3-embed-8b"}])
            try:
                pkg = kb_corpus_export.build_package(["lib-std-road"], tmp / "pkgs", with_vectors=False, pack_tar=False)
            finally:
                os.environ.pop("ANGINEER_DATA_ROOT", None)
                os.environ.pop("EMBEDDING_CONFIGS", None)

            manifest = json.loads((pkg / "manifest.json").read_text("utf-8"))
            self.assertEqual(manifest["schema_version"], 1)
            self.assertEqual(manifest["page_base"], 0)
            self.assertEqual(manifest["embed_model"], "qwen3-embed-8b")
            self.assertEqual(manifest["group"], "standards")
            self.assertIn("knowledge/groups/standards.sqlite", manifest["staged_roots"])
            # 落包文件 = 组 sqlite + 库目录树 + registry/meta json + manifest 之外全部有 sha256
            self.assertIn("files/knowledge/groups/standards.sqlite", manifest["files"])
            self.assertIn(
                "files/knowledge/libraries/lib-std-road/documents/d1/source/a.pdf", manifest["files"]
            )
            registry = json.loads((pkg / "registry" / "rows.json").read_text("utf-8"))
            self.assertEqual([r["library_id"] for r in registry["libraries"]], ["lib-std-road"])
            self.assertEqual([g["group_name"] for g in registry["groups"]], ["standards"])
            meta = json.loads((pkg / "meta" / "rows.json").read_text("utf-8"))
            # 只带走本批库的行，别的库不串包
            self.assertEqual([r["id"] for r in meta["nodes"]], ["d1"])
            self.assertEqual([r["node_id"] for r in meta["tree_nodes"]], ["d1"])

    def test_unknown_library_aborts(self):
        import tempfile

        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            root = _fake_data_root(tmp)
            os.environ["ANGINEER_DATA_ROOT"] = str(root)
            try:
                with self.assertRaises(SystemExit):
                    kb_corpus_export.read_registry(root, ["lib-std-road", "lib-not-exist"])
            finally:
                os.environ.pop("ANGINEER_DATA_ROOT", None)


if __name__ == "__main__":
    unittest.main()
