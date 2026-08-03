"""Phase 0 契约测试：build_id 孪生产物版本戳（阶段三起由统一写出口承担）。"""

import json
import re
from pathlib import Path
from types import SimpleNamespace

from docs_core.ingest.structure.popo_mapper import po_po_blocks_to_canonical
from docs_core.ingest.canonical.builder import build_canonical_document_from_popoblocks
from docs_core.write.projection import write_canonical_products
from fixtures.popo_fixtures import EMPTY_TREE, build_clean_fixture

MD_HEADER_RE = re.compile(r"^<!--\s*build_id:\s*([0-9a-f]{12})\s*-->\s*$")


def _fake_docs_service(monkeypatch):
    """替换全局 docs_service，避免测试触碰真实 DB。"""
    import importlib

    fake = SimpleNamespace(
        clear_document_segments=lambda doc_id: 0,
        save_document_segments=lambda *args, **kwargs: 0,
        index_store=SimpleNamespace(
            clear_doc_blocks=lambda doc_id: 0,
            insert_doc_blocks_base_rows=lambda rows: len(rows),
            update_doc_blocks_derived_rows=lambda rows: len(rows),
        ),
    )
    ks_module = importlib.import_module("docs_core.docs_service")
    monkeypatch.setattr(ks_module, "_docs_service", fake)
    return fake


def test_unified_write_stamps_consistent_build_id(tmp_path: Path, monkeypatch) -> None:
    _fake_docs_service(monkeypatch)
    blocks, outlines, _id_map, _pages = po_po_blocks_to_canonical("doc-1", build_clean_fixture(), EMPTY_TREE)
    document = build_canonical_document_from_popoblocks(
        library_id="lib-1",
        doc_id="doc-1",
        title="",
        blocks=blocks, outlines=outlines, pages=_pages,
    )
    md_out = tmp_path / "content.md"
    jsonl_out = tmp_path / "doc_blocks_graph.jsonl"
    meta_out = tmp_path / "doc_blocks_graph_meta.json"
    result = write_canonical_products(
        library_id="lib-1",
        doc_id="doc-1",
        document=document,
        build_id="abc123def456",
        content_md_path=md_out,
        graph_jsonl_path=jsonl_out,
        graph_meta_path=meta_out,
    )
    assert "build_id" in result

    md_text = md_out.read_text(encoding="utf-8")
    match = MD_HEADER_RE.match(md_text.splitlines()[0] if md_text.splitlines() else "")
    assert match, "content.md 首行必须是 build_id 注释"
    assert match.group(1) == result["build_id"] == "abc123def456"

    meta = json.loads(meta_out.read_text(encoding="utf-8"))
    assert meta.get("build_id") == "abc123def456"

    # markdown_line_start/end 仍与文件行号一致（header 偏移被计入）
    nodes = [json.loads(line) for line in jsonl_out.read_text(encoding="utf-8").splitlines() if line.strip()]
    for node in nodes:
        start, end = node["markdown_line_start"], node["markdown_line_end"]
        assert start is not None and end is not None and start >= 2, node


def test_build_id_roundtrip_via_api_helper(tmp_path: Path) -> None:
    from docs_core.write.store.doc_blocks_graph import extract_build_id_from_markdown

    assert extract_build_id_from_markdown("<!-- build_id: abcdef123456 -->\n正文") == "abcdef123456"
    assert extract_build_id_from_markdown("无头部注释的 md") is None
