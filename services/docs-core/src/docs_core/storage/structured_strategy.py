import re
from typing import Any, Dict, List


def extract_structured_items_from_markdown(markdown_text: str) -> List[Dict[str, Any]]:
    lines = markdown_text.splitlines()
    items: List[Dict[str, Any]] = []
    order_index = 0

    image_pattern = re.compile(r'!\[([^\]]*)\]\(([^)\s]+)(?:\s+"([^"]+)")?\)')
    heading_pattern = re.compile(r'^(#{1,6})\s+(.+?)\s*$')
    clause_pattern = re.compile(r'^\s*(\d+(?:\.\d+)*(?:[、.)])?)\s+(.+)$')

    idx = 0
    while idx < len(lines):
        line = lines[idx]
        heading_match = heading_pattern.match(line)
        if heading_match:
            level = len(heading_match.group(1))
            title = heading_match.group(2).strip()
            items.append(
                {
                    'item_type': 'heading',
                    'title': title,
                    'content': title,
                    'meta': {'level': level, 'line': idx + 1},
                    'order_index': order_index
                }
            )
            order_index += 1

        clause_match = clause_pattern.match(line)
        if clause_match:
            items.append(
                {
                    'item_type': 'clause',
                    'title': clause_match.group(1).strip(),
                    'content': clause_match.group(2).strip(),
                    'meta': {'line': idx + 1},
                    'order_index': order_index
                }
            )
            order_index += 1

        for image_match in image_pattern.finditer(line):
            items.append(
                {
                    'item_type': 'image',
                    'title': image_match.group(1).strip() or '未命名图片',
                    'content': image_match.group(2).strip(),
                    'meta': {'src': image_match.group(2).strip(), 'caption': (image_match.group(3) or '').strip(), 'line': idx + 1},
                    'order_index': order_index
                }
            )
            order_index += 1

        if '|' in line:
            table_lines = []
            start_line = idx + 1
            cursor = idx
            while cursor < len(lines) and '|' in lines[cursor]:
                table_lines.append(lines[cursor])
                cursor += 1
            if len(table_lines) >= 2 and re.match(r'^\s*\|?\s*[-: ]+\|(?:\s*[-: ]+\|)*\s*$', table_lines[1]):
                table_text = '\n'.join(table_lines)
                header_line = table_lines[0].strip().strip('|')
                headers = [h.strip() for h in header_line.split('|') if h.strip()]
                items.append(
                    {
                        'item_type': 'table',
                        'title': f'表格@{start_line}',
                        'content': table_text,
                        'meta': {'headers': headers, 'line': start_line, 'row_count': max(0, len(table_lines) - 2)},
                        'order_index': order_index
                    }
                )
                order_index += 1
                idx = cursor - 1

        idx += 1

    paragraph_buffer: List[str] = []
    paragraph_start = 1
    for line_no, line in enumerate(lines, start=1):
        if not line.strip():
            if paragraph_buffer:
                content = '\n'.join(paragraph_buffer).strip()
                if content and len(content) >= 20:
                    items.append(
                        {
                            'item_type': 'segment',
                            'title': f'段落@{paragraph_start}',
                            'content': content,
                            'meta': {'line': paragraph_start},
                            'order_index': order_index
                        }
                    )
                    order_index += 1
                paragraph_buffer = []
            continue
        if line.strip().startswith('#') or line.strip().startswith('|') or line.strip().startswith('!['):
            if paragraph_buffer:
                content = '\n'.join(paragraph_buffer).strip()
                if content and len(content) >= 20:
                    items.append(
                        {
                            'item_type': 'segment',
                            'title': f'段落@{paragraph_start}',
                            'content': content,
                            'meta': {'line': paragraph_start},
                            'order_index': order_index
                        }
                    )
                    order_index += 1
                paragraph_buffer = []
            continue
        if not paragraph_buffer:
            paragraph_start = line_no
        paragraph_buffer.append(line)

    if paragraph_buffer:
        content = '\n'.join(paragraph_buffer).strip()
        if content and len(content) >= 20:
            items.append(
                {
                    'item_type': 'segment',
                    'title': f'段落@{paragraph_start}',
                    'content': content,
                    'meta': {'line': paragraph_start},
                    'order_index': order_index
                }
            )

    return items


def build_structured_index_for_doc(library_id: str, doc_id: str, strategy: str = 'A_structured') -> Dict[str, Any]:
    from docs_core import file_storage, knowledge_service
    markdown_content = file_storage.read_markdown(library_id, doc_id)
    if markdown_content is None:
        raise ValueError('文档尚无可用 Markdown 内容')
    items = extract_structured_items_from_markdown(markdown_content)
    saved_count = knowledge_service.save_document_segments(doc_id, library_id, strategy, items)
    stats = knowledge_service.get_document_segment_stats(doc_id)
    return {'saved_count': saved_count, 'stats': stats}
