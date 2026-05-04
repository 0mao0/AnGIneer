"""引用构造器。"""
from typing import Any, Dict, List, Optional

from docs_core.query.contracts import CitationRichMedia, KnowledgeCitation, RetrievedItem


# 截断文本片段，便于前端显示引用摘要。
def build_snippet(text: str, limit: int = 180) -> str:
    compact = " ".join((text or "").split())
    if len(compact) <= limit:
        return compact
    return f"{compact[:limit].rstrip()}..."


# 推断内容类型：有富媒体时标记为 rich，否则为 text。
def _infer_content_type(item: RetrievedItem, rich_media: Optional[CitationRichMedia]) -> str:
    if rich_media:
        if rich_media.table_html or rich_media.math_content or rich_media.image_path or rich_media.image_paths:
            return "rich"
    entity_type = str(item.entity_type or "")
    if entity_type in ("table", "formula", "figure", "image"):
        return "rich"
    return "text"


# 按 doc_id 分组收集 block_uid，批量查询富媒体后映射回候选项。
def _batch_enrich_rich_media(
    candidates: List[RetrievedItem],
    knowledge_service: Any,
) -> Dict[str, CitationRichMedia]:
    if not knowledge_service:
        return {}
    doc_block_uids: Dict[str, List[str]] = {}
    for item in candidates:
        doc_id = item.doc_id
        block_uid = item.item_id
        if doc_id not in doc_block_uids:
            doc_block_uids[doc_id] = []
        doc_block_uids[doc_id].append(block_uid)
    raw_media_map: Dict[str, Dict[str, Any]] = {}
    for doc_id, block_uids in doc_block_uids.items():
        try:
            doc_media = knowledge_service.get_blocks_rich_media(doc_id, block_uids)
            for uid, media in doc_media.items():
                raw_media_map[uid] = media
        except Exception:
            continue
    source_file_names: Dict[str, str] = {}
    for doc_id in doc_block_uids:
        try:
            source_file_names[doc_id] = knowledge_service.get_doc_source_file_name(doc_id)
        except Exception:
            source_file_names[doc_id] = ""
    result: Dict[str, CitationRichMedia] = {}
    for item in candidates:
        raw = raw_media_map.get(item.item_id)
        if not raw:
            continue
        has_any = raw.get("table_html") or raw.get("math_content") or raw.get("image_path") or raw.get("image_paths")
        if not has_any and not raw.get("rich_media_order"):
            continue
        result[item.item_id] = CitationRichMedia(
            table_html=str(raw.get("table_html") or ""),
            math_content=str(raw.get("math_content") or ""),
            image_path=str(raw.get("image_path") or ""),
            image_paths=list(raw.get("image_paths") or []),
            rich_media_order=list(raw.get("rich_media_order") or []),
            source_file_name=source_file_names.get(item.doc_id, ""),
        )
    return result


# 将候选项转换为统一引用结构，携带完整内容与富媒体。
def build_citations(
    candidates: List[RetrievedItem],
    doc_title_map: Dict[str, str],
    knowledge_service: Any = None,
) -> List[KnowledgeCitation]:
    rich_media_map = _batch_enrich_rich_media(candidates, knowledge_service)
    citations: List[KnowledgeCitation] = []
    for item in candidates:
        rich_media = rich_media_map.get(item.item_id)
        content_type = _infer_content_type(item, rich_media)
        citations.append(
            KnowledgeCitation(
                target_id=item.item_id,
                target_type=item.entity_type,
                doc_id=item.doc_id,
                doc_title=doc_title_map.get(item.doc_id, item.title),
                page_idx=int(item.metadata.get("page_idx", 0) or 0),
                section_path=str(item.metadata.get("section_path", "") or ""),
                snippet=build_snippet(item.text),
                content=item.text,
                content_type=content_type,
                score=item.score,
                rich_media=rich_media,
            )
        )
    return citations
