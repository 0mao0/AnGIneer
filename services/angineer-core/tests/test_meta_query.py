# -*- coding: utf-8 -*-
"""meta_query（统计/元数据查询）通道测试。

覆盖：统计关键词规则、分类器规则优先、build_attempts 分支、knowledge_stats 本地直查。
"""
import sqlite3
import sys
from pathlib import Path

import pytest

SERVICES = Path(__file__).resolve().parents[3]
for pkg in ("angineer-core", "docs-core"):
    sys.path.insert(0, str(SERVICES / pkg / "src"))

from angineer_core.agent_policy import build_attempts
from angineer_core.agent_tools import StatsAdapter
from angineer_core.base_contracts import IntentResult
from angineer_core.classifier import IntentClassifier, _is_meta_query


class TestMetaQueryRule:
    @pytest.mark.parametrize("q", [
        "知识库有多少篇文档",
        "一共有多少篇文档？",
        "库里有哪些文档？",
        "文档数量的分布",
        "最近上传了多少份资料",
        "default 库里有多少篇文档",
        "有哪些知识库",
        "知识库文章数量",
    ])
    def test_positive(self, q):
        assert _is_meta_query(q)

    @pytest.mark.parametrize("q", [
        "波浪力分布规律是什么",          # 分布是工程词，无对象词
        "防波堤的设计规范有哪些",        # 规范不在对象词
        "如何计算码头前沿水深",
        "什么是港口吞吐量",
        "你好",
        "混凝土保护层最小厚度是多少",     # 多少 + 无对象词
    ])
    def test_negative(self, q):
        assert not _is_meta_query(q)


class TestClassifierMetaFirst:
    def test_meta_query_rule_precedes_llm(self):
        """统计问题应由规则直接命中 meta_query，不落入 LLM/语义检索。"""
        clf = IntentClassifier(sops=[])
        result = clf.classify_intent("知识库有多少篇文档")
        assert result.service_mode == "meta_query"
        assert result.intent_level == "L1"

    def test_engineering_question_not_meta(self):
        """工程内容问题不应被 meta 规则拦截。"""
        clf = IntentClassifier(sops=[])
        result = clf.classify_intent("防波堤的设计波浪要素有哪些")
        assert result.service_mode != "meta_query"


class TestBuildAttempts:
    def _intent(self, service_mode, level="L1"):
        return IntentResult(intent_level=level, service_mode=service_mode)

    def test_meta_query_branch(self):
        attempts = build_attempts(
            intent_result=self._intent("meta_query"),
            scene="docs", library_id="default", doc_ids=[],
            load_nodes=lambda: [], llm_factory=lambda: None,
        )
        assert len(attempts) == 1
        assert attempts[0].name == "统计/元数据查询"
        assert attempts[0].requires_tools is True

    def test_meta_query_overrides_other_levels(self):
        """即使 level 被判成 L2，service_mode=meta_query 也走统计通道。"""
        attempts = build_attempts(
            intent_result=self._intent("meta_query", level="L2"),
            scene="docs", library_id="default", doc_ids=[],
            load_nodes=lambda: [], llm_factory=lambda: None,
        )
        assert attempts[0].name == "统计/元数据查询"

    def test_l1_still_semantic(self):
        attempts = build_attempts(
            intent_result=self._intent("semantic_retrieval"),
            scene="docs", library_id="default", doc_ids=[],
            load_nodes=lambda: [], llm_factory=lambda: None,
        )
        assert attempts[0].name == "L1 语义检索"


@pytest.fixture
def fake_dbs(tmp_path, monkeypatch):
    """建最小临时 meta + records 库，patch 路径解析指向它们。"""
    meta = tmp_path / "kb" / "knowledge_meta.sqlite"
    meta.parent.mkdir(parents=True)
    conn = sqlite3.connect(meta)
    conn.executescript(
        """
        CREATE TABLE libraries (id TEXT PRIMARY KEY, name TEXT);
        CREATE TABLE nodes (id TEXT PRIMARY KEY, title TEXT, type TEXT, library_id TEXT,
                            status TEXT, deleted INTEGER DEFAULT 0, created_at TEXT, updated_at TEXT);
        CREATE TABLE doc_parse_stages (doc_id TEXT, stage TEXT, status TEXT, page_count INTEGER DEFAULT 0);
        INSERT INTO libraries VALUES ('default', '默认知识库'), ('law', '法律库');
        INSERT INTO nodes VALUES ('d1', '规范A', 'document', 'default', 'completed', 0, '2026-09-01T00:00:00', '2026-09-01T00:00:00');
        INSERT INTO nodes VALUES ('d2', '规范B', 'document', 'default', 'completed', 0, '2026-09-02T00:00:00', '2026-09-02T00:00:00');
        INSERT INTO nodes VALUES ('d3', '法律C', 'document', 'law', 'failed', 0, '2026-09-03T00:00:00', '2026-09-03T00:00:00');
        INSERT INTO nodes VALUES ('d4', '已删D', 'document', 'default', 'completed', 1, '2026-08-01T00:00:00', '2026-08-01T00:00:00');
        INSERT INTO doc_parse_stages VALUES ('d1', 'raw_parse', 'completed', 100);
        INSERT INTO doc_parse_stages VALUES ('d2', 'raw_parse', 'completed', 200);
        INSERT INTO doc_parse_stages VALUES ('d3', 'raw_parse', 'failed', 0);
        """
    )
    conn.commit()
    conn.close()

    records = tmp_path / "data" / "parse_records.sqlite"
    records.parent.mkdir(parents=True)
    rconn = sqlite3.connect(records)
    rconn.executescript(
        """
        CREATE TABLE parse_records (id INTEGER PRIMARY KEY, doc_id TEXT, file_name TEXT,
            file_format TEXT, file_size INTEGER, status TEXT, created_at TEXT, library_id TEXT);
        INSERT INTO parse_records VALUES (1, 'd1', '规范A.pdf', '.pdf', 1024, 'completed', '2026-09-01T00:00:00', 'default');
        INSERT INTO parse_records VALUES (2, 'd2', '规范B.pdf', '.pdf', 2048, 'completed', '2026-09-02T00:00:00', 'default');
        INSERT INTO parse_records VALUES (3, 'd3', '法律C.md', '.md', 512, 'completed', '2026-09-03T00:00:00', 'law');
        INSERT INTO parse_records VALUES (4, 'dX', '已删.pdf', '.pdf', 9999, 'deleted', '2026-09-01T00:00:00', 'default');
        """
    )
    rconn.commit()
    rconn.close()

    import docs_core.paths as paths
    monkeypatch.setattr(paths, "resolve_knowledge_meta_db_path", lambda: meta)
    monkeypatch.setattr(paths, "resolve_repo_root", lambda: tmp_path)
    monkeypatch.delenv("ANGINEER_DOCS_API_URL", raising=False)
    return tmp_path


class TestKnowledgeStats:
    def test_handler_all_libraries(self, fake_dbs):
        tool = StatsAdapter.knowledge_stats()
        result = tool.handler()
        assert result["documents"]["total"] == 3          # d1/d2/d3，d4 软删排除
        assert result["documents"]["deleted"] == 1
        assert result["documents"]["by_status"] == {"completed": 2, "failed": 1}
        lib_counts = {r["library_id"]: r["count"] for r in result["documents"]["by_library"]}
        assert lib_counts == {"default": 2, "law": 1}
        assert result["pages"]["total"] == 300            # 100+200，d3 failed 但 raw_parse 页数 0
        assert result["pages"]["max"]["pages"] == 200
        assert result["pages"]["min"]["pages"] == 100     # min 排除 0 页文档（d3 failed）
        assert result["storage"]["total_file_size_mb"] == round((1024 + 2048 + 512) / 1024 / 1024, 1)
        assert {f["format"] for f in result["uploads"]["by_format"]} == {"pdf", "md"}  # deleted 记录排除

    def test_handler_library_filter(self, fake_dbs):
        tool = StatsAdapter.knowledge_stats()
        result = tool.handler(library_id="law")
        assert result["documents"]["total"] == 1
        assert result["documents"]["by_status"] == {"failed": 1}

    def test_handler_default_library(self, fake_dbs):
        tool = StatsAdapter.knowledge_stats(default_library_id="law")
        result = tool.handler()
        assert result["documents"]["total"] == 1          # 工厂默认库生效

    def test_handler_explicit_all_overrides_default(self, fake_dbs):
        """显式空串/all 覆盖会话默认库 → 全库汇总。"""
        tool = StatsAdapter.knowledge_stats(default_library_id="law")
        for marker in ("", "all", "*", "全部"):
            result = tool.handler(library_id=marker)
            assert result["documents"]["total"] == 3, f"marker={marker!r}"
