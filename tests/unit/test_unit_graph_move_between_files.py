"""跨文件图谱移库单测（plan-graph-per-library-split 拆并适配）。"""
import gc
import os
import sqlite3
import sys
import tempfile
import unittest
from contextlib import closing
from pathlib import Path

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../../services/docs-core/src")))

from docs_core.step07_graph.graph_store import (  # noqa: E402
    GraphStore,
    move_doc_graph_between_files,
)


def _seed(db: Path, library_id: str, entities: list, relations: list,
          principles: list | None = None) -> None:
    db.parent.mkdir(parents=True, exist_ok=True)
    store = GraphStore(str(db))
    store.close()
    gc.collect()
    with closing(sqlite3.connect(str(db))) as conn:
        conn.executemany(
            "INSERT OR REPLACE INTO graph_entities (entity_id, name, layer, aliases_json,"
            " description, source_doc, source_clause, library_id, status, created_at, updated_at)"
            " VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            [(eid, name, "concept", "[]", "", "", "", library_id, "approved", "t", "t")
             for eid, name in entities],
        )
        conn.executemany(
            "INSERT OR REPLACE INTO graph_relations (relation_id, source_id, target_id,"
            " relation_type, confidence, evidence_text, source_clause, conflict_note,"
            " library_id, doc_id, created_at, updated_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
            [(rid, sid, tid, "requires", 0.9, "", "", "", library_id, doc, "t", "t")
             for rid, sid, tid, doc in relations],
        )
        for pid, doc in principles or []:
            conn.execute(
                "INSERT OR REPLACE INTO graph_principles (principle_id, principle_text,"
                " category, source_clause, evidence_quote, library_id, doc_id, created_at)"
                " VALUES (?,?,?,?,?,?,?,'t')", (pid, "p", "mandatory", "", "", library_id, doc)
            )
            conn.execute("INSERT OR IGNORE INTO principle_entities (principle_id, entity_id)"
                         " VALUES (?, ?)", (pid, entities[0][0]))
        conn.commit()


def _entities(db: Path) -> dict:
    with closing(sqlite3.connect(str(db))) as conn:
        return {r[0]: r[1] for r in conn.execute(
            "SELECT entity_id, library_id FROM graph_entities")}


class MoveBetweenFilesTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.src = self.root / "libA" / "graph.sqlite"
        self.dst = self.root / "libB" / "graph.sqlite"

    def tearDown(self):
        gc.collect()
        self._tmp.cleanup()

    def test_exclusive_entity_moves_shared_copies(self):
        _seed(self.src, "libA",
              entities=[("eA", "独占词"), ("eS", "共享词")],
              relations=[("rA", "eA", "eA", "d1"), ("rS", "eS", "eS", "d1"),
                         ("rK", "eS", "eS", "d9")],  # d9 不迁 → eS 共享
              principles=[("pA", "d1")])
        _seed(self.dst, "libB", entities=[], relations=[])

        stats = move_doc_graph_between_files(self.src, self.dst, "libA", "libB", ["d1"])
        self.assertEqual(stats["entities_moved"], 1)   # eA 独占搬移
        self.assertEqual(stats["entities_copied"], 1)  # eS 共享复制
        self.assertEqual(stats["relations_moved"], 2)
        self.assertEqual(stats["artifacts_moved"], 1)

        src_entities = _entities(self.src)
        dst_entities = _entities(self.dst)
        self.assertNotIn("eA", src_entities)           # 独占：源行删除、目标在场
        self.assertEqual(dst_entities["eA"], "libB")
        self.assertEqual(src_entities["eS"], "libA")   # 共享：源行保留
        copied = [eid for eid, lib in dst_entities.items()
                  if lib == "libB" and eid not in ("eA",)]
        self.assertEqual(len(copied), 1)               # 复制件换新 id
        with closing(sqlite3.connect(str(self.dst))) as conn:
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM graph_relations").fetchone()[0], 2)
            self.assertEqual(conn.execute("PRAGMA foreign_key_check").fetchall(), [])
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM graph_principles").fetchone()[0], 1)
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM principle_entities").fetchone()[0], 1)
        with closing(sqlite3.connect(str(self.src))) as conn:
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM graph_relations").fetchone()[0], 1)
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM graph_principles").fetchone()[0], 0)

    def test_name_collision_keeps_source_row(self):
        _seed(self.src, "libA", entities=[("eX", "码头")], relations=[("rX", "eX", "eX", "d1")])
        _seed(self.dst, "libB", entities=[("eY", "码头")], relations=[])
        stats = move_doc_graph_between_files(self.src, self.dst, "libA", "libB", ["d1"])
        self.assertEqual(stats["entities_merged"], 1)
        with closing(sqlite3.connect(str(self.dst))) as conn:
            row = conn.execute("SELECT target_id FROM graph_relations").fetchone()
        self.assertEqual(row[0], "eY")                 # 关系重指目标库同名行
        self.assertIn("eX", _entities(self.src))       # 源行保留（跨文件 FK 约束）

    def test_foreign_endpoint_copied_for_fk(self):
        _seed(self.src, "libA", entities=[("eA", "本库词"), ("eF", "他库词")],
              relations=[("rF", "eA", "eF", "d1")])
        # eF 归属他库（源文件中的拷贝件）
        with closing(sqlite3.connect(str(self.src))) as conn:
            conn.execute("UPDATE graph_entities SET library_id='libC' WHERE entity_id='eF'")
            conn.commit()
        _seed(self.dst, "libB", entities=[], relations=[])
        move_doc_graph_between_files(self.src, self.dst, "libA", "libB", ["d1"])
        with closing(sqlite3.connect(str(self.dst))) as conn:
            self.assertIsNotNone(conn.execute(
                "SELECT 1 FROM graph_entities WHERE entity_id='eF' AND library_id='libC'").fetchone())
            self.assertEqual(conn.execute("PRAGMA foreign_key_check").fetchall(), [])

    def test_idempotent_second_run(self):
        _seed(self.src, "libA", entities=[("eA", "独占词")], relations=[("rA", "eA", "eA", "d1")])
        _seed(self.dst, "libB", entities=[], relations=[])
        move_doc_graph_between_files(self.src, self.dst, "libA", "libB", ["d1"])
        stats = move_doc_graph_between_files(self.src, self.dst, "libA", "libB", ["d1"])
        self.assertEqual(stats["relations_moved"], 0)
        with closing(sqlite3.connect(str(self.dst))) as conn:
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM graph_relations").fetchone()[0], 1)


if __name__ == "__main__":
    unittest.main()
