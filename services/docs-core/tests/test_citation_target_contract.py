"""CitationTarget 展示页码契约。"""

from docs_core.models.types import CitationTarget
from fixtures.popo_fixtures import build_document_with_printed_labels


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
    document = build_document_with_printed_labels("doc-1")
    targets = document.citation_targets
    assert targets, "应有 citation targets"
    label_by_id = {target.target_id: target.printed_page_label for target in targets}
    assert label_by_id["doc-1:b1"] == "12"
