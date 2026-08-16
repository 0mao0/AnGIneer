"""P3 测试：graph_entities 补 library_id——同名实体按库隔离，检索按库过滤，旧表自动迁移。"""
import os
import sqlite3
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../../services/docs-core/src")))

from docs_core.step07_graph.config import EntityLayer  # noqa: E402
from docs_core.step07_graph.graph_store import GraphEntity, GraphStore  # noqa: E402


class GraphEntityScopeTests(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.db_path = os.path.join(self.tmpdir, "g.sqlite")
        self.store = GraphStore(self.db_path)

    def tearDown(self):
        self.store.close()
        import shutil

        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_same_name_entities_coexist_across_libraries(self):
        a = self.store.upsert_entity(GraphEntity(name="系缆力", layer=EntityLayer.CONCEPT, library_id="lib-a"))
        b = self.store.upsert_entity(GraphEntity(name="系缆力", layer=EntityLayer.CONCEPT, library_id="lib-b"))
        self.assertNotEqual(a.entity_id, b.entity_id)

    def test_upsert_merges_within_same_library(self):
        a = self.store.upsert_entity(GraphEntity(name="系缆力", layer=EntityLayer.CONCEPT, library_id="lib-a"))
        a2 = self.store.upsert_entity(GraphEntity(
            name="系缆力", layer=EntityLayer.CONCEPT, library_id="lib-a", aliases=["mooring force"],
        ))
        self.assertEqual(a.entity_id, a2.entity_id)
        self.assertIn("mooring force", a2.aliases)

    def test_search_filters_by_library(self):
        self.store.upsert_entity(GraphEntity(name="系缆力", layer=EntityLayer.CONCEPT, library_id="lib-a"))
        self.store.upsert_entity(GraphEntity(name="系缆墩", layer=EntityLayer.CONCEPT, library_id="lib-b"))

        scoped = self.store.search_entities("系缆", library_id="lib-a")
        self.assertEqual(len(scoped), 1)
        self.assertEqual(scoped[0].name, "系缆力")
        self.assertEqual(scoped[0].library_id, "lib-a")

    def test_search_without_library_keeps_legacy_behavior(self):
        self.store.upsert_entity(GraphEntity(name="系缆力", layer=EntityLayer.CONCEPT, library_id="lib-a"))
        self.store.upsert_entity(GraphEntity(name="系缆墩", layer=EntityLayer.CONCEPT, library_id="lib-b"))
        all_hits = self.store.search_entities("系缆")
        self.assertEqual(len(all_hits), 2)

    def test_get_entity_by_name_scoped(self):
        self.store.upsert_entity(GraphEntity(name="系缆力", layer=EntityLayer.CONCEPT, library_id="lib-a"))
        self.store.upsert_entity(GraphEntity(name="系缆力", layer=EntityLayer.CONCEPT, library_id="lib-b", description="B库版本"))
        hit = self.store.get_entity_by_name("系缆力", library_id="lib-b")
        self.assertEqual(hit.description, "B库版本")


class GraphSchemaMigrationTests(unittest.TestCase):
    def _make_legacy_db(self, db_path, with_relations=False):
        conn = sqlite3.connect(db_path)
        conn.executescript("""
            CREATE TABLE graph_entities (
                entity_id TEXT PRIMARY KEY,
                name TEXT NOT NULL UNIQUE,
                layer TEXT NOT NULL,
                aliases_json TEXT DEFAULT '[]',
                description TEXT DEFAULT '',
                source_doc TEXT DEFAULT '',
                source_clause TEXT DEFAULT '',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
        """)
        conn.execute(
            "INSERT INTO graph_entities (entity_id, name, layer, created_at, updated_at) "
            "VALUES ('e1', '系缆力', 'concept', '2026-01-01', '2026-01-01')"
        )
        if with_relations:
            conn.execute(
                "INSERT INTO graph_entities (entity_id, name, layer, created_at, updated_at) "
                "VALUES ('e2', '系缆墩', 'concept', '2026-01-01', '2026-01-01')"
            )
            conn.executescript("""
                CREATE TABLE graph_relations (
                    relation_id TEXT PRIMARY KEY,
                    source_id TEXT NOT NULL REFERENCES graph_entities(entity_id),
                    target_id TEXT NOT NULL REFERENCES graph_entities(entity_id),
                    relation_type TEXT NOT NULL,
                    confidence REAL NOT NULL DEFAULT 0.3,
                    evidence_text TEXT DEFAULT '', source_clause TEXT DEFAULT '',
                    conflict_note TEXT DEFAULT '', library_id TEXT DEFAULT '', doc_id TEXT DEFAULT '',
                    created_at TEXT NOT NULL, updated_at TEXT NOT NULL
                );
            """)
            conn.execute(
                "INSERT INTO graph_relations (relation_id, source_id, target_id, relation_type, created_at, updated_at) "
                "VALUES ('r1', 'e1', 'e2', 'defines', '2026-01-01', '2026-01-01')"
            )
        conn.commit()
        conn.close()

    def test_legacy_table_migrates_to_default_library(self):
        tmpdir = tempfile.mkdtemp()
        self.addCleanup(lambda: __import__("shutil").rmtree(tmpdir, ignore_errors=True))
        db_path = os.path.join(tmpdir, "legacy.sqlite")

        self._make_legacy_db(db_path)

        store = GraphStore(db_path)
        hit = store.get_entity_by_name("系缆力")
        self.assertIsNotNone(hit)
        self.assertEqual(hit.library_id, "default")
        cols = [r[1] for r in store._connect().execute("PRAGMA table_info(graph_entities)")]
        self.assertIn("library_id", cols)
        store.close()

    def test_migration_preserves_referencing_tables(self):
        """带外键引用的旧库迁移：引用文本不得被绑到旧表名，迁移后零 FK 违规。"""
        tmpdir = tempfile.mkdtemp()
        self.addCleanup(lambda: __import__("shutil").rmtree(tmpdir, ignore_errors=True))
        db_path = os.path.join(tmpdir, "legacy_rel.sqlite")

        self._make_legacy_db(db_path, with_relations=True)

        store = GraphStore(db_path)
        conn = store._connect()
        self.assertEqual(conn.execute("SELECT COUNT(*) FROM graph_entities").fetchone()[0], 2)
        self.assertEqual(conn.execute("SELECT COUNT(*) FROM graph_relations").fetchone()[0], 1)
        self.assertEqual(conn.execute("PRAGMA foreign_key_check").fetchall(), [])
        sql = conn.execute(
            "SELECT sql FROM sqlite_master WHERE name='graph_relations'"
        ).fetchone()[0]
        self.assertNotIn("_legacy", sql)
        store.close()

    def test_interrupted_migration_self_heals(self):
        """半成品（graph_entities_new 残留）自愈：补灌数据并完成重建。"""
        tmpdir = tempfile.mkdtemp()
        self.addCleanup(lambda: __import__("shutil").rmtree(tmpdir, ignore_errors=True))
        db_path = os.path.join(tmpdir, "partial.sqlite")

        self._make_legacy_db(db_path)
        conn = sqlite3.connect(db_path)
        conn.executescript("""
            CREATE TABLE graph_entities_new (
                entity_id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                layer TEXT NOT NULL,
                aliases_json TEXT DEFAULT '[]',
                description TEXT DEFAULT '',
                source_doc TEXT DEFAULT '',
                source_clause TEXT DEFAULT '',
                library_id TEXT NOT NULL DEFAULT 'default',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                UNIQUE(name, library_id)
            );
        """)
        conn.commit()
        conn.close()

        store = GraphStore(db_path)
        hit = store.get_entity_by_name("系缆力")
        self.assertIsNotNone(hit)
        self.assertEqual(hit.library_id, "default")
        tables = [r[0] for r in store._connect().execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        )]
        self.assertNotIn("graph_entities_new", tables)
        store.close()


if __name__ == "__main__":
    unittest.main()
