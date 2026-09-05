# -*- coding: utf-8 -*-
"""ANGINEER_CONTEXT_TOP_N（rerank 后上下文截断条数）回归测试。"""
import sys
from pathlib import Path

SERVICES = Path(__file__).resolve().parents[3]
for pkg in ("angineer-core", "docs-core"):
    sys.path.insert(0, str(SERVICES / pkg / "src"))

import angineer_core.agent_tools as agent_tools
from docs_core.step09_query.protocols.contracts import RetrievedItem


def _items(n):
    return [
        RetrievedItem.model_validate({
            "item_id": f"i{k}", "entity_type": "content", "doc_id": "d1",
            "title": "t", "text": f"内容{k}", "score": 1.0, "metadata": {},
        })
        for k in range(n)
    ]


def _assemble(monkeypatch, items):
    # reranker 打桩为恒等，只验证截断行为
    monkeypatch.setattr(
        "angineer_core.retrieval_pipeline.rerank_candidates",
        lambda *a, **k: list(a[1]),
    )
    return agent_tools._assemble_search_result(
        query="x", items=items, library_id="default", doc_title_map={},
        prefix="K", marker_allocator=None, rerank=True, task_type="content_qa",
        kind="text", source="knowledge_search",
    )


class TestContextTopN:
    def test_default_15(self, monkeypatch):
        monkeypatch.delenv("ANGINEER_CONTEXT_TOP_N", raising=False)
        result = _assemble(monkeypatch, _items(20))
        assert result["total"] == 15

    def test_env_override(self, monkeypatch):
        monkeypatch.setenv("ANGINEER_CONTEXT_TOP_N", "10")
        result = _assemble(monkeypatch, _items(20))
        assert result["total"] == 10

    def test_fewer_items_than_cap(self, monkeypatch):
        monkeypatch.setenv("ANGINEER_CONTEXT_TOP_N", "15")
        result = _assemble(monkeypatch, _items(7))
        assert result["total"] == 7
