import gc
import os
import sqlite3
import sys
import tempfile
import unittest
from contextlib import closing
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../../services/docs-core/src")))

from unittest import mock

from docs_core import corpus_slicing  # noqa: E402
from docs_core.corpus_slicing import (  # noqa: E402
    build_library_graph_slice,
    build_library_sqlite_slice,
    cleanup_stale_temp_collections,
    library_owns_collection_exclusively,
    library_vector_snapshot,
)

_FTS_COLS = ["chunk_id", "doc_id", "chunk_type", "section_path", "text_clean", "text_ngrams"]

_FTS_DDL = """
CREATE VIRTUAL TABLE canonical_chunk_fts USING fts5(
    chunk_id UNINDEXED, doc_id UNINDEXED, chunk_type UNINDEXED,
    section_path, text_clean UNINDEXED, text_ngrams, tokenize = 'unicode61'
)
"""


def _seed_group_db(path: Path) -> None:
    """两库三文档的组 sqlite 夹具：只建真实表的一个子集（缺表靠实现跳过）。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    with closing(sqlite3.connect(path)) as conn:
        conn.executescript(
            """
            CREATE TABLE canonical_documents (doc_id TEXT PRIMARY KEY, library_id TEXT NOT NULL, title TEXT);
            CREATE TABLE canonical_pages (doc_id TEXT NOT NULL, page_idx INTEGER, text TEXT);
            CREATE TABLE canonical_chunks (chunk_id TEXT PRIMARY KEY, doc_id TEXT NOT NULL,
                                           chunk_type TEXT, text_clean TEXT, updated_at TEXT);
            CREATE TABLE doc_blocks (block_id TEXT PRIMARY KEY, doc_id TEXT NOT NULL, text TEXT);
            CREATE INDEX idx_canonical_chunks_doc_type ON canonical_chunks(doc_id, chunk_type);
            CREATE INDEX idx_canonical_pages_doc ON canonical_pages(doc_id);
            CREATE TRIGGER trg_chunks_del AFTER DELETE ON canonical_chunks BEGIN SELECT 1; END;
            """
        )
        conn.execute(_FTS_DDL)
        conn.executemany(
            "INSERT INTO canonical_documents VALUES (?,?,?)",
            [("a1", "lib-a", "A 文档"), ("a2", "lib-a", "A 文档二"), ("b1", "lib-b", "B 文档")],
        )
        conn.executemany(
            "INSERT INTO canonical_pages VALUES (?,?,?)",
            [("a1", 0, "pa1"), ("a1", 1, "pa2"), ("b1", 0, "pb1")],
        )
        conn.executemany(
            "INSERT INTO canonical_chunks VALUES (?,?,?,?,?)",
            [
                ("c1", "a1", "clause", "waterway regulation alpha", "t"),
                ("c2", "a2", "clause", "waterway regulation beta", "t"),
                ("c3", "b1", "clause", "waterway other library", "t"),
            ],
        )
        conn.executemany(
            "INSERT INTO doc_blocks VALUES (?,?,?)",
            [("bl1", "a1", "x"), ("bl2", "b1", "y")],
        )
        conn.executemany(
            "INSERT INTO canonical_chunk_fts (chunk_id, doc_id, chunk_type, section_path, text_clean, text_ngrams) "
            "VALUES (?,?,?,?,?,?)",
            [
                # 真实 schema：text_clean 是 UNINDEXED，可检索列 = section_path + text_ngrams
                # （CJK/词形靠预先算好的 bigram 落进 text_ngrams）——'rg' 是 regulation 的 bigram
                ("c1", "a1", "clause", "1.1", "waterway regulation alpha", "wa at te er rg eg gu ul la at ti io on"),
                ("c2", "a2", "clause", "1.2", "waterway regulation beta", "wa at te er rg eg gu ul la at ti io on"),
                ("c3", "b1", "clause", "1.1", "waterway other library", "wa at te er ot th he er li ib br ra ar ry"),
            ],
        )
        conn.commit()


def _scalar(db: Path, sql: str, params=()):
    with closing(sqlite3.connect(db)) as conn:
        return conn.execute(sql, params).fetchone()[0]


class LibrarySqliteSliceTests(unittest.TestCase):
    def _build(self, tmp: Path):
        data_root = tmp / "data"
        group_db = data_root / "knowledge" / "groups" / "standards.sqlite"
        _seed_group_db(group_db)
        row = {"library_id": "lib-a", "sqlite_file": "knowledge/groups/standards.sqlite"}
        out = tmp / "slice.sqlite"
        counts = build_library_sqlite_slice(data_root, row, out)
        return out, counts

    def test_slice_contains_only_target_library(self):
        with tempfile.TemporaryDirectory() as td:
            out, counts = self._build(Path(td))
            self.assertEqual(
                _scalar(out, "SELECT COUNT(*) FROM canonical_documents"), 2)
            self.assertEqual(
                _scalar(out, "SELECT COUNT(*) FROM canonical_documents WHERE library_id='lib-b'"), 0)
            self.assertEqual(_scalar(out, "SELECT COUNT(*) FROM canonical_pages"), 2)
            self.assertEqual(_scalar(out, "SELECT COUNT(*) FROM canonical_chunks"), 2)
            self.assertEqual(_scalar(out, "SELECT COUNT(*) FROM doc_blocks"), 1)
            self.assertEqual(_scalar(out, "SELECT COUNT(*) FROM canonical_chunk_fts"), 2)
            for table in ("canonical_pages", "canonical_chunks", "doc_blocks", "canonical_chunk_fts"):
                self.assertEqual(
                    _scalar(out, f"SELECT COUNT(*) FROM {table} WHERE doc_id='b1'"), 0, table)
            # 源库缺表的兼容：夹具没有 canonical_vectors，切片重建里也不该有
            self.assertEqual(
                _scalar(out, "SELECT COUNT(*) FROM sqlite_master WHERE name='canonical_vectors'"), 0)
            # 计数回传
            self.assertEqual(counts["docs"], 2)
            self.assertEqual(counts["chunks"], 2)
            self.assertEqual(counts["bytes"], out.stat().st_size)
            self.assertEqual(counts["tables"]["doc_blocks"], 1)

    def test_slice_preserves_ddl_and_fts_search(self):
        with tempfile.TemporaryDirectory() as td:
            out, _ = self._build(Path(td))
            self.assertEqual(
                _scalar(out, "SELECT COUNT(*) FROM sqlite_master WHERE type='index' "
                             "AND name='idx_canonical_chunks_doc_type'"), 1)
            self.assertEqual(
                _scalar(out, "SELECT COUNT(*) FROM sqlite_master WHERE type='trigger' "
                             "AND name='trg_chunks_del'"), 1)
            # FTS 列结构原样（tokenize 配置随影子表）
            with closing(sqlite3.connect(out)) as conn:
                cols = [r[1] for r in conn.execute("PRAGMA table_info(canonical_chunk_fts)")]
            self.assertEqual(cols, _FTS_COLS)
            # FTS 真能检索，且只含本库行（'rg' 命中 c1/c2；c3 的 ngram 无 'rg' 且跨库被滤）
            with closing(sqlite3.connect(out)) as conn:
                hits = [r[0] for r in conn.execute(
                    "SELECT chunk_id FROM canonical_chunk_fts WHERE canonical_chunk_fts MATCH 'rg' "
                    "ORDER BY chunk_id")]
            self.assertEqual(hits, ["c1", "c2"])

    def test_slice_flushes_wal_writes(self):
        """源库有未 checkpoint 的 WAL 写入（连接仍开着）→ 切片必须看到（读侧先 checkpoint）。"""
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            data_root = tmp / "data"
            group_db = data_root / "knowledge" / "groups" / "standards.sqlite"
            _seed_group_db(group_db)
            holder = sqlite3.connect(group_db)
            try:
                holder.execute("PRAGMA journal_mode=WAL")
                holder.execute(
                    "INSERT INTO canonical_documents VALUES ('a9','lib-a','A 文档九')")
                holder.execute(
                    "INSERT INTO canonical_chunks VALUES ('c9','a9','clause','waterway regulation gamma','t')")
                holder.commit()  # 写入只在 -wal 里，未 checkpoint
                row = {"library_id": "lib-a", "sqlite_file": "knowledge/groups/standards.sqlite"}
                out = tmp / "slice.sqlite"
                counts = build_library_sqlite_slice(data_root, row, out)
            finally:
                holder.close()
            self.assertEqual(counts["docs"], 3)
            self.assertEqual(counts["chunks"], 3)
            self.assertEqual(
                _scalar(out, "SELECT COUNT(*) FROM canonical_chunks WHERE doc_id='a9'"), 1)


_GRAPH_TABLES = [
    "graph_entities", "graph_relations", "graph_principles", "principle_entities",
    "graph_examples", "example_entities", "graph_warnings", "warning_entities",
    "graph_frameworks", "graph_entity_deletions",
]


def _seed_graph_db(path: Path) -> None:
    """两库图谱夹具（真实 GraphStore schema）：含跨库引用——A 库关系端点 e3 与 A 库
    principle 联结实体 e3 均归属 B 库（F17 闭包场景）。"""
    from docs_core.step07_graph.graph_store import GraphStore  # noqa: PLC0415

    path.parent.mkdir(parents=True, exist_ok=True)
    GraphStore(str(path)).close()
    gc.collect()  # GraphStore._init_schema 的连接进引用循环，不 gc 则 Windows 锁住夹具文件

    with closing(sqlite3.connect(path)) as conn:
        conn.execute("PRAGMA foreign_keys=ON")
        conn.executemany(
            "INSERT INTO graph_entities (entity_id, name, layer, library_id, created_at, updated_at) "
            "VALUES (?,?,?,?,?,?)",
            [
                ("e1", "码头前沿水深", "concept", "lib-a", "t", "t"),
                ("e2", "设计船型", "condition", "lib-a", "t", "t"),
                ("e3", "共用实体", "concept", "lib-b", "t", "t"),
                ("e4", "B库独有", "concept", "lib-b", "t", "t"),
            ],
        )
        conn.executemany(
            "INSERT INTO graph_relations (relation_id, source_id, target_id, relation_type, "
            "library_id, doc_id, created_at, updated_at) VALUES (?,?,?,?,?,?,?,?)",
            [
                ("r1", "e1", "e2", "requires", "lib-a", "a1", "t", "t"),
                ("r2", "e1", "e3", "defines", "lib-a", "a1", "t", "t"),   # 端点是 B 库实体
                ("r3", "e3", "e4", "requires", "lib-b", "b1", "t", "t"),
            ],
        )
        conn.executemany(
            "INSERT INTO graph_principles (principle_id, principle_text, library_id, doc_id, created_at) "
            "VALUES (?,?,?,?,?)",
            [("p1", "原则一", "lib-a", "a1", "t"), ("p2", "原则二", "lib-b", "b1", "t")],
        )
        conn.executemany(
            "INSERT INTO principle_entities (principle_id, entity_id) VALUES (?,?)",
            [("p1", "e1"), ("p1", "e3"), ("p2", "e3")],  # p1 的联结挂 B 库实体 e3
        )
        conn.executemany(
            "INSERT INTO graph_examples (example_id, title, library_id, doc_id, created_at) "
            "VALUES (?,?,?,?,?)",
            [("ex1", "示例一", "lib-a", "a1", "t")],
        )
        conn.executemany(
            "INSERT INTO example_entities (example_id, entity_id) VALUES (?,?)",
            [("ex1", "e3")],
        )
        conn.executemany(
            "INSERT INTO graph_warnings (warning_id, warning_text, library_id, doc_id, created_at) "
            "VALUES (?,?,?,?,?)",
            [("w1", "警告一", "lib-a", "a1", "t")],
        )
        conn.executemany(
            "INSERT INTO warning_entities (warning_id, entity_id) VALUES (?,?)",
            [("w1", "e1")],
        )
        conn.executemany(
            "INSERT INTO graph_frameworks (framework_id, name, library_id, doc_id, created_at) "
            "VALUES (?,?,?,?,?)",
            [("f1", "框架一", "lib-a", "a1", "t")],
        )
        conn.executemany(
            "INSERT INTO graph_entity_deletions (library_id, name, deleted_at) VALUES (?,?,?)",
            [("lib-a", "GhostA", "t"), ("lib-b", "GhostB", "t")],
        )
        conn.commit()


def _rows(db: Path, sql: str, params=()):
    with closing(sqlite3.connect(db)) as conn:
        return sorted(conn.execute(sql, params).fetchall())


class LibraryGraphSliceTests(unittest.TestCase):
    def _build(self, tmp: Path, library_id="lib-a"):
        graph_db = tmp / "graph.sqlite"
        _seed_graph_db(graph_db)
        out = tmp / "graph-slice.sqlite"
        counts = build_library_graph_slice(graph_db, library_id, out)
        return out, counts

    def test_graph_slice_closure_scope(self):
        with tempfile.TemporaryDirectory() as td:
            out, counts = self._build(Path(td))
            # entities = 闭包：本库归属 ∪ 本库关系端点 ∪ 本库联结引用实体；无闭包外杂行（e4 排除）
            self.assertEqual(
                [r[0] for r in _rows(out, "SELECT entity_id FROM graph_entities")],
                ["e1", "e2", "e3"])
            # relations / artifacts / deletions 按 library_id 过滤（B 库 0 行）
            self.assertEqual(
                [r[0] for r in _rows(out, "SELECT relation_id FROM graph_relations ORDER BY relation_id")],
                ["r1", "r2"])
            self.assertEqual(
                [r[0] for r in _rows(out, "SELECT principle_id FROM graph_principles")], ["p1"])
            self.assertEqual(
                [r[0] for r in _rows(out, "SELECT example_id FROM graph_examples")], ["ex1"])
            self.assertEqual(
                [r[0] for r in _rows(out, "SELECT warning_id FROM graph_warnings")], ["w1"])
            self.assertEqual(
                [r[0] for r in _rows(out, "SELECT framework_id FROM graph_frameworks")], ["f1"])
            self.assertEqual(
                _rows(out, "SELECT library_id, name FROM graph_entity_deletions"), [("lib-a", "GhostA")])
            # junctions 按本库父 id 抽全行（含挂 B 库实体 e3 的行）
            self.assertEqual(
                _rows(out, "SELECT * FROM principle_entities"), [("p1", "e1"), ("p1", "e3")])
            self.assertEqual(_rows(out, "SELECT * FROM example_entities"), [("ex1", "e3")])
            self.assertEqual(_rows(out, "SELECT * FROM warning_entities"), [("w1", "e1")])
            # 闭包完整性硬断言：切片不留悬空 FK
            with closing(sqlite3.connect(out)) as conn:
                self.assertEqual(conn.execute("PRAGMA foreign_key_check").fetchall(), [])
            # 计数回传（含继承违例计数：合成源干净 → 0）
            self.assertEqual(counts["relations"], 2)
            self.assertEqual(counts["tables"]["graph_entities"], 3)
            self.assertEqual(counts["tables"]["graph_relations"], 2)
            self.assertEqual(counts["tables"]["principle_entities"], 2)
            self.assertEqual(counts["fk_violations"], 0)
            # DDL 完整（索引随库走）
            self.assertEqual(
                _scalar(out, "SELECT COUNT(*) FROM sqlite_master WHERE type='index' "
                             "AND name='idx_relations_source'"), 1)

    def test_graph_slice_empty_library_is_valid(self):
        with tempfile.TemporaryDirectory() as td:
            out, counts = self._build(Path(td), library_id="lib-none")
            with closing(sqlite3.connect(out)) as conn:
                names = {r[0] for r in conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'")}
                self.assertEqual(names, set(_GRAPH_TABLES))
                for table in _GRAPH_TABLES:
                    self.assertEqual(
                        conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0], 0, table)
                self.assertEqual(conn.execute("PRAGMA foreign_key_check").fetchall(), [])
            self.assertEqual(counts["relations"], 0)
            self.assertEqual(counts["tables"]["graph_entities"], 0)

    def test_graph_slice_counts_inherited_fk_dirt(self):
        """源库悬空行（实体删除残留）→ 忠实镜像 + 计数上报，不 abort（P1-7 实采生产库有 436 条）。"""
        with tempfile.TemporaryDirectory() as td:
            graph_db = Path(td) / "graph.sqlite"
            _seed_graph_db(graph_db)
            with closing(sqlite3.connect(graph_db)) as conn:
                conn.execute(
                    "INSERT INTO graph_relations (relation_id, source_id, target_id, relation_type, "
                    "library_id, doc_id, created_at, updated_at) "
                    "VALUES ('rX','e1','gone','requires','lib-a','a1','t','t')")
                conn.commit()
            out = Path(td) / "slice.sqlite"
            info = build_library_graph_slice(graph_db, "lib-a", out)
            self.assertEqual(info["fk_violations"], 1)
            self.assertEqual(
                _rows(out, "SELECT relation_id FROM graph_relations WHERE relation_id='rX'"), [("rX",)])
            with closing(sqlite3.connect(out)) as conn:
                self.assertEqual(len(conn.execute("PRAGMA foreign_key_check").fetchall()), 1)


class _FakeQdrant:
    """最小 qdrant-client 假身：记录调用、按一次 scroll 返回全量点。

    get_collection 返回**真实 pydantic 模型**（而非 SimpleNamespace 字符串）：
    P1-7 实采曾漏过一类 bug——GET 回的 HnswConfig 直接传 create_collection 会 pydantic
    ValidationError（入参要 HnswConfigDiff），假身用真模型 + create 侧真校验才能钉住转换逻辑。
    """

    def __init__(self, points=(), collections=()):
        self._points = list(points)
        self._collections = list(collections)
        self.created = []
        self.payload_indexes = []
        self.scroll_calls = []
        self.upsert_calls = []
        self.deleted_collections = []

    def get_collection(self, name):
        from qdrant_client import models

        vectors = models.VectorParams(size=8, distance=models.Distance.COSINE, on_disk=True)
        config = models.CollectionConfig.model_construct(
            params=models.CollectionParams.model_construct(vectors=vectors),
            hnsw_config=models.HnswConfig(m=16, ef_construct=100, full_scan_threshold=10000),
            quantization_config=models.BinaryQuantization(
                binary=models.BinaryQuantizationConfig(always_ram=True)),
        )
        return models.CollectionInfo.model_construct(config=config)

    def create_collection(self, **kwargs):
        from qdrant_client import models

        # 镜像 1.19 高层客户端的请求组装（strict 模型校验）：HnswConfig 直接传会在这里炸
        models.CreateCollection(
            vectors=kwargs.get("vectors_config"),
            sparse_vectors=kwargs.get("sparse_vectors_config"),
            hnsw_config=kwargs.get("hnsw_config"),
            quantization_config=kwargs.get("quantization_config"),
        )
        self.created.append(kwargs)

    def create_payload_index(self, **kwargs):
        self.payload_indexes.append(kwargs)

    def scroll(self, **kwargs):
        self.scroll_calls.append(kwargs)
        return list(self._points), None

    def upsert(self, **kwargs):
        self.upsert_calls.append(kwargs)

    def get_collections(self):
        return SimpleNamespace(collections=[SimpleNamespace(name=n) for n in self._collections])

    def delete_collection(self, name):
        self.deleted_collections.append(name)


def _fake_point(i: int):
    return SimpleNamespace(
        id=f"p{i}", vector=[0.1] * 8,
        payload={"library_id": "lib-a", "doc_id": "a1", "record_id": f"r{i}"},
    )


class VectorSnapshotTests(unittest.TestCase):
    def _patched_snapshot(self):
        calls = []

        def fake_create(collection, qdrant_url=None):
            calls.append(("create", collection))
            return "snap-1", 4096

        def fake_delete(collection, name, qdrant_url=None):
            calls.append(("delete", collection, name))

        return calls, mock.patch.object(corpus_slicing, "create_snapshot", fake_create), \
            mock.patch.object(corpus_slicing, "delete_snapshot", fake_delete)

    def test_snapshot_copies_points_to_temp_collection_and_cleans_up(self):
        calls, p_create, p_delete = self._patched_snapshot()
        fake = _FakeQdrant(points=[_fake_point(i) for i in range(257)])  # 257→两批 upsert
        with p_create, p_delete:
            with library_vector_snapshot("lib-a", "coll-lib-a", client=fake) as snap:
                temp = snap["collection"]
                self.assertTrue(temp.startswith("exp-tmp-lib-a-"))
                self.assertEqual(snap["snapshot"], "snap-1")
                self.assertEqual(snap["size"], 4096)
                self.assertEqual(snap["points"], 257)
                self.assertTrue(snap["temporary"])
                self.assertEqual(calls, [("create", temp)])  # 退出前不清理
        # 临时集合配置克隆源集合（dim/metric/量化）+ HNSW 转 Diff + payload 索引
        from qdrant_client import models

        created = fake.created[0]
        self.assertEqual(created["collection_name"], temp)
        self.assertEqual(created["vectors_config"].size, 8)
        self.assertIsInstance(created["hnsw_config"], models.HnswConfigDiff)
        self.assertEqual((created["hnsw_config"].m, created["hnsw_config"].ef_construct), (16, 100))
        self.assertIsInstance(created["quantization_config"], models.BinaryQuantization)
        self.assertEqual(
            {c["field_name"] for c in fake.payload_indexes}, {"doc_id", "library_id"})
        # scroll 按 library_id 过滤、带向量
        scroll = fake.scroll_calls[0]
        self.assertEqual(scroll["collection_name"], "coll-lib-a")
        self.assertTrue(scroll["with_vectors"])
        cond = scroll["scroll_filter"].must[0]
        self.assertEqual((cond.key, cond.match.value), ("library_id", "lib-a"))
        # upsert 保 point id + payload 原样、分两批（256+1）
        self.assertEqual([len(c["points"]) for c in fake.upsert_calls], [256, 1])
        first = fake.upsert_calls[0]["points"][0]
        self.assertEqual(first.id, "p0")
        self.assertEqual(first.payload["record_id"], "r0")
        # 退出即清理：删快照 + 删临时集合
        self.assertEqual(calls[-1], ("delete", temp, "snap-1"))
        self.assertEqual(fake.deleted_collections, [temp])

    def test_snapshot_exclusive_skips_copy(self):
        calls, p_create, p_delete = self._patched_snapshot()
        fake = _FakeQdrant()
        with p_create, p_delete:
            with library_vector_snapshot("lib-a", "coll-solo", exclusive=True, client=fake) as snap:
                self.assertEqual(snap["collection"], "coll-solo")
                self.assertFalse(snap["temporary"])
                self.assertIsNone(snap["points"])
        self.assertEqual(fake.created, [])
        self.assertEqual(fake.scroll_calls, [])
        self.assertEqual(calls, [("create", "coll-solo"), ("delete", "coll-solo", "snap-1")])
        self.assertEqual(fake.deleted_collections, [])  # 源集合不许动

    def test_library_owns_collection_exclusively(self):
        seen = {}

        def fake_list(*, include_retired=False):
            seen["include_retired"] = include_retired
            return [
                SimpleNamespace(library_id="lib-a", collection="c1"),
                SimpleNamespace(library_id="lib-b", collection="c1"),
            ]

        with mock.patch.object(corpus_slicing.library_registry, "list_libraries", fake_list):
            self.assertFalse(library_owns_collection_exclusively("lib-a", "c1"))
            self.assertTrue(seen["include_retired"])  # 退役库残留向量也在源集合里，必须计入
            self.assertFalse(library_owns_collection_exclusively("lib-x", "c1"))
        with mock.patch.object(
            corpus_slicing.library_registry, "list_libraries",
            lambda *, include_retired=False: [SimpleNamespace(library_id="lib-a", collection="c1")],
        ):
            self.assertTrue(library_owns_collection_exclusively("lib-a", "c1"))
        self.assertFalse(library_owns_collection_exclusively("lib-a", ""))  # 空 collection 无独占可言

    def test_cleanup_stale_temp_collections(self):
        fake = _FakeQdrant(collections=["exp-tmp-loan-1", "lib-a", "exp-tmp-x-2", "default"])
        removed = cleanup_stale_temp_collections(client=fake)
        self.assertEqual(removed, ["exp-tmp-loan-1", "exp-tmp-x-2"])
        self.assertEqual(fake.deleted_collections, ["exp-tmp-loan-1", "exp-tmp-x-2"])


if __name__ == "__main__":
    unittest.main()
