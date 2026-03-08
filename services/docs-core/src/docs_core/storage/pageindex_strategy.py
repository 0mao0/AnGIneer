import re
from typing import Any, Dict, List

from .structured_strategy import extract_structured_items_from_markdown


def _build_page_index_items(markdown_text: str) -> List[Dict[str, Any]]:
    lines = markdown_text.splitlines()
    items: List[Dict[str, Any]] = []
    order_index = 0
    page_no = 1
    heading_pattern = re.compile(r'^(#{1,6})\s+(.+?)\s*$')
    line_count = 0

    for idx, line in enumerate(lines, start=1):
        line_count += 1
        if line_count > 80:
            page_no += 1
            line_count = 1

        heading_match = heading_pattern.match(line)
        if heading_match:
            title = heading_match.group(2).strip()
            items.append(
                {
                    'item_type': 'page_heading',
                    'title': title,
                    'content': title,
                    'meta': {'line': idx, 'page_no': page_no},
                    'order_index': order_index
                }
            )
            order_index += 1
            continue

        clean = line.strip()
        if len(clean) >= 30 and not clean.startswith('|') and not clean.startswith('!['):
            items.append(
                {
                    'item_type': 'page_segment',
                    'title': f'页段@{idx}',
                    'content': clean,
                    'meta': {'line': idx, 'page_no': page_no},
                    'order_index': order_index
                }
            )
            order_index += 1

    if not items:
        return extract_structured_items_from_markdown(markdown_text)
    return items


def build_pageindex_for_doc(library_id: str, doc_id: str, strategy: str = 'C_pageindex') -> Dict[str, Any]:
    from docs_core import file_storage, knowledge_service

    markdown_content = file_storage.read_markdown(library_id, doc_id)
    if markdown_content is None:
        raise ValueError('文档尚无可用 Markdown 内容')

    items = _build_page_index_items(markdown_content)
    saved_count = knowledge_service.save_document_segments(doc_id, library_id, strategy, items)
    stats = knowledge_service.get_document_segment_stats(doc_id)
    return {'saved_count': saved_count, 'stats': stats}
