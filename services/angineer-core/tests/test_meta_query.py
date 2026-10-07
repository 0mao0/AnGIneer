# -*- coding: utf-8 -*-
"""统计/元数据查询相关测试（废 meta_query 路由后口径，2026-10-02）。

meta_query 特权岔道已删：统计题改由 L1 semantic_retrieval + knowledge_stats 工具自选承接。
覆盖：分类器降级路径（统计题→L1）、QA 工具箱含 knowledge_stats、build_attempts 对 legacy
service_mode 残值的优雅降级、guard 对 stats 结果的证据面兼容（P-1）、knowledge_stats 本地直查。
"""
import json
import sqlite3
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

SERVICES = Path(__file__).resolve().parents[3]
for pkg in ("angineer-core", "docs-core"):
    sys.path.insert(0, str(SERVICES / pkg / "src"))

from angineer_core.agent_policy import build_attempts
from angineer_core.agent_messages import AgentMessage
from angineer_core.agent_tools import StatsAdapter
from angineer_core.base_contracts import IntentResult
from angineer_core.classifier import IntentClassifier, _has_substantive_content, _check_l0_intent


class _FakeClassifyLLM:
    """分类器假客户端：只回固定文本，不联网（chat_result_guarded 只读 .text/.finish_reason）。"""

    def __init__(self, text: str):
        self._text = text

    def chat_result(self, messages, **_kwargs):
        return SimpleNamespace(text=self._text, finish_reason="stop")


class TestStatsQuestionsRouteL1:
    """废 meta_query 路由（2026-10-02 第二步）后：统计题无规则短路、无归一化兜底，
    由 LLM 判 L1（prompt v4）；LLM 失败时规则兜底经并入 L1_KEYWORDS 的计数词归 L1，
    且 _has_substantive_content 不再把统计题当闲聊吞进 L0（原 _is_meta_query 的 L0 兜底职责）。"""

    def test_fallback_classifies_stats_question_l1(self, monkeypatch):
        """LLM 挂掉时规则兜底把统计题判 L1 semantic_retrieval（计数词已并入 L1_KEYWORDS）。"""
        from angineer_core import ops_metrics

        monkeypatch.setattr(ops_metrics, "record_event", lambda *a, **k: None, raising=False)
        clf = IntentClassifier(sops=[], llm_client=_FakeClassifyLLM("这不是 JSON"))
        result = clf.classify_intent("知识库有多少篇文档")
        assert result.service_mode == "semantic_retrieval"
        assert result.intent_level == "L1"

    def test_stats_question_is_substantive_not_l0(self):
        """统计题是有实质内容的真问题：L0 闲聊分支不得吞掉（原 _is_meta_query 在此的兜底职责）。"""
        assert _has_substantive_content("知识库有多少篇文档")
        assert _has_substantive_content("最近上传了多少份资料")
        assert _check_l0_intent("知识库有多少篇文档") is None
        assert _check_l0_intent("最近上传了多少份资料") is None

    def test_engineering_distribution_question_still_l1_not_special(self, monkeypatch):
        """工程「分布」题无特殊通道（原 meta 规则的负例语义保留为回归哨兵）。"""
        from angineer_core import ops_metrics

        monkeypatch.setattr(ops_metrics, "record_event", lambda *a, **k: None, raising=False)
        clf = IntentClassifier(sops=[], llm_client=_FakeClassifyLLM("这不是 JSON"))
        result = clf.classify_intent("波浪力分布规律是什么")
        assert result.service_mode == "semantic_retrieval"


class TestQaToolboxHasStats:
    """knowledge_stats 下沉 L1 统一工具箱（2026-10-02 第二步）：统计题与正文题同档由模型自选。"""

    def test_qa_default_toolbox_has_five_tools(self):
        from angineer_core.agent_configs import build_qa_config

        config = build_qa_config(llm=object(), config_name="t")
        names = {t.name for t in config.tools}
        # calculator 于 2026-10-07 进 QA 档（数值题不再心算，配套 tool_codec 计算纪律）
        assert names == {
            "knowledge_search", "table_search", "entity_search",
            "knowledge_stats", "calculator",
        }

    def test_qa_table_first_toolbox_keeps_stats(self):
        from angineer_core.agent_configs import build_qa_config

        config = build_qa_config(llm=object(), config_name="t", task_type="table_qa")
        assert {t.name for t in config.tools} >= {"knowledge_stats"}
        assert config.tools[0].name == "table_search"  # 查表首位语义不被 stats 下沉破坏


class TestBuildAttemptsLegacyMetaValue:
    """meta_query 特权岔道已删：历史 service_mode="meta_query" 残值（Literal 保留 legacy）
    经 build_attempts 自然落 level 对应档，不再有「优先于一切 level」的独木桥。"""

    def _intent(self, service_mode, level="L1"):
        return IntentResult(intent_level=level, service_mode=service_mode)

    def test_legacy_meta_value_falls_to_l1(self):
        attempts = build_attempts(
            intent_result=self._intent("meta_query"),
            scene="docs", library_id="default", doc_ids=[],
            load_nodes=lambda: [], llm_factory=lambda: None,
        )
        assert len(attempts) == 1
        assert attempts[0].name == "L1 语义检索"

    def test_legacy_meta_value_no_longer_overrides_level(self):
        """即使 service_mode=meta_query，level=L2 仍走 L2 表格档（原「覆盖一切 level」语义删除）。"""
        attempts = build_attempts(
            intent_result=self._intent("meta_query", level="L2"),
            scene="docs", library_id="default", doc_ids=[],
            load_nodes=lambda: [], llm_factory=lambda: None,
        )
        assert attempts[0].name != "统计/元数据查询"

    def test_l1_still_semantic(self):
        attempts = build_attempts(
            intent_result=self._intent("semantic_retrieval"),
            scene="docs", library_id="default", doc_ids=[],
            load_nodes=lambda: [], llm_factory=lambda: None,
        )
        assert attempts[0].name == "L1 语义检索"


class TestGuardStatsEvidence:
    """P-1（废 meta_query 路由第二步）：knowledge_stats 返回无 items[]，统计摘要纳入 guard
    证据面后，no_evidence 与 unsupported_reference 两道闸不误杀正确统计答案（evidence_parts
    定版方案——否决「纯 stats 组合豁免 enforce_evidence」，那会重开无证据出数字的洞）。"""

    def _messages(self, answer, tool_content):
        return [
            AgentMessage(role="user", content="知识库里有多少篇文档？"),
            AgentMessage(role="tool", name="knowledge_stats", content=tool_content),
            AgentMessage(role="assistant", content=answer),
        ]

    def test_stats_answer_passes_both_gates(self):
        from angineer_core.agent_configs import make_final_answer_guard

        guard = make_final_answer_guard(enforce_evidence=True)
        tool_content = json.dumps(
            {"documents": {"total": 78}, "pages": {"total": 12000}, "storage": {"total_file_size_mb": 1.5}},
            ensure_ascii=False,
        )
        result = guard(self._messages("当前知识库共有 78 份文档，总页数 12000 页。", tool_content))
        assert result is None, f"统计答案不应被 guard 拦截：{result}"

    def test_stats_answer_with_unbacked_std_reference_still_flagged(self):
        """统计答案引用证据面里不存在的标准编号 → unsupported_reference 照常拦截：
        P-1 解除的是「空证据全量误杀」，token 级核对语义不因 stats 放宽（guard 语义不变）。"""
        from angineer_core.agent_configs import make_final_answer_guard

        guard = make_final_answer_guard(enforce_evidence=True)
        tool_content = json.dumps({"documents": {"total": 3}}, ensure_ascii=False)
        result = guard(self._messages("按 ISO 19880 统计口径，库内共 3 份文档。", tool_content))
        assert result is not None and result[2] == "unsupported_reference"

    def test_error_stats_result_still_refuses(self):
        """stats 返回 error JSON（如本地回退被禁）：不得当成证据，enforce_evidence 照常拒答。"""
        from angineer_core.agent_configs import make_final_answer_guard

        guard = make_final_answer_guard(enforce_evidence=True)
        tool_content = json.dumps({"error": "docs-api unreachable"}, ensure_ascii=False)
        result = guard(self._messages("共有 78 份文档。", tool_content))
        assert result is not None and result[2] == "no_evidence"


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

    # 本 fixture 注册的是 docs-core 侧真实适配器（Seam 4 端口），独立安装
    # angineer-core 的环境没有 docs-core：跳过依赖它的用例而不是报错。
    pytest.importorskip("docs_core.step09_query.agent_port")
    import docs_core.paths as paths
    from docs_core.step09_query import agent_port

    monkeypatch.setattr(paths, "resolve_knowledge_meta_db_path", lambda: meta)
    monkeypatch.setattr(paths, "resolve_repo_root", lambda: tmp_path)
    monkeypatch.delenv("ANGINEER_DOCS_API_URL", raising=False)
    # Seam 4：本地统计直查经 local_stats 端口消费 docs-core 适配器本体，
    # 这里注册真实适配器（上面的 paths monkeypatch 对适配器内的惰性 import 同样生效）
    from angineer_core import ports

    monkeypatch.setattr(ports, "_local_stats", agent_port.local_stats)
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
        """显式 all/*/全部 覆盖会话默认库 → 全库汇总。"""
        tool = StatsAdapter.knowledge_stats(default_library_id="law")
        for marker in ("all", "*", "全部", "ALL"):
            result = tool.handler(library_id=marker)
            assert result["documents"]["total"] == 3, f"marker={marker!r}"

    def test_handler_empty_string_falls_back_to_default(self, fake_dbs):
        """空串/空白/未填 = 未指定 → 回落会话默认库，不得当全库（2026-09-29 串库事故回归哨兵：
        模型习惯性把缺省参数填成空串，曾把「本库列举」跑成全库 350 篇）。"""
        tool = StatsAdapter.knowledge_stats(default_library_id="law")
        assert tool.handler()["documents"]["total"] == 1              # 不传
        assert tool.handler(library_id=None)["documents"]["total"] == 1
        assert tool.handler(library_id="")["documents"]["total"] == 1
        assert tool.handler(library_id="  ")["documents"]["total"] == 1
