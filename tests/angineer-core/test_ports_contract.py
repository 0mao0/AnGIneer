# -*- coding: utf-8 -*-
"""Seam 4 端口契约回归：每个端口一条「按生产形状注册 fake、走真实调用点、断言真被调通」用例。

事故模式（2026-09-19 夜间全量拒答，已修 1a6cb0c）：端口契约与适配器都是
两参 (library_id, doc_ids)，而 policy_query._load_doc_nodes 调用点只传一参——
TypeError 被 except 吞成「空节点」→ 检索恒 0 条 → 全量拒答，CI 全绿。

本文件的铁律：**fake 一律用显式签名，禁止 **kwargs 兜底**——调用点传错参/漏传参
必须让 TypeError 在测试里直接炸出来，而不是靠断言间接推。每条用例除断言结果外
都断言 fake 真的被调到了（防调用点被挪死后静默降级——sop_runner 的
_get_tool_registry 会吞异常返回 None，尤甚）。

覆盖（agent_search 七端口）：
- normalize_query / knowledge_local / table_local / entity_local /
  local_stats / engtool_registry / relevant_citations ← 本文件
另两个既有端口同模式覆盖在：
- local_nodes_loader → services/angineer-core/tests/test_entity_search_dual_track.py
  ::test_doc_nodes_local_fallback_uses_production_shaped_loader（事故用例本尊）
- local_rerank → tests/angineer-core/test_retrieval_pipeline.py
  ::test_rerank_candidates_not_degraded_uses_local
"""
import os
import sys
from unittest.mock import Mock

import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../../services/angineer-core/src")))
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../../services/ai-inference/src")))

from angineer_core import agent_tools, ports  # noqa: E402
from angineer_core.agent_tools import EngtoolAdapter, RetrieverAdapter, StatsAdapter  # noqa: E402
from angineer_core.base_contracts import SOP, Step  # noqa: E402
from angineer_core.sop_runner import SopRunner  # noqa: E402


@pytest.fixture(autouse=True)
def _no_http_no_disable(monkeypatch):
    """所有用例走本地端口分支：docs-api URL 与禁用开关都不能干扰。"""
    monkeypatch.delenv("ANGINEER_DOCS_API_URL", raising=False)
    monkeypatch.delenv("ANGINEER_DISABLE_LOCAL_FALLBACK", raising=False)
    monkeypatch.delenv("KG_DB_PATH", raising=False)


def test_normalize_query_port_contract(monkeypatch):
    seen = []

    def fake_normalizer(query: str) -> str:  # noqa: ANN001
        seen.append(query)
        return query + "!"

    monkeypatch.setattr(ports, "_query_normalizer", fake_normalizer)
    assert agent_tools._normalize_query("第六十条") == "第六十条!"
    assert seen == ["第六十条"]


def test_knowledge_local_port_contract(monkeypatch):
    seen = {}

    def fake_knowledge_local(*, query, library_id, doc_ids, top_k, task_type,
                             filters, nodes, dense, sparse, clause, formula):  # noqa: ANN001,ANN202
        seen.update(query=query, library_id=library_id, doc_ids=doc_ids,
                    top_k=top_k, task_type=task_type, nodes=list(nodes or []))
        return {"items": []}

    monkeypatch.setattr(ports, "_knowledge_local_search", fake_knowledge_local)
    result = agent_tools._run_knowledge_search(
        query="测试", library_id="lib-c", doc_ids=["d1"], doc_nodes=[],
        top_k=20, task_type="content_qa",
    )
    assert seen["query"] == "测试"
    assert seen["library_id"] == "lib-c"
    assert seen["doc_ids"] == ["d1"]
    # 链路调通：空结果但语义是「真没检索到」，不是端口 error
    assert result["total"] == 0 and "error" not in result


def test_table_local_port_contract(monkeypatch):
    seen = {}

    def fake_table_local(*, query, library_id, doc_ids, top_k, filters,
                         nodes, table, formula):  # noqa: ANN001,ANN202
        seen.update(query=query, library_id=library_id, nodes=list(nodes or []))
        return {"items": []}

    monkeypatch.setattr(ports, "_table_local_search", fake_table_local)
    tool = RetrieverAdapter.table_search(library_id="lib-c")
    result = tool.handler(query="表格")
    assert seen["query"] == "表格"
    assert seen["library_id"] == "lib-c"
    assert result["total"] == 0 and "error" not in result


def test_entity_local_port_contract(monkeypatch):
    seen = {}
    entity = Mock()
    entity.model_dump.return_value = {"name": "e1", "layer": "concept"}

    def fake_entity_local(*, query, library_id, db_path, limit):  # noqa: ANN001,ANN202
        seen.update(query=query, library_id=library_id, db_path=db_path, limit=limit)
        return [entity]

    monkeypatch.setattr(ports, "_entity_local_search", fake_entity_local)
    tool = RetrieverAdapter.entity_search(library_id="lib-c")
    result = tool.handler(query="系缆力")
    assert seen["query"] == "系缆力"
    assert seen["library_id"] == "lib-c"
    assert seen["limit"] == 20
    assert result["total"] == 1


def test_local_stats_port_contract(monkeypatch):
    seen = []

    def fake_local_stats(library_id):  # noqa: ANN001,ANN202
        seen.append(library_id)
        return {"documents": {"total": 7}}

    monkeypatch.setattr(ports, "_local_stats", fake_local_stats)
    tool = StatsAdapter.knowledge_stats()
    result = tool.handler()
    assert seen == [None]  # 未传 library_id → 端口收到 None（默认全库）
    assert result["documents"]["total"] == 7


def test_engtool_registry_port_contract(monkeypatch):
    """两个调用点：EngtoolAdapter.handler 与 SopRunner 工具步骤。

    SopRunner 的 _get_tool_registry 会吞异常返回 None（降级语义），
    所以必须断言 fake 真的被调了两次——少一次说明有调用点静默失效。
    """
    calls = []

    class _FakeTool:
        def run(self, **kwargs):
            return {"result": 42}

    class _FakeRegistry:
        @classmethod
        def get_tool(cls, name):
            return _FakeTool() if name in ("echo", "calc") else None

    def fake_registry():  # noqa: ANN202
        calls.append(1)
        return _FakeRegistry

    monkeypatch.setattr(ports, "_engtool_registry", fake_registry)

    # 调用点 1：EngtoolAdapter（agent_tools）
    tool = EngtoolAdapter.from_registry("echo")
    assert tool.handler(x=1)["result"] == 42

    # 调用点 2：SopRunner 工具步骤（sop_runner）
    sop = SOP(
        id="sop-c",
        name_zh="契约",
        steps=[Step(id="s1", name_zh="计算", tool="calc",
                    inputs={"expression": "1+1"}, outputs={"result": "result"})],
    )
    runner = SopRunner(llm_client=Mock())
    blackboard = runner.run_sop(sop, {})
    assert blackboard["result"] == 42
    assert runner.memory.history[0].status == "success"

    assert len(calls) == 2, "两个调用点都必须真的调到注册表 fake"


def test_relevant_citations_port_contract(monkeypatch):
    seen = []

    def fake_citations(query, items, limit):  # noqa: ANN001,ANN202
        seen.append((query, len(items), limit))
        return [{"marker": "K1"}]

    monkeypatch.setattr(ports, "_relevant_citations", fake_citations)
    out = agent_tools._build_relevant_citations("船闸规范", [object(), object()])
    assert out == [{"marker": "K1"}]
    assert seen == [("船闸规范", 2, 5)]
