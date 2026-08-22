"""层级化契约测试：solo 04 层级化 → jsonl → 05 重建三层一致性 + 空章节回归 + 旧格式回退。"""

import json
from pathlib import Path

import pytest
from docs_core.step04_structure.shared.title_level_refiner import (
    refine_document_title_levels,
)
from docs_core.step05_sqlite_fts.rebuild.graph_rebuilder import (
    rebuild_canonical_document_from_graph,
)
from docs_core.step04_structure.solo_engine import build_structured_from_rawfiles
from fixtures.popo_fixtures import content_list_block

KB = Path(__file__).resolve().parents[3] / "data" / "knowledge_base" / "libraries" / "default" / "documents"
REAL_FIXTURE_MISSING = not (KB / "doc-406e43e8" / "parsed").exists()
REAL_FIXTURE_REASON = "真实数据目录缺失（doc-406e43e8 解析产物不存在）"


class _CountingLLM:
    """记录调用次数，返回预设标题层级 items。"""

    def __init__(self, items):
        self.calls = 0
        self.items = items

    def chat(self, messages, **kwargs):
        self.calls += 1
        return json.dumps({"items": self.items})


def _hierarchy_pages() -> list:
    """第1章 / 1.1 / （一） 编号混排的 solo 输入。"""
    return [
        [
            content_list_block("title", "第1章 总则", level=1),
            content_list_block("paragraph", "本章内容概述。"),
        ],
        [
            content_list_block("title", "1.1 一般规定", level=2),
            content_list_block("paragraph", "一般规定内容。"),
        ],
        [
            content_list_block("title", "（一）适用范围", level=3),
            content_list_block("paragraph", "适用范围说明。"),
        ],
    ]


def _write_jsonl(tmp_path, nodes, outlines=None, pages=None):
    meta = {
        "edges": [],
        "stats": {},
        "generated_at": "2026-08-04T00:00:00",
        "outlines": outlines or [],
        "pages": pages or [],
    }
    with open(tmp_path / "doc_blocks_graph.jsonl", "w", encoding="utf-8") as f:
        for node in nodes:
            f.write(json.dumps(node, ensure_ascii=False) + "\n")
    (tmp_path / "doc_blocks_graph_meta.json").write_text(
        json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return meta


def test_three_level_consistency_through_jsonl_rebuild(tmp_path) -> None:
    """用例1：solo 04 层级化（mock LLM 校正）→ jsonl derived_level → 05 rebuilt 全等。"""
    raw_dir = tmp_path / "mineru_raw"
    raw_dir.mkdir(parents=True, exist_ok=True)
    (raw_dir / "content_list_v2.json").write_text(
        json.dumps(_hierarchy_pages(), ensure_ascii=False), encoding="utf-8"
    )
    result = build_structured_from_rawfiles(
        tmp_path, "doc-1", "doc-1", llm_client=None, options={"use_llm": False}
    )
    title_uids = [node["block_uid"] for node in result.nodes if node.get("block_type") == "title"]
    assert len(title_uids) == 3

    llm = _CountingLLM(
        items=[
            {"block_id": title_uids[0], "level": 1, "confidence": 0.95},
            {"block_id": title_uids[1], "level": 2, "confidence": 0.95},
            {"block_id": title_uids[2], "level": 3, "confidence": 0.9},
        ]
    )
    # solo 引擎只出规则层级；04 层级化校正走 title_level_refiner
    blocks = [dict(node) for node in result.nodes]
    from docs_core.models.types import CanonicalBlock

    canonical_blocks = [
        CanonicalBlock(
            block_id=node["block_uid"], doc_id="doc-1",
            page_idx=int(node.get("page_idx") or 0),
            block_type=node.get("block_type") or "unknown",
            text=node.get("plain_text") or "",
            text_clean=node.get("plain_text") or "",
            reading_order=int(node.get("block_seq") or 0),
            title_level=node.get("derived_level"),
        )
        for node in blocks
    ]
    canonical_blocks = refine_document_title_levels(
        canonical_blocks, use_llm=True, llm_client=llm,
    )
    assert llm.calls == 1, "低置信标题应触发一次 LLM 校正"
    refined = {b.block_id: b.title_level for b in canonical_blocks if b.block_type == "title"}
    assert refined == {uid: level for uid, level in zip(title_uids, (1, 2, 3))}

    nodes = [
        {
            "block_uid": b.block_id,
            "block_type": b.block_type,
            "page_idx": b.page_idx,
            "block_seq": b.reading_order,
            "plain_text": b.text,
            "derived_level": b.title_level,
            "title_path": "",
            "parent_uid": None,
        }
        for b in canonical_blocks
    ]
    _write_jsonl(tmp_path, nodes)
    graph = {
        "nodes": nodes,
        "edges": [],
        "stats": {},
        "outlines": [],
        "pages": [],
    }
    document = rebuild_canonical_document_from_graph("lib-1", "doc-1", graph, title="")
    rebuilt = {b.block_id: b.title_level for b in document.blocks if b.block_type == "title"}
    assert rebuilt == refined, "05 重建 title_level 必须原样采用 jsonl derived_level"


def test_empty_section_outline_survives_rebuild(tmp_path) -> None:
    """用例2（P6）：无正文空章节经 meta.outlines → rebuild 不丢失。"""
    nodes = [
        {
            "block_uid": "d:0:1", "block_type": "title", "page_idx": 0,
            "block_seq": 1, "plain_text": "1 总则", "derived_level": 1,
        },
        {
            "block_uid": "d:0:2", "block_type": "paragraph", "page_idx": 0,
            "block_seq": 2, "plain_text": "正文", "derived_level": None,
        },
    ]
    outlines = [
        {
            "outline_id": "outline-1", "doc_id": "doc-1", "level": 1,
            "title": "1 总则", "section_path": "1 总则", "page_idx": 0,
            "anchor_block_id": "d:0:1", "parent_outline_id": None,
        },
        {
            "outline_id": "outline-2", "doc_id": "doc-1", "level": 1,
            "title": "2 术语", "section_path": "2 术语", "page_idx": 3,
            "anchor_block_id": "outline-2-anchor", "parent_outline_id": None,
        },
    ]
    _write_jsonl(tmp_path, nodes, outlines=outlines)
    graph = {
        "nodes": nodes,
        "edges": [],
        "stats": {},
        "outlines": outlines,
        "pages": [],
    }
    document = rebuild_canonical_document_from_graph("lib-1", "doc-1", graph, title="")
    titles = [o.title for o in document.outlines]
    assert "2 术语" in titles, "空章节 outline 必须经 meta.outlines 存活"


def test_old_format_without_outlines_falls_back_to_title_blocks(tmp_path) -> None:
    """用例3：graph_data 无 outlines 键 → outline 从 title 块重推，不报错。"""
    graph = {
        "nodes": [
            {
                "block_uid": "t1", "block_type": "title", "page_idx": 0, "block_seq": 1,
                "plain_text": "5.1 一般规定", "derived_level": 2,
                "title_path": "5.1 一般规定", "parent_uid": None,
            },
            {
                "block_uid": "p1", "block_type": "paragraph", "page_idx": 0, "block_seq": 2,
                "plain_text": "正文", "derived_level": None, "parent_uid": "t1",
            },
        ],
        "edges": [],
    }
    assert "outlines" not in graph
    document = rebuild_canonical_document_from_graph("lib-1", "doc-1", graph, title="")
    assert document.outlines, "旧格式（无 outlines）必须从 title 块重推 outline"
    assert document.outlines[0].title == "5.1 一般规定"


@pytest.mark.skipif(REAL_FIXTURE_MISSING, reason=REAL_FIXTURE_REASON)
def test_front_matter_title_is_flat_and_part_marker():
    from docs_core.step04_structure.solo_engine import build_structured_from_rawfiles
    from docs_core.step04_structure.shared.page_role_classifier import DocumentPart
    parsed = KB / "doc-406e43e8" / "parsed"
    result = build_structured_from_rawfiles(
        parsed, "doc-406e43e8", "doc-406e43e8", llm_client=None, options={"use_llm": False}
    )
    by_uid = {n["block_uid"]: n for n in result.nodes}
    xiu = by_uid["doc-406e43e8:3:1"]   # 修订说明
    assert xiu["block_type"] == "title"
    assert xiu["derived_level"] is None
    assert xiu["document_part"] == DocumentPart.FRONT_MATTER.value
    body = by_uid["doc-406e43e8:8:1"]  # 2 基本规定
    assert body["derived_level"] == 1
    assert body["document_part"] == DocumentPart.BODY.value


@pytest.mark.skipif(REAL_FIXTURE_MISSING, reason=REAL_FIXTURE_REASON)
def test_real_doc_front_matter_non_toc_content_is_flat():
    from docs_core.step04_structure.solo_engine import build_structured_from_rawfiles
    parsed = KB / "doc-406e43e8" / "parsed"
    result = build_structured_from_rawfiles(
        parsed, "doc-406e43e8", "doc-406e43e8", llm_client=None, options={"use_llm": False}
    )
    front = [
        n for n in result.nodes
        if n.get("document_part") == "front_matter"
        and n.get("page_role") != "toc"
        and n.get("layout_category") == "content"
    ]
    assert front, "真实文档应包含非目录前置页内容块"
    for n in front:
        assert n["derived_level"] is None
        assert n.get("parent_uid") is None
        assert n.get("title_path") is None


@pytest.mark.skipif(REAL_FIXTURE_MISSING, reason=REAL_FIXTURE_REASON)
def test_furniture_blocks_have_no_hierarchy():
    parsed = KB / "doc-406e43e8" / "parsed"
    result = build_structured_from_rawfiles(
        parsed, "doc-406e43e8", "doc-406e43e8", llm_client=None, options={"use_llm": False}
    )
    furniture = [n for n in result.nodes if n.get("layout_category") == "furniture"]
    assert furniture, "真实文档应包含页饰块"
    for n in furniture:
        assert n["derived_level"] is None
        assert n.get("parent_uid") is None
        assert n.get("title_path") is None
    continuations = [
        n for n in result.nodes
        if n.get("block_type") == "page_header"
        and str(n.get("plain_text") or "").replace(" ", "").startswith("续表")
    ]
    assert continuations, "真实文档应包含续表标题"
    for n in continuations:
        assert n["layout_category"] == "content"
        assert n["page_role"] == "table_continuation"


def test_body_first_title_does_not_parent_to_front_matter(tmp_path) -> None:
    raw_dir = tmp_path / "mineru_raw"
    raw_dir.mkdir(parents=True, exist_ok=True)
    pages = [
        [content_list_block("title", "目次", level=1)],
        [content_list_block("title", "1.1 一般规定", level=1)],
    ]
    (raw_dir / "content_list_v2.json").write_text(
        json.dumps(pages, ensure_ascii=False), encoding="utf-8"
    )
    result = build_structured_from_rawfiles(
        tmp_path, "doc-x", "doc-x", llm_client=None, options={"use_llm": False}
    )
    body_title = next(
        n for n in result.nodes
        if n.get("plain_text") == "1.1 一般规定"
    )
    assert body_title["document_part"] == "body"
    assert body_title["parent_uid"] is None
