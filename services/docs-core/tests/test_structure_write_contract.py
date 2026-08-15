"""step04/05 写入契约测试：solo jsonl 写出口与 05 重建/行投影一致。"""

import importlib
import json
from pathlib import Path
import re
from types import SimpleNamespace

import pytest

from docs_core.step04_structure.shared.jsonl_io import get_doc_blocks_graph
from docs_core.step05_sqlite_fts.rows_projection import (
    build_doc_block_rows,
    build_document_segments,
)
from fixtures.popo_fixtures import (
    TABLE_HTML,
    build_canonical_from_solo_jsonl,
    content_list_block,
)


def _relations_document(tmp_path):
    """含 table/formula 的 solo 输入 → jsonl 重建 canonical（04 唯一生产者为 solo）。"""
    pages = [
        [
            content_list_block("title", "第一章 总则", level=1),
            content_list_block("paragraph", "正文 A"),
        ],
        [
            content_list_block("table", "表 1 参数表", table_html=TABLE_HTML),
            content_list_block("equation_interline", "F = ma", math="F = ma"),
            content_list_block("paragraph", "式中：F 为力。"),
        ],
    ]
    return build_canonical_from_solo_jsonl("doc-1", pages, tmp_path)


def test_jsonl_roundtrip_carries_relation_fields(tmp_path) -> None:
    """jsonl 节点上的 contd/table_merge/image_assoc 标记经 05 重建原样透传。"""
    from docs_core.step05_sqlite_fts.rebuild.graph_rebuilder import (
        rebuild_canonical_document_from_graph,
    )

    nodes = [
        {
            "block_uid": "d:0:1", "block_type": "paragraph", "page_idx": 0,
            "block_seq": 1, "plain_text": "续上段", "contd_target_id": "d:0:2",
        },
        {
            "block_uid": "d:0:2", "block_type": "paragraph", "page_idx": 0,
            "block_seq": 2, "plain_text": "正文", "image_assoc_id": "d:0:3",
        },
        {
            "block_uid": "d:0:3", "block_type": "figure", "page_idx": 0,
            "block_seq": 3, "plain_text": "",
        },
        {
            "block_uid": "d:1:1", "block_type": "table", "page_idx": 1,
            "block_seq": 4, "plain_text": "表 1", "table_merge_id": "d:2:1",
            "table_html": "<table><tr><td>a</td></tr></table>",
        },
    ]
    with open(tmp_path / "doc_blocks_graph.jsonl", "w", encoding="utf-8") as f:
        for node in nodes:
            f.write(json.dumps(node, ensure_ascii=False) + "\n")
    (tmp_path / "doc_blocks_graph_meta.json").write_text(
        json.dumps({"edges": [], "stats": {}, "generated_at": "", "outlines": [], "pages": []}),
        encoding="utf-8",
    )
    document = rebuild_canonical_document_from_graph("lib-1", "doc-1", {
        "nodes": nodes, "edges": [], "stats": {}, "outlines": [], "pages": [],
    }, title="")
    by_id = {block.block_id: block for block in document.blocks}
    assert by_id["d:0:1"].contd_target_id == "d:0:2"
    assert by_id["d:0:2"].image_assoc_id == "d:0:3"
    assert by_id["d:1:1"].table_merge_id == "d:2:1"


def test_base_rows_carry_table_html_math_content(tmp_path) -> None:
    document = _relations_document(tmp_path)
    base_rows, derived_rows = build_doc_block_rows(document)
    base_map = {row["block_uid"]: row for row in base_rows}
    derived_map = {row["block_uid"]: row for row in derived_rows}

    table_uid = next(b.block_id for b in document.blocks if b.block_type == "table")
    formula_uid = next(b.block_id for b in document.blocks if b.block_type == "formula")
    assert derived_map[table_uid]["table_html"] == TABLE_HTML
    assert derived_map[formula_uid]["math_content"] == "F = ma"
    assert base_map[table_uid]["content_json"].get("table_html") == TABLE_HTML
    assert base_map[formula_uid]["content_json"].get("math_content") == "F = ma"
    title_uid = next(b.block_id for b in document.blocks if b.block_type == "title")
    assert derived_map[title_uid]["derived_title_level"] == 1


def test_solo_jsonl_write_read_roundtrip(monkeypatch, tmp_path) -> None:
    """solo2json 写出口：jsonl 节点与读回 graph_data 一致。"""
    from docs_core.step04_structure import solo2json_pipeline
    from docs_core.step04_structure.solo_engine import StructuredResult

    monkeypatch.setenv("KNOWLEDGE_BASE_DIR", str(tmp_path))
    parsed = tmp_path / "libraries" / "lib" / "documents" / "doc" / "parsed"
    parsed.mkdir(parents=True, exist_ok=True)
    (parsed / "content.md").write_text("正文", encoding="utf-8")
    result = StructuredResult(
        nodes=[{
            "id": 1, "block_uid": "d:0:1", "block_type": "paragraph",
            "page_idx": 0, "block_seq": 1, "plain_text": "正文",
        }],
        edges=[], index_rows=[], stats={"derived_rows": []},
    )
    solo2json_pipeline._save_doc_blocks_graph("lib", "doc", result)
    graph = get_doc_blocks_graph("lib", "doc")
    assert graph is not None
    assert graph["nodes"] == result.nodes


def test_segments_cover_all_blocks(tmp_path) -> None:
    document = _relations_document(tmp_path)
    ranges = [
        {
            "block_id": block.block_id,
            "markdown_line_start": index + 1,
            "markdown_line_end": index + 1,
        }
        for index, block in enumerate(document.blocks)
    ]
    segments = build_document_segments(document, ranges)
    assert len(segments) == len(document.blocks)
    assert all("seg-" in segment["id"] for segment in segments)
    assert all("markdown_line_start" in segment["meta"] for segment in segments)


def test_no_import_of_retired_popo_modules() -> None:
    """退役的 popo 后端模块（mapper/jsonl 投影）不得再被 import。"""
    for module_name in (
        "docs_core.step04_structure.popo_projection",
        "docs_core.step04_structure.popo.popo_mapper",
        "docs_core.step04_structure.popo.popo2json",
    ):
        with pytest.raises(ImportError):
            importlib.import_module(module_name)
    root = Path(__file__).resolve().parents[1] / "src" / "docs_core"
    offenders = []
    import_pattern = re.compile(
        r"(?:import|from)\s+[.\w]*(?:popo_projection|popo_mapper|popo2json)"
    )
    for sub in ("step05_sqlite_fts", "step09_query"):
        for py in (root / sub).rglob("*.py"):
            if import_pattern.search(py.read_text(encoding="utf-8")):
                offenders.append(str(py))
    assert not offenders, f"05/09 不得引用退役 popo 后端模块: {offenders}"


def test_solo_jsonl_rebuild_produces_tables_and_citations(tmp_path) -> None:
    """solo 04 只出 jsonl；05 从 jsonl 重建后表格/引用/chunk 完整。"""
    document = _relations_document(tmp_path)
    assert document.tables, "solo 路径 canonical_tables 必须非空"
    assert document.citation_targets, "引用目标从 Canonical 对象直接构建"
    assert document.chunks, "chunk 仅由 CanonicalDocument 决定"


def test_document_part_passthrough_to_payload_and_canonical() -> None:
    import docs_core.step05_sqlite_fts.rows_projection as rows_projection
    from docs_core.models.types import CanonicalBlock

    block = CanonicalBlock(
        block_id="d:3:1", doc_id="d", page_idx=3, block_type="header_footer",
        text="广告页脚", layout_category="furniture",
        document_part="body", page_role="page_footer",
    )
    assert block.layout_category == "furniture"
    assert block.document_part == "body"
    assert block.page_role == "page_footer"
    payload = rows_projection._build_content_json(block)
    assert payload["layout_category"] == "furniture"
    assert payload["document_part"] == "body"
    assert payload["page_role"] == "page_footer"


def test_document_part_passthrough_content_block() -> None:
    import docs_core.step05_sqlite_fts.rows_projection as rows_projection
    from docs_core.models.types import CanonicalBlock

    block = CanonicalBlock(
        block_id="d:3:1", doc_id="d", page_idx=3, block_type="title",
        text="修订说明", document_part="front_matter", page_role="revision_notes",
    )
    assert block.document_part == "front_matter"
    assert block.page_role == "revision_notes"
    payload = rows_projection._build_content_json(block)
    assert payload["document_part"] == "front_matter"
    assert payload["page_role"] == "revision_notes"
