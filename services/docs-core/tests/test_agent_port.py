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
