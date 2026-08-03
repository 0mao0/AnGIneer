"""Phase 0 契约测试：popo mapper 噪声处置表 + raw_type + printed_page_label。"""

from docs_core.ingest.structure.popo_mapper import po_po_blocks_to_canonical

from fixtures.popo_fixtures import EMPTY_TREE, build_noise_fixture


def _map() -> tuple:
    blocks, outlines, id_map, pages = po_po_blocks_to_canonical(
        "doc-1", build_noise_fixture(), EMPTY_TREE
    )
    return blocks, outlines, id_map, pages


def test_pure_noise_blocks_dropped() -> None:
    blocks, _, _, _ = _map()
    dropped_ids = {3, 4, 5, 6, 7}  # page_number / page_title / header / footer / page_footnote
    block_ids = {b.block_id for b in blocks}
    for popo_id in dropped_ids:
        assert f"doc-1:b{popo_id}" not in block_ids


def test_remaining_blocks_have_raw_type() -> None:
    blocks, _, _, _ = _map()
    type_by_id = {
        1: "title", 2: "text", 8: "page_number", 9: "aside_text",
        10: "image", 13: "table",
    }
    for block in blocks:
        popo_id = int(block.source_ref)
        assert block.raw_type == type_by_id[popo_id], f"block {popo_id} raw_type={block.raw_type}"


def test_aside_text_kept_as_paragraph_with_raw_type() -> None:
    blocks, _, _, _ = _map()
    aside = next(b for b in blocks if int(b.source_ref) == 9)
    assert aside.block_type == "paragraph"
    assert aside.raw_type == "aside_text"


def test_caption_footnote_merged_into_host_and_dropped() -> None:
    blocks, _, _, _ = _map()
    block_by_id = {b.block_id: b for b in blocks}
    # caption/footnote 块不再独立存在
    for popo_id in {11, 12, 14, 15}:
        assert f"doc-1:b{popo_id}" not in block_by_id
    # 文本并入宿主
    image_host = block_by_id["doc-1:b10"]
    assert "图 1 结构示意" in image_host.text
    assert "示意图来源自测" in image_host.text
    table_host = block_by_id["doc-1:b13"]
    assert "表 1 参数表" in table_host.text
    assert "单位 kN" in table_host.text


def test_page_number_lands_in_pages_printed_label() -> None:
    blocks, _, _, pages = _map()
    assert pages, "pages 必须被构造"
    by_idx = {p.page_idx: p for p in pages}
    assert by_idx[0].printed_page_label == "12"
    assert by_idx[1].printed_page_label == "13"
    # page_number 块本身不产生 block
    assert not any(b.block_type == "header_footer" for b in blocks)


def test_clean_fixture_unchanged() -> None:
    from fixtures.popo_fixtures import build_clean_fixture

    blocks, _, _, _ = po_po_blocks_to_canonical("doc-1", build_clean_fixture(), EMPTY_TREE)
    assert len(blocks) == 4
    assert all(b.raw_type is not None for b in blocks)


def test_mapper_signature_returns_pages() -> None:
    from docs_core.ingest.canonical.types import CanonicalPage

    _, _, _, pages = _map()
    assert all(isinstance(p, CanonicalPage) for p in pages)
