"""build_id 孪生产物版本戳契约：solo 写出口统一承担。"""

import json
import re
from pathlib import Path

from docs_core.step04_structure.shared.jsonl_io import (
    extract_build_id_from_markdown,
    get_doc_blocks_graph,
)
from docs_core.step04_structure.solo_engine import StructuredResult
from docs_core.step04_structure import solo2json_pipeline

MD_HEADER_RE = re.compile(r"^<!--\s*build_id:\s*([0-9a-f]{12})\s*-->\s*$")


def _sample_result() -> StructuredResult:
    return StructuredResult(
        nodes=[{
            "id": 1, "block_uid": "doc:0:1", "block_type": "paragraph",
            "page_idx": 0, "block_seq": 1, "plain_text": "正文",
        }],
        edges=[], index_rows=[], stats={"derived_rows": []},
    )


def test_solo_write_stamps_consistent_build_id(tmp_path: Path, monkeypatch) -> None:
    """solo 写出口：content.md 首行与 meta build_id 一致，读回图一致。"""
    monkeypatch.setenv("KNOWLEDGE_BASE_DIR", str(tmp_path))
    parsed = tmp_path / "libraries" / "lib" / "documents" / "doc" / "parsed"
    parsed.mkdir(parents=True, exist_ok=True)
    (parsed / "content.md").write_text("正文", encoding="utf-8")

    solo2json_pipeline._save_doc_blocks_graph("lib", "doc", _sample_result())

    md_text = (parsed / "content.md").read_text(encoding="utf-8")
    match = MD_HEADER_RE.match(md_text.splitlines()[0] if md_text.splitlines() else "")
    assert match, "content.md 首行必须是 build_id 注释"
    meta = json.loads((parsed / "doc_blocks_graph_meta.json").read_text(encoding="utf-8"))
    assert meta.get("build_id") == match.group(1)
    assert re.fullmatch(r"[0-9a-f]{12}", meta["build_id"])

    graph = get_doc_blocks_graph("lib", "doc")
    assert graph is not None and len(graph["nodes"]) == 1


def test_build_id_roundtrip_via_api_helper() -> None:
    assert extract_build_id_from_markdown("<!-- build_id: abcdef123456 -->\n正文") == "abcdef123456"
    assert extract_build_id_from_markdown("无头部注释的 md") is None


def test_solo_write_fails_loudly_when_markdown_missing(tmp_path: Path, monkeypatch) -> None:
    """content.md 缺失时不得静默产出不一致配对：structure 阶段应显式失败。"""
    monkeypatch.setenv("KNOWLEDGE_BASE_DIR", str(tmp_path))
    parsed = tmp_path / "libraries" / "lib" / "documents" / "doc" / "parsed"
    parsed.mkdir(parents=True, exist_ok=True)

    import pytest

    with pytest.raises(RuntimeError, match="build_id 盖章失败"):
        solo2json_pipeline._save_doc_blocks_graph("lib", "doc", _sample_result())

    # 失败后不留半成品 meta（或至少不把不一致状态当成成功落盘）
    meta_path = parsed / "doc_blocks_graph_meta.json"
    assert not meta_path.exists()


def test_solo_write_replaces_stale_md_build_id(tmp_path: Path, monkeypatch) -> None:
    """md 残留旧 build_id 时，盖章必须替换首行而不是重复插入。"""
    monkeypatch.setenv("KNOWLEDGE_BASE_DIR", str(tmp_path))
    parsed = tmp_path / "libraries" / "lib" / "documents" / "doc" / "parsed"
    parsed.mkdir(parents=True, exist_ok=True)
    (parsed / "content.md").write_text(
        "<!-- build_id: aaaaaabbbbbb -->\n正文\n", encoding="utf-8"
    )
    meta_path = parsed / "doc_blocks_graph_meta.json"
    meta_path.write_text('{"build_id": "ccccccdddddd"}', encoding="utf-8")

    solo2json_pipeline._save_doc_blocks_graph("lib", "doc", _sample_result())

    md_text = (parsed / "content.md").read_text(encoding="utf-8")
    md_header_lines = [
        line for line in md_text.splitlines()
        if re.match(r"^<!--\s*build_id:", line.strip())
    ]
    assert md_header_lines == ["<!-- build_id: ccccccdddddd -->"]
    assert len(md_header_lines) == 1
    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    assert meta.get("build_id") == "ccccccdddddd"
