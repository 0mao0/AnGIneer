"""结构管线 stats 契约：引擎侧的可观测计数必须活到管道层。

2026-09-19 实踩：`build_structured_index_for_doc` 用新建的 dict 覆盖 `result.stats`，
引擎算出的 `continuation_text_reattaches` 等计数在管道层整批消失——回填/巡检时看不到
规则到底跑没跑（canary 报"重归属 None"就是这个坑）。本用例钉住"叠加而不是替换"。
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

from docs_core.step04_structure import solo2json_pipeline as pipeline  # noqa: E402
from docs_core.step04_structure.solo_engine import StructuredResult  # noqa: E402

ENGINE_ONLY_STATS = {
    "continuation_text_reattaches": 7,
    "continuation_merges": 2,
    "total_blocks": 42,
    "parser_version": "3.4.5",
}


@pytest.fixture()
def pipeline_stubs(monkeypatch, tmp_path):
    """把管线外部依赖全部短路，只留 stats 组装这一段真实代码。"""
    parsed_dir = tmp_path / "parsed"
    parsed_dir.mkdir(parents=True, exist_ok=True)
    captured: dict = {}

    monkeypatch.setattr(pipeline.paths, "get_parsed_dir", lambda *a, **k: parsed_dir)
    monkeypatch.setattr(pipeline.paths, "resolve_structure_input_dir", lambda *a, **k: tmp_path)
    monkeypatch.setattr(pipeline.paths, "resolve_structured_input_dir", lambda *a, **k: tmp_path)
    monkeypatch.setattr(
        pipeline._afs.file_storage, "get_doc_manifest", lambda *a, **k: {"source_file": "a.pdf"}
    )
    monkeypatch.setattr(
        pipeline,
        "build_structured_from_rawfiles",
        lambda **kwargs: StructuredResult(nodes=[], edges=[], index_rows=[], stats=dict(ENGINE_ONLY_STATS)),
    )

    def fake_save(library_id, doc_id, result):
        captured["saved_stats"] = dict(result.stats or {})
        return "/tmp/fake_graph.jsonl"

    monkeypatch.setattr(pipeline, "_save_doc_blocks_graph", fake_save)
    return captured


def test_engine_counts_survive_into_returned_stats(pipeline_stubs):
    steps: list[tuple] = []
    out = pipeline.build_structured_index_for_doc(
        library_id="lib-x",
        doc_id="doc-x",
        options={"use_llm": False},
        on_step=lambda *args: steps.append(args),
    )
    stats = out["stats"]
    for key, value in ENGINE_ONLY_STATS.items():
        assert stats.get(key) == value, f"引擎计数 {key} 在管道层丢了"
    # 管道层自己的字段仍在
    assert stats["nodes_count"] == 0
    assert stats["derive_version"] == "v1"


def test_engine_counts_are_written_into_meta(pipeline_stubs):
    pipeline.build_structured_index_for_doc(
        library_id="lib-x",
        doc_id="doc-x",
        options={"use_llm": False},
    )
    saved = pipeline_stubs["saved_stats"]
    assert saved.get("continuation_text_reattaches") == 7
    assert saved.get("popo_signal") is not None


def test_reattach_count_is_emitted_as_step(pipeline_stubs):
    """阶段抽屉显示的步骤列表里必须能看到重归属计数。"""
    steps: list[tuple] = []
    pipeline.build_structured_index_for_doc(
        library_id="lib-x",
        doc_id="doc-x",
        options={"use_llm": False},
        on_step=lambda *args: steps.append(args),
    )
    names = {row[0]: row for row in steps}
    assert "续接文本重归属" in names, f"没有发出重归属步骤：{list(names)}"
    step = names["续接文本重归属"]
    assert step[1] == "done"
    assert step[2] == "7 处"
