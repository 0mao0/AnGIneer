"""前置页扁平化 + 目录组内层级：solo_engine 契约测试。"""

import json

from fixtures.popo_fixtures import content_list_block


def _write_raw_pages(tmp_path):
    pages = [
        [  # page 0: cover
            content_list_block("title", "船闸闸阀门设计规范", level=1),
            content_list_block("paragraph", "中华人民共和国交通部发布"),
        ],
        [  # page 1: publication
            content_list_block("title", "中华人民共和国行业标准", level=1),
            content_list_block("paragraph", "主编单位：四川省交通厅内河勘察规划设计院"),
        ],
        [  # page 2: notice
            content_list_block("title", "关于发布《船闸闸阀门设计规范》的通知", level=1),
            content_list_block("paragraph", "交水发[2003]193号"),
        ],
        [  # page 3: revision
            content_list_block("title", "修订说明", level=1),
            content_list_block("paragraph", "本规范是在原规范基础上修订而成。"),
        ],
        [  # page 4: preface
            content_list_block("title", "前言", level=1),
            content_list_block("paragraph", "本规范主编单位为四川省交通厅。"),
        ],
        [  # page 5: toc
            content_list_block("title", "目次", level=1),
            content_list_block("paragraph", "1 总则 …… (1)"),
            content_list_block("paragraph", "1.1 一般规定 …… (2)"),
            content_list_block("paragraph", "2 基本规定 …… (5)"),
        ],
        [  # page 6: body
            content_list_block("title", "1 总则", level=1),
            content_list_block("paragraph", "总则内容。"),
        ],
    ]
    raw_dir = tmp_path / "mineru_raw"
    raw_dir.mkdir(parents=True, exist_ok=True)
    (raw_dir / "content_list_v2.json").write_text(
        json.dumps(pages, ensure_ascii=False), encoding="utf-8"
    )


def _build(tmp_path):
    from docs_core.step04_structure.solo_engine import build_structured_from_rawfiles

    _write_raw_pages(tmp_path)
    return build_structured_from_rawfiles(
        tmp_path, "doc-fm", "doc-fm", llm_client=None, options={"use_llm": False}
    ).nodes


def test_front_matter_non_toc_content_is_flat(tmp_path):
    nodes = _build(tmp_path)
    by_text = {n["plain_text"]: n for n in nodes}
    for text in (
        "船闸闸阀门设计规范",
        "中华人民共和国交通部发布",
        "中华人民共和国行业标准",
        "主编单位：四川省交通厅内河勘察规划设计院",
        "关于发布《船闸闸阀门设计规范》的通知",
        "修订说明",
        "本规范是在原规范基础上修订而成。",
        "前言",
        "本规范主编单位为四川省交通厅。",
    ):
        node = by_text[text]
        assert node["derived_level"] is None
        assert node.get("parent_uid") is None
        assert node.get("title_path") is None
        assert node["document_part"] == "front_matter"


def test_toc_marker_title_has_no_level_and_rows_keep_struct_levels(tmp_path):
    nodes = _build(tmp_path)
    by_text = {n["plain_text"]: n for n in nodes}
    toc = by_text["目次"]
    assert toc["derived_level"] is None
    assert toc["parent_uid"] is None
    assert toc["page_role"] == "toc"

    l1 = by_text["1 总则 …… (1)"]
    l2 = by_text["1.1 一般规定 …… (2)"]
    l2b = by_text["2 基本规定 …… (5)"]
    assert l1["derived_level"] == 1
    assert l1["parent_uid"] == toc["block_uid"]
    assert l2["derived_level"] == 2
    assert l2["parent_uid"] == l1["block_uid"]
    assert l2b["derived_level"] == 1
    assert l2b["parent_uid"] == toc["block_uid"]


def test_toc_continuation_page_with_single_merged_paragraph_is_toc(tmp_path):
    """目录续页若被 MinerU 合并成单个多条目段落，也应识别为 toc 页。"""
    pages = [
        [  # page 0: toc marker + 独立条目
            content_list_block("title", "目次", level=1),
            content_list_block("paragraph", "1 总则 …… (1)"),
            content_list_block("paragraph", "2 基本规定 …… (5)"),
        ],
        [  # page 1: 续页，多个条目被合并为一个段落
            content_list_block(
                "paragraph",
                "7.4 支承装置 …… (26)\n7.5 止水装置 …… (26)\n8 三角闸门 …… (28)",
            ),
        ],
        [  # page 2: body
            content_list_block("title", "2 基本规定", level=1),
            content_list_block("paragraph", "正文内容。"),
        ],
    ]
    raw_dir = tmp_path / "mineru_raw"
    raw_dir.mkdir(parents=True, exist_ok=True)
    (raw_dir / "content_list_v2.json").write_text(
        json.dumps(pages, ensure_ascii=False), encoding="utf-8"
    )

    from docs_core.step04_structure.solo_engine import build_structured_from_rawfiles

    result = build_structured_from_rawfiles(
        tmp_path, "doc-fm", "doc-fm", llm_client=None, options={"use_llm": False}
    )
    assert result.stats["toc_pages"] == [0, 1]
    page1_nodes = [n for n in result.nodes if n["page_idx"] == 1]
    assert page1_nodes
    assert all(n["page_role"] == "toc" for n in page1_nodes)


def test_appendix_only_document_builds_as_appendix(tmp_path):
    """纯附录文档（跨页表格）：所有内容页都应归入 appendix 部位。"""
    pages = [
        [  # page 0: 附录标题 + 正文段落 + 表格
            content_list_block("title", "附录 A 设计船型尺度及其他参数", level=1),
            content_list_block("paragraph", "A.0.1 设计船型及其尺度应通过分析论证确定。"),
            content_list_block("table", "表 A.0.2-1 杂货船设计船型尺度"),
        ],
        [  # page 1: 续表
            content_list_block("paragraph", "续表 A.0.2-2"),
            content_list_block("table", "表 A.0.2-3 油船设计船型尺度"),
        ],
        [  # page 2: 空页（只有页眉）
            content_list_block("page_header", "附录 A 设计船型尺度及其他参数"),
            content_list_block("page_number", "127"),
        ],
    ]
    raw_dir = tmp_path / "mineru_raw"
    raw_dir.mkdir(parents=True, exist_ok=True)
    (raw_dir / "content_list_v2.json").write_text(
        json.dumps(pages, ensure_ascii=False), encoding="utf-8"
    )

    from docs_core.step04_structure.solo_engine import build_structured_from_rawfiles

    nodes = build_structured_from_rawfiles(
        tmp_path, "doc-appendix", "doc-appendix", llm_client=None,
        options={"use_llm": False},
    ).nodes
    for n in nodes:
        if n["block_type"] in ("page_header", "page_number", "page_footer"):
            continue
        assert n["document_part"] == "appendix"
        assert n["page_role"] == "appendix"


def test_body_first_title_still_level_one(tmp_path):
    nodes = _build(tmp_path)
    by_text = {n["plain_text"]: n for n in nodes}
    body = by_text["1 总则"]
    assert body["document_part"] == "body"
    assert body["derived_level"] == 1
    para = by_text["总则内容。"]
    assert para["parent_uid"] == body["block_uid"]
    assert para["derived_level"] == 2


class _FakeLLM:
    def __init__(self, items):
        self.items = items

    def chat(self, messages, **kwargs):
        return json.dumps({"items": self.items})


def test_resolve_title_levels_skips_front_matter_non_toc_titles():
    from docs_core.step04_structure.shared.title_level_resolver import resolve_title_levels

    nodes = [
        {
            "block_uid": "fm:rev", "block_type": "title", "plain_text": "修订说明",
            "document_part": "front_matter", "page_role": "revision_notes",
            "derived_level": None, "confidence": 0.0,
        },
        {
            "block_uid": "fm:toc", "block_type": "title", "plain_text": "目次",
            "document_part": "front_matter", "page_role": "toc",
            "derived_level": None, "confidence": 0.0,
        },
        {
            "block_uid": "body:1", "block_type": "title", "plain_text": "1 总则",
            "document_part": "body", "page_role": "body",
            "derived_level": 1, "confidence": 0.95,
        },
    ]
    llm = _FakeLLM([
        {"block_id": "fm:rev", "level": 1, "confidence": 0.99},
        {"block_id": "fm:toc", "level": 1, "confidence": 0.99},
    ])
    updated, _stats = resolve_title_levels(
        nodes,
        popo_levels={"fm:rev": 1, "fm:toc": 1},
        llm_client=llm,
        use_llm=True,
    )
    by_uid = {n["block_uid"]: n for n in updated}
    assert by_uid["fm:rev"]["derived_level"] is None
    assert by_uid["fm:toc"]["derived_level"] is None
    assert by_uid["body:1"]["derived_level"] == 1


def test_refine_document_title_levels_skips_front_matter_non_toc_titles():
    from docs_core.models.types import CanonicalBlock
    from docs_core.step04_structure.shared.title_level_refiner import refine_document_title_levels

    blocks = [
        CanonicalBlock(
            block_id="fm:rev", doc_id="doc", page_idx=0, block_type="title",
            text="修订说明", text_clean="修订说明", reading_order=1,
            title_level=None, document_part="front_matter", page_role="revision_notes",
        ),
        CanonicalBlock(
            block_id="body:1", doc_id="doc", page_idx=6, block_type="title",
            text="1 总则", text_clean="1 总则", reading_order=2,
            title_level=None, document_part="body", page_role="body",
        ),
    ]
    llm = _FakeLLM([
        {"block_id": "fm:rev", "level": 1, "confidence": 0.99},
        {"block_id": "body:1", "level": 1, "confidence": 0.99},
    ])
    updated = refine_document_title_levels(
        blocks,
        use_llm=True,
        llm_client=llm,
    )
    by_id = {b.block_id: b for b in updated}
    assert by_id["fm:rev"].title_level is None
    assert by_id["body:1"].title_level == 1
