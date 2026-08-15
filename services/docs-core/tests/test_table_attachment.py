"""续表附件化：跨页表的续页表头不展示、不进语义，但保留在 jsonl。"""

from docs_core.step04_structure.popo.popo_table_continuation import (
    attach_table_continuation_headers,
    detect_table_continuations,
)


def _node(
    uid,
    page_idx,
    block_type,
    text="",
    *,
    bbox=None,
    block_seq=1,
    caption=None,
    merged_from=None,
    layout_category="content",
):
    return {
        "block_uid": uid,
        "id": uid,
        "page_idx": page_idx,
        "block_seq": block_seq,
        "block_type": block_type,
        "plain_text": text,
        "bbox": bbox or [0.0, 0.0, 1.0, 1.0],
        "caption": caption,
        "merged_from": merged_from,
        "layout_category": layout_category,
    }


def test_continuation_marker_above_table_detected_in_page_header():
    """续表标记若被解析成 page_header 且在目标表上方，也应触发跨页表合并。"""
    nodes = [
        _node("t1", 19, "table", bbox=[0.04, 0.151, 0.909, 0.916], block_seq=1),
        _node("t2", 20, "table", bbox=[0.06, 0.105, 0.915, 0.804], block_seq=1),
        _node(
            "cont-header",
            20,
            "page_header",
            "续表 D.6.2-4",
            bbox=[0.789, 0.077, 0.888, 0.107],
            block_seq=3,
        ),
    ]
    instructions = detect_table_continuations(nodes, doc_id="doc-x")
    assert any(
        instr["kind"] == "table_merge"
        and instr["source_uid"] == "t1"
        and instr["target_uid"] == "t2"
        for instr in instructions
    )


def test_attach_marks_continuation_header_and_links_head():
    """续页顶部引用表号的短文本块应标记为 attachment 并挂到首表。"""
    head = _node(
        "head",
        0,
        "table",
        caption="表 A.0.2-2 散货船设计船型尺度",
        bbox=[0.1, 0.3, 0.9, 0.9],
        merged_from=["frag:uid"],
    )
    header = _node(
        "cont-uid",
        1,
        "paragraph",
        "续表 A.0.2-2",
        bbox=[0.702, 0.1, 0.81, 0.116],
        block_seq=1,
    )
    nodes = [head, header]
    changed = attach_table_continuation_headers(
        nodes, {"frag:uid": 1}
    )
    assert changed == 1
    assert header["layout_category"] == "attachment"
    assert head["caption_block_uids"] == ["cont-uid"]


def test_attach_falls_back_to_page_header_number_when_caption_missing():
    """首表无 caption 时，用本页表号页眉（表 D.6.2-4）确定表组。"""
    head = _node(
        "head",
        19,
        "table",
        bbox=[0.04, 0.151, 0.909, 0.916],
        merged_from=["frag:uid"],
    )
    caption_header = _node(
        "cap-header",
        19,
        "page_header",
        "表 D.6.2-4",
        bbox=[0.8, 0.123, 0.881, 0.151],
        block_seq=2,
        layout_category="furniture",
    )
    cont_header = _node(
        "cont-uid",
        20,
        "page_header",
        "续表 D.6.2-4",
        bbox=[0.789, 0.077, 0.888, 0.107],
        block_seq=3,
    )
    nodes = [head, caption_header, cont_header]
    changed = attach_table_continuation_headers(
        nodes, {"frag:uid": 20}
    )
    assert changed == 1
    assert cont_header["layout_category"] == "attachment"
    assert head["caption_block_uids"] == ["cont-uid"]


def test_attach_works_when_table_merge_was_rejected():
    """合并被校验拒绝时，仍可通过 head_fragment_pages 把续页表头附件化。"""
    head = _node(
        "head",
        19,
        "table",
        caption="表 D.6.2-4",
        bbox=[0.04, 0.151, 0.909, 0.916],
    )
    cont_header = _node(
        "cont-uid",
        20,
        "page_header",
        "续表 D.6.2-4",
        bbox=[0.789, 0.077, 0.888, 0.107],
        block_seq=3,
    )
    nodes = [head, cont_header]
    changed = attach_table_continuation_headers(
        nodes, {"frag:uid": 20}, {"head": [20]}
    )
    assert changed == 1
    assert cont_header["layout_category"] == "attachment"
    assert head["caption_block_uids"] == ["cont-uid"]


def test_canonical_builder_skips_attachment_nodes():
    """attachment 节点不进入 canonical / FTS / 检索等语义层。"""
    from docs_core.step05_sqlite_fts.rebuild.canonical_builder import (
        build_canonical_blocks_from_source,
    )

    raw_blocks = [
        {
            "block_uid": "b1",
            "page_idx": 0,
            "block_seq": 1,
            "block_type": "paragraph",
            "text": "正常内容",
            "layout_category": "content",
        },
        {
            "block_uid": "b2",
            "page_idx": 1,
            "block_seq": 1,
            "block_type": "paragraph",
            "text": "续表 A.0.2-2",
            "layout_category": "attachment",
        },
    ]
    blocks = build_canonical_blocks_from_source("doc-x", raw_blocks)
    assert [b.block_id for b in blocks] == ["b1"]
