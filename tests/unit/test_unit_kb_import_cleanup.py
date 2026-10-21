"""kv_corpus_import_cleanup：孤儿暂存 + 半成品库（registry 无行）清理。

场景对应 P3-4 kill 演练：apply 在 registry 写入前被强杀，任务表随进程消失。
"""
import importlib.util
import io
import os
import shutil
import sqlite3
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest import mock

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "services" / "docs-core" / "src"))

from docs_core import library_registry  # noqa: E402

SCRIPT = REPO_ROOT / "scripts" / "kb_corpus_import_cleanup.py"


def _load_script():
    spec = importlib.util.spec_from_file_location("kb_corpus_import_cleanup", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _make_meta(root: Path) -> None:
    db = root / "knowledge" / "knowledge_meta.sqlite"
    db.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db)
    try:
        with conn:
            conn.execute("CREATE TABLE libraries (id TEXT PRIMARY KEY)")
            conn.execute("CREATE TABLE nodes (id TEXT PRIMARY KEY, library_id TEXT, deleted INTEGER DEFAULT 0)")
            conn.execute("CREATE TABLE tree_node (id TEXT PRIMARY KEY, scope_id TEXT)")
    finally:
        conn.close()


class ImportCleanupTest(unittest.TestCase):
    def setUp(self) -> None:
        self.root = Path(tempfile.mkdtemp())
        self._env = mock.patch.dict(os.environ, {
            "ANGINEER_DATA_ROOT": str(self.root),
            "ANGINEER_REGISTRY_DB": str(self.root / "registry.sqlite"),
            "QDRANT_URL": "http://127.0.0.1:1",
        })
        self._env.start()
        library_registry.ensure_schema(self.root / "registry.sqlite")
        library_registry.register_library("keep", name="保留库", group_name="system")
        _make_meta(self.root)

        # 半成品：目录 + meta 行（无 registry 行）
        (self.root / "knowledge/libraries/phantom/documents").mkdir(parents=True)
        (self.root / "knowledge/libraries/phantom/index.sqlite").write_bytes(b"x")
        (self.root / "knowledge/libraries/keep").mkdir(parents=True)
        conn = sqlite3.connect(self.root / "knowledge/knowledge_meta.sqlite")
        try:
            with conn:
                conn.execute("INSERT INTO libraries (id) VALUES ('phantom'), ('keep')")
                conn.execute(
                    "INSERT INTO nodes (id, library_id, deleted) VALUES "
                    "('doc-p', 'phantom', 0), ('doc-k', 'keep', 0)")
                conn.execute(
                    "INSERT INTO tree_node (id, scope_id) VALUES ('t-p', 'phantom'), ('t-k', 'keep')")
        finally:
            conn.close()

        # 孤儿暂存包
        pkg = self.root / "scratch/imports/imp-dead/package.zip"
        pkg.parent.mkdir(parents=True)
        pkg.write_bytes(b"PK\x03\x04")

        self.mod = _load_script()

    def tearDown(self) -> None:
        self._env.stop()
        shutil.rmtree(self.root, ignore_errors=True)

    def _run(self, argv):
        out = io.StringIO()
        with redirect_stdout(out):
            code = self.mod.main(argv)
        return code, out.getvalue()

    def test_dry_run_changes_nothing(self):
        code, out = self._run(["--scratch"])
        self.assertEqual(code, 0)
        self.assertIn("phantom", out)
        self.assertTrue((self.root / "scratch/imports/imp-dead/package.zip").exists())
        self.assertTrue((self.root / "knowledge/libraries/phantom").exists())

    def test_apply_removes_orphan_scratch_and_partial_library(self):
        code, _ = self._run(["--apply", "--scratch"])
        self.assertEqual(code, 0)
        self.assertFalse((self.root / "scratch/imports/imp-dead").exists())
        self.assertFalse((self.root / "knowledge/libraries/phantom").exists())

        conn = sqlite3.connect(self.root / "knowledge/knowledge_meta.sqlite")
        try:
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM libraries WHERE id='phantom'").fetchone()[0], 0)
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM nodes WHERE library_id='phantom'").fetchone()[0], 0)
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM tree_node WHERE scope_id='phantom'").fetchone()[0], 0)
            # 已注册库不动
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM libraries WHERE id='keep'").fetchone()[0], 1)
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM nodes WHERE library_id='keep'").fetchone()[0], 1)
        finally:
            conn.close()
        self.assertTrue((self.root / "knowledge/libraries/keep").exists())

    def test_registered_library_is_refused(self):
        code, _ = self._run(["--apply", "--library", "keep"])
        self.assertEqual(code, 2)
        self.assertTrue((self.root / "knowledge/libraries/keep").exists())


if __name__ == "__main__":
    unittest.main()
