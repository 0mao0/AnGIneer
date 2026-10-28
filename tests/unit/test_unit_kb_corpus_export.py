"""语料包 v2 导出契约测试：大包（bundle）套每库小包（library），每库自包含、两层 sha256 可对账。"""
import gc
import hashlib
import io
import json
import os
import sqlite3
import sys
import tempfile
import unittest
import zipfile
from contextlib import ExitStack, closing, contextmanager
from pathlib import Path
from unittest import mock

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../../services/docs-core/src")))

from docs_core import corpus_package, corpus_slicing  # noqa: E402


def _seed_registry(root: Path) -> None:
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
        conn.executemany(
            "INSERT INTO library_registry VALUES (?,?,?,?,?,?,?,?,?)",
            [
                ("lib-a", "库A", "", "standards", "knowledge/groups/standards.sqlite", "coll-a", "active", "t", "t"),
                ("lib-b", "库B", "", "standards", "knowledge/groups/standards.sqlite", "coll-b", "active", "t", "t"),
            ],
        )
        conn.execute("INSERT INTO library_groups VALUES ('standards','规范','t','t')")
        conn.commit()


def _seed_group(root: Path) -> None:
    """两库共用的组 sqlite（a1/a2∈lib-a，b1∈lib-b；FTS 可检索列=text_ngrams）。"""
    path = root / "knowledge" / "groups" / "standards.sqlite"
    path.parent.mkdir(parents=True, exist_ok=True)
    with closing(sqlite3.connect(path)) as conn:
        conn.executescript(
            """
            CREATE TABLE canonical_documents (doc_id TEXT PRIMARY KEY, library_id TEXT NOT NULL, title TEXT);
            CREATE TABLE canonical_pages (doc_id TEXT NOT NULL, page_idx INTEGER, text TEXT);
            CREATE TABLE canonical_chunks (chunk_id TEXT PRIMARY KEY, doc_id TEXT NOT NULL,
                                           chunk_type TEXT, text_clean TEXT, updated_at TEXT);
            CREATE TABLE doc_blocks (block_id TEXT PRIMARY KEY, doc_id TEXT NOT NULL, text TEXT);
            CREATE VIRTUAL TABLE canonical_chunk_fts USING fts5(
                chunk_id UNINDEXED, doc_id UNINDEXED, chunk_type UNINDEXED,
                section_path, text_clean UNINDEXED, text_ngrams, tokenize = 'unicode61');
            CREATE INDEX idx_canonical_chunks_doc ON canonical_chunks(doc_id);
            """
        )
        conn.executemany(
            "INSERT INTO canonical_documents VALUES (?,?,?)",
            [("a1", "lib-a", "A 文档"), ("a2", "lib-a", "A 文档二"), ("b1", "lib-b", "B 文档")],
        )
        conn.execute("INSERT INTO canonical_pages VALUES ('a1', 0, 'pa')")
        conn.executemany(
            "INSERT INTO canonical_chunks VALUES (?,?,?,?,?)",
            [("c1", "a1", "clause", "waterway alpha", "t"),
             ("c2", "a2", "clause", "waterway beta", "t"),
             ("c3", "b1", "clause", "waterway other", "t")],
        )
        conn.execute("INSERT INTO doc_blocks VALUES ('bl1','a1','x')")
        conn.executemany(
            "INSERT INTO canonical_chunk_fts (chunk_id, doc_id, chunk_type, section_path, text_clean, text_ngrams) "
            "VALUES (?,?,?,?,?,?)",
            [
                ("c1", "a1", "clause", "1.1", "waterway alpha", "wa at te er rg eg gu ul la"),
                ("c2", "a2", "clause", "1.2", "waterway beta", "wa at te er rg eg gu ul la"),
                ("c3", "b1", "clause", "1.1", "waterway other", "wa at te er ot th he er"),
            ],
        )
        conn.commit()


def _seed_graph(root: Path) -> None:
    """两库图谱：lib-a 关系端点 e3 与 principle 联结引用 e3 均归属 lib-b（闭包场景）。"""
    from docs_core.step07_graph.graph_store import GraphStore  # noqa: PLC0415

    path = root / "knowledge" / "graph.sqlite"
    GraphStore(str(path)).close()
    gc.collect()  # GraphStore 初始化连接进引用循环，不 gc 则 Windows 锁文件
    with closing(sqlite3.connect(path)) as conn:
        conn.execute("PRAGMA foreign_keys=ON")
        conn.executemany(
            "INSERT INTO graph_entities (entity_id, name, layer, library_id, created_at, updated_at) "
            "VALUES (?,?,?,?,?,?)",
            [("e1", "实体一", "concept", "lib-a", "t", "t"),
             ("e2", "实体二", "condition", "lib-a", "t", "t"),
             ("e3", "共用实体", "concept", "lib-b", "t", "t"),
             ("e4", "B库独有", "concept", "lib-b", "t", "t")],
        )
        conn.executemany(
            "INSERT INTO graph_relations (relation_id, source_id, target_id, relation_type, "
            "library_id, doc_id, created_at, updated_at) VALUES (?,?,?,?,?,?,?,?)",
            [("r1", "e1", "e2", "requires", "lib-a", "a1", "t", "t"),
             ("r2", "e1", "e3", "defines", "lib-a", "a1", "t", "t"),
             ("r3", "e3", "e4", "requires", "lib-b", "b1", "t", "t")],
        )
        conn.execute(
            "INSERT INTO graph_principles (principle_id, principle_text, library_id, doc_id, created_at) "
            "VALUES ('p1','原则一','lib-a','a1','t')")
        conn.executemany(
            "INSERT INTO principle_entities (principle_id, entity_id) VALUES (?,?)",
            [("p1", "e1"), ("p1", "e3")],
        )
        conn.commit()


def _seed_meta(root: Path) -> None:
    meta = root / "knowledge" / "knowledge_meta.sqlite"
    meta.parent.mkdir(parents=True, exist_ok=True)
    with closing(sqlite3.connect(meta)) as conn:
        conn.executescript(
            """
            CREATE TABLE nodes (id TEXT PRIMARY KEY, library_id TEXT, file_path TEXT);
            CREATE TABLE tree_node (node_id TEXT PRIMARY KEY, scope_id TEXT, extra_json TEXT);
            CREATE TABLE libraries (id TEXT PRIMARY KEY, name TEXT NOT NULL,
                                    description TEXT, created_at TEXT NOT NULL, updated_at TEXT NOT NULL);
            """
        )
        conn.executemany(
            "INSERT INTO nodes VALUES (?,?,?)",
            [("n1", "lib-a", "knowledge/libraries/lib-a/documents/d1/source/a.pdf"),
             # n2 是数据迁移契约的雷（旧绝对路径形态）：必须进 warnings 不进 blocker
             ("n2", "lib-a", "data\\knowledge_base\\old\\x.pdf"),
             ("n3", "lib-b", "knowledge/libraries/lib-b/documents/d2/source/b.pdf")],
        )
        conn.executemany(
            "INSERT INTO tree_node VALUES (?,?,?)",
            [("n1", "lib-a", "{}"), ("n3", "lib-b", "{}")],
        )
        conn.executemany(
            "INSERT INTO libraries VALUES (?,?,?,?,?)",
            [("lib-a", "库A", "", "t", "t"), ("lib-other", "别的库", "", "t", "t")],
        )
        conn.commit()


def _seed_files(root: Path) -> None:
    for rel, data in [
        ("knowledge/libraries/lib-a/documents/d1/source/a.pdf", b"%PDF-1.5 fake a"),
        ("knowledge/libraries/lib-a/documents/d1/parsed/text.json", b"{}"),
        ("knowledge/libraries/lib-a/documents/d1/parsed/mineru_raw/raw.json", b"raw"),  # 排除
        ("knowledge/libraries/lib-a/index.sqlite", b"STALE-SLICE"),  # lib 根旧切片，排除
        ("knowledge/libraries/lib-b/documents/d2/source/b.pdf", b"%PDF-1.5 fake b"),
    ]:
        p = root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(data)


def _seed_evals_library(root: Path) -> None:
    """evals 组：库根在 evals/corpora/libraries（P1-8 的回归夹具）。"""
    with closing(sqlite3.connect(root / "registry.sqlite")) as conn:
        conn.execute(
            "INSERT INTO library_registry VALUES (?,?,?,?,?,?,?,?,?)",
            ("lib-e", "评测库E", "", "evals", "evals/groups/evals_corpus.sqlite",
             "evals_corpus", "active", "t", "t"),
        )
        conn.commit()
    group = root / "evals" / "groups" / "evals_corpus.sqlite"
    group.parent.mkdir(parents=True, exist_ok=True)
    with closing(sqlite3.connect(group)) as conn:
        conn.executescript(
            """
            CREATE TABLE canonical_documents (doc_id TEXT PRIMARY KEY, library_id TEXT NOT NULL, title TEXT);
            CREATE TABLE canonical_chunks (chunk_id TEXT PRIMARY KEY, doc_id TEXT NOT NULL,
                                           chunk_type TEXT, text_clean TEXT, updated_at TEXT);
            """
        )
        conn.execute("INSERT INTO canonical_documents VALUES ('e1','lib-e','E 文档')")
        conn.execute("INSERT INTO canonical_chunks VALUES ('ce1','e1','clause','eval text','t')")
        conn.commit()
    with closing(sqlite3.connect(root / "knowledge" / "knowledge_meta.sqlite")) as conn:
        conn.execute(
            "INSERT INTO nodes VALUES (?,?,?)",
            ("ne1", "lib-e", "evals/corpora/libraries/lib-e/documents/d3/source/c.pdf"),
        )
        conn.execute("INSERT INTO tree_node VALUES (?,?,?)", ("ne1", "lib-e", "{}"))
        conn.execute(
            "INSERT INTO libraries VALUES (?,?,?,?,?)",
            ("lib-e", "评测库E", "", "t", "t"),
        )
        conn.commit()
    source = root / "evals/corpora/libraries/lib-e/documents/d3/source/c.pdf"
    source.parent.mkdir(parents=True, exist_ok=True)
    source.write_bytes(b"%PDF-1.5 eval")


def _fake_data_root(tmp: Path) -> Path:
    root = tmp / "data"
    root.mkdir(parents=True)
    _seed_registry(root)
    _seed_group(root)
    _seed_graph(root)
    _seed_meta(root)
    _seed_files(root)
    return root


class KbCorpusBundleV2Tests(unittest.TestCase):
    def setUp(self):
        self._td = tempfile.TemporaryDirectory()
        self.addCleanup(self._td.cleanup)
        self.tmp = Path(self._td.name)
        self.root = _fake_data_root(self.tmp)
        os.environ["ANGINEER_DATA_ROOT"] = str(self.root)
        os.environ["ANGINEER_REGISTRY_DB"] = str(self.root / "registry.sqlite")
        os.environ["EMBEDDING_CONFIGS"] = json.dumps([{"model": "qwen3-embed-8b"}])
        self.addCleanup(lambda: os.environ.pop("ANGINEER_DATA_ROOT", None))
        self.addCleanup(lambda: os.environ.pop("ANGINEER_REGISTRY_DB", None))
        self.addCleanup(lambda: os.environ.pop("EMBEDDING_CONFIGS", None))
        self.snap_calls = []

    def _qdrant_patches(self):
        @contextmanager
        def fake_snapshot(library_id, collection, *, exclusive=False, client=None):
            self.snap_calls.append((library_id, collection, exclusive))
            yield {"collection": f"exp-tmp-{library_id}-1", "snapshot": f"s-{library_id}",
                   "size": 16, "points": 3, "temporary": not exclusive}

        def fake_count(collection, library_id, qdrant_url=None):
            return {"coll-a": 3, "coll-b": 7}.get(collection, 0)

        return [
            mock.patch.object(corpus_slicing, "library_vector_snapshot", fake_snapshot),
            mock.patch.object(corpus_slicing, "cleanup_stale_temp_collections", lambda *a, **k: []),
            mock.patch.object(corpus_slicing, "library_owns_collection_exclusively", lambda *a, **k: False),
            mock.patch.object(corpus_package, "open_snapshot",
                              lambda collection, name, qdrant_url=None: io.BytesIO(f"SNAP:{name}".encode())),
            mock.patch.object(corpus_package, "count_points_filtered", fake_count),
        ]

    def _bundle(self, libs, **kwargs):
        with ExitStack() as stack:
            for p in self._qdrant_patches():
                stack.enter_context(p)
            data = b"".join(corpus_package.iter_bundle_zip(libs, data_root=self.root, **kwargs))
        return zipfile.ZipFile(io.BytesIO(data))

    # ------------------------------------------------------------- scan

    def test_scan_selection_per_library_detail(self):
        with ExitStack() as stack:
            for p in self._qdrant_patches():
                stack.enter_context(p)
            result = corpus_package.scan_selection(self.root, ["lib-a", "lib-b"])
        libs = {r["library_id"]: r for r in result["libraries"]}
        self.assertEqual(set(libs), {"lib-a", "lib-b"})
        self.assertEqual(libs["lib-a"]["counts"], {"docs": 2, "chunks": 2})
        self.assertEqual(libs["lib-b"]["counts"], {"docs": 1, "chunks": 1})
        self.assertEqual(libs["lib-a"]["vector_points"], 3)
        self.assertEqual(libs["lib-b"]["vector_points"], 7)
        # files 字节 = 本库目录树（排除 mineru_raw 与 lib 根 index.sqlite）
        expected_a = (
            (self.root / "knowledge/libraries/lib-a/documents/d1/source/a.pdf").stat().st_size
            + (self.root / "knowledge/libraries/lib-a/documents/d1/parsed/text.json").stat().st_size
        )
        self.assertEqual(libs["lib-a"]["files_bytes"], expected_a)
        # sqlite 估算 = 组库体积 × 本库 chunk 占比（仅参考值）
        group_size = (self.root / "knowledge/groups/standards.sqlite").stat().st_size
        self.assertEqual(libs["lib-a"]["sqlite_estimate"], int(group_size * 2 / 3))
        # totals 汇总；无同组警告、无 peers 概念
        self.assertEqual(result["totals"]["vector_points"], 10)
        self.assertEqual(result["totals"]["files_bytes"], sum(r["files_bytes"] for r in result["libraries"]))
        self.assertFalse([w for w in result.get("warnings", []) if "同组" in w])
        self.assertNotIn("peers", result)
        with self.assertRaises(ValueError):
            corpus_package.scan_selection(self.root, ["lib-not-exist"])

    # ------------------------------------------------------------- bundle

    def _assert_inner_single_lib(self, outer, lib_id):
        inner_bytes = outer.read(f"libraries/{lib_id}.zip")
        inner = zipfile.ZipFile(io.BytesIO(inner_bytes))
        names = set(inner.namelist())
        self.assertIn("manifest.json", names)
        self.assertIn("registry/rows.json", names)
        self.assertIn("meta/rows.json", names)
        self.assertIn("index/index.sqlite", names)
        self.assertIn("graph/graph.sqlite", names)
        iman = json.loads(inner.read("manifest.json"))
        # 内层 sha256 全覆盖可对账
        self.assertEqual(set(iman["files"]), names - {"manifest.json"})
        for rel, digest in iman["files"].items():
            self.assertEqual(hashlib.sha256(inner.read(rel)).hexdigest(), digest, rel)
        return inner, names, iman

    def test_bundle_single_library_self_contained(self):
        outer = self._bundle(["lib-a"])
        self.assertEqual(set(outer.namelist()), {"manifest.json", "libraries/lib-a.zip"})
        oman = json.loads(outer.read("manifest.json"))
        self.assertEqual(oman["kind"], "bundle")
        self.assertEqual(oman["schema_version"], 2)
        self.assertEqual(oman["embed_model"], "qwen3-embed-8b")
        self.assertEqual(oman["page_base"], 0)
        inner_bytes = outer.read("libraries/lib-a.zip")
        entry = oman["libraries"][0]
        self.assertEqual(entry["library_id"], "lib-a")
        self.assertEqual(entry["group_name"], "standards")
        self.assertEqual(entry["entry"], "libraries/lib-a.zip")
        self.assertEqual(entry["bytes"], len(inner_bytes))
        self.assertEqual(entry["sha256"], hashlib.sha256(inner_bytes).hexdigest())
        self.assertEqual(oman["files"]["libraries/lib-a.zip"], entry["sha256"])
        self.assertEqual(entry["counts"]["docs"], 2)

        inner, names, iman = self._assert_inner_single_lib(outer, "lib-a")
        self.assertEqual(iman["kind"], "library")
        self.assertEqual(iman["library_id"], "lib-a")
        self.assertEqual(iman["schema_version"], 2)
        self.assertEqual(iman["page_base"], 0)
        self.assertEqual(iman["embed_model"], "qwen3-embed-8b")
        # 自包含条目集：文档树只含本库（排除 mineru_raw 与 lib 根 index.sqlite）
        self.assertEqual(names, {
            "manifest.json", "registry/rows.json", "meta/rows.json",
            "index/index.sqlite", "graph/graph.sqlite", "qdrant/vectors.snapshot",
            "files/knowledge/libraries/lib-a/documents/d1/source/a.pdf",
            "files/knowledge/libraries/lib-a/documents/d1/parsed/text.json",
        })
        # counts：切片实测（docs/chunks=sqlite 切片；vectors=快照点数；graph=闭包切片）
        self.assertEqual(iman["counts"]["docs"], 2)
        self.assertEqual(iman["counts"]["chunks"], 2)
        self.assertEqual(iman["counts"]["vectors"], 3)
        self.assertEqual(iman["counts"]["graph_relations"], 2)
        self.assertEqual(iman["counts"]["graph_tables"]["graph_entities"], 3)
        # registry 原样（含原 sqlite_file/collection 供追溯）+ 其组行
        reg = json.loads(inner.read("registry/rows.json"))
        self.assertEqual([r["library_id"] for r in reg["libraries"]], ["lib-a"])
        self.assertEqual(reg["libraries"][0]["sqlite_file"], "knowledge/groups/standards.sqlite")
        self.assertEqual(reg["libraries"][0]["collection"], "coll-a")
        self.assertEqual([g["group_name"] for g in reg["groups"]], ["standards"])
        # meta：本库 nodes/tree_node + meta libraries 行（修复 F10 缺口）
        meta_rows = json.loads(inner.read("meta/rows.json"))
        self.assertEqual({r["id"] for r in meta_rows["nodes"]}, {"n1", "n2"})
        self.assertEqual([r["node_id"] for r in meta_rows["tree_nodes"]], ["n1"])
        self.assertEqual([r["id"] for r in meta_rows["libraries"]], ["lib-a"])
        # file_path 守卫：非规范相对路径逐条告警（不阻断）
        self.assertTrue(any("n2" in w for w in iman["warnings"]))
        self.assertFalse(any("n1" in w for w in iman["warnings"]))
        # index 切片可查询（写临时文件开 sqlite；FTS 命中的只有本库行）
        idx = self.tmp / "inner-index.sqlite"
        idx.write_bytes(inner.read("index/index.sqlite"))
        with closing(sqlite3.connect(idx)) as conn:
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM canonical_documents").fetchone()[0], 2)
            hits = [r[0] for r in conn.execute(
                "SELECT chunk_id FROM canonical_chunk_fts WHERE canonical_chunk_fts MATCH 'rg' "
                "ORDER BY chunk_id")]
        self.assertEqual(hits, ["c1", "c2"])
        # 快照曾被拉取且带库过滤入口（temp 拷贝路径）
        self.assertEqual(self.snap_calls, [("lib-a", "coll-a", False)])

    def test_bundle_two_libraries_are_independent(self):
        outer = self._bundle(["lib-a", "lib-b"])
        self.assertEqual(set(outer.namelist()),
                         {"manifest.json", "libraries/lib-a.zip", "libraries/lib-b.zip"})
        oman = json.loads(outer.read("manifest.json"))
        self.assertEqual({e["library_id"] for e in oman["libraries"]}, {"lib-a", "lib-b"})
        inner_b, names_b, iman_b = self._assert_inner_single_lib(outer, "lib-b")
        # 小包自包含：不混入别库文件/元数据
        self.assertIn("files/knowledge/libraries/lib-b/documents/d2/source/b.pdf", names_b)
        self.assertFalse([n for n in names_b if "lib-a" in n])
        meta_b = json.loads(inner_b.read("meta/rows.json"))
        self.assertEqual({r["id"] for r in meta_b["nodes"]}, {"n3"})
        self.assertEqual(iman_b["counts"]["docs"], 1)
        # lib-b 图谱闭包 = 本库行 {e3,e4}（r3 端点），不含 lib-a 独有实体
        self.assertEqual(iman_b["counts"]["graph_relations"], 1)
        self.assertEqual(iman_b["counts"]["graph_tables"]["graph_entities"], 2)

    def test_bundle_without_vectors_skips_snapshot(self):
        outer = self._bundle(["lib-a"], with_vectors=False)
        _, names, iman = self._assert_inner_single_lib(outer, "lib-a")
        self.assertNotIn("qdrant/vectors.snapshot", names)
        self.assertEqual(iman["counts"]["vectors"], 0)
        self.assertEqual(self.snap_calls, [])

    def test_bundle_library_without_graph_succeeds(self):
        """回归（2026-10-28 生产实踩）：图谱拆分迁移把全局 graph.sqlite 改名后，
        无本库 graph 文件的库导出走 else 分支——旧代码 closing(...).close() 在
        Py3.11 直接 AttributeError，整包导出 failed。修后须照常出包（空 graph 占位）。"""
        (self.root / "knowledge" / "graph.sqlite").rename(
            self.root / "knowledge" / "graph.sqlite.migrated-tmp")
        outer = self._bundle(["lib-a"])
        inner, names, iman = self._assert_inner_single_lib(outer, "lib-a")
        self.assertIn("graph/graph.sqlite", names)
        self.assertEqual(iman["counts"]["graph_relations"], 0)
        # 占位文件必须是有效 sqlite（0 字节约会拖垮导入侧）
        gpath = self.tmp / "empty-graph-check.sqlite"
        gpath.write_bytes(inner.read("graph/graph.sqlite"))
        con = sqlite3.connect(gpath)
        try:
            self.assertEqual(con.execute("select count(*) from sqlite_master").fetchone()[0], 0)
        finally:
            con.close()

    def test_bundle_finds_per_library_graph_file(self):
        """回归（2026-10-28 生产实踩）：图谱按 library_root 存库文件、注册表 sqlite_file
        却指 groups/*.sqlite，旧导出拿 sqlite_file 父目录找图谱 → 本库 707 条 relations
        静默清零出包。修后解析器与运行时读写同源，必须切出真实闭包。"""
        global_g = self.root / "knowledge" / "graph.sqlite"
        lib_a_g = self.root / "knowledge" / "libraries" / "lib-a" / "graph.sqlite"
        lib_a_g.write_bytes(global_g.read_bytes())  # 模拟拆分迁移：图谱已入本库文件
        global_g.rename(self.root / "knowledge" / "graph.sqlite.migrated-tmp")
        outer = self._bundle(["lib-a"])
        inner, _names, iman = self._assert_inner_single_lib(outer, "lib-a")
        self.assertEqual(iman["counts"]["graph_relations"], 2)
        self.assertGreater(iman["counts"]["graph_tables"].get("graph_entities", 0), 0)

    def test_evals_group_files_follow_group_root(self):
        _seed_evals_library(self.root)
        with ExitStack() as stack:
            for p in self._qdrant_patches():
                stack.enter_context(p)
            preview = corpus_package.scan_selection(self.root, ["lib-e"])
        lib = preview["libraries"][0]
        expected = (
            self.root / "evals/corpora/libraries/lib-e/documents/d3/source/c.pdf"
        ).stat().st_size
        self.assertEqual(lib["files_bytes"], expected)

        outer = self._bundle(["lib-e"], with_vectors=False)
        inner = zipfile.ZipFile(io.BytesIO(outer.read("libraries/lib-e.zip")))
        names = set(inner.namelist())
        self.assertIn(
            "files/evals/corpora/libraries/lib-e/documents/d3/source/c.pdf", names
        )
        self.assertFalse([n for n in names if n.startswith("files/knowledge/libraries/lib-e/")])
        iman = json.loads(inner.read("manifest.json"))
        self.assertFalse([w for w in iman["warnings"] if "file_path" in w])


if __name__ == "__main__":
    unittest.main()
