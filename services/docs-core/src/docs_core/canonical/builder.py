"""Docs canonical schema 构建器。"""
from html.parser import HTMLParser
import re
from typing import Any, List, Tuple

from docs_core.canonical.types import (
    CanonicalBlock,
    CanonicalChunk,
    CanonicalDocument,
    CanonicalOutlineNode,
    CanonicalTable,
    CitationTarget,
)
from docs_core.structured.result_store_json import file_storage
from docs_core.tables import build_table_representations


# 清洗文本，生成适合检索和比较的简化字段。
def clean_text(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "")).strip()


# 基于字符长度做粗粒度 token 估算，用于 chunk 控制。
def estimate_token_count(text: str) -> int:
    normalized = clean_text(text)
    if not normalized:
        return 0
    return max(1, len(normalized) // 4)


# 基于标题编号和原始层级推断章节层级。
def infer_title_level(text: str, raw_level: object = None) -> int:
    if isinstance(raw_level, int) and raw_level > 0:
        return raw_level

    normalized = clean_text(text)
    if re.match(r"^\d+\.\d+\.\d+", normalized):
        return 3
    if re.match(r"^\d+\.\d+", normalized):
        return 2
    if re.match(r"^\d+[\.\s、]", normalized):
        return 1
    if re.match(r"^[一二三四五六七八九十]+[、.]", normalized):
        return 1
    return 1


class SimpleHtmlTableParser(HTMLParser):
    """最小 HTML 表格解析器。"""

    def __init__(self) -> None:
        super().__init__()
        self.rows: List[List[str]] = []
        self._current_row: List[str] = []
        self._current_cell: List[str] = []
        self._in_cell = False

    def handle_starttag(self, tag: str, attrs: List[Tuple[str, str | None]]) -> None:
        if tag == "tr":
            self._current_row = []
        if tag in {"td", "th"}:
            self._in_cell = True
            self._current_cell = []

    def handle_endtag(self, tag: str) -> None:
        if tag in {"td", "th"} and self._in_cell:
            self._in_cell = False
            self._current_row.append(clean_text("".join(self._current_cell)))
            self._current_cell = []
        if tag == "tr" and self._current_row:
            self.rows.append(self._current_row)
            self._current_row = []

    def handle_data(self, data: str) -> None:
        if self._in_cell:
            self._current_cell.append(data)


# 解析 HTML 表格为二维数组。
def parse_table_html(table_html: str) -> List[List[str]]:
    parser = SimpleHtmlTableParser()
    parser.feed(table_html or "")
    return [row for row in parser.rows if any(cell.strip() for cell in row)]


# 归一化不同来源中的 block_type，收敛到 canonical schema 支持的枚举。
def normalize_block_type(raw_block_type: object) -> str:
    block_type = str(raw_block_type or "unknown").strip()
    mapping = {
        "text": "paragraph",
        "para": "paragraph",
        "paragraph": "paragraph",
        "list": "list_item",
        "list_item": "list_item",
        "table": "table",
        "table_caption": "table_caption",
        "figure": "figure",
        "image": "figure",
        "figure_caption": "figure_caption",
        "header_footer": "header_footer",
        "footnote": "footnote",
        "equation": "formula",
        "equation_interline": "formula",
        "inline_formula": "formula",
        "formula": "formula",
        "title": "title",
    }
    return mapping.get(block_type, "unknown")


# 把 doc_blocks_graph 节点适配为 canonical builder 可消费的统一块结构。
def adapt_graph_node(raw_node: dict[str, Any], index: int) -> dict[str, Any]:
    title_path = raw_node.get("title_path")
    section_path = ""
    if isinstance(title_path, list):
        section_path = " / ".join(str(item).strip() for item in title_path if str(item).strip())

    block_type = normalize_block_type(raw_node.get("block_type"))

    return {
        "id": raw_node.get("id") or f"graph-block-{index}",
        "block_uid": raw_node.get("block_uid") or raw_node.get("id") or f"graph-block-{index}",
        "block_type": block_type,
        "page_idx": raw_node.get("page_idx") or 0,
        "block_seq": raw_node.get("block_seq") or index,
        "text": raw_node.get("plain_text") or "",
        "content": raw_node.get("plain_text") or "",
        "derived_title_level": raw_node.get("derived_level"),
        "title_level": raw_node.get("derived_level"),
        "section_path": section_path,
        "parent_block_uid": raw_node.get("parent_uid"),
        "source_ref": raw_node.get("id"),
        "table_html": raw_node.get("table_html"),
        "caption": raw_node.get("plain_text") if block_type == "table" else "",
    }


# 统一加载 canonical 构建所需的原始块，优先 MinerU blocks，缺失时回退 graph nodes。
def load_source_blocks(library_id: str, doc_id: str) -> List[dict[str, Any]]:
    raw_blocks = file_storage.read_mineru_blocks(library_id, doc_id)
    if raw_blocks:
        return raw_blocks

    graph_payload = file_storage.read_doc_blocks_graph(library_id, doc_id)
    graph_nodes = graph_payload.get("nodes", []) if isinstance(graph_payload, dict) else []
    adapted_nodes = [
        adapt_graph_node(raw_node, index)
        for index, raw_node in enumerate(graph_nodes)
        if isinstance(raw_node, dict)
    ]
    return adapted_nodes


# 从 MinerU blocks 构建 canonical blocks。
def build_canonical_blocks(library_id: str, doc_id: str) -> List[CanonicalBlock]:
    raw_blocks = load_source_blocks(library_id, doc_id)
    canonical_blocks: List[CanonicalBlock] = []
    for index, raw_block in enumerate(raw_blocks):
        text = str(raw_block.get("text") or raw_block.get("content") or "").strip()
        canonical_blocks.append(
            CanonicalBlock(
                block_id=str(raw_block.get("block_uid") or raw_block.get("id") or f"block-{index}"),
                doc_id=doc_id,
                page_idx=int(raw_block.get("page_idx") or raw_block.get("page") or 0),
                block_type=normalize_block_type(raw_block.get("block_type") or raw_block.get("type")),
                text=text,
                text_clean=clean_text(text),
                reading_order=int(raw_block.get("block_seq") or index),
                title_level=(
                    int(raw_block.get("derived_title_level"))
                    if raw_block.get("derived_title_level") is not None
                    else (
                        int(raw_block.get("title_level"))
                        if raw_block.get("title_level") is not None
                        else None
                    )
                ),
                section_path=str(raw_block.get("section_path") or ""),
                source="mineru",
                source_ref=str(raw_block.get("source_ref") or "") or None,
                parent_block_id=str(raw_block.get("parent_block_uid") or "") or None,
            )
        )
    return canonical_blocks


# 为 blocks 推导 section_path，并构建 outline 树。
def build_canonical_outlines(blocks: List[CanonicalBlock]) -> Tuple[List[CanonicalBlock], List[CanonicalOutlineNode]]:
    ordered_blocks = sorted(blocks, key=lambda block: (block.page_idx, block.reading_order))
    normalized_blocks: List[CanonicalBlock] = []
    outlines: List[CanonicalOutlineNode] = []
    title_stack: List[Tuple[int, str, str]] = []

    for index, block in enumerate(ordered_blocks):
        next_block = block
        if block.block_type == "title" and block.text_clean:
            level = infer_title_level(block.text_clean, block.title_level)
            while title_stack and title_stack[-1][0] >= level:
                title_stack.pop()
            outline_id = f"outline-{block.block_id or index}"
            title_stack.append((level, block.text_clean, outline_id))
            section_path = " / ".join(item[1] for item in title_stack)
            next_block = block.model_copy(update={"title_level": level, "section_path": section_path})
            outlines.append(
                CanonicalOutlineNode(
                    outline_id=outline_id,
                    doc_id=block.doc_id,
                    level=level,
                    title=block.text_clean,
                    section_path=section_path,
                    page_idx=block.page_idx,
                    anchor_block_id=block.block_id,
                    parent_outline_id=title_stack[-2][2] if len(title_stack) >= 2 else None,
                )
            )
        elif title_stack and not block.section_path:
            section_path = " / ".join(item[1] for item in title_stack)
            next_block = block.model_copy(update={"section_path": section_path})
        normalized_blocks.append(next_block)
    return normalized_blocks, outlines


# 将一组 blocks 合并为结构感知 chunk。
def build_canonical_chunks(blocks: List[CanonicalBlock]) -> List[CanonicalChunk]:
    ordered_blocks = sorted(blocks, key=lambda block: (block.page_idx, block.reading_order))
    chunks: List[CanonicalChunk] = []
    current_blocks: List[CanonicalBlock] = []

    def flush_current(chunk_type: str = "content") -> None:
        nonlocal current_blocks
        if not current_blocks:
            return
        text = "\n".join(block.text_clean for block in current_blocks if block.text_clean).strip()
        if not text:
            current_blocks = []
            return
        first_block = current_blocks[0]
        last_block = current_blocks[-1]
        chunks.append(
            CanonicalChunk(
                chunk_id=f"chunk-{first_block.block_id}",
                doc_id=first_block.doc_id,
                chunk_type=chunk_type,
                text=text,
                text_clean=clean_text(text),
                token_count=estimate_token_count(text),
                section_path=first_block.section_path,
                page_start=first_block.page_idx,
                page_end=last_block.page_idx,
                source_block_ids=[block.block_id for block in current_blocks],
                citation_targets=[
                    CitationTarget(
                        target_id=first_block.block_id,
                        target_type=chunk_type,
                        doc_id=first_block.doc_id,
                        page_idx=first_block.page_idx,
                        section_path=first_block.section_path,
                        display_title=first_block.section_path or first_block.text_clean[:32],
                        snippet=clean_text(text)[:180],
                    )
                ],
            )
        )
        current_blocks = []

    for block in ordered_blocks:
        if not block.text_clean:
            continue

        if block.block_type == "title":
            flush_current()
            chunks.append(
                CanonicalChunk(
                    chunk_id=f"chunk-title-{block.block_id}",
                    doc_id=block.doc_id,
                    chunk_type="outline_anchor",
                    text=block.text_clean,
                    text_clean=block.text_clean,
                    token_count=estimate_token_count(block.text_clean),
                    section_path=block.section_path,
                    page_start=block.page_idx,
                    page_end=block.page_idx,
                    source_block_ids=[block.block_id],
                    citation_targets=[
                        CitationTarget(
                            target_id=block.block_id,
                            target_type="title",
                            doc_id=block.doc_id,
                            page_idx=block.page_idx,
                            section_path=block.section_path,
                            display_title=block.text_clean,
                            snippet=block.text_clean,
                        )
                    ],
                )
            )
            continue

        if current_blocks and (
            block.section_path != current_blocks[0].section_path
            or block.page_idx - current_blocks[-1].page_idx > 1
            or estimate_token_count("\n".join(item.text_clean for item in current_blocks + [block])) > 260
        ):
            flush_current("list_procedure" if current_blocks[0].block_type == "list_item" else "content")

        current_blocks.append(block)

        if block.block_type == "table" and block.text_clean:
            flush_current("table_summary")

    flush_current("list_procedure" if current_blocks and current_blocks[0].block_type == "list_item" else "content")
    return chunks


# 从原始表格块构建 canonical tables 与 table chunks。
def build_canonical_tables(
    library_id: str,
    doc_id: str,
    blocks: List[CanonicalBlock],
) -> Tuple[List[CanonicalTable], List[CanonicalChunk]]:
    raw_blocks = load_source_blocks(library_id, doc_id)
    block_map = {block.block_id: block for block in blocks}
    tables: List[CanonicalTable] = []
    table_chunks: List[CanonicalChunk] = []

    for index, raw_block in enumerate(raw_blocks):
        block_type = str(raw_block.get("block_type") or raw_block.get("type") or "")
        if block_type != "table":
            continue

        block_id = str(raw_block.get("block_uid") or raw_block.get("id") or f"table-{index}")
        canonical_block = block_map.get(block_id)
        page_idx = canonical_block.page_idx if canonical_block else int(raw_block.get("page_idx") or 0)
        section_path = canonical_block.section_path if canonical_block else str(raw_block.get("section_path") or "")

        content_payload: Any = raw_block.get("content") if isinstance(raw_block.get("content"), dict) else {}
        table_html = (
            str(raw_block.get("table_html") or "")
            or str(content_payload.get("html") or "")
        ).strip()
        if not table_html:
            continue

        parsed_rows = parse_table_html(table_html)
        if not parsed_rows:
            continue

        header_rows = parsed_rows[:1]
        body_rows = parsed_rows[1:] if len(parsed_rows) > 1 else []
        caption = (
            str(raw_block.get("caption") or "")
            or str(content_payload.get("table_caption") or "")
        ).strip()
        title = caption or (canonical_block.text_clean if canonical_block else "") or f"表格-{index + 1}"
        representations = build_table_representations(title, header_rows, body_rows)

        table = CanonicalTable(
            table_id=f"table-{block_id}",
            doc_id=doc_id,
            page_start=page_idx,
            page_end=page_idx,
            title=title,
            caption=caption,
            table_type=representations["table_type"],
            header_rows=[[str(cell) for cell in row] for row in header_rows],
            body_rows=[[str(cell) for cell in row] for row in body_rows],
            row_count=len(body_rows),
            col_count=max((len(row) for row in parsed_rows), default=0),
            source_block_ids=[block_id],
            summary=str(representations.get("table_summary") or ""),
            row_keys=[str(item) for item in representations.get("table_row_keys", [])],
            text_chunks=[str(item) for item in representations.get("table_text_chunks", [])],
        )
        tables.append(table)

        summary_text = table.summary or f"{table.title} 表格摘要"
        table_chunks.append(
            CanonicalChunk(
                chunk_id=f"chunk-{table.table_id}-summary",
                doc_id=doc_id,
                chunk_type="table_summary",
                text=summary_text,
                text_clean=clean_text(summary_text),
                token_count=estimate_token_count(summary_text),
                section_path=section_path,
                page_start=page_idx,
                page_end=page_idx,
                source_block_ids=[block_id],
                citation_targets=[
                    CitationTarget(
                        target_id=table.table_id,
                        target_type="table",
                        doc_id=doc_id,
                        page_idx=page_idx,
                        section_path=section_path,
                        display_title=table.title,
                        snippet=summary_text[:180],
                    )
                ],
            )
        )

        row_chunk_type = "table_mapping_row" if table.table_type == "mapping_enum" else "table_text_row"
        for row_index, row_text in enumerate(table.text_chunks):
            table_chunks.append(
                CanonicalChunk(
                    chunk_id=f"chunk-{table.table_id}-row-{row_index}",
                    doc_id=doc_id,
                    chunk_type=row_chunk_type,
                    text=row_text,
                    text_clean=clean_text(row_text),
                    token_count=estimate_token_count(row_text),
                    section_path=section_path,
                    page_start=page_idx,
                    page_end=page_idx,
                    source_block_ids=[block_id],
                    citation_targets=[
                        CitationTarget(
                            target_id=table.table_id,
                            target_type="table_row",
                            doc_id=doc_id,
                            page_idx=page_idx,
                            section_path=section_path,
                            display_title=table.title,
                            snippet=clean_text(row_text)[:180],
                        )
                    ],
                )
            )

    return tables, table_chunks


# 基于现有落盘结果构建最小 canonical document。
def build_canonical_document(library_id: str, doc_id: str, title: str = "") -> CanonicalDocument:
    markdown = file_storage.read_markdown(library_id, doc_id) or ""
    blocks = build_canonical_blocks(library_id, doc_id)
    blocks, outlines = build_canonical_outlines(blocks)
    chunks = build_canonical_chunks(blocks)
    tables, table_chunks = build_canonical_tables(library_id, doc_id, blocks)
    inferred_title = title or next((block.text for block in blocks if block.block_type == "title" and block.text), doc_id)
    page_count = 0
    if blocks:
        page_count = max(block.page_idx for block in blocks) + 1

    document = CanonicalDocument(
        doc_id=doc_id,
        library_id=library_id,
        title=inferred_title,
        source_file_name=doc_id,
        source_file_type="pdf",
        page_count=page_count,
        status="completed" if markdown or blocks else "pending",
        blocks=blocks,
        outlines=outlines,
        chunks=chunks + table_chunks,
        tables=tables,
    )
    return document
