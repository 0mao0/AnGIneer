"""Markdown ??????write ?????

? markdown ???? heading/clause/table/segment/image ??????
???? mineru blocks ????????????
"""
import re
from pathlib import Path
from typing import Any, Dict, List, Optional


# Markdown 提取结构化项目
def extract_structured_items_from_markdown(
    markdown_text: str,
    mineru_blocks: List[Dict[str, Any]] = None,
) -> List[Dict[str, Any]]:
    lines = markdown_text.splitlines()
    items: List[Dict[str, Any]] = []
    order_index = 0

    image_pattern = re.compile(r'!\[([^\]]*)\]\(([^)\s]+)(?:\s+"([^"]*)")?\)')
    heading_pattern = re.compile(r"^(#{1,6})\s+(.+?)\s*$")
    clause_pattern = re.compile(r"^\s*(\d+(?:\.\d+)*(?:[)])?)\s+(.+)$")

    # 清理文本，保留中文字符、字母和数字，用于模糊匹配
    def clean_text(text: str) -> str:
        if not text:
            return ""
        return re.sub(r"[^\u4e00-\u9fa5a-zA-Z0-9]", "", text).lower()

    # 判断当前行是否属Markdown 表格行
    def is_table_row(text: str) -> bool:
        stripped = text.strip()
        return stripped.startswith("|") and stripped.endswith("|") and stripped.count("|") >= 2

    # 判断当前行是否为 Markdown 表格分隔行
    def is_table_separator(text: str) -> bool:
        stripped = text.strip().replace(" ", "")
        return bool(stripped) and set(stripped) <= {"|", "-", ":"}

    blocks_by_type: Dict[str, List[Dict[str, Any]]] = {}
    if mineru_blocks:
        for block in mineru_blocks:
            block_type = block.get("type", "paragraph")
            block["cleaned_text"] = clean_text(block.get("text", ""))
            if block_type not in blocks_by_type:
                blocks_by_type[block_type] = []
            blocks_by_type[block_type].append(block)

    stats = {
        "total_items": 0,
        "matched_items": 0,
        "types": {},
    }
    last_matched_idx: Dict[str, int] = {}

    # 在指定类型块中查找最佳匹配项
    def find_best_match(text: str, block_type: str) -> Optional[Dict[str, Any]]:
        if not mineru_blocks or block_type not in blocks_by_type:
            return None

        cleaned = clean_text(text)
        if not cleaned:
            return None

        blocks = blocks_by_type[block_type]
        start_idx = last_matched_idx.get(block_type, 0)
        best_match = None
        best_score = 0.0

        for idx in range(start_idx, len(blocks)):
            block = blocks[idx]
            block_text = block.get("cleaned_text", "")
            if not block_text:
                continue

            if cleaned == block_text:
                last_matched_idx[block_type] = idx + 1
                return block

            if cleaned in block_text or block_text in cleaned:
                shorter = min(len(cleaned), len(block_text))
                longer = max(len(cleaned), len(block_text))
                score = shorter / longer if longer else 0.0
                if score > best_score and score >= 0.6:
                    best_score = score
                    best_match = block

        if best_match:
            try:
                match_idx = blocks.index(best_match)
                last_matched_idx[block_type] = match_idx + 1
            except ValueError:
                pass

        return best_match

    # 把匹配到MinerU 元信息写meta
    def enrich_meta(meta: Dict[str, Any], match: Optional[Dict[str, Any]], block_type: str) -> None:
        stats["total_items"] += 1
        stats["types"].setdefault(block_type, {"total": 0, "matched": 0})
        stats["types"][block_type]["total"] += 1

        if not match:
            return

        stats["matched_items"] += 1
        stats["types"][block_type]["matched"] += 1
        meta["mineru_match"] = {
            "bbox": match.get("bbox"),
            "page_idx": match.get("page_idx"),
            "block_idx": match.get("block_idx"),
            "type": match.get("type"),
        }

    idx = 0
    while idx < len(lines):
        line = lines[idx]
        image_match = image_pattern.search(line)
        if image_match:
            alt_text = image_match.group(1) or ""
            src = image_match.group(2) or ""
            title = image_match.group(3) or alt_text or Path(src).name
            meta = {"line": idx + 1, "src": src}
            match = find_best_match(title, "image")
            enrich_meta(meta, match, "image")
            items.append(
                {
                    "item_type": "image",
                    "title": title,
                    "content": alt_text or title,
                    "meta": meta,
                    "order_index": order_index,
                }
            )
            order_index += 1
            idx += 1
            continue

        heading_match = heading_pattern.match(line)
        if heading_match:
            level = len(heading_match.group(1))
            title = heading_match.group(2).strip()
            meta = {"line": idx + 1, "level": level}
            match = find_best_match(title, "title")
            enrich_meta(meta, match, "title")
            items.append(
                {
                    "item_type": "heading",
                    "title": title,
                    "content": title,
                    "meta": meta,
                    "order_index": order_index,
                }
            )
            order_index += 1
            idx += 1
            continue

        clause_match = clause_pattern.match(line)
        if clause_match:
            marker = clause_match.group(1).strip()
            content = clause_match.group(2).strip()
            title = f"{marker} {content}".strip()
            meta = {"line": idx + 1, "clause_marker": marker}
            match = find_best_match(title, "paragraph")
            enrich_meta(meta, match, "paragraph")
            items.append(
                {
                    "item_type": "clause",
                    "title": marker,
                    "content": content,
                    "meta": meta,
                    "order_index": order_index,
                }
            )
            order_index += 1
            idx += 1
            continue

        if is_table_row(line):
            table_lines = [line]
            next_idx = idx + 1
            while next_idx < len(lines) and is_table_row(lines[next_idx]):
                table_lines.append(lines[next_idx])
                next_idx += 1
            content = "\n".join(table_lines)
            title = table_lines[0].strip()
            meta = {"line": idx + 1, "rows": len(table_lines)}
            match = find_best_match(content, "table")
            enrich_meta(meta, match, "table")
            items.append(
                {
                    "item_type": "table",
                    "title": title[:50],
                    "content": content,
                    "meta": meta,
                    "order_index": order_index,
                }
            )
            order_index += 1
            idx = next_idx
            continue

        if is_table_separator(line):
            idx += 1
            continue

        text = line.strip()
        if text:
            meta = {"line": idx + 1}
            match = find_best_match(text, "segment")
            enrich_meta(meta, match, "segment")
            items.append(
                {
                    "item_type": "segment",
                    "title": text[:50],
                    "content": text,
                    "meta": meta,
                    "order_index": order_index,
                }
            )
            order_index += 1

        idx += 1

    total_items = stats["total_items"]
    matched_items = stats["matched_items"]
    match_rate = matched_items / total_items if total_items else 0
    print(f"[StructuredStrategy] Match rate: {match_rate:.2%} ({matched_items}/{total_items})")

    return items


__all__ = [
    "extract_structured_items_from_markdown",
]
