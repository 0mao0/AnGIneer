"""阶段三契约测试：写入唯一出口（graph/segments/base_rows 从 CanonicalDocument 统一生成）。"""

import importlib
import json
from pathlib import Path
import re
from types import SimpleNamespace

import pytest

from docs_core.read.normalize.popo.popo_mapper import po_po_blocks_to_canonical
from docs_core.read.organize.builder import build_canonical_document_from_popoblocks
from docs_core.write.projection import (
    build_doc_block_rows,
    build_doc_blocks_graph,
    build_document_segments,
    render_content_md,
    write_canonical_products,
)
from fixtures.popo_fixtures import (
    EMPTY_TREE,
    TABLE_HTML,
    make_block,
)


def _relations_document():
    """含 contd / image_assoc / table_merge 关联与 bbox 的 popo 输入。"""
    tree = {
        "type": "root",
        "children": [
            {
                "type": "text", "title": "第一章 总则", "level": 1,
                "location": [{"bbox": [0.0, 0.0, 1.0, 1.0], "page": 1}],
                "block_ids": [1],
                "children": [
                    {
                        "type": "text", "title": "第一节", "level": 2,
                        "location": [{"bbox": [0.0, 0.0, 1.0, 1.0], "page": 1}],
                        "block_ids": [2],
                        "children": [],
                    },
                ],
            },
        ],
    }
    fixture = [
        make_block(1, 1, "title", "第一章 总则", level=1),
        make_block(2, 1, "text", "续上段内容", contd=3),
        make_block(3, 1, "text", "正文 A", image=4),
        make_block(4, 1, "image", "", image=-1),
        make_block(5, 1, "image_caption", "图 1 示意图", image=4),
        make_block(6, 2, "table", TABLE_HTML, table_merge=10),
        make_block(7, 2, "table_caption", "表 1 参数表", table_merge=6),
        make_block(8, 2, "equation", "F = ma"),
        make_block(9, 2, "text", "式中：F 为力。"),
        make_block(10, 3, "table", "<table><tr><td>续</td><td>表</td></tr></table>", table_merge=6),
    ]
    blocks, outlines, _, pages = po_po_blocks_to_canonical("doc-1", fixture, tree)
    document = build_canonical_document_from_popoblocks(
        library_id="lib-1", doc_id="doc-1", title="",
        blocks=blocks, outlines=outlines, pages=pages,
    )
    return document


def _fake_knowledge_service(monkeypatch):
    fake = SimpleNamespace(
        clear_document_segments=lambda doc_id: 0,
        save_document_segments=lambda *args, **kwargs: 0,
        index_store=SimpleNamespace(
            clear_doc_blocks=lambda doc_id: 0,
            insert_doc_blocks_base_rows=lambda rows: len(rows),
            update_doc_blocks_derived_rows=lambda rows: len(rows),
        ),
    )
    ks_module = importlib.import_module("docs_core.knowledge_service")
    monkeypatch.setattr(ks_module, "_knowledge_service", fake)
    return fake


def test_graph_nodes_carry_popo_relations_direct() -> None:
    document = _relations_document()
    _md, ranges = render_content_md(document.blocks, build_id="abc123def456")
    graph = build_doc_blocks_graph(document, ranges)
    node_map = {node["block_uid"]: node for node in graph["nodes"]}

    # 三边字段不经 jsonl 中转直达
    assert node_map["doc-1:b2"]["contd_target_id"] == "doc-1:b3"
    assert node_map["doc-1:b3"]["image_assoc_id"] == "doc-1:b4"
    assert node_map["doc-1:b6"]["table_merge_id"] == "doc-1:b10"
    # bbox 直达
    assert node_map["doc-1:b3"]["bbox"] == [0.0, 0.0, 100.0, 50.0]
    # markdown 行号直达（header 偏移）
    assert node_map["doc-1:b1"]["markdown_line_start"] >= 2
    # 边集合含三类关系 + 顺序边
    edge_labels = {edge["label"] for edge in graph["edges"]}
    assert {"parent", "contd", "table_merge", "before"} <= edge_labels


def test_base_rows_carry_table_html_math_content() -> None:
    document = _relations_document()
    base_rows, derived_rows = build_doc_block_rows(document)
    base_map = {row["block_uid"]: row for row in base_rows}
    derived_map = {row["block_uid"]: row for row in derived_rows}

    table_uid = "doc-1:b6"
    formula_uid = "doc-1:b8"
    assert derived_map[table_uid]["table_html"] == TABLE_HTML
    assert derived_map[formula_uid]["math_content"] == "F = ma"
    # content_json 不再是空壳（G4/P11）
    assert base_map[table_uid]["content_json"].get("table_html") == TABLE_HTML
    assert base_map[formula_uid]["content_json"].get("math_content") == "F = ma"
    # derived_title_level / title_path 对齐
    assert derived_map["doc-1:b1"]["derived_title_level"] == 1


def test_unified_write_matches_pure_builders(tmp_path, monkeypatch) -> None:
    _fake_knowledge_service(monkeypatch)
    document = _relations_document()
    md_out = tmp_path / "content.md"
    jsonl_out = tmp_path / "doc_blocks_graph.jsonl"
    meta_out = tmp_path / "doc_blocks_graph_meta.json"

    result = write_canonical_products(
        library_id="lib-1", doc_id="doc-1", document=document,
        build_id="abc123def456",
        content_md_path=md_out, graph_jsonl_path=jsonl_out, graph_meta_path=meta_out,
    )
    _md, ranges = render_content_md(document.blocks, build_id="abc123def456")
    expected_graph = build_doc_blocks_graph(document, ranges)
    written_nodes = [
        json.loads(line)
        for line in jsonl_out.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    assert written_nodes == expected_graph["nodes"]
    meta = json.loads(meta_out.read_text(encoding="utf-8"))
    assert meta["edges"] == expected_graph["edges"]
    assert meta["build_id"] == "abc123def456"
    assert result["segments_count"] >= 0
    assert result["base_rows_count"] == len(document.blocks)
    assert result["derived_rows_count"] == len(document.blocks)


def test_segments_cover_all_blocks() -> None:
    document = _relations_document()
    _md, ranges = render_content_md(document.blocks)
    segments = build_document_segments(document, ranges)
    assert len(segments) == len(document.blocks)
    assert all("seg-" in segment["id"] for segment in segments)
    assert all("markdown_line_start" in segment["meta"] for segment in segments)


def test_no_import_of_popoprojection() -> None:
    with pytest.raises(ImportError):
        importlib.import_module("docs_core.read.normalize.popo.popo_projection")
    root = Path(__file__).resolve().parents[1] / "src" / "docs_core"
    offenders = []
    import_pattern = re.compile(r"(?:import|from)\s+[.\w]*popo_projection")
    for sub in ("write", "query"):
        for py in (root / sub).rglob("*.py"):
            if import_pattern.search(py.read_text(encoding="utf-8")):
                offenders.append(str(py))
    assert not offenders, f"write/query 不得引用 popo_projection: {offenders}"


def test_popoblocks_no_longer_depends_on_graph_jsonl(tmp_path) -> None:
    """popo 路径表格/引用直接消费 CanonicalBlock（无 graph jsonl 也可完整构建）。"""
    document = _relations_document()
    assert document.tables, "popo 路径 canonical_tables 必须非空"
    assert document.citation_targets, "引用目标从 Canonical 对象直接构建"
    assert document.chunks, "chunk 仅由 CanonicalDocument 决定"
