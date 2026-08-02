"""Phase 0 契约测试：build_id 孪生产物版本戳。"""

import json
import re
from pathlib import Path

from docs_core.read.normalize.popo.popo_mapper import po_po_blocks_to_canonical
from docs_core.read.normalize.popo.popo_projection import run_popo_projection
from fixtures.popo_fixtures import EMPTY_TREE, build_clean_fixture

MD_HEADER_RE = re.compile(r"^<!--\s*build_id:\s*([0-9a-f]{12})\s*-->\s*$")


def test_popo_projection_stamps_consistent_build_id(tmp_path: Path) -> None:
    blocks, outlines, _id_map, _pages = po_po_blocks_to_canonical("doc-1", build_clean_fixture(), EMPTY_TREE)
    graph_out = tmp_path / "doc_blocks_graph.json"
    md_out = tmp_path / "content.md"

    result = run_popo_projection(
        library_id="lib-1",
        doc_id="doc-1",
        blocks=blocks,
        outlines=outlines,
        mineru_content_md="原文 markdown",
        graph_output_path=str(graph_out),
        content_md_output_path=str(md_out),
    )
    assert "build_id" in result

    md_text = md_out.read_text(encoding="utf-8")
    match = MD_HEADER_RE.match(md_text.splitlines()[0] if md_text.splitlines() else "")
    assert match, "content.md 首行必须是 build_id 注释"
    md_build_id = match.group(1)

    meta_path = tmp_path / "doc_blocks_graph_meta.json"
    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    assert meta.get("build_id") == md_build_id == result["build_id"]

    # markdown_line_start/end 仍与文件行号一致（header 偏移被计入）
    jsonl_path = tmp_path / "doc_blocks_graph.jsonl"
    nodes = [json.loads(line) for line in jsonl_path.read_text(encoding="utf-8").splitlines() if line.strip()]
    for node in nodes:
        start, end = node["markdown_line_start"], node["markdown_line_end"]
        assert start is not None and end is not None and start >= 2, node


def test_build_id_roundtrip_via_api_helper(tmp_path: Path) -> None:
    from docs_core.write.store.assets_file_store import extract_build_id_from_markdown

    assert extract_build_id_from_markdown("<!-- build_id: abcdef123456 -->\n正文") == "abcdef123456"
    assert extract_build_id_from_markdown("无头部注释的 md") is None
