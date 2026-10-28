"""graph_files 单测：按库路径解析/遍历/按实体定位 + 全局→按库拆分迁移。"""
import gc
import sqlite3
import sys
import tempfile
import unittest
from contextlib import closing
from pathlib import Path

sys.path.insert(0, __import__("os").path.abspath(
    __import__("os").path.join(__file__, "../../../services/docs-core/src")))

from docs_core.step07_graph import graph_files  # noqa: E402
from docs_core.step07_graph.graph_store import GraphStore  # noqa: E402


def _seed_global_graph(global_db: Path) -> None:
    """全局单文件夹具：双库 + 跨库关系 + 工件/联结 + 孤儿联结 + 删除台账。"""
    global_db.parent.mkdir(parents=True, exist_ok=True)
    store = GraphStore(str(global_db))
    store.close()
    gc.collect()
    with closing(sqlite3.connect(str(global_db))) as conn:
        conn.executemany(
            'INSERT OR REPLACE INTO graph_entities (entity_id, name, layer, aliases_json,'
            ' description, source_doc, source_clause, library_id, status, created_at, updated_at)'
            ' VALUES (?,?,?,?,?,?,?,?,?,?,?)',
            [
                ("e-A1", "船闸", "concept", "[]", "", "", "", "libA", "approved", "t", "t"),
                ("e-A2", "护岸", "concept", "[]", "", "", "", "libA", "approved", "t", "t"),
                ("e-B1", "码头结构", "concept", "[]", "", "", "", "libB", "approved", "t", "t"),
                ("e-N1", "空标实体", "concept", "[]", "", "", "", "", "approved", "t", "t"),
            ],
        )
        conn.executemany(
            'INSERT OR REPLACE INTO graph_relations (relation_id, source_id, target_id,'
            ' relation_type, confidence, evidence_text, source_clause, conflict_note,'
            ' library_id, doc_id, created_at, updated_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)',
            [
                ("r-1", "e-A1", "e-A2", "requires", 0.9, "", "", "", "libA", "d-1", "t", "t"),
                # 跨库：关系归 libA，端点 e-B1 属 libB → 拆分后 e-B1 拷贝进 libA 文件
                ("r-2", "e-A1", "e-B1", "constrains", 0.8, "", "", "", "libA", "d-1", "t", "t"),
            ],
        )
        conn.execute(
            'INSERT INTO graph_principles (principle_id, principle_text, category,'
            ' source_clause, evidence_quote, library_id, doc_id, created_at)'
            ' VALUES ("p-1", "原则1", "mandatory", "", "", "libA", "d-1", "t")'
        )
        conn.execute('INSERT INTO principle_entities (principle_id, entity_id) VALUES ("p-1", "e-A2")')
        # 孤儿联结：父原则不存在 → 按实体归属 libA（不跳过）
        conn.execute('INSERT INTO principle_entities (principle_id, entity_id) VALUES ("p-x", "e-A1")')
        # 全悬空联结：父不存在 + 实体不存在 → 跳过计数
        conn.execute('INSERT INTO principle_entities (principle_id, entity_id) VALUES ("p-y", "e-zz")')
        conn.execute(
            'INSERT INTO graph_entity_deletions (library_id, name, deleted_at) VALUES ("libB", "旧词", "t")'
        )
        conn.commit()


class GraphFilesSplitTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)

    def tearDown(self):
        gc.collect()
        self._tmp.cleanup()

    def test_resolve_prefers_library_file_then_global_then_creates(self):
        per = graph_files.library_graph_db_path("libA", base_dir=self.root)
        self.assertEqual(
            graph_files.resolve_graph_db_for_library("libA", base_dir=self.root), per
        )  # 两者皆缺 → 返回库文件（新建语义）
        per.parent.mkdir(parents=True, exist_ok=True)
        per.write_text("")
        self.assertEqual(
            graph_files.resolve_graph_db_for_library("libA", base_dir=self.root), per
        )  # 库文件在场优先
        per.unlink()
        (self.root / "graph.sqlite").write_text("")
        self.assertEqual(
            graph_files.resolve_graph_db_for_library("libA", base_dir=self.root),
            self.root / "graph.sqlite",
        )  # 库文件缺、全局在 → 全局回退

    def test_split_global_graph(self):
        _seed_global_graph(self.root / "graph.sqlite")
        report = graph_files.split_global_graph_if_present(base_dir=self.root)
        self.assertIsNotNone(report)
        self.assertEqual(report["skipped"].get("principle_entities"), 1)  # 全悬空联结被跳过

        lib_a = graph_files.library_graph_db_path("libA", base_dir=self.root)
        lib_b = graph_files.library_graph_db_path("libB", base_dir=self.root)
        self.assertTrue(lib_a.exists() and lib_b.exists())
        self.assertFalse((self.root / "graph.sqlite").exists())
        backups = list(self.root.glob("graph.sqlite.migrated-*"))
        self.assertEqual(len(backups), 1)

        with closing(sqlite3.connect(str(lib_a))) as conn:
            own = conn.execute(
                "SELECT COUNT(*) FROM graph_entities WHERE library_id='libA'").fetchone()[0]
            self.assertEqual(own, 2)  # 自有 e-A1/e-A2
            e3 = conn.execute(
                "SELECT library_id FROM graph_entities WHERE entity_id='e-B1'").fetchone()
            self.assertIsNotNone(e3)  # 跨库端点随行拷贝（保 FK），library_id 仍标 libB
            self.assertEqual(e3[0], "libB")
            self.assertEqual(
                conn.execute("SELECT COUNT(*) FROM graph_relations").fetchone()[0], 2)
            self.assertEqual(
                conn.execute("SELECT COUNT(*) FROM principle_entities").fetchone()[0], 2)
            self.assertEqual(
                conn.execute("SELECT COUNT(*) FROM graph_principles").fetchone()[0], 1)
            # FK 核心保证：关系表无悬空（跨库端点拷贝在场）；
            # 孤儿联结（父工件已删）忠实落盘、允许报悬空（与全局文件历史口径一致）
            fk = conn.execute("PRAGMA foreign_key_check").fetchall()
            self.assertEqual([v for v in fk if v[0] == "graph_relations"], [])
            self.assertEqual([v[0] for v in fk], ["principle_entities"])
        with closing(sqlite3.connect(str(lib_b))) as conn:
            self.assertEqual(
                conn.execute("SELECT COUNT(*) FROM graph_entities WHERE library_id='libB'")
                .fetchone()[0], 1)
            self.assertEqual(
                conn.execute("SELECT COUNT(*) FROM graph_relations").fetchone()[0], 0)
            self.assertEqual(
                conn.execute("SELECT COUNT(*) FROM graph_entity_deletions").fetchone()[0], 1)
        # 空标实体归 default 库文件
        default_db = graph_files.library_graph_db_path("default", base_dir=self.root)
        self.assertTrue(default_db.exists())
        with closing(sqlite3.connect(str(default_db))) as conn:
            self.assertEqual(
                conn.execute("SELECT library_id FROM graph_entities WHERE entity_id='e-N1'")
                .fetchone()[0], "default")

        # 幂等：全局已改名，二次运行 no-op
        self.assertIsNone(graph_files.split_global_graph_if_present(base_dir=self.root))

    def test_iter_and_find_entity(self):
        _seed_global_graph(self.root / "graph.sqlite")
        graph_files.split_global_graph_if_present(base_dir=self.root)
        paths = dict(graph_files.iter_library_graph_paths(base_dir=self.root))
        self.assertEqual(set(paths), {"default", "libA", "libB"})
        hit = graph_files.find_graph_db_for_entity("e-B1", base_dir=self.root)
        self.assertEqual(hit[0], "libB")
        self.assertEqual(hit[1], paths["libB"])  # 命中自有文件而非引用方拷贝件
        self.assertIsNone(graph_files.find_graph_db_for_entity("e-none", base_dir=self.root))

    def test_split_no_global_is_noop(self):
        self.assertIsNone(graph_files.split_global_graph_if_present(base_dir=self.root))


if __name__ == "__main__":
    unittest.main()
