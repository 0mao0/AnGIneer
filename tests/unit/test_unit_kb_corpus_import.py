import json
import os
import sqlite3
import sys
import unittest
from contextlib import closing
from pathlib import Path

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../../scripts")))

import kb_corpus_import  # noqa: E402


class EmbedGateTests(unittest.TestCase):
    """闸一：向量与现网 embedding 模型对账——谁建的索引锁谁的模型，跨模型复用=检索静默错乱。"""

    def test_model_mismatch_requires_reembed_flag(self):
        manifest = {"embed_model": "model-A", "collections": ["standards"]}
        with self.assertRaises(SystemExit):
            kb_corpus_import.check_embed_gate(manifest, env_model="model-B", allow_reembed=False)
        # 允许重嵌时放行，但必须明确不带 snapshot 恢复
        kb_corpus_import.check_embed_gate(manifest, env_model="model-B", allow_reembed=True)

    def test_model_match_passes(self):
        manifest = {"embed_model": "model-A", "collections": ["standards"]}
        kb_corpus_import.check_embed_gate(manifest, env_model="model-A", allow_reembed=False)

    def test_manifest_without_model_aborts(self):
        manifest = {"embed_model": "", "collections": ["standards"]}
        with self.assertRaises(SystemExit):
            kb_corpus_import.check_embed_gate(manifest, env_model="model-B", allow_reembed=False)


class ConflictGateTests(unittest.TestCase):
    """闸二：同名库/同 id 节点/已存在的非空 collection 一律拒绝——生产库混覆盖不可逆。"""

    def _target_db(self, tmp: Path) -> sqlite3.Connection:
        db = tmp / "target.sqlite"
        conn = sqlite3.connect(db)
        conn.execute("CREATE TABLE library_registry (library_id TEXT PRIMARY KEY)")
        conn.execute("INSERT INTO library_registry VALUES ('lib-exist')")
        conn.execute("CREATE TABLE nodes (id TEXT PRIMARY KEY)")
        conn.execute("INSERT INTO nodes VALUES ('d-clash')")
        conn.commit()
        return conn

    def test_conflicts_detected(self):
        import tempfile

        with tempfile.TemporaryDirectory() as td:
            conn = self._target_db(Path(td))
            try:
                clashes = kb_corpus_import.check_conflict_gate(
                    conn,
                    package_libraries=[{"library_id": "lib-exist"}, {"library_id": "lib-new"}],
                    package_node_ids=["d-clash", "d-fresh"],
                )
            finally:
                conn.close()
        self.assertIn("lib-exist", clashes)
        self.assertIn("d-clash", clashes)
        self.assertNotIn("lib-new", clashes)
        self.assertNotIn("d-fresh", clashes)


class SchemaGateTests(unittest.TestCase):
    def test_unknown_schema_version_aborts(self):
        with self.assertRaises(SystemExit):
            kb_corpus_import.check_schema_gate({"schema_version": 999})

    def test_known_schema_passes(self):
        kb_corpus_import.check_schema_gate({"schema_version": 1})


class ChecksumGateTests(unittest.TestCase):
    def test_tampered_file_detected(self):
        import tempfile

        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / "a.bin").write_bytes(b"original")
            manifest = {"files": {"a.bin": kb_corpus_import.sha256(root / "a.bin"), "b.bin": "deadbeef"}}
            with self.assertRaises(SystemExit):
                kb_corpus_import.check_package_files(root, manifest)

    def test_valid_package_passes(self):
        import tempfile

        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / "a.bin").write_bytes(b"original")
            manifest = {"files": {"a.bin": kb_corpus_import.sha256(root / "a.bin")}}
            kb_corpus_import.check_package_files(root, manifest)


if __name__ == "__main__":
    unittest.main()
