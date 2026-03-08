import tempfile
from typing import Any, Dict

from .structured_strategy import extract_structured_items_from_markdown


def build_mineru_rag_index_for_doc(library_id: str, doc_id: str, strategy: str = 'B_mineru_rag') -> Dict[str, Any]:
    from docs_core import file_storage, knowledge_service, mineru_rag

    markdown_content = file_storage.read_markdown(library_id, doc_id)
    if markdown_content is None:
        raise ValueError('文档尚无可用 Markdown 内容')

    items = extract_structured_items_from_markdown(markdown_content)
    saved_count = knowledge_service.save_document_segments(doc_id, library_id, strategy, items)
    rag_result: Dict[str, Any] = {'success': False}

    with tempfile.NamedTemporaryFile(mode='w', suffix='.md', delete=False, encoding='utf-8') as handle:
        handle.write(markdown_content)
        temp_md = handle.name

    try:
        rag_result = mineru_rag.build_knowledge_base([temp_md], library_id)
    finally:
        try:
            import os
            if os.path.exists(temp_md):
                os.remove(temp_md)
        except Exception:
            pass

    stats = knowledge_service.get_document_segment_stats(doc_id)
    return {'saved_count': saved_count, 'stats': stats, 'rag_result': rag_result}
