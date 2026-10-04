"""build_qa_config / build_complex_config / build_attempts：library_ids 穿透到 knowledge_search。

参数名与装配点按现码 agent_configs.py（build_qa_config 无 load_nodes/llm_factory 形参，
计划片段系示意，按实际签名断言）。table/entity 不接收 library_ids（铁律 4，限首库降级）。
"""
from types import SimpleNamespace

import pytest

from angineer_core import agent_tools
from angineer_core.agent_configs import build_qa_config
from angineer_core.agent_policy import build_attempts


@pytest.fixture
def spy(monkeypatch):
    """拦 knowledge_search 装配调用（转手调真身，产物仍是可用 AgentTool）。"""
    calls = []
    orig = agent_tools.RetrieverAdapter.knowledge_search

    def _spy(**kwargs):
        calls.append(dict(kwargs))
        return orig(**kwargs)

    monkeypatch.setattr(agent_tools.RetrieverAdapter, "knowledge_search", staticmethod(_spy))
    return calls


class TestQaConfigLibraryIds:
    def test_build_qa_config_passes_library_ids(self, spy):
        build_qa_config(llm=None, library_id="libA", library_ids=["libA", "libB"])
        assert spy, "knowledge_search 未被装配"
        assert spy[0].get("library_ids") == ["libA", "libB"]
        assert spy[0].get("library_id") == "libA"

    def test_build_qa_config_legacy_omits(self, spy):
        # 铁律 3：旧调用不传 → 装配参数为 None（全链行为不变）
        build_qa_config(llm=None, library_id="libA")
        assert spy[0].get("library_ids") is None


class TestBuildAttemptsLibraryIds:
    def _intent(self, level, service_mode):
        return SimpleNamespace(intent_level=level, service_mode=service_mode, intent_type="")

    def _run(self, intent, **over):
        params = dict(
            intent_result=intent, scene="qa", library_id="libA", doc_ids=[],
            load_nodes=lambda: [], llm_factory=lambda: None,
            library_ids=["libA", "libB"],
        )
        params.update(over)
        attempts = build_attempts(**params)
        for attempt in attempts:
            attempt.config_factory()  # 触发装配
        return attempts

    def test_l1_passes_to_qa_config(self, spy):
        self._run(self._intent("L1", "semantic_retrieval"))
        assert spy
        assert all(c.get("library_ids") == ["libA", "libB"] for c in spy)

    def test_l2_both_attempts_pass(self, spy):
        attempts = self._run(self._intent("L2", "structured_lookup"))
        assert len(attempts) == 2
        assert len(spy) == 2
        assert all(c.get("library_ids") == ["libA", "libB"] for c in spy)

    def test_complex_passes(self, spy):
        self._run(self._intent("L3", "dynamic_orchestration"))
        assert spy
        assert spy[0].get("library_ids") == ["libA", "libB"]

    def test_legacy_build_attempts_omits(self, spy):
        # 铁律 3：build_attempts 不传 library_ids → 装配为 None
        attempts = build_attempts(
            intent_result=self._intent("L1", "semantic_retrieval"), scene="qa",
            library_id="libA", doc_ids=[], load_nodes=lambda: [], llm_factory=lambda: None,
        )
        attempts[0].config_factory()
        assert spy[0].get("library_ids") is None
