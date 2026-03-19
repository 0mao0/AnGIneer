"""
结构化策略 - A1 结构结果生成与持久化

职责：
- 调用 mineru_structure.build_graph_from_mineru 得到 A1
- 落盘 parsed/doc_blocks_graph.json
- 写入 data/knowledge_base/doc_blocks.sqlite
- 负责幂等与事务，不写算法细节
"""
import json
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from docs_core.storage.file_storage import file_storage
from docs_core.parser.mineru_structure import (
    build_graph_from_mineru,
    A1StructureResult
)


def _get_llm_client():
    """延迟获取 AnGIneer LLM 客户端，避免循环导入。"""
    try:
        from angineer_core.infra.llm_client import llm_client
        return llm_client
    except ImportError:
        return None


def _resolve_doc_blocks_db_path() -> Path:
    """解析 doc_blocks.sqlite 路径。"""
    root_dir = Path(__file__).resolve().parents[5]
    data_dir = root_dir / 'data' / 'knowledge_base'
    data_dir.mkdir(parents=True, exist_ok=True)
    return data_dir / 'doc_blocks.sqlite'


def _ensure_doc_blocks_schema(conn: sqlite3.Connection) -> None:
    """确保 doc_blocks 表结构存在。"""
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS doc_blocks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            doc_id TEXT NOT NULL,
            doc_name TEXT,
            page_idx INTEGER NOT NULL,
            page_width REAL NOT NULL,
            page_height REAL NOT NULL,
            block_seq INTEGER NOT NULL,
            block_uid TEXT NOT NULL,
            block_type TEXT NOT NULL,
            content_json TEXT NOT NULL,
            plain_text TEXT,
            bbox_abs_x1 REAL NOT NULL,
            bbox_abs_y1 REAL NOT NULL,
            bbox_abs_x2 REAL NOT NULL,
            bbox_abs_y2 REAL NOT NULL,
            page_seq INTEGER,
            sub_type TEXT,
            bbox_norm_x1 REAL,
            bbox_norm_y1 REAL,
            bbox_norm_x2 REAL,
            bbox_norm_y2 REAL,
            bbox_source TEXT,
            raw_title_level INTEGER,
            derived_title_level INTEGER,
            title_path TEXT,
            parent_block_uid TEXT,
            prev_block_uid TEXT,
            next_block_uid TEXT,
            explain_for_block_uid TEXT,
            explain_type TEXT,
            table_type TEXT,
            table_nest_level INTEGER,
            table_html TEXT,
            math_type TEXT,
            math_content TEXT,
            image_path TEXT,
            quality_score REAL,
            derived_confidence REAL,
            derived_by TEXT,
            derive_version TEXT,
            parser_version TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            is_active INTEGER NOT NULL
        )
        """
    )
    conn.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_doc_blocks_block_uid "
        "ON doc_blocks(block_uid)"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_doc_blocks_doc_page_seq "
        "ON doc_blocks(doc_id, page_idx, block_seq)"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_doc_blocks_doc_type "
        "ON doc_blocks(doc_id, block_type)"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_doc_blocks_doc_active "
        "ON doc_blocks(doc_id, is_active)"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_doc_blocks_doc_parent "
        "ON doc_blocks(doc_id, parent_block_uid)"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_doc_blocks_doc_heading "
        "ON doc_blocks(doc_id, derived_title_level, page_idx)"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_doc_blocks_doc_explain "
        "ON doc_blocks(doc_id, explain_for_block_uid)"
    )


def _clear_doc_blocks(conn: sqlite3.Connection, doc_id: str) -> int:
    """清除文档的旧块记录（幂等）。"""
    cursor = conn.execute(
        "DELETE FROM doc_blocks WHERE doc_id = ?",
        (doc_id,)
    )
    return cursor.rowcount


def _insert_base_blocks(
    conn: sqlite3.Connection,
    rows: List[Dict[str, Any]]
) -> int:
    """批量插入基础块记录。"""
    inserted = 0
    for row in rows:
        conn.execute(
            """
            INSERT INTO doc_blocks (
                doc_id, doc_name, page_idx, page_width, page_height,
                block_seq, block_uid, block_type, content_json, plain_text,
                bbox_abs_x1, bbox_abs_y1, bbox_abs_x2, bbox_abs_y2,
                created_at, updated_at, is_active
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1)
            """,
            (
                row.get("doc_id"),
                row.get("doc_name"),
                row.get("page_idx", 0),
                row.get("page_width", 0.0),
                row.get("page_height", 0.0),
                row.get("block_seq", 0),
                row.get("block_uid"),
                row.get("block_type"),
                json.dumps(row.get("content_json", {}), ensure_ascii=False),
                row.get("plain_text", ""),
                row.get("bbox_abs_x1", 0.0),
                row.get("bbox_abs_y1", 0.0),
                row.get("bbox_abs_x2", 0.0),
                row.get("bbox_abs_y2", 0.0),
                row.get("created_at"),
                row.get("updated_at"),
            )
        )
        inserted += 1
    return inserted


def _update_derived_fields(
    conn: sqlite3.Connection,
    rows: List[Dict[str, Any]]
) -> int:
    """更新推导字段。"""
    updated = 0
    for row in rows:
        conn.execute(
            """
            UPDATE doc_blocks SET
                page_seq = ?,
                sub_type = ?,
                bbox_norm_x1 = ?,
                bbox_norm_y1 = ?,
                bbox_norm_x2 = ?,
                bbox_norm_y2 = ?,
                bbox_source = ?,
                raw_title_level = ?,
                derived_title_level = ?,
                title_path = ?,
                parent_block_uid = ?,
                prev_block_uid = ?,
                next_block_uid = ?,
                explain_for_block_uid = ?,
                explain_type = ?,
                table_type = ?,
                table_nest_level = ?,
                table_html = ?,
                math_type = ?,
                math_content = ?,
                image_path = ?,
                quality_score = ?,
                derived_confidence = ?,
                derived_by = ?,
                derive_version = ?,
                parser_version = ?,
                updated_at = ?
            WHERE block_uid = ?
            """,
            (
                row.get("page_seq"),
                row.get("sub_type"),
                row.get("bbox_norm_x1"),
                row.get("bbox_norm_y1"),
                row.get("bbox_norm_x2"),
                row.get("bbox_norm_y2"),
                row.get("bbox_source"),
                row.get("raw_title_level"),
                row.get("derived_title_level"),
                row.get("title_path"),
                row.get("parent_block_uid"),
                row.get("prev_block_uid"),
                row.get("next_block_uid"),
                row.get("explain_for_block_uid"),
                row.get("explain_type"),
                row.get("table_type"),
                row.get("table_nest_level"),
                row.get("table_html"),
                row.get("math_type"),
                row.get("math_content"),
                row.get("image_path"),
                row.get("quality_score"),
                row.get("derived_confidence"),
                row.get("derived_by"),
                row.get("derive_version"),
                row.get("parser_version"),
                row.get("updated_at"),
                row.get("block_uid"),
            )
        )
        updated += 1
    return updated


def _save_doc_blocks_graph(
    library_id: str,
    doc_id: str,
    result: A1StructureResult
) -> str:
    """保存 doc_blocks_graph.json 文件。"""
    parsed_dir = file_storage.get_parsed_dir(library_id, doc_id)
    graph_path = parsed_dir / 'doc_blocks_graph.json'
    
    payload = {
        "nodes": result.nodes,
        "edges": result.edges,
        "stats": result.stats,
        "generated_at": datetime.now().isoformat()
    }
    
    with open(graph_path, 'w', encoding='utf-8') as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
    
    return str(graph_path)


def build_structured_index_for_doc(
    library_id: str,
    doc_id: str,
    strategy: str = 'A_structured',
    options: Optional[Dict[str, Any]] = None
) -> Dict[str, Any]:
    """
    为文档构建结构化索引。
    
    Args:
        library_id: 知识库ID
        doc_id: 文档ID
        strategy: 策略名称 (默认 A_structured)
        options: 可选配置项
            - use_llm: 是否使用 LLM 细化标题层级 (默认 True)
            - derive_version: 推导版本标识
    
    Returns:
        包含 saved_count 和 stats 的字典
    """
    opts = options or {}
    use_llm = opts.get("use_llm", True)
    derive_version = opts.get("derive_version", "v1")
    
    parsed_dir = file_storage.get_parsed_dir(library_id, doc_id)
    raw_dir = parsed_dir / 'mineru_raw'
    
    if not raw_dir.exists():
        raw_dir = parsed_dir
    
    content_list_path = raw_dir / 'content_list_v2.json'
    if not content_list_path.exists():
        raise ValueError(f'文档尚无 MinerU 解析结果: {content_list_path}')
    
    llm_client = None
    if use_llm:
        llm_client = _get_llm_client()
    
    doc_name = ""
    doc_info = file_storage.get_doc_manifest(library_id, doc_id)
    if doc_info.get("source_file"):
        doc_name = Path(doc_info["source_file"]).name
    
    result = build_graph_from_mineru(
        parsed_dir=parsed_dir,
        doc_id=doc_id,
        doc_name=doc_name,
        llm_client=llm_client,
        options={
            "use_llm": use_llm,
            "derive_version": derive_version
        }
    )
    
    if result.stats.get("error"):
        raise ValueError(f'构建结构失败: {result.stats.get("error")}')
    
    graph_path = _save_doc_blocks_graph(library_id, doc_id, result)
    
    db_path = _resolve_doc_blocks_db_path()
    with sqlite3.connect(db_path) as conn:
        _ensure_doc_blocks_schema(conn)
        _clear_doc_blocks(conn, doc_id)
        
        base_rows = result.stats.get("base_rows", [])
        derived_rows = result.stats.get("derived_rows", [])
        
        inserted = _insert_base_blocks(conn, base_rows) if base_rows else 0
        updated = _update_derived_fields(conn, derived_rows) if derived_rows else 0
        
        conn.commit()
    
    stats = {
        "nodes_count": len(result.nodes),
        "edges_count": len(result.edges),
        "index_rows_count": len(result.index_rows),
        "base_rows_count": inserted,
        "derived_rows_count": updated,
        "llm_status": result.stats.get("llm_status", "disabled"),
        "derive_version": derive_version,
        "graph_path": graph_path
    }
    
    return {
        "saved_count": inserted,
        "stats": stats
    }


def get_doc_blocks_graph(library_id: str, doc_id: str) -> Optional[Dict[str, Any]]:
    """获取文档的块图谱。"""
    parsed_dir = file_storage.get_parsed_dir(library_id, doc_id)
    graph_path = parsed_dir / 'doc_blocks_graph.json'
    
    if not graph_path.exists():
        return None
    
    with open(graph_path, 'r', encoding='utf-8') as f:
        return json.load(f)


def query_doc_blocks(
    doc_id: str,
    block_type: Optional[str] = None,
    derived_level: Optional[int] = None,
    limit: int = 100
) -> List[Dict[str, Any]]:
    """查询文档块记录。"""
    db_path = _resolve_doc_blocks_db_path()
    
    if not db_path.exists():
        return []
    
    with sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        
        query = "SELECT * FROM doc_blocks WHERE doc_id = ? AND is_active = 1"
        params = [doc_id]
        
        if block_type:
            query += " AND block_type = ?"
            params.append(block_type)
        
        if derived_level is not None:
            query += " AND derived_title_level = ?"
            params.append(derived_level)
        
        query += " ORDER BY page_idx, block_seq LIMIT ?"
        params.append(limit)
        
        rows = conn.execute(query, params).fetchall()
        
        return [dict(row) for row in rows]


def get_doc_blocks_stats(doc_id: str) -> Dict[str, Any]:
    """获取文档块统计信息。"""
    db_path = _resolve_doc_blocks_db_path()
    
    if not db_path.exists():
        return {"error": "db_not_found"}
    
    with sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        
        total = conn.execute(
            "SELECT COUNT(*) as cnt FROM doc_blocks WHERE doc_id = ? AND is_active = 1",
            (doc_id,)
        ).fetchone()["cnt"]
        
        by_type = conn.execute(
            "SELECT block_type, COUNT(*) as cnt FROM doc_blocks "
            "WHERE doc_id = ? AND is_active = 1 GROUP BY block_type",
            (doc_id,)
        ).fetchall()
        
        by_level = conn.execute(
            "SELECT derived_title_level, COUNT(*) as cnt FROM doc_blocks "
            "WHERE doc_id = ? AND is_active = 1 AND derived_title_level IS NOT NULL "
            "GROUP BY derived_title_level",
            (doc_id,)
        ).fetchall()
        
        titles_without_level = conn.execute(
            "SELECT COUNT(*) as cnt FROM doc_blocks "
            "WHERE doc_id = ? AND is_active = 1 AND block_type = 'title' "
            "AND derived_title_level IS NULL",
            (doc_id,)
        ).fetchone()["cnt"]
        
        return {
            "total": total,
            "by_type": {r["block_type"]: r["cnt"] for r in by_type},
            "by_level": {r["derived_title_level"]: r["cnt"] for r in by_level},
            "titles_without_level": titles_without_level
        }


def extract_structured_items_from_markdown(
    markdown_text: str,
    mineru_blocks: List[Dict[str, Any]] = None
) -> List[Dict[str, Any]]:
    """从 Markdown 提取结构化项目（兼容旧接口）。"""
    import re
    
    lines = markdown_text.splitlines()
    items: List[Dict[str, Any]] = []
    order_index = 0

    image_pattern = re.compile(r'!\[([^\]]*)\]\(([^)\s]+)(?:\s+"([^"]+)")?\)')
    heading_pattern = re.compile(r'^(#{1,6})\s+(.+?)\s*$')
    clause_pattern = re.compile(r'^\s*(\d+(?:\.\d+)*(?:[、.)])?)\s+(.+)$')

    def clean_text(text: str) -> str:
        """清理文本，保留中文字符、字母和数字，用于模糊匹配"""
        if not text:
            return ""
        return re.sub(r'[^\u4e00-\u9fa5a-zA-Z0-9]', '', text).lower()

    blocks_by_type: Dict[str, List[Dict[str, Any]]] = {}
    if mineru_blocks:
        for b in mineru_blocks:
            b_type = b.get('type', 'paragraph')
            b['cleaned_text'] = clean_text(b.get('text', ''))
            if b_type not in blocks_by_type:
                blocks_by_type[b_type] = []
            blocks_by_type[b_type].append(b)

    stats = {
        'total_items': 0,
        'matched_items': 0,
        'types': {}
    }

    last_matched_idx: Dict[str, int] = {}

    def find_best_match(item_text: str, item_type: str) -> Optional[Dict[str, Any]]:
        if not mineru_blocks:
            return None
        
        type_map = {
            'heading': ['title', 'heading'],
            'clause': ['title', 'paragraph', 'list'],
            'segment': ['paragraph', 'list', 'text'],
            'image': ['image'],
            'table': ['table']
        }
        target_types = type_map.get(item_type, ['paragraph'])
        
        candidates = []
        for t in target_types:
            candidates.extend(blocks_by_type.get(t, []))
            
        if not candidates:
            return None
            
        item_text_clean = clean_text(item_text)
        if not item_text_clean:
            return None
            
        best_block = None
        max_overlap = 0
        
        start_search_idx = last_matched_idx.get(item_type, 0)
        
        search_ranges = [
            range(start_search_idx, len(candidates)),
            range(0, start_search_idx)
        ]
        
        for r in search_ranges:
            for i in r:
                b = candidates[i]
                b_text_clean = b.get('cleaned_text', '')
                if not b_text_clean:
                    continue
                
                if item_text_clean in b_text_clean or b_text_clean in item_text_clean:
                    overlap = min(len(item_text_clean), len(b_text_clean))
                    if overlap > max_overlap:
                        max_overlap = overlap
                        best_block = b
                        last_matched_idx[item_type] = i
                        if overlap > 50:
                            break
            if best_block:
                break
                    
        return best_block

    def enrich_meta(meta: Dict[str, Any], block: Optional[Dict[str, Any]], item_type: str):
        stats['total_items'] += 1
        stats['types'][item_type] = stats['types'].get(item_type, 0) + 1
        if block:
            stats['matched_items'] += 1
            meta['bbox'] = block.get('bbox')
            meta['page'] = block.get('page')
            meta['page_idx'] = block.get('page_idx')
            if 'page_width' in block:
                meta['page_width'] = block['page_width']
            if 'page_height' in block:
                meta['page_height'] = block['page_height']
            meta['mineru_block_id'] = block.get('id')
            meta['match_source'] = 'backend_stitching'

    idx = 0
    while idx < len(lines):
        line = lines[idx]
        heading_match = heading_pattern.match(line)
        if heading_match:
            level = len(heading_match.group(1))
            title = heading_match.group(2).strip()
            meta = {'level': level, 'line': idx + 1}
            match = find_best_match(title, 'heading')
            enrich_meta(meta, match, 'heading')
            items.append({
                'item_type': 'heading',
                'title': title,
                'content': title,
                'meta': meta,
                'order_index': order_index
            })
            order_index += 1

        clause_match = clause_pattern.match(line)
        if clause_match:
            title = clause_match.group(1).strip()
            content = clause_match.group(2).strip()
            meta = {'line': idx + 1}
            match = find_best_match(f"{title} {content}", 'clause')
            enrich_meta(meta, match, 'clause')
            items.append({
                'item_type': 'clause',
                'title': title,
                'content': content,
                'meta': meta,
                'order_index': order_index
            })
            order_index += 1

        for image_match in image_pattern.finditer(line):
            title = image_match.group(1).strip() or '未命名图片'
            content = image_match.group(2).strip()
            meta = {
                'src': content,
                'caption': (image_match.group(3) or '').strip(),
                'line': idx + 1
            }
            match = find_best_match(title, 'image')
            enrich_meta(meta, match, 'image')
            items.append({
                'item_type': 'image',
                'title': title,
                'content': content,
                'meta': meta,
                'order_index': order_index
            })
            order_index += 1

        if '|' in line:
            table_lines = []
            start_line = idx + 1
            cursor = idx
            while cursor < len(lines) and '|' in lines[cursor]:
                table_lines.append(lines[cursor])
                cursor += 1
            if len(table_lines) >= 2 and re.match(
                r'^\s*\|?\s*[-: ]+\|(?:\s*[-: ]+\|)*\s*$',
                table_lines[1]
            ):
                table_text = '\n'.join(table_lines)
                header_line = table_lines[0].strip().strip('|')
                headers = [h.strip() for h in header_line.split('|') if h.strip()]
                meta = {
                    'headers': headers,
                    'line': start_line,
                    'row_count': max(0, len(table_lines) - 2)
                }
                match = find_best_match(table_text[:100], 'table')
                enrich_meta(meta, match, 'table')
                items.append({
                    'item_type': 'table',
                    'title': f'表格@{start_line}',
                    'content': table_text,
                    'meta': meta,
                    'order_index': order_index
                })
                order_index += 1
                idx = cursor - 1

        idx += 1

    paragraph_buffer: List[str] = []
    paragraph_start = 1
    
    def add_paragraph_item():
        nonlocal order_index
        if paragraph_buffer:
            content = '\n'.join(paragraph_buffer).strip()
            if content and len(content) >= 20:
                meta = {'line': paragraph_start}
                match = find_best_match(content, 'segment')
                enrich_meta(meta, match, 'segment')
                items.append({
                    'item_type': 'segment',
                    'title': f'段落@{paragraph_start}',
                    'content': content,
                    'meta': meta,
                    'order_index': order_index
                })
                order_index += 1

    for line_no, line in enumerate(lines, start=1):
        if not line.strip():
            add_paragraph_item()
            paragraph_buffer = []
            continue
        if line.strip().startswith('#') or line.strip().startswith('|') or line.strip().startswith('!['):
            add_paragraph_item()
            paragraph_buffer = []
            continue
        if not paragraph_buffer:
            paragraph_start = line_no
        paragraph_buffer.append(line)

    add_paragraph_item()
    
    if stats['total_items'] > 0:
        match_rate = stats['matched_items'] / stats['total_items'] * 100
        print(f"[StructuredStrategy] Match rate: {match_rate:.2f}% ({stats['matched_items']}/{stats['total_items']})")

    return items
