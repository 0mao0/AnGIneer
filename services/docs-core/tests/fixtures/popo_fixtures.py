"""Phase 0 测试共享 fixture：伪造 popo enriched_blocks 输入。"""

import json

EMPTY_TREE = {"type": "root", "children": []}

TABLE_HTML = (
    "<table><tr><td>参数</td><td>数值</td></tr>"
    "<tr><td>高度</td><td>100</td></tr></table>"
)

MERGED_TABLE_HTML = (
    "<table><tr><th colspan=\"2\">参数</th><th>数值</th></tr>"
    "<tr><td>高度</td><td>H</td><td>100</td></tr>"
    "<tr><td>宽度</td><td>B</td><td>200</td></tr>"
    "<tr><td>深度</td><td>D</td><td>300</td></tr></table>"
)


def make_block(
    block_id: int,
    page: int,
    block_type: str,
    content: str,
    *,
    level: int = -1,
    image: int = -1,
    table_merge: int = -1,
    contd: int = -1,
    cell_list: list = None,
) -> dict:
    payload = {
        "id": block_id,
        "page": page,
        "type": block_type,
        "content": content,
        "bbox": [0.0, 0.0, 100.0, 50.0],
        "level": level,
        "image": image,
        "table_merge": table_merge,
        "contd": contd,
    }
    if cell_list is not None:
        payload["cell_list"] = cell_list
    return payload


def build_noise_fixture() -> list[dict]:
    """含各类噪声块的 popo enriched_blocks 样本。"""
    blocks = [
        make_block(1, 1, "title", "第一章 总则", level=1),
        make_block(2, 1, "text", "这是正文段落。"),
        make_block(3, 1, "page_number", "12"),
        make_block(4, 1, "page_title", "某工程标准"),
        make_block(5, 1, "header", "页眉文本"),
        make_block(6, 1, "footer", "第 1 页 共 3 页"),
        make_block(7, 1, "page_footnote", "页脚注释"),
        make_block(8, 2, "page_number", "13"),
        make_block(9, 1, "aside_text", "旁注：本页内容依据勘误表修改"),
        make_block(10, 1, "image", "", image=-1),
        make_block(11, 1, "image_caption", "图 1 结构示意", image=10),
        make_block(12, 1, "image_footnote", "注：示意图来源自测", image=10),
        make_block(13, 2, "table", TABLE_HTML, table_merge=-1),
        make_block(14, 2, "table_caption", "表 1 参数表", table_merge=13),
        make_block(15, 2, "table_footnote", "注：单位 kN", table_merge=13),
    ]
    return blocks


def build_clean_fixture() -> list[dict]:
    """无噪声块的 popo enriched_blocks 样本。"""
    return [
        make_block(1, 1, "title", "第一章 总则", level=1),
        make_block(2, 1, "text", "这是正文段落。"),
        make_block(3, 2, "equation", "F = ma"),
        make_block(4, 2, "text", "式中：F 为合力。"),
    ]


def build_table_fixture() -> list[dict]:
    """含跨页合并表格（多数据行 + colspan + cell_list）的 popo enriched_blocks 样本。"""
    return [
        make_block(1, 1, "title", "第五章 构件", level=1),
        make_block(2, 2, "table", MERGED_TABLE_HTML, table_merge=-1, cell_list=[0, 1, 0]),
        make_block(3, 2, "table_caption", "表 5.2-1 构件尺寸参数", table_merge=2),
        make_block(4, 2, "table_footnote", "注：单位 mm", table_merge=2),
    ]


def content_list_block(
    block_type: str,
    text: str,
    *,
    level: int | None = None,
    table_html: str | None = None,
    math: str | None = None,
    bbox=None,
) -> dict:
    """构造 solo 引擎可消费的 content_list_v2 页面块。"""
    content: dict = {}
    if block_type == "title":
        content["title_content"] = [{"type": "text", "content": text}]
        if level is not None:
            content["level"] = level
    elif block_type == "paragraph":
        content["paragraph_content"] = [{"type": "text", "content": text}]
    elif block_type == "equation_interline":
        content["math_content"] = math or text
    elif block_type == "table":
        content["html"] = table_html or ""
        content["table_caption"] = [{"type": "text", "content": text}]
    else:
        content["text"] = text
    return {
        "type": block_type,
        "content": content,
        "bbox": list(bbox) if bbox else [0.0, 0.0, 100.0, 50.0],
    }


def build_canonical_from_solo_jsonl(
    doc_id: str,
    content_list_pages,
    out_dir,
    *,
    library_id: str = "lib-1",
):
    """solo 04 全链路（content_list_v2 → StructuredResult → jsonl/meta）→ 05 rebuild。

    PoPo 后端退役后，04 的唯一生产者为 solo；契约测试统一经此链获取 canonical 文档。
    """
    from docs_core.step04_structure.solo_engine import build_structured_from_rawfiles
    from docs_core.step05_sqlite_fts.rebuild.graph_rebuilder import (
        rebuild_canonical_document_from_graph,
    )

    raw_dir = out_dir / "mineru_raw"
    raw_dir.mkdir(parents=True, exist_ok=True)
    (raw_dir / "content_list_v2.json").write_text(
        json.dumps(content_list_pages, ensure_ascii=False),
        encoding="utf-8",
    )
    result = build_structured_from_rawfiles(
        out_dir, doc_id, doc_id, llm_client=None, options={"use_llm": False}
    )
    if result.stats.get("error"):
        raise ValueError(f"solo 构建失败: {result.stats.get('error')}")
    with open(out_dir / "doc_blocks_graph.jsonl", "w", encoding="utf-8") as f:
        for node in result.nodes:
            f.write(json.dumps(node, ensure_ascii=False) + "\n")
    meta = {
        "edges": result.edges,
        "stats": result.stats,
        "generated_at": "2026-08-04T00:00:00",
        "build_id": "test-build-000001",
    }
    (out_dir / "doc_blocks_graph_meta.json").write_text(
        json.dumps(meta, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    nodes = []
    with open(out_dir / "doc_blocks_graph.jsonl", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                nodes.append(json.loads(line))
    graph = {
        "nodes": nodes,
        "edges": meta["edges"],
        "stats": meta["stats"],
        "outlines": [],
        "pages": [],
    }
    return rebuild_canonical_document_from_graph(library_id, doc_id, graph, title="")


def build_document_with_printed_labels(
    doc_id: str = "doc-1",
    *,
    library_id: str = "lib-1",
    page_labels=None,
):
    """直接构造带 printed_page_label 的 canonical 文档（solo 时代 labels 由调用方提供）。"""
    from docs_core.models.types import CanonicalBlock, CanonicalPage
    from docs_core.step05_sqlite_fts.rebuild.canonical_builder import (
        build_canonical_document_from_blocks,
    )

    labels = page_labels or {0: "12", 1: "13"}
    blocks = [
        CanonicalBlock(
            block_id=f"{doc_id}:b1", doc_id=doc_id, page_idx=0,
            block_type="title", text="第一章 总则", text_clean="第一章 总则",
            reading_order=1,
        ),
        CanonicalBlock(
            block_id=f"{doc_id}:b2", doc_id=doc_id, page_idx=1,
            block_type="paragraph", text="正文", text_clean="正文",
            reading_order=2,
        ),
    ]
    pages = [
        CanonicalPage(doc_id=doc_id, page_idx=page_idx, printed_page_label=label)
        for page_idx, label in sorted(labels.items())
    ]
    return build_canonical_document_from_blocks(
        library_id, doc_id, blocks=blocks, pages=pages,
    )
