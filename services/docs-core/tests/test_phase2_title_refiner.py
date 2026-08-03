"""阶段二契约测试：标题层级校正器通用化 + 置信度策略（G6）。"""

import json

from docs_core.ingest.canonical.types import CanonicalBlock
from docs_core.ingest.structure.title_level_refiner import (
    DEFAULT_CONFIDENCE_THRESHOLD,
    estimate_backend_level_confidence,
    resolve_title_level_refinement,
)


def _title(block_id: str, text: str, level=None, source: str = "mineru") -> CanonicalBlock:
    return CanonicalBlock(
        block_id=block_id, doc_id="d", block_type="title",
        text=text, text_clean=text, title_level=level, source=source,
        page_idx=0, reading_order=0,
    )


class _CountingLLM:
    """记录调用次数与收到的标题文本，返回预设 items。"""

    def __init__(self, items=None):
        self.calls = 0
        self.items = items or []
        self.received_texts: list[str] = []

    def chat(self, messages, **kwargs):
        self.calls += 1
        payload = json.loads(messages[-1]["content"])
        self.received_texts = [str(item["text"]) for item in payload.get("items", [])]
        return json.dumps({"items": self.items})


def test_confidence_strategies_per_backend() -> None:
    # solo：编号正则 0.95 / 原始 level 0.6 / 无 level 0.0
    assert estimate_backend_level_confidence("5.1 一般规定", 3, backend="solo") == 0.95
    assert estimate_backend_level_confidence("第一节 总则", 2, backend="solo") == 0.6
    assert estimate_backend_level_confidence("第一节 总则", None, backend="solo") == 0.0
    # popo：4B 无 confidence，编号正则回退 0.8 / 纯文本 0.3
    assert estimate_backend_level_confidence("5.1 一般规定", 3, backend="popo") == 0.8
    assert estimate_backend_level_confidence("第一节 总则", 2, backend="popo") == 0.3
    assert estimate_backend_level_confidence("第一节 总则", None, backend="popo") == 0.0
    # auto 按 block.source 判别
    assert estimate_backend_level_confidence("5.1", 2, backend="auto", source="mineru") == 0.95
    assert estimate_backend_level_confidence("5.1", 2, backend="auto", source="mineru-popo") == 0.8
    assert DEFAULT_CONFIDENCE_THRESHOLD == 0.85


def test_skips_llm_when_confidence_above_threshold() -> None:
    llm = _CountingLLM()
    blocks = [_title("b1", "5.1 一般规定", level=3, source="mineru")]  # solo 0.95 >= 0.85
    candidates, llm_levels, status = resolve_title_level_refinement(
        blocks, llm, use_llm=True
    )
    assert llm.calls == 0
    assert status == "skipped_by_confidence"
    assert llm_levels == {}
    assert candidates[0]["confidence"] == 0.95
    assert candidates[0]["backend_level"] == 3


def test_calls_llm_for_below_threshold() -> None:
    llm = _CountingLLM(items=[{"block_id": "b1", "level": 1, "confidence": 0.9}])
    blocks = [_title("b1", "第一节 总则", level=2, source="mineru-popo")]  # popo 0.3 < 0.85
    candidates, llm_levels, status = resolve_title_level_refinement(
        blocks, llm, use_llm=True
    )
    assert llm.calls == 1
    assert status == "ok"
    assert llm_levels["b1"] == (1, 0.9)
    assert candidates[0]["confidence"] == 0.3
    assert llm.received_texts == ["第一节 总则"]


def test_only_title_blocks_are_candidates() -> None:
    llm = _CountingLLM()
    blocks = [
        _title("b1", "第一章 总则", level=1),
        CanonicalBlock(block_id="p1", doc_id="d", block_type="paragraph", text="正文"),
        CanonicalBlock(block_id="t1", doc_id="d", block_type="table", text="表"),
    ]
    candidates, _, _ = resolve_title_level_refinement(blocks, llm, use_llm=True)
    assert [item["block_id"] for item in candidates] == ["b1"]


def _popo_title_fixture(title_text: str, level: int) -> list[dict]:
    return [
        {
            "id": 1, "page": 1, "type": "title", "content": title_text,
            "bbox": [0.0, 0.0, 1.0, 1.0], "level": level,
            "image": -1, "table_merge": -1, "contd": -1,
        },
        {
            "id": 2, "page": 1, "type": "text", "content": "正文",
            "bbox": [0.0, 0.0, 1.0, 1.0], "level": -1,
            "image": -1, "table_merge": -1, "contd": -1,
        },
    ]


def test_builder_corrects_popo_mixed_numbering_titles() -> None:
    """验收场景：第一节/一、/(一) 混用，popo 路径层级被 LLM 校正。"""
    from docs_core.ingest.canonical.builder import build_canonical_document_from_popoblocks
    from docs_core.ingest.structure.popo_mapper import po_po_blocks_to_canonical
    from fixtures.popo_fixtures import EMPTY_TREE

    blocks, outlines, _, pages = po_po_blocks_to_canonical(
        "doc-1", _popo_title_fixture("第一节 总则", 2), EMPTY_TREE
    )
    llm = _CountingLLM(items=[{"block_id": "doc-1:b1", "level": 1, "confidence": 0.95}])
    document = build_canonical_document_from_popoblocks(
        library_id="lib-1", doc_id="doc-1", title="",
        blocks=blocks, outlines=outlines, pages=pages,
        use_llm=True, llm_client=llm,
    )
    assert llm.calls == 1
    title_block = next(b for b in document.blocks if b.block_type == "title")
    assert title_block.title_level == 1


def test_builder_popo_numbered_title_still_calls_llm() -> None:
    """popo 编号标题置信度 0.8 < 0.85，仍发起 LLM（计划设定）。"""
    from docs_core.ingest.canonical.builder import build_canonical_document_from_popoblocks
    from docs_core.ingest.structure.popo_mapper import po_po_blocks_to_canonical
    from fixtures.popo_fixtures import EMPTY_TREE

    blocks, outlines, _, pages = po_po_blocks_to_canonical(
        "doc-1", _popo_title_fixture("5.1 一般规定", 3), EMPTY_TREE
    )
    llm = _CountingLLM(items=[{"block_id": "doc-1:b1", "level": 2, "confidence": 0.9}])
    document = build_canonical_document_from_popoblocks(
        library_id="lib-1", doc_id="doc-1", title="",
        blocks=blocks, outlines=outlines, pages=pages,
        use_llm=True, llm_client=llm,
    )
    assert llm.calls == 1
    title_block = next(b for b in document.blocks if b.block_type == "title")
    assert title_block.title_level == 2


def test_builder_solo_numbered_title_skips_llm() -> None:
    """solo 编号标题置信度 0.95 ≥ 0.85，零 LLM 调用。"""
    from docs_core.ingest.canonical.builder import rebuild_canonical_document_from_graph

    graph = {
        "nodes": [
            {
                "block_uid": "t1", "block_type": "title", "page_idx": 0, "block_seq": 1,
                "plain_text": "5.1 一般规定", "derived_level": 3, "section_path": "",
            },
            {
                "block_uid": "p1", "block_type": "paragraph", "page_idx": 0, "block_seq": 2,
                "plain_text": "正文", "derived_level": None, "section_path": "",
            },
        ],
        "edges": [],
    }
    llm = _CountingLLM()
    document = rebuild_canonical_document_from_graph(
        "lib-1", "doc-1", graph, title="示例", use_llm=True, llm_client=llm
    )
    assert llm.calls == 0
    title_block = next(b for b in document.blocks if b.block_type == "title")
    assert title_block.title_level == 3


def test_builder_solo_plain_title_calls_llm() -> None:
    """solo 非编号标题置信度 0.6 < 0.85，发起 LLM 校正。"""
    from docs_core.ingest.canonical.builder import rebuild_canonical_document_from_graph

    graph = {
        "nodes": [
            {
                "block_uid": "t1", "block_type": "title", "page_idx": 0, "block_seq": 1,
                "plain_text": "第一节 总则", "derived_level": 2, "section_path": "",
            },
            {
                "block_uid": "p1", "block_type": "paragraph", "page_idx": 0, "block_seq": 2,
                "plain_text": "正文", "derived_level": None, "section_path": "",
            },
        ],
        "edges": [],
    }
    llm = _CountingLLM(items=[{"block_id": "t1", "level": 1, "confidence": 0.9}])
    document = rebuild_canonical_document_from_graph(
        "lib-1", "doc-1", graph, title="示例", use_llm=True, llm_client=llm
    )
    assert llm.calls == 1
    title_block = next(b for b in document.blocks if b.block_type == "title")
    assert title_block.title_level == 1
