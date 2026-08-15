"""PageBBox 模型与 CanonicalBlock/CanonicalTable 跨页几何字段契约。"""

from docs_core.models.types import BoundingBox, CanonicalBlock, CanonicalTable, PageBBox


def test_page_bbox_model_roundtrip() -> None:
    page_bbox = PageBBox(page_idx=12, bbox=BoundingBox(x0=0.1, y0=0.2, x1=0.3, y1=0.4))
    payload = page_bbox.model_dump(mode="json")
    restored = PageBBox(**payload)
    assert restored.page_idx == 12
    assert restored.bbox.x0 == 0.1


def test_canonical_block_carries_page_bboxes_and_merged_from() -> None:
    block = CanonicalBlock(
        block_id="d:0:1",
        doc_id="d",
        page_idx=0,
        block_type="paragraph",
        text="完整段落",
        text_clean="完整段落",
        reading_order=1,
        page_bboxes=[
            PageBBox(page_idx=0, bbox=BoundingBox(x0=0, y0=0, x1=1, y1=1)),
            PageBBox(page_idx=1, bbox=BoundingBox(x0=0, y0=0, x1=1, y1=1)),
        ],
        merged_from=["d:1:1"],
    )
    assert len(block.page_bboxes) == 2
    assert block.page_bboxes[-1].page_idx == 1
    assert block.merged_from == ["d:1:1"]


def test_canonical_table_carries_page_bboxes() -> None:
    table = CanonicalTable(
        table_id="t-1",
        doc_id="d",
        page_start=3,
        page_end=4,
        page_bboxes=[
            PageBBox(page_idx=3, bbox=BoundingBox()),
            PageBBox(page_idx=4, bbox=BoundingBox()),
        ],
    )
    assert table.page_bboxes is not None
    assert table.page_bboxes[1].page_idx == 4
