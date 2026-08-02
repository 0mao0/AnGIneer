"""Phase 0 契约测试：CitationTarget 展示页码。"""

from docs_core.read.organize.types import CitationTarget


def test_citation_target_display_label_fallback() -> None:
    # printed_page_label 优先
    target = CitationTarget(
        target_id="t1", target_type="title", doc_id="d", page_idx=4,
        printed_page_label="iv",
    )
    assert target.display_page_label == "iv"
    # 缺省回退到物理页序（1-based）
    target2 = CitationTarget(target_id="t2", target_type="title", doc_id="d", page_idx=4)
    assert target2.display_page_label == "5"


def test_citation_targets_built_with_page_labels() -> None:
    from docs_core.read.normalize.popo.popo_mapper import po_po_blocks_to_canonical
    from docs_core.read.organize.builder import (
        build_canonical_document_from_popoblocks,
        build_citation_targets_from_graph,
    )
    from fixtures.popo_fixtures import EMPTY_TREE, build_clean_fixture

    blocks, outlines, _id_map, _pages = po_po_blocks_to_canonical("doc-1", build_clean_fixture(), EMPTY_TREE)
    document = build_canonical_document_from_popoblocks(
        library_id="lib-1", doc_id="doc-1", title="",
        blocks=blocks, outlines=outlines,
    )
    targets = document.citation_targets
    assert targets, "应有 citation targets"
    for target in targets:
        assert target.display_page_label == str(target.page_idx + 1)
