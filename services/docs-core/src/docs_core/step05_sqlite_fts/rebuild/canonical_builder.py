"""canonical 领域构建器：blocks/outlines/chunks/tables/语义 组装核心（归位 step05）。

归属说明：CanonicalDocument 的唯一组装点收敛在 05（本包）；04 只出 jsonl。
对 step04 的 import（formula_semantics / title_level_refiner / table_html_utils /
jsonl_io）属合法 05→04 单向依赖。
"""
from dataclasses import dataclass
from datetime import UTC, datetime
import re
from typing import Any, List, Optional, Tuple

from docs_core.step05_sqlite_fts.rebuild.tag_rules import infer_conditions, infer_entity_tags
from docs_core.models.types import (
    CanonicalBlock,
    CanonicalChunk,
    CanonicalDocument,
    CanonicalOutlineNode,
    CanonicalPage,
    CanonicalTable,
    CitationTarget,
    PageBBox,
)
from docs_core.step04_structure.shared.formula_semantics import enrich_formula_block
from docs_core.step05_sqlite_fts.rebuild.table_semantics import (
    TABLE_SEMANTICS_VERSION,
    build_table_full_text,
    enrich_canonical_table,
    parse_table_rows,
    split_header_body,
)
from docs_core.step04_structure.shared.title_level_refiner import refine_document_title_levels


@dataclass
class CanonicalSourceInput:
    """canonical 构建所需的落盘输入（由调用方读取提供，builder 不碰文件系统）。"""

    graph_data: Optional[dict] = None
    raw_blocks: Optional[List[dict]] = None
    markdown: str = ""
    manifest: Optional[dict] = None


# 基于 blocks 的 page_idx 推导页面列表（solo 路径；popo 路径由 mapper 提供 pages）
def build_pages_from_blocks(blocks: List[CanonicalBlock]) -> List[CanonicalPage]:
    if not blocks:
        return []
    max_page = max((block.page_idx for block in blocks), default=0)
    return [
        CanonicalPage(doc_id=blocks[0].doc_id, page_idx=page_idx)
        for page_idx in range(max_page + 1)
    ]


def build_page_label_map(pages: List[CanonicalPage]) -> dict[int, str]:
    return {page.page_idx: page.printed_page_label for page in pages if page.printed_page_label}


def _parse_page_bboxes(raw_page_bboxes: Any) -> Optional[List[PageBBox]]:
    """把 jsonl 原始 page_bboxes（bbox 为 [x0, y0, x1, y1] 数组）解析为 PageBBox 模型。"""
    if not isinstance(raw_page_bboxes, list) or not raw_page_bboxes:
        return None
    parsed: List[PageBBox] = []
    for item in raw_page_bboxes:
        if not isinstance(item, dict):
            continue
        bbox = item.get("bbox")
        if isinstance(bbox, (list, tuple)) and len(bbox) >= 4:
            bbox = {
                "x0": float(bbox[0]),
                "y0": float(bbox[1]),
                "x1": float(bbox[2]),
                "y1": float(bbox[3]),
            }
        parsed.append(PageBBox(page_idx=int(item.get("page_idx") or 0), bbox=bbox))
    return parsed or None


# 从标题文本中提取规范条号，如 "5.2.3"
def extract_clause_id(text: str) -> str | None:
    if not text:
        return None
    match = re.match(r"^(\d+(?:\.\d+){1,4})\s", clean_text(text))
    if match:
        return match.group(1)
    return None


# 从 section_path 中提取最近章节归属（取最后一段）
def extract_inherited_chapter(section_path: str) -> str | None:
    if not section_path:
        return None
    parts = [part.strip() for part in section_path.split("/") if part.strip()]
    if not parts:
        return None
    return parts[-1]


# 清洗文本，生成适合检索和比较的简化字段
def clean_text(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "")).strip()


# 基于字符长度做粗粒度 token 估算，用chunk 控制
def estimate_token_count(text: str) -> int:
    normalized = clean_text(text)
    if not normalized:
        return 0
    return max(1, len(normalized) // 4)


# 基于标题编号和原始层级推断章节层级
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
    if re.match(r"^[一二三四五六七八九十]+", normalized):
        return 1
    return 1


# 归一化不同来源中block_type，收敛到 canonical schema 支持的枚举
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
        "page_header": "header_footer",
        "page_number": "header_footer",
        "page_footer": "header_footer",
        "footnote": "footnote",
        "equation": "formula",
        "equation_interline": "formula",
        "inline_formula": "formula",
        "formula": "formula",
        "title": "title",
        "index": "toc",
        "toc": "toc",
    }
    return mapping.get(block_type, "unknown")


# MinerU blocks 构建 canonical blocks
def build_canonical_blocks(doc_id: str, source: CanonicalSourceInput) -> List[CanonicalBlock]:
    raw_blocks = source.raw_blocks or []
    return build_canonical_blocks_from_source(doc_id, raw_blocks)


# 从已归一化的 source blocks 构建 canonical blocks
def build_canonical_blocks_from_source(doc_id: str, raw_blocks: List[dict[str, Any]]) -> List[CanonicalBlock]:
    canonical_blocks: List[CanonicalBlock] = []
    for index, raw_block in enumerate(raw_blocks):
        if str(raw_block.get("layout_category") or "") == "attachment":
            continue
        text = str(raw_block.get("text") or raw_block.get("content") or "").strip()
        section_path = str(raw_block.get("section_path") or "")
        formula_semantics = raw_block.get("formula_semantics")
        canonical_blocks.append(
            CanonicalBlock(
                block_id=str(raw_block.get("block_uid") or raw_block.get("id") or f"block-{index}"),
                doc_id=doc_id,
                page_idx=int(raw_block.get("page_idx") or raw_block.get("page") or 0),
                block_type=normalize_block_type(raw_block.get("block_type") or raw_block.get("type")),
                text=text,
                text_clean=clean_text(text),
                bbox=raw_block.get("bbox"),
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
                contd_target_id=raw_block.get("contd_target_id"),
                image_assoc_id=raw_block.get("image_assoc_id"),
                table_merge_id=raw_block.get("table_merge_id"),
                raw_type=raw_block.get("raw_type"),
                document_part=raw_block.get("document_part"),
                page_role=raw_block.get("page_role"),
                layout_category=raw_block.get("layout_category"),
                page_bboxes=_parse_page_bboxes(raw_block.get("page_bboxes")),
                merged_from=raw_block.get("merged_from"),
                table_html=raw_block.get("table_html"),
                formula_semantics=(
                    dict(formula_semantics)
                    if isinstance(formula_semantics, dict) and formula_semantics
                    else None
                ),
                clause_id=extract_clause_id(text),
                inherited_chapter=extract_inherited_chapter(section_path),
                entity_tags=infer_entity_tags(text, section_path),
                conditions=infer_conditions(text, section_path),
            )
        )
    return canonical_blocks


# blocks 推导 section_path，并构建 outline 树
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
            next_block = block.model_copy(update={
                "title_level": level,
                "section_path": section_path,
                "clause_id": extract_clause_id(block.text_clean),
                "inherited_chapter": extract_inherited_chapter(section_path),
                "entity_tags": infer_entity_tags(block.text_clean, section_path),
                "conditions": infer_conditions(block.text_clean, section_path),
            })
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
            next_block = block.model_copy(update={
                "section_path": section_path,
                "inherited_chapter": extract_inherited_chapter(section_path),
            })
        normalized_blocks.append(next_block)
    return normalized_blocks, outlines


# 标题/目录块 → outline_anchor chunk（锚点参与 locate_qa，不混入正文检索）
def _build_anchor_chunk(block: CanonicalBlock, label_map: dict[int, str], prefix: str) -> CanonicalChunk:
    return CanonicalChunk(
        chunk_id=f"chunk-{prefix}-{block.block_id}",
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
                printed_page_label=label_map.get(block.page_idx),
            )
        ],
        inherited_chapter=block.inherited_chapter,
        entity_tags=block.entity_tags,
        conditions=block.conditions,
        exam_tags=block.exam_tags,
        clause_id=block.clause_id,
    )


# 将一blocks 合并为结构感chunk
def build_canonical_chunks(
    blocks: List[CanonicalBlock],
    page_label_map: Optional[dict[int, str]] = None,
) -> List[CanonicalChunk]:
    ordered_blocks = sorted(blocks, key=lambda block: (block.page_idx, block.reading_order))
    chunks: List[CanonicalChunk] = []
    current_blocks: List[CanonicalBlock] = []
    label_map = page_label_map or {}

    def flush_current(chunk_type: str = "content") -> None:
        nonlocal current_blocks
        if not current_blocks:
            return
        text = "\n".join(block.text_clean for block in current_blocks if block.text_clean).strip()
        if not text:
            current_blocks = []
            return
        first_block = current_blocks[0]

        def _block_page_end(block: CanonicalBlock) -> int:
            page_bboxes = block.page_bboxes or []
            if page_bboxes:
                return max(int(item.page_idx) for item in page_bboxes)
            return block.page_idx

        page_end = max(_block_page_end(block) for block in current_blocks)
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
                page_end=page_end,
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
                        printed_page_label=label_map.get(first_block.page_idx),
                    )
                ],
                inherited_chapter=first_block.inherited_chapter,
                entity_tags=first_block.entity_tags,
                conditions=first_block.conditions,
                exam_tags=first_block.exam_tags,
                clause_id=first_block.clause_id,
            )
        )
        current_blocks = []

    for block in ordered_blocks:
        if not block.text_clean:
            continue
        # 页眉页脚不参与正文 chunk（展示层保留在 blocks/segments）
        if block.block_type == "header_footer":
            continue

        if block.block_type == "title":
            flush_current()
            chunks.append(_build_anchor_chunk(block, label_map, "title"))
            continue

        # 目录保留为章节锚点，但不混入正文 chunk
        if block.block_type == "toc":
            flush_current()
            chunks.append(_build_anchor_chunk(block, label_map, "toc"))
            continue

        is_in_formula_group = current_blocks and any(b.block_type == "formula" for b in current_blocks)
        is_formula_param = is_in_formula_group and block.block_type == "paragraph"
        should_flush = current_blocks and (
            (block.section_path != current_blocks[0].section_path and not is_formula_param)
            or block.page_idx - current_blocks[-1].page_idx > 1
            or (not is_formula_param and estimate_token_count("\n".join(item.text_clean for item in current_blocks + [block])) > 260)
        )
        if should_flush:
            flush_current("formula_block" if is_in_formula_group else ("list_procedure" if _is_list_procedure_group(current_blocks) else "content"))

        current_blocks.append(block)

        if block.block_type == "table" and block.text_clean:
            has_formula = any(b.block_type == "formula" for b in current_blocks[:-1])
            if has_formula:
                formula_idx = next(i for i, b in enumerate(current_blocks) if b.block_type == "formula")
                formula_group = current_blocks[formula_idx:-1]
                pre_formula = current_blocks[:formula_idx]
                if pre_formula:
                    current_blocks = pre_formula
                    flush_current("content")
                current_blocks = formula_group
                flush_current("formula_block")
                current_blocks = [block]
            flush_current("table_summary")

    is_formula_tail = current_blocks and any(b.block_type == "formula" for b in current_blocks)
    flush_current("formula_block" if is_formula_tail else ("list_procedure" if _is_list_procedure_group(current_blocks) else "content"))
    return chunks


# P9 加固：组内 list_item 占比过半（>50%）才定流程块类型
def _is_list_procedure_group(blocks: List[CanonicalBlock]) -> bool:
    if not blocks:
        return False
    list_items = sum(1 for block in blocks if block.block_type == "list_item")
    return list_items >= 1 and list_items / len(blocks) > 0.5


# 从已归一化的 source blocks 构建 canonical tables/table chunks
def build_canonical_tables_from_source(
    doc_id: str,
    raw_blocks: List[dict[str, Any]],
    blocks: List[CanonicalBlock],
) -> Tuple[List[CanonicalTable], List[CanonicalChunk]]:
    block_map = {block.block_id: block for block in blocks}
    raw_by_id = {
        str(raw_block.get("block_uid") or raw_block.get("id") or f"table-{index}"): raw_block
        for index, raw_block in enumerate(raw_blocks)
    }

    # 候选表格块：graph 原始块优先（solo）；popo 路径 graph 节点无 table_html 或
    # graph 为空时，回退 CanonicalBlock.table_html 旁路字段。
    candidates: List[tuple[str, dict[str, Any], Optional[CanonicalBlock]]] = []
    seen_ids: set[str] = set()
    for index, raw_block in enumerate(raw_blocks):
        block_type = str(raw_block.get("block_type") or raw_block.get("type") or "")
        if block_type != "table":
            continue
        block_id = str(raw_block.get("block_uid") or raw_block.get("id") or f"table-{index}")
        canonical_block = block_map.get(block_id)
        content_payload: Any = raw_block.get("content") if isinstance(raw_block.get("content"), dict) else {}
        table_html = (
            str(raw_block.get("table_html") or "")
            or str(content_payload.get("html") or "")
            or str((canonical_block.table_html or "") if canonical_block else "")
        ).strip()
        if not table_html:
            continue
        candidates.append((block_id, raw_block, canonical_block))
        seen_ids.add(block_id)
    for block in blocks:
        if block.block_type != "table" or not block.table_html:
            continue
        if block.block_id in seen_ids:
            continue
        candidates.append((block.block_id, raw_by_id.get(block.block_id, {}), block))
        seen_ids.add(block.block_id)

    tables: List[CanonicalTable] = []
    table_chunks: List[CanonicalChunk] = []

    for index, (block_id, raw_block, canonical_block) in enumerate(candidates):
        page_idx = canonical_block.page_idx if canonical_block else int(raw_block.get("page_idx") or 0)
        section_path = canonical_block.section_path if canonical_block else str(raw_block.get("section_path") or "")

        content_payload: Any = raw_block.get("content") if isinstance(raw_block.get("content"), dict) else {}
        table_html = (
            str(raw_block.get("table_html") or "")
            or str(content_payload.get("html") or "")
            or str((canonical_block.table_html or "") if canonical_block else "")
        ).strip()
        if not table_html:
            continue

        parsed_rows = parse_table_rows(table_html)
        if not parsed_rows:
            continue

        header_rows, body_rows = split_header_body(parsed_rows)
        caption = (
            str(raw_block.get("caption") or "")
            or str(content_payload.get("table_caption") or "")
        ).strip()
        title = _resolve_table_title(caption, canonical_block, header_rows, index)

        table = CanonicalTable(
            table_id=f"table-{block_id}",
            doc_id=doc_id,
            page_bboxes=canonical_block.page_bboxes if canonical_block else None,
            page_start=page_idx,
            page_end=max(
                [int(item.page_idx) for item in (canonical_block.page_bboxes or [])] or [page_idx]
            ),
            title=title,
            caption=caption,
            header_rows=[[str(cell) for cell in row] for row in header_rows],
            body_rows=[[str(cell) for cell in row] for row in body_rows],
            row_count=len(body_rows),
            col_count=max((len(row) for row in parsed_rows), default=0),
            source_block_ids=[block_id],
            summary="",
            row_keys=[],
            text_chunks=[],
        )
        sidecar = raw_block.get("table_semantics")
        sidecar_current = (
            isinstance(sidecar, dict)
            and bool(sidecar)
            and str(sidecar.get("version") or "") == TABLE_SEMANTICS_VERSION
        )
        if sidecar_current:
            # 04 已生成同版本 table_semantics 旁路：05 透传，不再重算
            table = table.model_copy(
                update={
                    "table_type": str(sidecar.get("table_type") or "hybrid"),
                    "summary": str(sidecar.get("table_summary") or ""),
                    "row_keys": [str(item) for item in sidecar.get("table_row_keys") or []],
                    "text_chunks": [str(item) for item in sidecar.get("table_text_chunks") or []],
                }
            )
        else:
            enriched = enrich_canonical_table(table)
            table = table.model_copy(
                update={
                    "table_type": enriched["table_type"],
                    "summary": enriched["summary"],
                    "row_keys": enriched["row_keys"],
                    "text_chunks": enriched["text_chunks"],
                }
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
                inherited_chapter=canonical_block.inherited_chapter if canonical_block else None,
                entity_tags=canonical_block.entity_tags if canonical_block else [],
                conditions=canonical_block.conditions if canonical_block else [],
                exam_tags=canonical_block.exam_tags if canonical_block else [],
                clause_id=canonical_block.clause_id if canonical_block else None,
            )
        )

        full_text = build_table_full_text(table.title, table.header_rows, table.body_rows)
        if full_text:
            table_chunks.append(
                CanonicalChunk(
                    chunk_id=f"chunk-{table.table_id}-full",
                    doc_id=doc_id,
                    chunk_type="table_full",
                    text=full_text,
                    text_clean=clean_text(full_text),
                    token_count=estimate_token_count(full_text),
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
                            snippet=full_text[:180],
                        )
                    ],
                    inherited_chapter=canonical_block.inherited_chapter if canonical_block else None,
                    entity_tags=canonical_block.entity_tags if canonical_block else [],
                    conditions=canonical_block.conditions if canonical_block else [],
                    exam_tags=canonical_block.exam_tags if canonical_block else [],
                    clause_id=canonical_block.clause_id if canonical_block else None,
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
                    inherited_chapter=canonical_block.inherited_chapter if canonical_block else None,
                    entity_tags=canonical_block.entity_tags if canonical_block else [],
                    conditions=canonical_block.conditions if canonical_block else [],
                    exam_tags=canonical_block.exam_tags if canonical_block else [],
                    clause_id=canonical_block.clause_id if canonical_block else None,
                )
            )

    return tables, table_chunks


# 解析表格展示标题。popo 路径（raw_type=="table"）优先取并入宿主文本中的
# “表 N xxx” caption 行，否则回退表头行；solo 路径保持原行为（text_clean 回退）。
def _resolve_table_title(
    caption: str,
    canonical_block: Optional[CanonicalBlock],
    header_rows: List[List[str]],
    index: int,
) -> str:
    if caption:
        return caption
    if canonical_block is not None and canonical_block.raw_type == "table":
        caption_line = next(
            (
                line.strip()
                for line in (canonical_block.text or "").splitlines()
                if re.match(r"^\s*表\s*\d", line)
            ),
            "",
        )
        if caption_line:
            return caption_line
        header_text = " | ".join(cell for cell in (header_rows[0] if header_rows else []) if cell).strip()
        if header_text:
            return header_text[:60]
        return f"表格-{index + 1}"
    return (canonical_block.text_clean if canonical_block else "") or f"表格-{index + 1}"


# 从 blocks 构建稳定的独立 citation targets（可选附带原始节点信息用于图/公式标题）
def build_citation_targets(
    doc_id: str,
    blocks: List[CanonicalBlock],
    tables: List[CanonicalTable],
    pages: Optional[List[CanonicalPage]] = None,
    *,
    raw_node_map: Optional[dict[str, dict[str, Any]]] = None,
) -> List[CitationTarget]:
    label_map = build_page_label_map(pages or [])
    table_block_ids = {table.source_block_ids[0]: table for table in tables if table.source_block_ids}
    targets: List[CitationTarget] = []
    seen_keys: set[tuple[str, str]] = set()

    def append_target(target: CitationTarget) -> None:
        dedupe_key = (target.target_id, target.target_type)
        if dedupe_key in seen_keys:
            return
        seen_keys.add(dedupe_key)
        targets.append(target)

    for block in blocks:
        raw_block = (raw_node_map or {}).get(block.block_id, {})
        block_type = block.block_type
        if block_type == "table" and block.block_id in table_block_ids:
            table = table_block_ids[block.block_id]
            append_target(
                CitationTarget(
                    target_id=table.table_id,
                    target_type="table",
                    doc_id=doc_id,
                    page_idx=table.page_start,
                    bbox=block.bbox,
                    section_path=block.section_path,
                    display_title=table.title or table.caption or "表格",
                    snippet=clean_text(table.summary or table.caption or block.text_clean)[:180],
                    printed_page_label=label_map.get(table.page_start),
                )
            )
            continue
        if block_type == "figure":
            caption = str(raw_block.get("caption") or "").strip()
            footnote = str(raw_block.get("footnote") or "").strip()
            display_title = caption or block.text_clean or "图片"
            snippet = clean_text(" ".join(item for item in [block.text_clean, caption, footnote] if item))[:180]
            append_target(
                CitationTarget(
                    target_id=block.block_id,
                    target_type="figure",
                    doc_id=doc_id,
                    page_idx=block.page_idx,
                    bbox=block.bbox,
                    section_path=block.section_path,
                    display_title=display_title,
                    snippet=snippet or display_title,
                    printed_page_label=label_map.get(block.page_idx),
                )
            )
            continue
        if block_type == "formula":
            content_json = raw_block.get("content_json") if isinstance(raw_block.get("content_json"), dict) else {}
            formula_number = str(content_json.get("formula_number") or "").strip()
            formula_summary = str(content_json.get("formula_summary") or "").strip()
            display_title = clean_text(" ".join(item for item in ["公式", formula_number] if item)) or "公式"
            snippet = clean_text(" ".join(item for item in [formula_summary, block.text_clean] if item))[:180]
            append_target(
                CitationTarget(
                    target_id=block.block_id,
                    target_type="formula",
                    doc_id=doc_id,
                    page_idx=block.page_idx,
                    bbox=block.bbox,
                    section_path=block.section_path,
                    display_title=display_title,
                    snippet=snippet or display_title,
                    printed_page_label=label_map.get(block.page_idx),
                )
            )
            continue
        if block_type == "title":
            append_target(
                CitationTarget(
                    target_id=block.block_id,
                    target_type="title",
                    doc_id=doc_id,
                    page_idx=block.page_idx,
                    bbox=block.bbox,
                    section_path=block.section_path,
                    display_title=block.text_clean or "标题",
                    snippet=(block.text_clean or block.section_path or "标题")[:180],
                    printed_page_label=label_map.get(block.page_idx),
                )
            )
    return targets


# 语义层挂在 Canonical 之后——公式语义增强（表格已在 build_canonical_tables_*
# 内经 enrich_canonical_table 填充），两条后端统一受益。产物挂在 CanonicalBlock
# 的 formula_semantics 旁路字段（随 graph jsonl 节点与 doc_blocks 行保留）。
def enrich_document_semantics(
    document: CanonicalDocument,
    *,
    use_llm: bool = False,
    llm_client: Any = None,
    llm_model: Optional[str] = None,
) -> CanonicalDocument:
    if not document.blocks:
        return document
    ordered = sorted(document.blocks, key=lambda block: (block.page_idx, block.reading_order))
    formula_contracts: dict[str, dict] = {}
    for block in ordered:
        if block.block_type == "formula":
            if block.formula_semantics and not use_llm:
                # jsonl 已落盘的公式语义（04 生产）：05 重建时原样透传，不重算
                contract = dict(block.formula_semantics)
            else:
                contract = enrich_formula_block(
                    block,
                    ordered,
                    llm_client=llm_client,
                    llm_model=llm_model,
                    use_llm=use_llm,
                )
            formula_contracts[block.block_id] = contract
    new_blocks: List[CanonicalBlock] = [
        block.model_copy(update={"formula_semantics": formula_contracts[block.block_id]})
        if block.block_id in formula_contracts
        else block
        for block in document.blocks
    ]
    return document.model_copy(update={"blocks": new_blocks})


# 直接消费 CanonicalBlock（经 graph jsonl 适配）构建 canonical document，
# 表格/引用目标均从 Canonical 对象生成。
def build_canonical_document_from_blocks(
    library_id: str,
    doc_id: str,
    title: str = "",
    blocks: Optional[List[CanonicalBlock]] = None,
    pages: Optional[List[CanonicalPage]] = None,
    *,
    outlines: Optional[List[CanonicalOutlineNode]] = None,
    raw_blocks: Optional[List[dict[str, Any]]] = None,
    raw_node_map: Optional[dict[str, dict[str, Any]]] = None,
    markdown: str = "",
    manifest: Optional[dict] = None,
    use_llm: bool = False,
    llm_client: Any = None,
    llm_model: Optional[str] = None,
) -> CanonicalDocument:
    markdown = markdown or ""
    manifest = manifest or {}
    local_blocks = list(blocks) if blocks else []
    local_blocks = refine_document_title_levels(
        local_blocks,
        use_llm=use_llm,
        llm_client=llm_client,
        llm_model=llm_model,
    )
    # 块 section_path 回填始终执行；outline 列表仅在调用方未提供时由标题块重推
    local_blocks, generated_outlines = build_canonical_outlines(local_blocks)
    final_outlines = outlines if outlines is not None else generated_outlines
    local_pages = list(pages) if pages else build_pages_from_blocks(local_blocks)
    label_map = build_page_label_map(local_pages)
    chunks = build_canonical_chunks(local_blocks, label_map)
    tables, table_chunks = build_canonical_tables_from_source(doc_id, raw_blocks or [], local_blocks)
    inferred_title = title or next(
        (block.text for block in local_blocks if block.block_type == "title" and block.text), doc_id
    )
    source_file_name = ""
    if manifest.get("source_file"):
        source_file_name = str(manifest.get("source_file") or "").split("\\")[-1].split("/")[-1]
    page_count = 0
    if local_blocks:
        page_count = max(block.page_idx for block in local_blocks) + 1
    timestamp = datetime.now(UTC).isoformat()

    document = CanonicalDocument(
        doc_id=doc_id,
        library_id=library_id,
        title=inferred_title,
        source_file_name=source_file_name or doc_id,
        source_file_type="pdf",
        page_count=page_count,
        status="completed" if markdown or local_blocks else "pending",
        created_at=timestamp,
        updated_at=timestamp,
        pages=local_pages,
        blocks=local_blocks,
        outlines=final_outlines,
        chunks=chunks + table_chunks,
        tables=tables,
        citation_targets=build_citation_targets(doc_id, local_blocks, tables, local_pages, raw_node_map=raw_node_map),
    )
    return enrich_document_semantics(
        document,
        use_llm=use_llm,
        llm_client=llm_client,
        llm_model=llm_model,
    )


# 基于给定落盘输入构建 canonical document（source 缺省时按空输入构建）
def build_canonical_document(
    library_id: str,
    doc_id: str,
    title: str = "",
    *,
    source: Optional[CanonicalSourceInput] = None,
    use_llm: bool = False,
    llm_client: Any = None,
    llm_model: Optional[str] = None,
) -> CanonicalDocument:
    src = source or CanonicalSourceInput()
    blocks = build_canonical_blocks(doc_id, src)
    return build_canonical_document_from_blocks(
        library_id,
        doc_id,
        title=title,
        blocks=blocks,
        markdown=src.markdown or "",
        manifest=src.manifest or {},
        use_llm=use_llm,
        llm_client=llm_client,
        llm_model=llm_model,
    )
