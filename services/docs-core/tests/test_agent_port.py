# -*- coding: utf-8 -*-
"""agent_port 适配器测试（C1 Seam 4，2026-09-19）。

配方本体（五路召回 + fuse + 表格兜底 / 统计聚合 / 引用挑选）从
angineer_core.agent_tools 平移到本模块，测试随代码搬来、语义不变；
引擎侧只保留「端口接线 + 装配层」测试。
"""
import os
import sys
from pathlib import Path

SERVICES = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(SERVICES / "docs-core" / "src"))

from docs_core.step09_query import agent_port  # noqa: E402
from docs_core.step09_query.protocols.contracts import RetrievedItem  # noqa: E402


class TestNormalizeQuery:
    def test_chinese_clause_numbers(self):
        assert agent_port.normalize_query("第六十条 航道") == "第60条 航道"

    def test_plain_query_unchanged(self):
        assert agent_port.normalize_query("普通查询") == "普通查询"


class TestKnowledgeLocalSearchFormula:
    def test_formula_query_includes_formula_context(self, monkeypatch):
        from unittest.mock import patch

        fake_item = RetrievedItem(
            item_id="ctx-1",
            entity_type="formula_context",
            doc_id="d1",
            title="6.2 航道建设规模及航行标准",
            text="式中 t_{1} ——每潮次船舶通过航道的持续时间(h)",
            score=10.0,
            retrieval_policy="formula_context",
            metadata={"source_kind": "formula_context", "chunk_type": "formula_context"},
        )
        with patch("docs_core.step09_query.retrieval.formula_retriever.FormulaRetriever") as cls:
            cls.return_value.retrieve.return_value = [fake_item]
            result = agent_port.knowledge_local_search(
                query="乘潮进港时间怎么算",
                library_id="default",
                doc_ids=[],
                top_k=20,
                task_type="content_qa",
                nodes=[],
            )
        items = result.get("items") or []
        assert any(getattr(it, "item_id", None) == "ctx-1" for it in items)

    def test_non_formula_query_skips_formula_retriever(self, monkeypatch):
        from unittest.mock import patch

        with patch("docs_core.step09_query.retrieval.formula_retriever.FormulaRetriever") as cls:
            agent_port.knowledge_local_search(
                query="上航数联是什么",
                library_id="default",
                doc_ids=[],
                top_k=20,
                task_type="content_qa",
                nodes=[],
            )
        cls.assert_not_called()


class TestStageTimesSurface:
    """方案 E（req-table-retrieval-latency §10）：stage_times 随返回值上浮，docs-core 不感知观测设施。"""

    class _Stub:
        def retrieve(self, *args, **kwargs):
            return []

    def test_knowledge_local_search_returns_stage_times(self):
        result = agent_port.knowledge_local_search(
            query="乘潮进港时间怎么算",
            library_id="default",
            doc_ids=[],
            top_k=20,
            nodes=[],
            dense=self._Stub(),
            sparse=self._Stub(),
            clause=self._Stub(),
            formula=self._Stub(),
        )
        stages = result.get("stage_times")
        assert isinstance(stages, dict)
        assert {"dense", "sparse", "clause", "fuse"} <= set(stages)
        assert all(isinstance(v, float) for v in stages.values())

    def test_table_local_search_returns_stage_times(self):
        result = agent_port.table_local_search(
            query="码头前沿水深富裕高度 散货船 5万吨级 规范",
            library_id="default",
            doc_ids=[],
            top_k=20,
            nodes=[],
            table=self._Stub(),
            formula=self._Stub(),
        )
        stages = result.get("stage_times")
        assert isinstance(stages, dict)
        assert {"table", "formula", "fuse"} <= set(stages)
        assert all(isinstance(v, float) for v in stages.values())


class TestRelevantCitations:
    def test_marker_and_target_id(self):
        items = [
            RetrievedItem(item_id="a", entity_type="content", doc_id="d1", title="t1",
                          text="船闸规范 闸门有 4 个等级", score=1.0,
                          metadata={"doc_title": "船闸规范.pdf", "cite": "K1"}),
            RetrievedItem(item_id="b", entity_type="content", doc_id="d2", title="t2",
                          text="海港 航道 2 级", score=1.0,
                          metadata={"doc_title": "海港2.pdf", "cite": "K2"}),
        ]
        citations = agent_port.relevant_citations("船闸规范", items)
        assert citations[0]["marker"] == "K1"
        assert citations[0]["target_id"] == "a"

    def test_empty_items(self):
        assert agent_port.relevant_citations("任意", []) == []

    def test_default_covers_all_markers(self):
        """默认 limit=None：解析表必须覆盖全部 cite（2026-10-22 答案引用 K6+ 回退 doc_id）。"""
        items = [
            RetrievedItem(item_id=f"i{i}", entity_type="content", doc_id=f"d{i}", title=f"t{i}",
                          text=("船闸规范 闸门" if i == 10 else "海港 航道") + f" 第{i}条",
                          score=1.0, metadata={"cite": f"K{i}"})
            for i in range(1, 16)
        ]
        citations = agent_port.relevant_citations("船闸规范", items)
        assert len(citations) == 15
        assert {c["marker"] for c in citations} == {f"K{i}" for i in range(1, 16)}
        assert citations[0]["marker"] == "K10"  # 短语命中优先，其余按原顺序

    def test_explicit_limit_keeps_display_semantics(self):
        items = [
            RetrievedItem(item_id=f"i{i}", entity_type="content", doc_id=f"d{i}", title=f"t{i}",
                          text=("船闸规范" if i in (1, 2) else "海港") + f" 第{i}条",
                          score=1.0, metadata={"cite": f"K{i}"})
            for i in range(1, 6)
        ]
        citations = agent_port.relevant_citations("船闸规范", items, limit=5)
        assert len(citations) == 2  # 旧语义：只取命中项


class TestLocalStatsTitles:
    def _build_dbs(self, tmp_path, doc_count):
        import sqlite3

        (tmp_path / "data").mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(tmp_path / "meta.sqlite")
        conn.execute(
            "CREATE TABLE nodes (id TEXT PRIMARY KEY, title TEXT, status TEXT,"
            " deleted INTEGER DEFAULT 0, library_id TEXT DEFAULT 'default')"
        )
        conn.execute("CREATE TABLE doc_parse_stages (doc_id TEXT, stage TEXT, page_count INTEGER)")
        conn.execute("CREATE TABLE libraries (id TEXT PRIMARY KEY, name TEXT)")
        conn.execute("INSERT INTO libraries VALUES ('default','默认库')")
        for i in range(doc_count):
            conn.execute(
                "INSERT INTO nodes VALUES (?,?,?,?,?)",
                (f"d{i}", f"规范文档{i:03d}", "completed", 0, "default"),
            )
            conn.execute("INSERT INTO doc_parse_stages VALUES (?,?,?)", (f"d{i}", "raw_parse", 10 + i))
        conn.execute("INSERT INTO nodes VALUES (?,?,?,?,?)", ("gone", "已删除文档", "completed", 1, "default"))
        conn.commit()
        conn.close()
        rconn = sqlite3.connect(tmp_path / "data" / "parse_records.sqlite")
        rconn.execute(
            "CREATE TABLE parse_records (id TEXT, status TEXT, library_id TEXT,"
            " created_at TEXT, file_format TEXT, file_size INTEGER)"
        )
        for i in range(doc_count):
            rconn.execute(
                "INSERT INTO parse_records VALUES (?,?,?,?,?,?)",
                (f"d{i}", "done", "default", "2026-09-01T00:00:00", "pdf", 1024),
            )
        rconn.commit()
        rconn.close()

    def _run(self, tmp_path, doc_count, monkeypatch):
        self._build_dbs(tmp_path, doc_count)
        import docs_core.paths as docs_paths

        monkeypatch.setattr(docs_paths, "resolve_knowledge_meta_db_path", lambda: tmp_path / "meta.sqlite")
        monkeypatch.setattr(docs_paths, "resolve_repo_root", lambda: tmp_path)
        return agent_port.local_stats("default")

    def test_titles_enumeration_field(self, tmp_path, monkeypatch):
        docs = self._run(tmp_path, 3, monkeypatch)["documents"]
        titles = docs["titles"]
        assert [t["title"] for t in titles] == ["规范文档000", "规范文档001", "规范文档002"]
        assert all(t["status"] == "completed" for t in titles)
        assert docs["titles_total"] == 3
        assert not docs["titles_truncated"]

    def test_titles_capped_and_truncated(self, tmp_path, monkeypatch):
        docs = self._run(tmp_path, 105, monkeypatch)
        docs = docs["documents"]
        assert len(docs["titles"]) == 100
        assert docs["titles_truncated"]
        assert docs["titles_total"] == 105


def test_knowledge_local_search_passes_library_ids():
    """A7（现码校准）：knowledge_local_search 是进程内本地召回配方、不经 retrieve_knowledge
    （计划的 mock 目标不存在）——改用伪检索器验证多库集合透传进 KnowledgeQueryRequest。"""
    from docs_core.step09_query import agent_port

    captured = []

    class _Capturing:
        def retrieve(self, request, nodes, *args):
            captured.append(request)
            return []

    agent_port.knowledge_local_search(
        query="q", library_id="libA", library_ids=["libA", "libB"], top_k=20,
        nodes=[], dense=_Capturing(), sparse=_Capturing(), clause=_Capturing(),
    )
    assert captured  # 三路检索器均被调用
    assert all(request.library_ids == ["libA", "libB"] for request in captured)
    assert all(request.library_id == "libA" for request in captured)


class TestItemLibraryTags:
    """逐条库标回填（2026-10-16 引用 404 修复）：多库会话里条目必须自带库归属，
    否则引擎侧引用/证据只能回退会话首库，非首库文档必 404「Document not found」。"""

    class _Items:
        def __init__(self, items):
            self._items = items

        def retrieve(self, *args, **kwargs):
            return list(self._items)

    class _Empty:
        def retrieve(self, *args, **kwargs):
            return []

    @staticmethod
    def _nodes():
        from types import SimpleNamespace

        # 两个库的节点：doc-a 在 libA（会话首库），doc-b 在 libB（非首库）
        return [
            SimpleNamespace(id="doc-a", library_id="libA", type="document"),
            SimpleNamespace(id="doc-b", library_id="libB", type="document"),
        ]

    @staticmethod
    def _item(doc_id, cite):
        return RetrievedItem(
            item_id=f"chunk-{doc_id}:1:1", entity_type="paragraph", doc_id=doc_id,
            title="t", text=f"《规范》{cite} 正文", score=1.0, rerank_score=0.9,
            metadata={"cite": cite},
        )

    def test_knowledge_items_tagged_by_node_library(self):
        from docs_core.step09_query import agent_port

        items = [self._item("doc-a", "K1"), self._item("doc-b", "K2")]
        result = agent_port.knowledge_local_search(
            query="内河航道养护有什么技术要求", library_id="libA",
            library_ids=["libA", "libB"], top_k=20, task_type="content_qa",
            nodes=self._nodes(), dense=self._Items(items), sparse=self._Empty(), clause=self._Empty(),
        )
        tagged = {item.doc_id: item.metadata.get("library_id") for item in result["items"]}
        assert tagged.get("doc-a") == "libA"
        assert tagged.get("doc-b") == "libB"

    def test_table_items_tagged_by_node_library(self):
        from docs_core.step09_query import agent_port

        result = agent_port.table_local_search(
            query="航道维护尺度 取值", library_id="libA", top_k=20,
            nodes=self._nodes(), table=self._Items([self._item("doc-b", "T1")]), formula=self._Empty(),
        )
        assert result["items"][0].metadata.get("library_id") == "libB"

    @staticmethod
    def _patch_docs_service(monkeypatch, fake):
        """补丁打在真模块上：包属性 `docs_core.docs_service` 是单例代理，
        而适配器走 `from docs_core.docs_service import get_docs_service`（取真模块）。"""
        import sys

        import docs_core.docs_service  # noqa: F401 — 确保真模块已进 sys.modules

        monkeypatch.setattr(sys.modules["docs_core.docs_service"], "get_docs_service", fake)

    def test_unknown_doc_not_tagged_with_first_library(self, monkeypatch):
        """取不到归属宁可不标：按首库猜会把引用与证据的库归属一起写错。"""
        from docs_core.step09_query import agent_port
        from types import SimpleNamespace

        self._patch_docs_service(
            monkeypatch,
            lambda: (_ for _ in ()).throw(RuntimeError("meta 库不可用")),
        )
        result = agent_port.knowledge_local_search(
            query="内河航道养护有什么技术要求", library_id="libA",
            library_ids=["libA", "libB"], top_k=20, task_type="content_qa",
            nodes=[SimpleNamespace(id="doc-x", type="document")],  # 节点不带库标
            dense=self._Items([self._item("doc-x", "K1")]), sparse=self._Empty(), clause=self._Empty(),
        )
        assert "library_id" not in result["items"][0].metadata

    def test_node_without_library_reads_through_meta_store(self, monkeypatch):
        """外部注入节点可能不带库标：读 meta 库穿一次（同 retrieve_service._retrieve_multi）。"""
        from docs_core.step09_query import agent_port
        from types import SimpleNamespace

        class _Meta:
            def get_node_library_id(self, doc_id):
                return "libB" if doc_id == "doc-b" else ""

        self._patch_docs_service(
            monkeypatch,
            lambda: SimpleNamespace(meta_store=_Meta()),
        )
        result = agent_port.knowledge_local_search(
            query="内河航道养护有什么技术要求", library_id="libA",
            library_ids=["libA", "libB"], top_k=20, task_type="content_qa",
            nodes=[SimpleNamespace(id="doc-b", type="document")],
            dense=self._Items([self._item("doc-b", "K1")]), sparse=self._Empty(), clause=self._Empty(),
        )
        assert result["items"][0].metadata.get("library_id") == "libB"
