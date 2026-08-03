"""Docs canonical schema 构建器"""
from dataclasses import dataclass
from datetime import UTC, datetime
import re
from typing import Any, List, Optional, Tuple

from docs_core.ingest.canonical.tag_rules import infer_conditions, infer_entity_tags
from docs_core.ingest.canonical.types import (
    CanonicalBlock,
    CanonicalChunk,
    CanonicalDocument,
    CanonicalOutlineNode,
    CanonicalPage,
    CanonicalTable,
    CitationTarget,
)
from docs_core.ingest.semantics.formula_semantics import enrich_canonical_block
from docs_core.ingest.semantics.table_semantics import enrich_canonical_table
from docs_core.ingest.structure.popo_table_extract import parse_table_html
from docs_core.ingest.structure.title_level_refiner import resolve_title_level_refinement


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


def _coerce_bbox(raw_bbox: object) -> object:
    """把语义图中的 bbox 归一化为 canonical BoundingBox 兼容字典。"""
    if isinstance(raw_bbox, dict):
        return raw_bbox
    if isinstance(raw_bbox, (list, tuple)) and len(raw_bbox) >= 4:
        return {
            "x0": float(raw_bbox[0] or 0.0),
            "y0": float(raw_bbox[1] or 0.0),
            "x1": float(raw_bbox[2] or 0.0),
            "y1": float(raw_bbox[3] or 0.0),
        }
    return None


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
        "footnote": "footnote",
        "equation": "formula",
        "equation_interline": "formula",
        "inline_formula": "formula",
        "formula": "formula",
        "title": "title",
    }
    return mapping.get(block_type, "unknown")


# 归一化图谱中的章节标题，尽量去掉目录页里尾部页码噪声
def normalize_graph_section_title(text: str) -> str:
    normalized = clean_text(text)
    return re.sub(r"\s*\(\d+\)\s*$", "", normalized)


# 基于图谱父子关系推导当前节点的可section_path
def resolve_graph_section_path(
    block_uid: str,
    node_map: dict[str, dict[str, Any]],
    cache: dict[str, str],
) -> str:
    if not block_uid:
        return ""
    cached_value = cache.get(block_uid)
    if cached_value is not None:
        return cached_value
    node = node_map.get(block_uid) or {}
    parent_uid = str(node.get("parent_uid") or "").strip()
    parent_path = resolve_graph_section_path(parent_uid, node_map, cache) if parent_uid else ""
    node_text = normalize_graph_section_title(str(node.get("plain_text") or node.get("text") or "").strip())
    node_block_type = normalize_block_type(node.get("block_type"))
    current_title = ""
    if node_text and (node.get("derived_level") is not None or node_block_type == "title"):
        current_title = node_text
    if current_title and parent_path:
        cache[block_uid] = f"{parent_path} / {current_title}"
    else:
        cache[block_uid] = current_title or parent_path
    return cache[block_uid]


# 把单doc_blocks_graph 节点适配canonical builder 可消费的统一块结构
def adapt_graph_node(raw_node: dict[str, Any], index: int, section_path: str) -> dict[str, Any]:
    block_type = normalize_block_type(raw_node.get("block_type"))
    content_json = raw_node.get("content_json") if isinstance(raw_node.get("content_json"), dict) else {}

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
        "bbox": _coerce_bbox(raw_node.get("bbox")),
        "table_html": raw_node.get("table_html"),
        "raw_type": raw_node.get("raw_type"),
        "content_json": content_json,
        "caption": raw_node.get("caption") or (raw_node.get("plain_text") if block_type == "table" else ""),
        "footnote": raw_node.get("footnote") or "",
    }


# 把整份图谱节点转换为 canonical builder 可消费的最终审核块结构
def adapt_graph_nodes(graph_nodes: List[dict[str, Any]]) -> List[dict[str, Any]]:
    node_map = {
        str(node.get("block_uid") or node.get("id") or "").strip(): node
        for node in graph_nodes
        if isinstance(node, dict) and str(node.get("block_uid") or node.get("id") or "").strip()
    }
    section_path_cache: dict[str, str] = {}
    adapted_nodes: List[dict[str, Any]] = []
    for index, raw_node in enumerate(graph_nodes):
        if not isinstance(raw_node, dict):
            continue
        block_uid = str(raw_node.get("block_uid") or raw_node.get("id") or "").strip()
        section_path = resolve_graph_section_path(block_uid, node_map, section_path_cache)
        adapted_nodes.append(adapt_graph_node(raw_node, index, section_path))
    return adapted_nodes


# 统一加载 canonical 构建所需的最终审核块，优graph nodes，其mineru_blocks
def load_source_blocks(source: CanonicalSourceInput) -> List[dict[str, Any]]:
    graph_payload = source.graph_data or {}
    graph_nodes = graph_payload.get("nodes", []) if isinstance(graph_payload, dict) else []
    if graph_nodes:
        return adapt_graph_nodes(graph_nodes)

    raw_blocks = source.raw_blocks or []
    if raw_blocks:
        return raw_blocks
    return []


# MinerU blocks 构建 canonical blocks
def build_canonical_blocks(doc_id: str, source: CanonicalSourceInput) -> List[CanonicalBlock]:
    raw_blocks = load_source_blocks(source)
    return build_canonical_blocks_from_source(doc_id, raw_blocks)


# 从已归一化的 source blocks 构建 canonical blocks
def build_canonical_blocks_from_source(doc_id: str, raw_blocks: List[dict[str, Any]]) -> List[CanonicalBlock]:
    canonical_blocks: List[CanonicalBlock] = []
    for index, raw_block in enumerate(raw_blocks):
        text = str(raw_block.get("text") or raw_block.get("content") or "").strip()
        section_path = str(raw_block.get("section_path") or "")
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
                raw_type=raw_block.get("raw_type"),
                table_html=raw_block.get("table_html"),
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


# 阶段二：标题层级 LLM 校正（Canonical 生成之后、outlines/chunks 之前），
# 对两条后端统一生效。置信度 ≥ 阈值的标题不发起 LLM 调用。
def refine_document_title_levels(
    blocks: List[CanonicalBlock],
    *,
    use_llm: bool = False,
    llm_client: Any = None,
    llm_model: Optional[str] = None,
) -> List[CanonicalBlock]:
    title_blocks = [
        block for block in blocks
        if block.block_type == "title" and (block.text_clean or block.text)
    ]
    if not title_blocks:
        return blocks
    candidates, llm_levels, _status = resolve_title_level_refinement(
        title_blocks,
        llm_client,
        use_llm=use_llm,
        llm_model=llm_model,
    )
    if not llm_levels:
        return blocks
    candidate_map = {candidate["block_id"]: candidate for candidate in candidates}
    by_id = {block.block_id: block for block in blocks}
    for block_id, (level, confidence) in llm_levels.items():
        block = by_id.get(block_id)
        if block is None:
            continue
        candidate = candidate_map.get(block_id)
        current_confidence = float(candidate.get("confidence") or 0.0) if candidate else 0.0
        if block.title_level is None or confidence >= current_confidence:
            by_id[block_id] = block.model_copy(update={"title_level": level})
    return [by_id[block.block_id] for block in blocks]


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
                            printed_page_label=label_map.get(block.page_idx),
                        )
                    ],
                    inherited_chapter=block.inherited_chapter,
                    entity_tags=block.entity_tags,
                    conditions=block.conditions,
                    exam_tags=block.exam_tags,
                    clause_id=block.clause_id,
                )
            )
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


# 从原始表格块构建 canonical tables table chunks
def build_canonical_tables(
    doc_id: str,
    blocks: List[CanonicalBlock],
    source: CanonicalSourceInput,
) -> Tuple[List[CanonicalTable], List[CanonicalChunk]]:
    raw_blocks = load_source_blocks(source)
    return build_canonical_tables_from_source(doc_id, raw_blocks, blocks)


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
    # graph 为空时，回退 CanonicalBlock.table_html 旁路字段（阶段一 G1）。
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

        parsed_rows = parse_table_html(table_html)
        if not parsed_rows:
            continue

        header_rows = parsed_rows[:1]
        body_rows = parsed_rows[1:] if len(parsed_rows) > 1 else []
        caption = (
            str(raw_block.get("caption") or "")
            or str(content_payload.get("table_caption") or "")
        ).strip()
        title = _resolve_table_title(caption, canonical_block, header_rows, index)

        table = CanonicalTable(
            table_id=f"table-{block_id}",
            doc_id=doc_id,
            page_start=page_idx,
            page_end=page_idx,
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


# 阶段一：解析表格展示标题。popo 路径（raw_type=="table"）优先取并入宿主文本中的
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


# 从语义图重建稳定的独立 citation targets
def build_citation_targets_from_graph(
    doc_id: str,
    graph_data: dict[str, Any],
    blocks: List[CanonicalBlock],
    tables: List[CanonicalTable],
    pages: Optional[List[CanonicalPage]] = None,
) -> List[CitationTarget]:
    raw_blocks = adapt_graph_nodes(graph_data.get("nodes", []))
    raw_block_map = {
        str(item.get("block_uid") or item.get("id") or "").strip(): item
        for item in raw_blocks
        if isinstance(item, dict)
    }
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
        raw_block = raw_block_map.get(block.block_id, {})
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


# 阶段一：语义层挂在 Canonical 之后——公式语义增强（表格已在 build_canonical_tables_*
# 内经 enrich_canonical_table 填充），两条后端统一受益。产物挂在 CanonicalBlock 的
# formula_semantics 旁路字段（构建期，不落库；挂载点由阶段三统一投影时定）。
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
            contract = enrich_canonical_block(
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


# 阶段四（G3/P1b）：直接消费后端产出的 CanonicalBlock 构建 canonical document，
# 不再经 graph jsonl 中转（表格/引用目标均从 Canonical 对象生成）。
def build_canonical_document_from_blocks(
    library_id: str,
    doc_id: str,
    title: str = "",
    blocks: Optional[List[CanonicalBlock]] = None,
    pages: Optional[List[CanonicalPage]] = None,
    *,
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
    local_blocks, outlines = build_canonical_outlines(local_blocks)
    local_pages = list(pages) if pages else build_pages_from_blocks(local_blocks)
    label_map = build_page_label_map(local_pages)
    chunks = build_canonical_chunks(local_blocks, label_map)
    tables, table_chunks = build_canonical_tables_from_source(doc_id, [], local_blocks)
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
        outlines=outlines,
        chunks=chunks + table_chunks,
        tables=tables,
        citation_targets=build_citation_targets_from_graph(doc_id, {}, local_blocks, tables, local_pages),
    )
    return enrich_document_semantics(document)


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


# 直接从给定语义图重建 canonical document
def rebuild_canonical_document_from_graph(
    library_id: str,
    doc_id: str,
    graph_data: dict[str, Any],
    title: str = "",
    *,
    use_llm: bool = False,
    llm_client: Any = None,
    llm_model: Optional[str] = None,
) -> CanonicalDocument:
    raw_blocks = adapt_graph_nodes(graph_data.get("nodes", []))
    blocks = build_canonical_blocks_from_source(doc_id, raw_blocks)
    blocks = refine_document_title_levels(
        blocks,
        use_llm=use_llm,
        llm_client=llm_client,
        llm_model=llm_model,
    )
    blocks, outlines = build_canonical_outlines(blocks)
    pages = build_pages_from_blocks(blocks)
    label_map = build_page_label_map(pages)
    chunks = build_canonical_chunks(blocks, label_map)
    tables, table_chunks = build_canonical_tables_from_source(doc_id, raw_blocks, blocks)
    inferred_title = title or next((block.text for block in blocks if block.block_type == "title" and block.text), doc_id)
    page_count = max((block.page_idx for block in blocks), default=-1) + 1 if blocks else 0
    timestamp = datetime.now(UTC).isoformat()
    document = CanonicalDocument(
        doc_id=doc_id,
        library_id=library_id,
        title=inferred_title,
        source_file_name=doc_id,
        source_file_type="pdf",
        page_count=page_count,
        status="completed" if blocks else "pending",
        created_at=timestamp,
        updated_at=timestamp,
        pages=pages,
        blocks=blocks,
        outlines=outlines,
        chunks=chunks + table_chunks,
        tables=tables,
        citation_targets=build_citation_targets_from_graph(doc_id, graph_data, blocks, tables, pages),
    )
    return enrich_document_semantics(document)


# 基于最终审核结果重建 canonical document（纯构建，落库由调用方负责）
def rebuild_canonical_document(
    library_id: str,
    doc_id: str,
    title: str = "",
    *,
    source: Optional[CanonicalSourceInput] = None,
    use_llm: bool = False,
    llm_client: Any = None,
    llm_model: Optional[str] = None,
) -> CanonicalDocument:
    return build_canonical_document(
        library_id,
        doc_id,
        title=title,
        source=source,
        use_llm=use_llm,
        llm_client=llm_client,
        llm_model=llm_model,
    )


# 阶段四：从后端产出的 CanonicalBlock 重建 canonical 文档（solo 适配器路径，纯构建）。
def rebuild_canonical_document_from_blocks(
    library_id: str,
    doc_id: str,
    title: str = "",
    blocks: Optional[List[CanonicalBlock]] = None,
    *,
    markdown: str = "",
    manifest: Optional[dict] = None,
    use_llm: bool = False,
    llm_client: Any = None,
    llm_model: Optional[str] = None,
) -> CanonicalDocument:
    return build_canonical_document_from_blocks(
        library_id,
        doc_id,
        title=title,
        blocks=blocks,
        markdown=markdown,
        manifest=manifest,
        use_llm=use_llm,
        llm_client=llm_client,
        llm_model=llm_model,
    )


def build_canonical_document_from_popoblocks(
    library_id: str,
    doc_id: str,
    title: str = "",
    blocks: Optional[List[CanonicalBlock]] = None,
    outlines: Optional[List[CanonicalOutlineNode]] = None,
    pages: Optional[List[CanonicalPage]] = None,
    *,
    manifest: Optional[dict] = None,
    use_llm: bool = False,
    llm_client: Any = None,
    llm_model: Optional[str] = None,
) -> CanonicalDocument:
    manifest = manifest or {}
    local_blocks = list(blocks) if blocks else []
    local_blocks = refine_document_title_levels(
        local_blocks,
        use_llm=use_llm,
        llm_client=llm_client,
        llm_model=llm_model,
    )
    local_pages = list(pages) if pages else build_pages_from_blocks(local_blocks)
    label_map = build_page_label_map(local_pages)
    chunks = build_canonical_chunks(local_blocks, label_map)
    # 阶段三（P1b）：popo 路径直接消费 CanonicalBlock，不再经 graph jsonl 中转
    tables, table_chunks = build_canonical_tables_from_source(doc_id, [], local_blocks)
    citation_targets = build_citation_targets_from_graph(doc_id, {}, local_blocks, tables, local_pages)
    local_outlines = list(outlines) if outlines else []
    inferred_title = title or next(
        (block.text for block in local_blocks if block.block_type == "title" and block.text), doc_id
    )
    page_count = max((block.page_idx for block in local_blocks), default=-1) + 1 if local_blocks else 0
    source_file_name = ""
    if manifest.get("source_file"):
        source_file_name = str(manifest.get("source_file") or "").split("\\")[-1].split("/")[-1]
    timestamp = datetime.now(UTC).isoformat()

    document = CanonicalDocument(
        doc_id=doc_id,
        library_id=library_id,
        title=inferred_title,
        source_file_name=source_file_name or doc_id,
        source_file_type="pdf",
        page_count=page_count,
        status="completed" if local_blocks else "pending",
        created_at=timestamp,
        updated_at=timestamp,
        pages=local_pages,
        blocks=local_blocks,
        outlines=local_outlines,
        chunks=chunks + table_chunks,
        tables=tables,
        citation_targets=citation_targets,
    )
    return enrich_document_semantics(document)
