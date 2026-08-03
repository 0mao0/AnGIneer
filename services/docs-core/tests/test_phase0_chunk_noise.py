"""Phase 0 契约测试：chunk 级噪声断言 + list_procedure 判定。"""

from docs_core.ingest.structure.popo_mapper import po_po_blocks_to_canonical
from docs_core.ingest.canonical.builder import build_canonical_chunks, build_canonical_outlines
from fixtures.popo_fixtures import EMPTY_TREE, build_noise_fixture


def _chunks():
    blocks, _, _, _ = po_po_blocks_to_canonical("doc-1", build_noise_fixture(), EMPTY_TREE)
    blocks, _ = build_canonical_outlines(blocks)
    return build_canonical_chunks(blocks)


def test_content_chunks_have_no_page_number_or_header_text() -> None:
    chunks = _chunks()
    full_text = "\n".join(c.text for c in chunks)
    for noise in ("12", "某工程标准", "页眉文本", "第 1 页 共 3 页", "页脚注释"):
        assert noise not in full_text, f"噪声文本不应进入 chunk: {noise}"


def test_footnote_text_appears_once_via_host() -> None:
    chunks = _chunks()
    occurrences = sum(c.text.count("示意图来源自测") for c in chunks)
    assert occurrences == 1, f"footnote 文本应只在宿主 chunk 出现一次，实际 {occurrences}"


def test_caption_text_appears_once_via_host() -> None:
    chunks = _chunks()
    occurrences = sum(c.text.count("图 1 结构示意") for c in chunks)
    assert occurrences == 1


def _build_chunks(types):
    from docs_core.ingest.canonical.types import CanonicalBlock

    blocks = [
        CanonicalBlock(
            block_id=f"b{i}", doc_id="d", page_idx=0, reading_order=i,
            block_type=t, text=t, text_clean=t,
        )
        for i, t in enumerate(types)
    ]
    return build_canonical_chunks(blocks)


def test_list_procedure_requires_majority_list_items() -> None:
    # 1 个 list_item + 1 个 paragraph：不算流程块
    chunks = _build_chunks(["list_item", "paragraph"])
    assert all(c.chunk_type != "list_procedure" for c in chunks)
    # 2 个 list_item + 1 个 paragraph：算流程块
    chunks = _build_chunks(["list_item", "list_item", "paragraph"])
    assert any(c.chunk_type == "list_procedure" for c in chunks)
    # 纯 list_item：算流程块
    chunks = _build_chunks(["list_item", "list_item"])
    assert any(c.chunk_type == "list_procedure" for c in chunks)
    # 纯 paragraph：不算
    chunks = _build_chunks(["paragraph", "paragraph"])
    assert all(c.chunk_type != "list_procedure" for c in chunks)
