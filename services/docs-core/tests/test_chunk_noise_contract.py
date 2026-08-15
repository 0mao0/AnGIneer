"""chunk 契约测试：list_procedure 判定 + solo 链路 chunk 完整。"""

from docs_core.step05_sqlite_fts.rebuild.canonical_builder import build_canonical_chunks
from fixtures.popo_fixtures import build_canonical_from_solo_jsonl, content_list_block


def _build_chunks(types):
    from docs_core.models.types import CanonicalBlock

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


def test_solo_chain_chunks_cover_content(tmp_path) -> None:
    """solo jsonl 链路：正文/公式进入 chunk，标题不进正文 chunk。"""
    pages = [
        [
            content_list_block("title", "第一章 总则", level=1),
            content_list_block("paragraph", "正文内容。"),
        ],
        [
            content_list_block("equation_interline", "F = ma", math="F = ma"),
            content_list_block("paragraph", "式中：F 为合力。"),
        ],
    ]
    document = build_canonical_from_solo_jsonl("doc-1", pages, tmp_path)
    assert document.chunks
    full_text = "\n".join(c.text for c in document.chunks)
    assert "正文内容" in full_text
    assert "F = ma" in full_text
