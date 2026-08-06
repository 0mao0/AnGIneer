"""
原始解析文件到结构化结果对象的构建器

核心算法：
- 无限深度层级推断
- 编号段落提升
- parent/title_path/explain_for 推断

输出：结构化结果对象（nodes, edges, index_rows, stats）。
04 的落盘真相是 doc_blocks_graph.jsonl + meta（由 solo2json 投影）。
"""
import datetime as dt
import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple, TYPE_CHECKING

if TYPE_CHECKING:
    from ai_inference.llm_client import LLMClient


def now_iso() -> str:
    """返回UTC时区的ISO时间字符串。"""
    return dt.datetime.now(dt.timezone.utc).isoformat()


def read_json(path: Path) -> Any:
    """读取并解析JSON文件。"""
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def extract_plain_text(block_type: str, content: dict[str, Any]) -> str:
    """按块类型提取可读纯文本。"""
    def collect_from_any(node: Any) -> list[str]:
        """递归收集任意结构中的文本片段。"""
        parts: list[str] = []
        if isinstance(node, str):
            parts.append(node)
            return parts
        if isinstance(node, list):
            for item in node:
                parts.extend(collect_from_any(item))
            return parts
        if isinstance(node, dict):
            for key in ("content", "text", "value"):
                val = node.get(key)
                if isinstance(val, str):
                    parts.append(val)
            for key in ("item_content", "list_items", "children", "spans"):
                val = node.get(key)
                if isinstance(val, (list, dict, str)):
                    parts.extend(collect_from_any(val))
            return parts
        return parts

    def collect_from_spans(spans: Any) -> str:
        """拼接span数组中的文本内容。"""
        if not isinstance(spans, list):
            return ""
        parts: list[str] = []
        for item in spans:
            if isinstance(item, dict):
                val = item.get("content")
                if isinstance(val, str):
                    parts.append(val)
            elif isinstance(item, str):
                parts.append(item)
        return "".join(parts).strip()

    if block_type == "title":
        return collect_from_spans(content.get("title_content"))
    if block_type == "paragraph":
        return collect_from_spans(content.get("paragraph_content"))
    if block_type == "page_header":
        return collect_from_spans(content.get("page_header_content"))
    if block_type == "page_footer":
        return collect_from_spans(content.get("page_footer_content"))
    if block_type == "page_number":
        return collect_from_spans(content.get("page_number_content"))
    if block_type in ("list", "index"):
        items = content.get("list_items")
        if isinstance(items, (list, dict)):
            txt = collect_from_any(items)
            merged = " ".join(x.strip() for x in txt if isinstance(x, str) and x.strip()).strip()
            merged = re.sub(r"\s+", " ", merged)
            return merged
        return ""
    if block_type == "equation_interline":
        v = content.get("math_content")
        return v.strip() if isinstance(v, str) else ""
    if block_type == "table":
        cap = collect_from_spans(content.get("table_caption"))
        foot = collect_from_spans(content.get("table_footnote"))
        return " ".join([x for x in [cap, foot] if x]).strip()
    if block_type == "image":
        cap = collect_from_spans(content.get("image_caption"))
        foot = collect_from_spans(content.get("image_footnote"))
        return " ".join([x for x in [cap, foot] if x]).strip()
    return ""


def parse_bbox(raw_bbox: Any) -> tuple[float, float, float, float]:
    """把bbox转换为四元浮点坐标。"""
    if not isinstance(raw_bbox, list) or len(raw_bbox) != 4:
        return 0.0, 0.0, 0.0, 0.0
    return tuple(float(v) for v in raw_bbox)  # type: ignore[return-value]


def normalize_match_text(text: str) -> str:
    """归一化文本以提高跨源匹配稳定性。"""
    if not text:
        return ""
    compact = re.sub(r"\s+", "", text)
    compact = re.sub(r"[，。；：、“”‘’（）()\[\]【】<>《》,.;:!?！？·—\-~]", "", compact)
    return compact.strip().lower()


def extract_layout_text(payload: Any) -> str:
    """从 layout 块中提取可比对文本。"""
    fragments: list[str] = []

    def collect(node: Any) -> None:
        if isinstance(node, str):
            val = node.strip()
            if val:
                fragments.append(val)
            return
        if isinstance(node, list):
            for item in node:
                collect(item)
            return
        if isinstance(node, dict):
            for key in ("content", "text", "value"):
                value = node.get(key)
                if isinstance(value, str) and value.strip():
                    fragments.append(value.strip())
            for key in ("spans", "lines", "blocks", "children"):
                value = node.get(key)
                if isinstance(value, (list, dict, str)):
                    collect(value)

    collect(payload)
    if not fragments:
        return ""
    merged = " ".join(fragments)
    return re.sub(r"\s+", " ", merged).strip()


def collect_text_fragments(payload: Any) -> list[str]:
    """递归收集任意结构中的文本片段。"""
    fragments: list[str] = []

    def collect(node: Any) -> None:
        if isinstance(node, str):
            value = node.strip()
            if value:
                fragments.append(value)
            return
        if isinstance(node, list):
            for item in node:
                collect(item)
            return
        if isinstance(node, dict):
            for key in ("content", "text", "value"):
                value = node.get(key)
                if isinstance(value, str) and value.strip():
                    fragments.append(value.strip())
            for value in node.values():
                if isinstance(value, (list, dict, str)):
                    collect(value)

    collect(payload)
    return list(dict.fromkeys(fragments))


def extract_media_fragment_text(payload: Any) -> str:
    """把 caption/footnote 片段数组拼成纯文本（与 plain_text 中的表题/表注一致）。"""
    if isinstance(payload, str):
        return payload.strip()
    if not isinstance(payload, list):
        return ""
    parts: list[str] = []
    for item in payload:
        if isinstance(item, dict):
            value = item.get("content")
            if isinstance(value, str) and value.strip():
                parts.append(value.strip())
        elif isinstance(item, str) and item.strip():
            parts.append(item.strip())
    return "".join(parts).strip() if parts else ""


def build_related_text_needles(values: list[str]) -> list[str]:
    """把文本片段转换为可用于跨块匹配的归一化候选。"""
    needles = [normalize_match_text(value) for value in values if normalize_match_text(value)]
    filtered = [value for value in needles if len(value) >= 2]
    filtered.sort(key=len, reverse=True)
    return list(dict.fromkeys(filtered))


def is_caption_like_text(value: str) -> bool:
    """判断文本是否看起来像图表题注编号。"""
    return bool(re.match(r"^(图|表|figure|table)\s*[0-9a-z\u4e00-\u9fa5]", value, re.IGNORECASE))


def matches_related_text(row_text: str, needles: list[str]) -> bool:
    """判断候选行文本是否命中图表 caption 或 footnote 文本。"""
    if not row_text or not needles:
        return False
    return any(
        needle in row_text
        or (len(row_text) >= 10 and row_text in needle)
        or (is_caption_like_text(row_text) and needle.startswith(row_text[: min(len(row_text), 32)]))
        for needle in needles
    )


def is_struct_heading_candidate(block_type: str, text: str) -> bool:
    """判断候选块是否更像结构标题而非图表题注或脚注。"""
    normalized_type = str(block_type or "").strip().lower()
    if normalized_type == "title":
        return True
    if normalized_type not in {"paragraph", "list", "list_item"}:
        return False
    return infer_struct_level(text) is not None


def collect_media_related_block_refs(row: dict[str, Any], rows: list[dict[str, Any]]) -> dict[str, list[str]]:
    """为图表块收集同页 caption 与 footnote 的关联 block_uid。"""
    block_type = str(row.get("block_type") or "").strip().lower()
    if block_type not in {"image", "table"}:
        return {}

    content_json = row.get("content_json") if isinstance(row.get("content_json"), dict) else {}
    caption_key = "table_caption" if block_type == "table" else "image_caption"
    footnote_key = "table_footnote" if block_type == "table" else "image_footnote"
    caption_needles = build_related_text_needles(collect_text_fragments(content_json.get(caption_key)))
    footnote_needles = build_related_text_needles(collect_text_fragments(content_json.get(footnote_key)))
    if not caption_needles and not footnote_needles:
        return {}

    block_uid = str(row.get("block_uid") or "").strip()
    page_idx = int(row.get("page_idx", -1) or -1)
    excluded_types = {"image", "table", "header", "footer", "page_header", "page_number"}
    caption_refs: list[str] = []
    footnote_refs: list[str] = []

    for candidate in rows:
        candidate_uid = str(candidate.get("block_uid") or candidate.get("id") or "").strip()
        if not candidate_uid or candidate_uid == block_uid:
            continue
        candidate_page_idx = int(candidate.get("page_idx", -1) or -1)
        if candidate_page_idx != page_idx:
            continue
        candidate_type = str(candidate.get("block_type") or candidate.get("type") or "").strip().lower()
        if candidate_type in excluded_types:
            continue
        candidate_text_raw = str(candidate.get("plain_text") or candidate.get("text") or "").strip()
        if not candidate_text_raw:
            continue
        if is_struct_heading_candidate(candidate_type, candidate_text_raw):
            continue
        candidate_text = normalize_match_text(candidate_text_raw)
        if caption_needles and matches_related_text(candidate_text, caption_needles):
            caption_refs.append(candidate_uid)
        if footnote_needles and matches_related_text(candidate_text, footnote_needles):
            footnote_refs.append(candidate_uid)

    result: dict[str, list[str]] = {}
    if caption_refs:
        result["caption_block_uids"] = list(dict.fromkeys(caption_refs))
    if footnote_refs:
        result["footnote_block_uids"] = list(dict.fromkeys(footnote_refs))
    return result

# 为图表 caption 或 footnote 构造用于匹配 model.json 的文本候选。
def build_media_text_needles(payload: Any) -> list[str]:
    """为图表 caption 或 footnote 构造用于匹配 model.json 的文本候选。"""
    fragments = collect_text_fragments(payload)
    merged = "".join(fragment.strip() for fragment in fragments if fragment and fragment.strip()).strip()
    values = [*fragments]
    if merged:
        values.append(merged)
    return build_related_text_needles(values)

# 从任意结构中提取 bbox 列表。
def extract_media_bbox_list(payload: Any) -> list[list[float]]:
    """从任意结构中提取 bbox 列表。"""
    if not isinstance(payload, list):
        return []
    results: list[list[float]] = []
    for item in payload:
        if not isinstance(item, (list, tuple)) or len(item) < 4:
            continue
        try:
            bbox = [float(item[0]), float(item[1]), float(item[2]), float(item[3])]
        except (TypeError, ValueError):
            continue
        results.append(bbox)
    return results

# 从 model.json 提取页面级图表与题注候选流。
def build_model_media_candidate_map(model_payload: Any) -> dict[int, list[dict[str, Any]]]:
    """从 model.json 提取页面级图表与题注候选流。"""
    if not isinstance(model_payload, list):
        return {}
    allowed_types = {"image", "table", "image_caption", "image_footnote", "table_caption", "table_footnote"}
    page_map: dict[int, list[dict[str, Any]]] = {}
    for page_idx, page_items in enumerate(model_payload):
        if not isinstance(page_items, list):
            continue
        page_candidates: list[dict[str, Any]] = []
        for seq, item in enumerate(page_items):
            if not isinstance(item, dict):
                continue
            item_type = str(item.get("type") or "").strip().lower()
            if item_type not in allowed_types:
                continue
            bbox = parse_bbox(item.get("bbox"))
            if not any(bbox):
                continue
            text = str(item.get("content") or "").strip()
            normalized_text = normalize_match_text(text)
            page_candidates.append({
                "seq": seq,
                "kind": item_type,
                "bbox": [bbox[0], bbox[1], bbox[2], bbox[3]],
                "text": text,
                "normalized_text": normalized_text
            })
        if page_candidates:
            page_map[page_idx] = page_candidates
    return page_map

# 按文本从 model.json 候选中解析图表 caption/footnote 的 bbox 列表。
# 按页面顺序把 model.json 中的 caption/footnote bbox 对齐到 content_list 图表块。
def build_order_aligned_media_bbox_map(
    page_blocks: list[dict[str, Any]],
    page_candidates: list[dict[str, Any]]
) -> dict[int, dict[str, list[list[float]]]]:
    """按页面顺序把 model.json 中的 caption/footnote bbox 对齐到 content_list 图表块。"""
    if not page_blocks or not page_candidates:
        return {}

    main_kinds = {"image", "table"}
    related_to_main = {
        "image_caption": "image",
        "image_footnote": "image",
        "table_caption": "table",
        "table_footnote": "table",
    }

    block_targets_by_kind: dict[str, list[dict[str, Any]]] = {"image": [], "table": []}
    model_anchors_by_kind: dict[str, list[dict[str, Any]]] = {"image": [], "table": []}

    for block_index, block in enumerate(page_blocks, start=1):
        if not isinstance(block, dict):
            continue
        block_type = str(block.get("type") or "").strip().lower()
        if block_type in main_kinds:
            block_targets_by_kind[block_type].append({
                "block_index": block_index,
                "kind": block_type
            })

    for candidate in page_candidates:
        candidate_kind = str(candidate.get("kind") or "").strip().lower()
        if candidate_kind in main_kinds:
            model_anchors_by_kind[candidate_kind].append(candidate)

    aligned_targets_by_kind: dict[str, list[dict[str, Any]]] = {"image": [], "table": []}
    for kind in ("image", "table"):
        block_targets = block_targets_by_kind[kind]
        anchor_targets = model_anchors_by_kind[kind]
        for index, block_target in enumerate(block_targets):
            if index >= len(anchor_targets):
                break
            aligned_targets_by_kind[kind].append({
                **block_target,
                "anchor_seq": int(anchor_targets[index].get("seq", index)),
                "anchor_bbox": anchor_targets[index].get("bbox"),
            })

    def candidate_sort_key(item: dict[str, Any]) -> tuple[float, float]:
        bbox = item.get("bbox")
        if isinstance(bbox, list) and len(bbox) >= 4:
            cy = (float(bbox[1]) + float(bbox[3])) / 2.0
            cx = (float(bbox[0]) + float(bbox[2])) / 2.0
            return cy, cx
        return 0.0, 0.0

    def score_candidate_to_target(candidate: dict[str, Any], target: dict[str, Any]) -> tuple[float, float, float]:
        candidate_seq = int(candidate.get("seq", 0))
        target_seq = int(target.get("anchor_seq", 0))
        seq_gap = abs(candidate_seq - target_seq)
        candidate_bbox = candidate.get("bbox")
        target_bbox = target.get("anchor_bbox")
        vertical_gap = 0.0
        horizontal_gap = 0.0
        if isinstance(candidate_bbox, list) and len(candidate_bbox) >= 4 and isinstance(target_bbox, list) and len(target_bbox) >= 4:
            candidate_cy = (float(candidate_bbox[1]) + float(candidate_bbox[3])) / 2.0
            target_cy = (float(target_bbox[1]) + float(target_bbox[3])) / 2.0
            candidate_cx = (float(candidate_bbox[0]) + float(candidate_bbox[2])) / 2.0
            target_cx = (float(target_bbox[0]) + float(target_bbox[2])) / 2.0
            vertical_gap = abs(candidate_cy - target_cy)
            horizontal_gap = abs(candidate_cx - target_cx)
        return seq_gap, vertical_gap, horizontal_gap

    aligned_map: dict[int, dict[str, list[list[float]]]] = {}
    related_candidates = [
        candidate for candidate in page_candidates
        if str(candidate.get("kind") or "").strip().lower() in related_to_main
    ]
    related_candidates.sort(key=candidate_sort_key)

    for candidate in related_candidates:
        candidate_kind = str(candidate.get("kind") or "").strip().lower()
        main_kind = related_to_main[candidate_kind]
        aligned_targets = aligned_targets_by_kind.get(main_kind, [])
        if not aligned_targets:
            continue
        best_target = min(
            aligned_targets,
            key=lambda target: score_candidate_to_target(candidate, target)
        )
        bbox = candidate.get("bbox")
        if not isinstance(bbox, list) or len(bbox) < 4:
            continue
        value_key = "caption_bboxes" if "caption" in candidate_kind else "footnote_bboxes"
        aligned_map.setdefault(int(best_target["block_index"]), {}).setdefault(value_key, []).append([
            float(bbox[0]),
            float(bbox[1]),
            float(bbox[2]),
            float(bbox[3]),
        ])

    return aligned_map


def resolve_media_region_bboxes(
    page_candidates: list[dict[str, Any]],
    kind: str,
    payload: Any
) -> list[list[float]]:
    """按文本从 model.json 候选中解析图表 caption/footnote 的 bbox 列表。"""
    if not page_candidates:
        return []
    needles = build_media_text_needles(payload)
    if not needles:
        return []
    matches: list[list[float]] = []
    for candidate in page_candidates:
        if str(candidate.get("kind") or "") != kind:
            continue
        candidate_text = str(candidate.get("normalized_text") or "")
        if not candidate_text or not matches_related_text(candidate_text, needles):
            continue
        bbox = candidate.get("bbox")
        if isinstance(bbox, list) and len(bbox) >= 4:
            matches.append([float(bbox[0]), float(bbox[1]), float(bbox[2]), float(bbox[3])])
    matches.sort(key=lambda item: (item[1], item[0], item[3], item[2]))
    unique: list[list[float]] = []
    seen: set[tuple[float, float, float, float]] = set()
    for bbox in matches:
        key = (bbox[0], bbox[1], bbox[2], bbox[3])
        if key in seen:
            continue
        seen.add(key)
        unique.append(bbox)
    return unique

# 为图表块补齐 caption/footnote 的显式 bbox 列表。
def enrich_media_content_bboxes(
    block_type: str,
    content_json: dict[str, Any],
    page_candidates: list[dict[str, Any]],
    aligned_media_bboxes: dict[str, list[list[float]]] | None = None
) -> dict[str, list[list[float]]]:
    """为图表块补齐 caption/footnote 的显式 bbox 列表。"""
    if block_type not in {"image", "table"} or not isinstance(content_json, dict):
        return {}
    caption_key = "table_caption" if block_type == "table" else "image_caption"
    footnote_key = "table_footnote" if block_type == "table" else "image_footnote"
    caption_bbox_key = f"{caption_key}_bboxes"
    footnote_bbox_key = f"{footnote_key}_bboxes"

    caption_bboxes = extract_media_bbox_list((aligned_media_bboxes or {}).get("caption_bboxes"))
    if not caption_bboxes:
        caption_bboxes = extract_media_bbox_list(content_json.get(caption_bbox_key))
    if not caption_bboxes:
        caption_bboxes = resolve_media_region_bboxes(page_candidates, caption_key, content_json.get(caption_key))
    footnote_bboxes = extract_media_bbox_list((aligned_media_bboxes or {}).get("footnote_bboxes"))
    if not footnote_bboxes:
        footnote_bboxes = extract_media_bbox_list(content_json.get(footnote_bbox_key))
    if not footnote_bboxes:
        footnote_bboxes = resolve_media_region_bboxes(page_candidates, footnote_key, content_json.get(footnote_key))

    if caption_bboxes:
        content_json[caption_bbox_key] = caption_bboxes
    if footnote_bboxes:
        content_json[footnote_bbox_key] = footnote_bboxes

    result: dict[str, list[list[float]]] = {}
    if caption_bboxes:
        result["caption_bboxes"] = caption_bboxes
    if footnote_bboxes:
        result["footnote_bboxes"] = footnote_bboxes
    return result


def text_match_score(source: str, target: str) -> float:
    """计算文本匹配分值。"""
    src = normalize_match_text(source)
    tgt = normalize_match_text(target)
    if not src or not tgt:
        return 0.0
    if src == tgt:
        return 1.0
    if src in tgt or tgt in src:
        overlap = min(len(src), len(tgt)) / max(len(src), len(tgt))
        return 0.72 + overlap * 0.24
    return 0.0


def resolve_layout_bbox(
    page_candidates: list[dict[str, Any]],
    text: str,
    preferred_kinds: tuple[str, ...]
) -> tuple[float, float, float, float] | None:
    """按文本在 layout 候选中解析更精确 bbox。"""
    if not text.strip() or not page_candidates:
        return None

    best: dict[str, Any] | None = None
    best_score = 0.0
    for candidate in page_candidates:
        if candidate.get("used"):
            continue
        kind = str(candidate.get("kind") or "")
        if preferred_kinds and kind not in preferred_kinds:
            continue
        score = text_match_score(text, str(candidate.get("text") or ""))
        if score <= 0:
            continue
        if preferred_kinds and kind == preferred_kinds[0]:
            score += 0.04
        if score > best_score:
            best = candidate
            best_score = score

    if best is None and preferred_kinds:
        for candidate in page_candidates:
            if candidate.get("used"):
                continue
            score = text_match_score(text, str(candidate.get("text") or ""))
            if score > best_score:
                best = candidate
                best_score = score

    if best is None or best_score < 0.74:
        return None

    best["used"] = True
    bbox = best.get("bbox")
    if isinstance(bbox, tuple) and len(bbox) == 4:
        return bbox
    return None


def build_layout_candidates(layout_payload: Any) -> dict[int, list[dict[str, Any]]]:
    """构建按页组织的 layout 文本与 bbox 候选。"""
    page_map: dict[int, list[dict[str, Any]]] = {}
    if not isinstance(layout_payload, dict):
        return page_map

    pdf_info = layout_payload.get("pdf_info")
    if not isinstance(pdf_info, list):
        return page_map

    for page_idx, page in enumerate(pdf_info):
        if not isinstance(page, dict):
            continue
        para_blocks = page.get("para_blocks")
        if not isinstance(para_blocks, list):
            continue
        candidates: list[dict[str, Any]] = []
        for para_block in para_blocks:
            if not isinstance(para_block, dict):
                continue
            para_type = str(para_block.get("type") or "")
            para_bbox = parse_bbox(para_block.get("bbox"))
            para_text = extract_layout_text(para_block)
            if para_text and any(para_bbox):
                candidates.append({
                    "text": para_text,
                    "bbox": para_bbox,
                    "kind": para_type or "unknown",
                    "used": False
                })

            if para_type == "list":
                child_blocks = para_block.get("blocks")
                if isinstance(child_blocks, list):
                    for child in child_blocks:
                        if not isinstance(child, dict):
                            continue
                        child_bbox = parse_bbox(child.get("bbox"))
                        child_text = extract_layout_text(child)
                        if not child_text or not any(child_bbox):
                            continue
                        child_type = str(child.get("type") or "text")
                        candidates.append({
                            "text": child_text,
                            "bbox": child_bbox,
                            "kind": "list_item" if child_type == "text" else child_type,
                            "used": False
                        })
        page_map[page_idx] = candidates
    return page_map


def load_raw(raw_dir: Path) -> tuple[list[list[dict[str, Any]]], dict[int, tuple[float, float]], str, dict[str, Any], Any, dict[str, Any]]:
    """读取解析结果并返回内容、页面尺寸、解析器版本、model 数据与 middle 数据。"""
    content_list_path = raw_dir / "content_list_v2.json"
    if not content_list_path.exists():
        content_list_path = raw_dir / "content_list.json"
    layout_path = raw_dir / "layout.json"
    model_path = raw_dir / "model.json"
    middle_path = raw_dir / "middle.json"
    
    if not content_list_path.exists():
        return [], {}, "", {}, [], {}
    
    parsed_blocks = read_json(content_list_path)
    parser_version = ""
    page_size_map: dict[int, tuple[float, float]] = {}
    layout_payload: dict[str, Any] = {}
    model_payload: Any = []
    middle_payload: dict[str, Any] = {}
    
    if layout_path.exists():
        layout = read_json(layout_path)
        if isinstance(layout, dict):
            layout_payload = layout
        pdf_info = layout.get("pdf_info", []) if isinstance(layout, dict) else []
        for page in pdf_info:
            idx = int(page.get("page_idx", 0))
            size = page.get("page_size", [0, 0])
            if isinstance(size, list) and len(size) == 2:
                page_size_map[idx] = (float(size[0]), float(size[1]))
        parser_version = str(layout.get("_version_name", "")) if isinstance(layout, dict) else ""

    if model_path.exists():
        model_payload = read_json(model_path)

    if middle_path.exists():
        middle_payload = read_json(middle_path)

    if not page_size_map and model_payload:
        pages = model_payload if isinstance(model_payload, list) else [model_payload]
        for page in pages:
            if not isinstance(page, dict):
                continue
            info = page.get("page_info") or {}
            idx = int(info.get("page_no", 0))
            w = float(info.get("width") or 0)
            h = float(info.get("height") or 0)
            if w > 0 and h > 0:
                page_size_map[idx] = (w, h)

    # hybrid-engine 的 model.json 没有 page_info；页面尺寸在 middle.json 的
    # pdf_info[page].page_size（原始坐标系，如 612x825）。
    if not page_size_map and isinstance(middle_payload, dict):
        for page in middle_payload.get("pdf_info") or []:
            if not isinstance(page, dict):
                continue
            try:
                idx = int(page.get("page_idx", 0))
            except (TypeError, ValueError):
                continue
            size = page.get("page_size") or []
            if not isinstance(size, (list, tuple)) or len(size) < 2:
                continue
            try:
                w, h = float(size[0] or 0), float(size[1] or 0)
            except (TypeError, ValueError):
                continue
            if w > 0 and h > 0:
                page_size_map[idx] = (w, h)

    # 校准：content_list_v2 的 bbox 可能与 model.json 的 page_info 使用不同坐标系。
    # 当 bbox 最大值远小于 page_info 报告的页面尺寸时，说明 scale 不匹配，
    # 需要用 bbox 自身的最大值反推实际页面尺寸。
    # 注意：仅当 layout.json 缺失（page_size_map 来自 model.json）时才校准。
    if not layout_payload and page_size_map and parsed_blocks:
        for idx, page_items in enumerate(parsed_blocks):
            if idx not in page_size_map:
                continue
            page_max_x, page_max_y = 0.0, 0.0
            for item in page_items:
                bbox = item.get("bbox")
                if isinstance(bbox, list) and len(bbox) == 4:
                    page_max_x = max(page_max_x, float(bbox[2]))
                    page_max_y = max(page_max_y, float(bbox[3]))
            if page_max_x <= 0 or page_max_y <= 0:
                continue
            w, h = page_size_map[idx]
            # bbox 值域在 0~1100 内且页面尺寸明显更大：判定为 1000 归一化坐标系
            # （MinerU 3.4 自部署版 content_list_v2 的输出格式；逐页判断以兼容横排页）
            # hybrid-engine 的 page_size 来自 middle.json（如 612x825），此时
            # content_list_v2 的 bbox 最大值反而超过 page_size，同样判定为 1000 坐标系。
            if (
                page_max_x <= 1100 and page_max_y <= 1100
                and (
                    w > 1100 or h > 1100
                    or page_max_x > w * 1.05
                    or page_max_y > h * 1.05
                )
            ):
                page_size_map[idx] = (1000.0, 1000.0)
            elif page_max_y < h * 0.5:
                # 兜底：用 bbox 最大值 + 5% 边距估算
                margin_x = page_max_x * 0.05
                margin_y = page_max_y * 0.05
                page_size_map[idx] = (page_max_x + margin_x, page_max_y + margin_y)

    return parsed_blocks, page_size_map, parser_version, layout_payload, model_payload, middle_payload


# middle.json 图表子块 bbox：para_blocks 与 content_list 逐位对齐（content_list 仅页尾
# 多出 page_header/page_number/page_footer），子块 bbox 用 middle page_size 归一化到 0..1。
def _middle_media_region_map(middle_payload: Any) -> dict[int, dict[int, dict[str, Any]]]:
    """提取 middle.json 图表 caption/footnote/table_body 子块 bbox。

    返回 {page_idx: {para_index: {"caption_bboxes"/"footnote_bboxes"/"body_bbox"/"row_count"}}}，
    para_index 与 content_list 非页眉/页码块的顺序一一对应。
    """
    result: dict[int, dict[int, dict[str, Any]]] = {}
    if not isinstance(middle_payload, dict):
        return result
    for page in middle_payload.get("pdf_info") or []:
        if not isinstance(page, dict):
            continue
        try:
            page_idx = int(page.get("page_idx", 0))
        except (TypeError, ValueError):
            continue
        size = page.get("page_size") or [0, 0]
        if not isinstance(size, (list, tuple)) or len(size) < 2:
            continue
        try:
            pw, ph = float(size[0] or 0), float(size[1] or 0)
        except (TypeError, ValueError):
            continue
        if pw <= 0 or ph <= 0:
            continue
        page_map: dict[int, dict[str, Any]] = {}
        for para_index, block in enumerate(page.get("para_blocks") or []):
            if not isinstance(block, dict):
                continue
            btype = str(block.get("type") or "").strip().lower()
            if btype not in {"image", "table", "chart"}:
                continue
            caption: list[list[float]] = []
            footnote: list[list[float]] = []
            body_bbox: list[float] | None = None
            row_count: int | None = None
            for sub in block.get("blocks") or []:
                if not isinstance(sub, dict):
                    continue
                sub_type = str(sub.get("type") or "").strip().lower()
                raw_bbox = sub.get("bbox")
                if not isinstance(raw_bbox, (list, tuple)) or len(raw_bbox) < 4:
                    continue
                try:
                    unit = [
                        min(1.0, max(0.0, float(raw_bbox[0]) / pw)),
                        min(1.0, max(0.0, float(raw_bbox[1]) / ph)),
                        min(1.0, max(0.0, float(raw_bbox[2]) / pw)),
                        min(1.0, max(0.0, float(raw_bbox[3]) / ph)),
                    ]
                except (TypeError, ValueError):
                    continue
                if sub_type in ("image_caption", "table_caption", "chart_caption"):
                    caption.append(unit)
                elif sub_type in ("image_footnote", "table_footnote", "chart_footnote"):
                    footnote.append(unit)
                elif sub_type == "table_body":
                    body_bbox = unit
                    row_count = None
                    for line in sub.get("lines") or []:
                        if not isinstance(line, dict):
                            continue
                        for span in line.get("spans") or []:
                            if isinstance(span, dict) and str(span.get("type") or "").strip().lower() == "table":
                                html = str(span.get("html") or "")
                                row_count = len(re.findall(r"<tr[ >]", html, re.IGNORECASE))
                                break
                        if row_count is not None:
                            break
            entry: dict[str, Any] = {}
            if caption:
                entry["caption_bboxes"] = caption
            if footnote:
                entry["footnote_bboxes"] = footnote
            if body_bbox is not None:
                entry["body_bbox"] = body_bbox
            if row_count:
                entry["row_count"] = row_count
            if entry:
                page_map[para_index] = entry
        if page_map:
            result[page_idx] = page_map
    return result


# model.json 公式编号：display_formula 与紧随其后的 formula_number 相邻配对，
# bbox 用 page_info 尺寸归一化到 0..1，按页、按公式顺序返回。
def _model_formula_number_map(model_payload: Any) -> dict[int, list[list[float]]]:
    """提取 model.json layout_dets 中的公式编号 bbox。"""
    result: dict[int, list[list[float]]] = {}
    if not isinstance(model_payload, list):
        return result
    for page_idx, page in enumerate(model_payload):
        if isinstance(page, list):
            # hybrid-engine：每页为裸列表，条目 bbox 已归一化
            numbers: list[list[float]] = []
            pending_formula = False
            for det in page:
                if not isinstance(det, dict):
                    continue
                det_type = str(det.get("type") or det.get("label") or "").strip().lower()
                if det_type in ("display_formula", "formula", "interline_equation"):
                    pending_formula = True
                    continue
                if det_type in ("formula_number", "equation_number") and pending_formula:
                    raw_bbox = det.get("bbox")
                    if isinstance(raw_bbox, (list, tuple)) and len(raw_bbox) >= 4:
                        try:
                            numbers.append([
                                min(1.0, max(0.0, float(v)))
                                for v in raw_bbox[:4]
                            ])
                        except (TypeError, ValueError):
                            pass
                    pending_formula = False
            if numbers:
                result[page_idx] = numbers
            continue
        if not isinstance(page, dict):
            continue
        info = page.get("page_info") or {}
        try:
            pw, ph = float(info.get("width") or 0), float(info.get("height") or 0)
        except (TypeError, ValueError):
            continue
        if pw <= 0 or ph <= 0:
            continue
        dets = page.get("layout_dets") or []
        if not isinstance(dets, list):
            continue
        ordered = sorted(
            (det for det in dets if isinstance(det, dict)),
            key=lambda det: int(det.get("index") or 0),
        )
        numbers: list[list[float]] = []
        pending_formula = False
        for det in ordered:
            label = str(det.get("label") or "").strip().lower()
            if label == "display_formula":
                pending_formula = True
                continue
            if label == "formula_number" and pending_formula:
                raw_bbox = det.get("bbox")
                if isinstance(raw_bbox, (list, tuple)) and len(raw_bbox) >= 4:
                    try:
                        numbers.append([
                            min(1.0, max(0.0, float(raw_bbox[0]) / pw)),
                            min(1.0, max(0.0, float(raw_bbox[1]) / ph)),
                            min(1.0, max(0.0, float(raw_bbox[2]) / pw)),
                            min(1.0, max(0.0, float(raw_bbox[3]) / ph)),
                        ])
                    except (TypeError, ValueError):
                        pass
                pending_formula = False
        if numbers:
            result[page_idx] = numbers
    return result


def _model_type_recognition_map(model_payload: Any) -> dict[int, list[tuple[str, float | None, list[float]]]]:
    """从 model.json 提取每页 layout_dets 的 (label, score, 归一化 bbox)。

    bbox 按 page_info 的 width/height 归一化到 0..1，与节点 bbox 坐标系一致。
    score 非数值时保留 None（仅该候选不可用于匹配），label/bbox 缺失的候选跳过。
    hybrid-engine 的 model.json 是裸列表，条目自带 0..1 bbox，直接透传。
    """
    result: dict[int, list[tuple[str, float | None, list[float]]]] = {}
    pages = model_payload if isinstance(model_payload, list) else [model_payload]
    for page_idx, page in enumerate(pages):
        if isinstance(page, list):
            # hybrid-engine：每页为裸列表，条目 bbox 已归一化，score 通常缺失
            items: list[tuple[str, float | None, list[float]]] = []
            for det in page:
                if not isinstance(det, dict):
                    continue
                label = str(det.get("type") or det.get("label") or "").strip()
                raw_bbox = det.get("bbox")
                if not label or not isinstance(raw_bbox, (list, tuple)) or len(raw_bbox) < 4:
                    continue
                try:
                    bbox_norm = [
                        min(1.0, max(0.0, float(raw_bbox[0]))),
                        min(1.0, max(0.0, float(raw_bbox[1]))),
                        min(1.0, max(0.0, float(raw_bbox[2]))),
                        min(1.0, max(0.0, float(raw_bbox[3]))),
                    ]
                except (TypeError, ValueError):
                    continue
                score = det.get("score")
                items.append((label, float(score) if isinstance(score, (int, float)) else None, bbox_norm))
            if items:
                result[page_idx] = items
            continue
        if not isinstance(page, dict):
            continue
        info = page.get("page_info") or {}
        try:
            page_idx = int(info.get("page_no", 0))
            pw = float(info.get("width") or 0)
            ph = float(info.get("height") or 0)
        except (TypeError, ValueError):
            continue
        if pw <= 0 or ph <= 0:
            continue
        items: list[tuple[str, float | None, list[float]]] = []
        for det in page.get("layout_dets") or []:
            if not isinstance(det, dict):
                continue
            label = str(det.get("label") or "").strip()
            raw_bbox = det.get("bbox")
            if not label or not isinstance(raw_bbox, (list, tuple)) or len(raw_bbox) < 4:
                continue
            try:
                bbox_norm = [
                    min(1.0, max(0.0, float(raw_bbox[0]) / pw)),
                    min(1.0, max(0.0, float(raw_bbox[1]) / ph)),
                    min(1.0, max(0.0, float(raw_bbox[2]) / pw)),
                    min(1.0, max(0.0, float(raw_bbox[3]) / ph)),
                ]
            except (TypeError, ValueError):
                continue
            score = det.get("score")
            if score is None:
                continue
            items.append((label, float(score) if isinstance(score, (int, float)) else None, bbox_norm))
        if items:
            result[page_idx] = items
    return result


def _middle_text_recognition_scores(middle_payload: Any) -> dict[int, list[float | None]]:
    """从 middle.json 按页提取 para_blocks 的文本识别置信度。

    para_blocks 与 content_list 非页眉/页码块逐位对齐（solo_engine 既有假设，
    见 _middle_media_region_map 的 para_index 用法）。每个块取 lines/spans 中
    score 的最小值；无 span 的块（公式/图片/表格）记 None。
    """
    result: dict[int, list[float | None]] = {}
    if not isinstance(middle_payload, dict):
        return result
    for page in middle_payload.get("pdf_info") or []:
        if not isinstance(page, dict):
            continue
        page_idx = int(page.get("page_idx") or 0)
        scores: list[float | None] = []
        for block in page.get("para_blocks") or []:
            if not isinstance(block, dict):
                scores.append(None)
                continue
            span_scores = [
                s.get("score")
                for line in block.get("lines") or []
                if isinstance(line, dict)
                for s in line.get("spans") or []
                if isinstance(s, dict) and isinstance(s.get("score"), (int, float))
            ]
            scores.append(min(span_scores) if span_scores else None)
        result[page_idx] = scores
    return result


def _nearest_type_score(
    page_items: list[tuple[str, float | None, list[float]]],
    nx1: float | None,
    ny1: float | None,
    nx2: float | None,
    ny2: float | None,
    tol: float = 0.05,
) -> float | None:
    """在页内 layout_dets 候选中找与节点 bbox 中心最近的 score（归一化坐标）。

    中心距离超过 tol 视为未匹配；score 为 None 的候选跳过。实测公式节点
    还原后中心距离 < 0.005，tol=0.05 足够宽松且能挡住串到相邻块。
    """
    if not page_items or nx1 is None or ny1 is None or nx2 is None or ny2 is None:
        return None
    cx = (nx1 + nx2) / 2.0
    cy = (ny1 + ny2) / 2.0
    best: float | None = None
    best_d: float | None = None
    for _label, score, bbox in page_items:
        if score is None:
            continue
        bcx = (bbox[0] + bbox[2]) / 2.0
        bcy = (bbox[1] + bbox[3]) / 2.0
        d = (cx - bcx) ** 2 + (cy - bcy) ** 2
        if best_d is None or d < best_d:
            best_d = d
            best = score
    if best_d is not None and best_d <= tol * tol:
        return best
    return None


def infer_title_level(text: str, raw_level: Any) -> tuple[int | None, float, str]:
    """用规则与原始level推断标题级别。"""
    txt = (text or "").strip()
    m = re.match(r"^(\d+(?:\.\d+)*)", txt)
    if m:
        level = m.group(1).count(".") + 1
        if level >= 1:
            return level, 0.95, "rule"
    if isinstance(raw_level, int) and raw_level >= 1:
        return raw_level, 0.6, "raw"
    return None, 0.0, "none"


def extract_struct_number(text: str) -> str | None:
    """提取结构编号或附录编号锚点。"""
    txt = (text or "").strip()
    if not txt:
        return None
    m = re.match(r"^(\d+(?:\.\d+)*)", txt)
    if m:
        return m.group(1)
    m2 = re.match(r"^(附录[A-Z])", txt)
    if m2:
        return m2.group(1)
    return None


def infer_struct_level(text: str) -> int | None:
    """从结构编号提取无限深度层级。"""
    struct_no = extract_struct_number(text)
    if not struct_no:
        return None
    if struct_no.startswith("附录"):
        return 1
    return struct_no.count(".") + 1


def should_treat_as_struct_heading(block_type: str, text: str, is_toc_row: bool, is_toc_page: bool) -> bool:
    """判断是否把非title块按结构标题处理。"""
    if is_toc_row or is_toc_page:
        return False
    if block_type not in ("paragraph", "list"):
        return False
    return infer_struct_level(text) is not None


def is_equation_explain_continuation(text: str) -> bool:
    """?????????????"""
    txt = (text or "").strip()
    if not txt:
        return False
    if re.match(r"^\d+(?:\.\d+)*", txt):
        return False
    # ?? MinerU LaTeX ???\pmb { \ t } _ { 1 } -> t_1?K _ { t } -> K_t?
    # ?????????????????6.2.8 ? K_t/t_1/t_2/t_3 ????
    compact = re.sub(r"\\[A-Za-z]+\s*\{\s*\\?\s*([^{}]*?)\s*\}", r"\1", txt)
    compact = re.sub(r"\s*\{\s*([^{}]*?)\s*\}", r"\1", compact)
    compact = re.sub(r"\s+", "", compact)
    if compact.startswith(("\u5f0f\u4e2d", "\u5176\u4e2d", "\u6ce8")):
        return True
    if re.match(r"^[\u2022\u00b7][A-Za-z\u0391-\u03a9\u03b1-\u03c9][A-Za-z0-9_{}()\\\-^/.']*(?:[\u2014\uff0d\u2013\u4e00=:\uff1a])", compact):
        return True
    if re.match(r"^[A-Za-z\u0391-\u03a9\u03b1-\u03c9][A-Za-z0-9_{}()\\\-^/.']*(?:[\u2014\uff0d\u2013\u4e00=:\uff1a])", compact):
        return True
    return re.match(r"^[A-Za-z\u0391-\u03a9\u03b1-\u03c9][A-Za-z0-9_{}()\\\-^/.']*[\u4e00-\u9fff(\uff08]", compact) is not None



def find_recent_equation_uid(rows: list[Any], idx: int, max_back: int = 8) -> str | None:
    """回溯最近可作为说明父级的公式块。"""
    current = rows[idx]
    page_idx = current["page_idx"]
    for j in range(idx - 1, max(-1, idx - max_back), -1):
        prev = rows[j]
        if prev["page_idx"] != page_idx:
            break
        prev_type = prev["block_type"]
        if prev_type == "equation_interline":
            return prev["block_uid"]
        if prev_type in ("title", "table", "image", "page_header", "page_number"):
            break
    return None


def derive_explain_target(rows: list[Any], idx: int) -> tuple[str | None, str | None, float, str]:
    """为说明性段落回溯关联公式或图表目标。"""
    current = rows[idx]
    if current["block_type"] not in ("paragraph", "list"):
        return None, None, 0.0, "none"
    txt = (current["plain_text"] or "").strip()
    if not txt:
        return None, None, 0.0, "none"
    trigger = txt.startswith("式中") or txt.startswith("其中") or txt.startswith("注") or is_equation_explain_continuation(txt)
    if not trigger:
        return None, None, 0.0, "none"
    recent_equation_uid = find_recent_equation_uid(rows, idx)
    if recent_equation_uid:
        return recent_equation_uid, "equation", 0.85 if txt.startswith(("式中", "其中", "注")) else 0.8, "rule"
    page_idx = current["page_idx"]
    for j in range(idx - 1, max(-1, idx - 8), -1):
        prev = rows[j]
        if prev["page_idx"] != page_idx:
            break
        t = prev["block_type"]
        if t in ("equation_interline", "table", "image"):
            return prev["block_uid"], t.replace("_interline", ""), 0.85, "rule"
    return None, None, 0.2, "rule"


def detect_toc_row_ids(rows: list[Any]) -> set[int]:
    """检测目录页并返回目录相关行ID集合。"""
    def is_toc_marker(text: str) -> bool:
        """判断是否目录页标记文本。"""
        compact = re.sub(r"\s+", "", text)
        return compact in {"目录", "目次"}

    def is_toc_item(text: str) -> bool:
        """判断文本是否目录条目样式。"""
        compact = re.sub(r"\s+", "", text)
        if not compact:
            return False
        if is_toc_marker(compact):
            return True
        has_leader = ("……" in compact) or ("..." in compact) or ("…" in compact)
        has_page_tail = re.search(r"(?:\(|（)?\d{1,4}(?:\)|）)?$", compact) is not None
        if not has_page_tail:
            return False
        starts_like_heading = re.match(r"^(附录[A-Z]|附录|引用标准名录|条文说明|\d+(?:[.\-]\d+)*)", compact) is not None
        if starts_like_heading:
            return True
        return has_leader and len(compact) >= 8

    candidate_types = {"title", "list", "paragraph"}
    pages: dict[int, list[Any]] = {}
    marker_pages: set[int] = set()
    for row in rows:
        page_idx = int(row["page_idx"])
        pages.setdefault(page_idx, []).append(row)
        text = (row["plain_text"] or "").strip()
        if text and is_toc_marker(text):
            marker_pages.add(page_idx)
    if not marker_pages:
        return set()
    page_order = sorted(pages.keys())
    first_marker = min(marker_pages)
    toc_pages: set[int] = set(marker_pages)
    collecting = False
    for page_idx in page_order:
        if page_idx < first_marker:
            continue
        rows_in_page = pages.get(page_idx, [])
        text_rows = [r for r in rows_in_page if r["block_type"] in candidate_types]
        toc_like = 0
        for r in text_rows:
            text = (r["plain_text"] or "").strip()
            if text and is_toc_item(text):
                toc_like += 1
        page_is_toc_like = False
        if text_rows:
            ratio = toc_like / float(len(text_rows))
            page_is_toc_like = toc_like >= 2 or (len(text_rows) >= 2 and ratio >= 0.45)
        if page_idx in marker_pages:
            collecting = True
            toc_pages.add(page_idx)
            continue
        if collecting:
            if page_is_toc_like:
                toc_pages.add(page_idx)
            else:
                break
    result: set[int] = set()
    for page_idx in sorted(toc_pages):
        for row in pages.get(page_idx, []):
            if row["block_type"] not in candidate_types:
                continue
            text = (row["plain_text"] or "").strip()
            if not text:
                continue
            result.add(int(row["id"]))
    return result


_AUX_BLOCK_TYPES = {"page_header", "page_footer", "page_number", "header", "footer"}
_CONT_TEXT_BLOCK_TYPES = {"paragraph", "text", "list_item"}
_TERMINAL_PUNCT = set("。！？；;!?）】」』》\"”’)].")
_HEADING_NUMBER_RE = re.compile(r"^\d+(?:\.\d+)*\s*")
_HEADING_MARKER_PREFIXES = ("第", "附录", "附", "目", "表", "图")
_MAX_FRAGMENT_LEN = 10


def _middle_block_text(block: dict[str, Any]) -> str:
    """提取 middle.json preproc 块的纯文本（lines -> spans -> content）。"""
    parts: list[str] = []
    for line in block.get("lines") or []:
        if not isinstance(line, dict):
            continue
        for span in line.get("spans") or []:
            if isinstance(span, dict):
                parts.append(str(span.get("content") or ""))
    return "".join(parts)


def _page_last_text_ends_cut(middle_payload: Any, page_idx: int) -> bool | None:
    """判断 middle.json 中某页最后一个正文块是否断在句中（无句末标点）。

    MinerU 段落装配跨页合并文本时，会把续页行并入首页块，导致 content_list
    里首页块文本完整、续页留下空块。middle.json 的 preproc_blocks 仍保留逐页
    行级文本，因此“页末文本未以句末标点结束”是续文存在的强证据。
    """
    if not isinstance(middle_payload, dict):
        return None
    pages = middle_payload.get("pdf_info")
    if not isinstance(pages, list) or not (0 <= page_idx < len(pages)):
        return None
    page = pages[page_idx]
    if not isinstance(page, dict):
        return None
    text_blocks: list[str] = []
    for block in page.get("preproc_blocks") or []:
        if not isinstance(block, dict):
            continue
        block_type = str(block.get("type") or "").strip().lower()
        if block_type in _AUX_BLOCK_TYPES:
            continue
        text = _middle_block_text(block).strip()
        if text:
            text_blocks.append(text)
    if not text_blocks:
        return None
    last_text = text_blocks[-1]
    return bool(last_text) and last_text[-1] not in _TERMINAL_PUNCT


def _row_norm_bbox(row: dict[str, Any]) -> tuple[float, float, float, float] | None:
    """按行内 page_width/page_height 归一化 bbox（与节点 bbox 逻辑一致）。"""
    page_width = float(row.get("page_width") or 0.0)
    page_height = float(row.get("page_height") or 0.0)
    ax1 = float(row.get("bbox_abs_x1") or 0.0)
    ay1 = float(row.get("bbox_abs_y1") or 0.0)
    ax2 = float(row.get("bbox_abs_x2") or 0.0)
    ay2 = float(row.get("bbox_abs_y2") or 0.0)
    if page_width > 0 and page_height > 0 and (ax2 > page_width * 1.2 or ay2 > page_height * 1.2):
        return (ax1 / 1000.0, ay1 / 1000.0, ax2 / 1000.0, ay2 / 1000.0)
    if page_width > 0 and page_height > 0:
        return (ax1 / page_width, ay1 / page_height, ax2 / page_width, ay2 / page_height)
    return None


def _is_empty_continuation_pair(
    source: dict[str, Any],
    target: dict[str, Any],
    middle_payload: Any,
    source_page: int,
) -> bool:
    """上一页末段 + 下一页首空块是否构成 MinerU 跨页段落续文对。"""
    if str(source.get("block_type") or "") not in _CONT_TEXT_BLOCK_TYPES:
        return False
    if str(target.get("block_type") or "") not in _CONT_TEXT_BLOCK_TYPES:
        return False
    if not (source.get("plain_text") or "").strip():
        return False
    if (target.get("plain_text") or "").strip():
        return False
    if source.get("page_bboxes") or source.get("merged_from") or source.get("contd_target_id") or source.get("table_merge_id"):
        return False
    src_bbox = _row_norm_bbox(source)
    tgt_bbox = _row_norm_bbox(target)
    if not src_bbox or not tgt_bbox:
        return False
    _, _, _, src_y2 = src_bbox
    _, tgt_y1, _, _ = tgt_bbox
    # 上一页末段应位于页底，下一页续块应位于页首
    if src_y2 < 0.80 or tgt_y1 > 0.35:
        return False
    cut_evidence = _page_last_text_ends_cut(middle_payload, source_page)
    # 必须有 middle.json 的断句证据才合并，避免误并正常的页底段落 + 页首空块
    return cut_evidence is True


def _looks_like_heading(text: str) -> bool:
    """判断短文本是否更像真实标题而非续文碎片。"""
    compact = re.sub(r"\s+", "", text)
    if not compact:
        return True
    if _HEADING_NUMBER_RE.match(compact):
        return True
    return compact.startswith(_HEADING_MARKER_PREFIXES)


def _is_fragment_continuation_pair(
    source: dict[str, Any],
    target: dict[str, Any],
    middle_payload: Any,
    source_page: int,
) -> bool:
    """上一页末段 + 下一页页首短碎片（如被误判为 title 的“料；”）是否构成续文对。"""
    if str(source.get("block_type") or "") not in _CONT_TEXT_BLOCK_TYPES:
        return False
    target_type = str(target.get("block_type") or "").strip().lower()
    if target_type not in {"paragraph", "text", "list_item", "title"}:
        return False
    source_text = (source.get("plain_text") or "").strip()
    target_text = (target.get("plain_text") or "").strip()
    if not source_text or not target_text:
        return False
    if source_text[-1] in _TERMINAL_PUNCT:
        return False
    if len(target_text) > _MAX_FRAGMENT_LEN:
        return False
    if _looks_like_heading(target_text):
        return False
    if target_text[-1] not in _TERMINAL_PUNCT and (source_text + target_text)[-1] not in _TERMINAL_PUNCT:
        return False
    if source.get("page_bboxes") or source.get("merged_from") or source.get("contd_target_id") or source.get("table_merge_id"):
        return False
    src_bbox = _row_norm_bbox(source)
    tgt_bbox = _row_norm_bbox(target)
    if not src_bbox or not tgt_bbox:
        return False
    _, _, _, src_y2 = src_bbox
    _, tgt_y1, _, tgt_y2 = tgt_bbox
    # 上一页末段位于页底、下一页碎片位于页首且高度很小
    if src_y2 < 0.80 or tgt_y1 > 0.35 or tgt_y2 - tgt_y1 > 0.20:
        return False
    cut_evidence = _page_last_text_ends_cut(middle_payload, source_page)
    return cut_evidence is True


def _merge_mineru_continuation_rows(
    rows: list[dict[str, Any]],
    middle_payload: Any,
) -> int:
    """把 MinerU 跨页段落装配遗留的续页残块并入上一页末段。

    两类现象：
    1. 文本被并入首页块，续页只剩空块（无 page_bboxes，前端高亮只覆盖首页）；
    2. 续页残留短碎片（如被误判为 title 的“料；”），文本与首页块分离。
    此处为首页段补充 page_bboxes、合并碎片文本并移除续页残块。
    """
    rows_by_page: dict[int, list[dict[str, Any]]] = {}
    for row in rows:
        rows_by_page.setdefault(int(row.get("page_idx") or 0), []).append(row)

    source_by_uid: dict[str, dict[str, Any]] = {}
    removed_uids: set[str] = set()

    for page_idx in sorted(rows_by_page):
        page_rows = rows_by_page[page_idx]
        content_rows = [row for row in page_rows if str(row.get("block_type") or "") not in _AUX_BLOCK_TYPES]
        if not content_rows:
            continue
        source = content_rows[-1]
        next_rows = rows_by_page.get(page_idx + 1)
        if not next_rows:
            continue
        next_content = [row for row in next_rows if str(row.get("block_type") or "") not in _AUX_BLOCK_TYPES]
        if not next_content:
            continue
        target = next_content[0]
        is_empty_pair = _is_empty_continuation_pair(source, target, middle_payload, page_idx)
        is_fragment_pair = _is_fragment_continuation_pair(source, target, middle_payload, page_idx)
        if not is_empty_pair and not is_fragment_pair:
            continue
        src_bbox = _row_norm_bbox(source)
        tgt_bbox = _row_norm_bbox(target)
        if not src_bbox or not tgt_bbox:
            continue
        source["page_bboxes"] = [
            {
                "page_idx": page_idx,
                "bbox": [float(v) for v in src_bbox],
            },
            {
                "page_idx": page_idx + 1,
                "bbox": [float(v) for v in tgt_bbox],
            },
        ]
        if is_fragment_pair:
            fragment_text = (target.get("plain_text") or "").strip()
            if fragment_text:
                source["plain_text"] = (source.get("plain_text") or "") + fragment_text
                source_cj = source.get("content_json")
                if isinstance(source_cj, dict):
                    paragraph_content = source_cj.get("paragraph_content")
                    if isinstance(paragraph_content, list) and paragraph_content:
                        first = paragraph_content[0]
                        if isinstance(first, dict) and "content" in first:
                            first["content"] = str(first.get("content") or "") + fragment_text
                    elif not paragraph_content:
                        source_cj["paragraph_content"] = [
                            {"type": "text", "content": fragment_text},
                        ]
        source["merged_from"] = [str(target.get("block_uid") or target.get("id") or "").strip()]
        source_by_uid[str(source.get("block_uid") or source.get("id") or "").strip()] = source
        removed_uids.add(str(target.get("block_uid") or target.get("id") or "").strip())

    if not removed_uids:
        return 0

    merged_count = len(source_by_uid)
    kept: list[dict[str, Any]] = []
    for row in rows:
        uid = str(row.get("block_uid") or row.get("id") or "").strip()
        if uid in removed_uids:
            continue
        kept.append(row)
    rows[:] = kept
    # 全局重排 block_seq，保持阅读序连续
    for index, row in enumerate(rows, start=1):
        row["block_seq"] = index
    return merged_count


@dataclass
class StructuredResult:
    """结构化结果对象。"""
    nodes: List[Dict[str, Any]] = field(default_factory=list)
    edges: List[Dict[str, Any]] = field(default_factory=list)
    index_rows: List[Dict[str, Any]] = field(default_factory=list)
    stats: Dict[str, Any] = field(default_factory=dict)


def build_structured_from_rawfiles(
    parsed_dir: Path,
    doc_id: str,
    doc_name: str = "",
    llm_client: Optional["LLMClient"] = None,
    options: Optional[Dict[str, Any]] = None
) -> StructuredResult:
    """
    从原始解析结果构建结构化对象。
    
    Args:
        parsed_dir: 解析结果目录，应包含 mineru_raw/ 子目录
        doc_id: 文档ID
        doc_name: 文档名称
        llm_client: 可选的 LLM 客户端，用于标题层级细化
        options: 可选配置项
            - use_llm: 是否使用 LLM 细化 (默认 True)
            - llm_model: 指定标题层级细化使用的模型配置名
            - derive_version: 推导版本标识
    
    Returns:
        StructuredResult: 包含 nodes, edges, index_rows, stats
    """
    opts = options or {}
    use_llm = opts.get("use_llm", True)
    llm_model = str(opts.get("llm_model") or "").strip() or None
    derive_version = opts.get("derive_version", "v1")
    
    raw_dir = parsed_dir / "mineru_raw"
    if not raw_dir.exists():
        raw_dir = parsed_dir
    
    parsed_blocks, page_size_map, parser_version, layout_payload, model_payload, middle_payload = load_raw(raw_dir)
    type_score_map = _model_type_recognition_map(model_payload)
    text_score_map = _middle_text_recognition_scores(middle_payload)
    layout_candidates = build_layout_candidates(layout_payload)
    model_media_candidates = build_model_media_candidate_map(model_payload)
    middle_region_map = _middle_media_region_map(middle_payload)
    formula_number_map = _model_formula_number_map(model_payload)
    
    if not parsed_blocks:
        return StructuredResult(stats={"error": "no_parsed_blocks", "raw_dir": str(raw_dir)})
    
    ts = now_iso()
    rows: list[dict[str, Any]] = []
    block_seq_global = 0
    
    for page_idx, page_blocks in enumerate(parsed_blocks):
        if not isinstance(page_blocks, list):
            continue
        page_width, page_height = page_size_map.get(page_idx, (0.0, 0.0))
        page_layout_candidates = layout_candidates.get(page_idx, [])
        middle_pos = 0
        eq_pos = 0
        page_aligned_media_bboxes = build_order_aligned_media_bbox_map(
            page_blocks,
            model_media_candidates.get(page_idx, [])
        )
        
        for i, block in enumerate(page_blocks, start=1):
            block_type = str(block.get("type", ""))
            content = block.get("content", {})
            if not isinstance(content, dict):
                content = {}
            x1, y1, x2, y2 = parse_bbox(block.get("bbox"))
            is_aux_block = block_type in ("page_header", "page_number", "page_footer")
            middle_idx = None if is_aux_block else middle_pos
            if not is_aux_block:
                middle_pos += 1
            
            list_items = content.get("list_items")
            if block_type == "list" and isinstance(list_items, list) and len(list_items) > 1:
                for li, item in enumerate(list_items, start=1):
                    item_content: dict[str, Any] = {
                        "list_type": content.get("list_type"),
                        "list_items": [item]
                    }
                    media_bbox_info = enrich_media_content_bboxes(
                        block_type,
                        item_content,
                        model_media_candidates.get(page_idx, []),
                        page_aligned_media_bboxes.get(i)
                    )
                    block_seq_global += 1
                    block_uid = f"{doc_id}:{page_idx}:{i}:li{li}"
                    plain_text = extract_plain_text("list", item_content)
                    resolved_bbox = resolve_layout_bbox(
                        page_layout_candidates,
                        plain_text,
                        ("list_item", "paragraph", "text")
                    )
                    item_x1, item_y1, item_x2, item_y2 = resolved_bbox or (x1, y1, x2, y2)
                    rows.append({
                        "id": len(rows) + 1,
                        "doc_id": doc_id,
                        "doc_name": doc_name,
                        "page_idx": page_idx,
                        "page_width": page_width,
                        "page_height": page_height,
                        "block_seq": block_seq_global,
                        "block_uid": block_uid,
                        "block_type": block_type,
                        "content_json": item_content,
                        "plain_text": plain_text,
                        "bbox_abs_x1": item_x1,
                        "bbox_abs_y1": item_y1,
                        "bbox_abs_x2": item_x2,
                        "bbox_abs_y2": item_y2,
                        "created_at": ts,
                        "updated_at": ts,
                        "caption_bboxes": media_bbox_info.get("caption_bboxes"),
                        "footnote_bboxes": media_bbox_info.get("footnote_bboxes"),
                        "table_header_bbox": None,
                        "equation_number_bbox": None,
                        "middle_idx": middle_idx,
                    })
                continue
            
            block_seq_global += 1
            block_uid = f"{doc_id}:{page_idx}:{i}"
            plain_text = extract_plain_text(block_type, content)
            aligned_media_bboxes = page_aligned_media_bboxes.get(i)
            if middle_idx is not None:
                middle_entry = middle_region_map.get(page_idx, {}).get(middle_idx)
                if middle_entry:
                    aligned_media_bboxes = dict(aligned_media_bboxes or {})
                    for _mkey in ("caption_bboxes", "footnote_bboxes"):
                        if middle_entry.get(_mkey) and not aligned_media_bboxes.get(_mkey):
                            aligned_media_bboxes[_mkey] = middle_entry[_mkey]
            media_bbox_info = enrich_media_content_bboxes(
                block_type,
                content,
                model_media_candidates.get(page_idx, []),
                aligned_media_bboxes
            )
            equation_number_bbox: list[float] | None = None
            if block_type == "equation_interline":
                _page_numbers = formula_number_map.get(page_idx) or []
                if eq_pos < len(_page_numbers):
                    equation_number_bbox = _page_numbers[eq_pos]
                eq_pos += 1
            table_header_bbox: list[float] | None = None
            if block_type == "table" and middle_idx is not None:
                _middle_entry = middle_region_map.get(page_idx, {}).get(middle_idx)
                if _middle_entry:
                    _body = _middle_entry.get("body_bbox")
                    _rc = _middle_entry.get("row_count")
                    if _body and not _rc:
                        _html = content.get("html") if isinstance(content.get("html"), str) else None
                        if _html:
                            _rc = len(re.findall(r"<tr[ >]", _html, re.IGNORECASE))
                    if _body and _rc and _rc >= 1:
                        table_header_bbox = [_body[0], _body[1], _body[2], _body[1] + (_body[3] - _body[1]) / _rc]
            preferred_layout_types: dict[str, tuple[str, ...]] = {
                "title": ("title",),
                "paragraph": ("text", "paragraph"),
                "table": ("table",),
                "image": ("image", "figure"),
                "equation_interline": ("equation", "interline_equation", "text"),
                "list": ("list",)
            }
            resolved_bbox = resolve_layout_bbox(
                page_layout_candidates,
                plain_text,
                preferred_layout_types.get(block_type, ("text", block_type))
            )
            row_x1, row_y1, row_x2, row_y2 = resolved_bbox or (x1, y1, x2, y2)
            rows.append({
                "id": len(rows) + 1,
                "doc_id": doc_id,
                "doc_name": doc_name,
                "page_idx": page_idx,
                "page_width": page_width,
                "page_height": page_height,
                "block_seq": block_seq_global,
                "block_uid": block_uid,
                "block_type": block_type,
                "content_json": content,
                "plain_text": plain_text,
                "bbox_abs_x1": row_x1,
                "bbox_abs_y1": row_y1,
                "bbox_abs_x2": row_x2,
                "bbox_abs_y2": row_y2,
                "created_at": ts,
                "updated_at": ts,
                "caption_bboxes": media_bbox_info.get("caption_bboxes"),
                "footnote_bboxes": media_bbox_info.get("footnote_bboxes"),
                "table_header_bbox": table_header_bbox,
                "equation_number_bbox": equation_number_bbox,
                "middle_idx": middle_idx,
            })
    
    continuation_merges = _merge_mineru_continuation_rows(rows, middle_payload)
    
    toc_row_ids = detect_toc_row_ids(rows)
    toc_pages = {int(r["page_idx"]) for r in rows if int(r["id"]) in toc_row_ids}
    
    heading_stack: dict[int, str] = {}
    number_anchor_uid: dict[str, str] = {}
    recent_struct_anchor_uid: str | None = None
    toc_root_uid: str | None = None
    toc_number_anchor_uid: dict[str, str] = {}
    derived_level_by_uid: dict[str, int] = {}
    active_equation_explain_uid: str | None = None
    active_equation_explain_page_idx: int | None = None
    node_by_uid: dict[str, dict[str, Any]] = {}
    formula_group: list[str] = []

    def attach_explanation_to_group(paragraph_uid: str) -> None:
        for group_uid in formula_group:
            group_node = node_by_uid.get(group_uid)
            if group_node is not None:
                group_node.setdefault("explanation_uids", [])
                if paragraph_uid not in group_node["explanation_uids"]:
                    group_node["explanation_uids"].append(paragraph_uid)
    
    nodes: list[dict[str, Any]] = []
    edges: list[dict[str, Any]] = []
    index_rows: list[dict[str, Any]] = []
    derived_rows: list[dict[str, Any]] = []
    
    excluded_types: set[str] = set()  # 展示层全量可见；05 语义层自行收敛页眉/页脚
    
    for i, row in enumerate(rows):
        content = row["content_json"]
        raw_level = content.get("level") if isinstance(content, dict) else None
        derived_level = None
        confidence = 0.0
        derived_by = "rule"
        title_path = None
        parent_uid = None
        block_type = row["block_type"] or ""
        text = row["plain_text"] or ""
        is_toc_row = int(row["id"]) in toc_row_ids
        is_toc_page = int(row["page_idx"]) in toc_pages
        compact_text = re.sub(r"\s+", "", text)
        
        if block_type == "title":
            derived_level, confidence, by = infer_title_level(row["plain_text"] or "", raw_level)
            derived_by = by
            
            if is_toc_row:
                title_path = None
                parent_uid = None
                derived_by = "toc" if derived_by == "none" else f"toc+{derived_by}"
                if compact_text in ("目录", "目次"):
                    toc_root_uid = row["block_uid"]
                else:
                    struct_no = extract_struct_number(text)
                    if struct_no:
                        parent_candidate = None
                        if "." in struct_no:
                            parts = struct_no.split(".")
                            for end in range(len(parts) - 1, 0, -1):
                                cand = ".".join(parts[:end])
                                if cand in toc_number_anchor_uid:
                                    parent_candidate = toc_number_anchor_uid[cand]
                                    break
                        parent_uid = parent_candidate or toc_root_uid
                        toc_number_anchor_uid[struct_no] = row["block_uid"]
                    elif toc_root_uid:
                        parent_uid = toc_root_uid
            elif derived_level is not None:
                for lv in list(heading_stack.keys()):
                    if lv >= derived_level:
                        del heading_stack[lv]
                parent_uid = heading_stack.get(derived_level - 1)
                heading_stack[derived_level] = row["block_uid"]
                title_path = ">".join(heading_stack[k] for k in sorted(heading_stack.keys()))
                struct_no = extract_struct_number(text)
                if struct_no:
                    number_anchor_uid[struct_no] = row["block_uid"]
                recent_struct_anchor_uid = row["block_uid"]
        else:
            if block_type not in excluded_types:
                if is_toc_row or is_toc_page:
                    struct_no = extract_struct_number(text)
                    if struct_no:
                        parent_candidate = None
                        if "." in struct_no:
                            parts = struct_no.split(".")
                            for end in range(len(parts) - 1, 0, -1):
                                cand = ".".join(parts[:end])
                                if cand in toc_number_anchor_uid:
                                    parent_candidate = toc_number_anchor_uid[cand]
                                    break
                        parent_uid = parent_candidate or toc_root_uid
                        toc_number_anchor_uid[struct_no] = row["block_uid"]
                    elif toc_root_uid:
                        parent_uid = toc_root_uid
                    derived_by = "toc" if derived_by == "none" else f"toc+{derived_by}"
                    title_path = None
                
                treat_as_heading = should_treat_as_struct_heading(block_type, text, is_toc_row, is_toc_page)
                if treat_as_heading:
                    derived_level = infer_struct_level(text)
                    if derived_level is not None:
                        confidence = max(confidence, 0.93)
                        derived_by = "rule"
                        for lv in list(heading_stack.keys()):
                            if lv >= derived_level:
                                del heading_stack[lv]
                        parent_uid = heading_stack.get(derived_level - 1)
                        heading_stack[derived_level] = row["block_uid"]
                        title_path = ">".join(heading_stack[k] for k in sorted(heading_stack.keys()))
                        struct_no = extract_struct_number(text)
                        if struct_no:
                            number_anchor_uid[struct_no] = row["block_uid"]
                        recent_struct_anchor_uid = row["block_uid"]
                else:
                    if heading_stack:
                        title_path = ">".join(heading_stack[k] for k in sorted(heading_stack.keys()))
                        parent_uid = heading_stack[max(heading_stack.keys())]
                    struct_no = extract_struct_number(text)
                    if struct_no:
                        parts = struct_no.split(".")
                        for end in range(len(parts) - 1, 0, -1):
                            candidate = ".".join(parts[:end])
                            cand_uid = number_anchor_uid.get(candidate)
                            if cand_uid:
                                parent_uid = cand_uid
                                break
                        if struct_no not in number_anchor_uid:
                            number_anchor_uid[struct_no] = row["block_uid"]
                        recent_struct_anchor_uid = row["block_uid"]
                    elif not (is_toc_row or is_toc_page) and recent_struct_anchor_uid:
                        parent_uid = recent_struct_anchor_uid
            else:
                derived_by = "meta"
        
        prev_uid = rows[i - 1]["block_uid"] if i > 0 else None
        next_uid = rows[i + 1]["block_uid"] if i + 1 < len(rows) else None
        explain_uid, explain_type, exp_conf, exp_by = derive_explain_target(rows, i)
        
        row_page_idx = int(row["page_idx"])
        if block_type in ("paragraph", "list"):
            if explain_uid and explain_type == "equation":
                active_equation_explain_uid = explain_uid
                active_equation_explain_page_idx = row_page_idx
                parent_uid = explain_uid
                attach_explanation_to_group(row["block_uid"])
            elif (
                active_equation_explain_uid
                and active_equation_explain_page_idx == row_page_idx
                and is_equation_explain_continuation(text)
            ):
                explain_uid = active_equation_explain_uid
                explain_type = "equation"
                exp_conf = max(exp_conf, 0.72)
                exp_by = "rule"
                parent_uid = active_equation_explain_uid
                attach_explanation_to_group(row["block_uid"])
            elif is_equation_explain_continuation(text):
                recent_equation_uid = find_recent_equation_uid(rows, i)
                if recent_equation_uid:
                    active_equation_explain_uid = recent_equation_uid
                    active_equation_explain_page_idx = row_page_idx
                    explain_uid = recent_equation_uid
                    explain_type = "equation"
                    exp_conf = max(exp_conf, 0.76)
                    exp_by = "rule"
                    parent_uid = recent_equation_uid
                    attach_explanation_to_group(row["block_uid"])
                else:
                    active_equation_explain_uid = None
                    active_equation_explain_page_idx = None
            else:
                active_equation_explain_uid = None
                active_equation_explain_page_idx = None
        elif block_type in ("equation_interline", "title", "table", "image", "page_header", "page_number"):
            active_equation_explain_uid = None
            active_equation_explain_page_idx = None
            if block_type == "equation_interline":
                formula_group.append(row["block_uid"])
            else:
                formula_group = []
        
        if exp_conf > confidence:
            confidence = exp_conf
        if exp_by != "none":
            derived_by = "rule"
        
        if derived_level is None and parent_uid:
            parent_level = derived_level_by_uid.get(parent_uid)
            if parent_level is not None:
                derived_level = parent_level + 1
        
        page_width = float(row["page_width"] or 0.0)
        page_height = float(row["page_height"] or 0.0)
        ax1 = float(row["bbox_abs_x1"])
        ay1 = float(row["bbox_abs_y1"])
        ax2 = float(row["bbox_abs_x2"])
        ay2 = float(row["bbox_abs_y2"])
        
        use_1000_scale = page_width > 0 and page_height > 0 and (ax2 > page_width * 1.2 or ay2 > page_height * 1.2)
        if use_1000_scale:
            nx1 = ax1 / 1000.0
            ny1 = ay1 / 1000.0
            nx2 = ax2 / 1000.0
            ny2 = ay2 / 1000.0
            bbox_source = "mixed_1000"
        else:
            nx1 = (ax1 / page_width) if page_width else None
            ny1 = (ay1 / page_height) if page_height else None
            nx2 = (ax2 / page_width) if page_width else None
            ny2 = (ay2 / page_height) if page_height else None
            bbox_source = "mixed_page"

        row_page_idx = int(row["page_idx"])
        type_recognition_score = _nearest_type_score(
            type_score_map.get(row_page_idx, []), nx1, ny1, nx2, ny2
        )
        text_recognition_score = None
        _row_middle_idx = row.get("middle_idx")
        if _row_middle_idx is not None:
            page_text_scores = text_score_map.get(row_page_idx, [])
            if _row_middle_idx < len(page_text_scores):
                text_recognition_score = page_text_scores[_row_middle_idx]
        
        if derived_level is not None:
            derived_level_by_uid[row["block_uid"]] = int(derived_level)
        
        prev_uid = rows[i - 1]["block_uid"] if i > 0 else None
        next_uid = rows[i + 1]["block_uid"] if i + 1 < len(rows) else None
        
        image_path = None
        table_html = None
        math_content = None
        table_type = None
        math_type = None
        if isinstance(content, dict):
            image_source = content.get("image_source")
            if isinstance(image_source, dict):
                p = image_source.get("path")
                if isinstance(p, str):
                    image_path = p
            table_html = content.get("html") if isinstance(content.get("html"), str) else None
            table_type = content.get("table_type") if isinstance(content.get("table_type"), str) else None
            math_content = content.get("math_content") if isinstance(content.get("math_content"), str) else None
            math_type = content.get("math_type") if isinstance(content.get("math_type"), str) else None

        caption_text = None
        footnote_text = None
        if block_type in ("table", "image") and isinstance(content, dict):
            caption_key = "table_caption" if block_type == "table" else "image_caption"
            footnote_key = "table_footnote" if block_type == "table" else "image_footnote"
            caption_text = extract_media_fragment_text(content.get(caption_key)) or None
            footnote_text = extract_media_fragment_text(content.get(footnote_key)) or None

        related_refs = collect_media_related_block_refs(row, rows)
        caption_block_uids = related_refs.get("caption_block_uids", [])
        footnote_block_uids = related_refs.get("footnote_block_uids", [])
        caption_bboxes = extract_media_bbox_list(row.get("caption_bboxes"))
        footnote_bboxes = extract_media_bbox_list(row.get("footnote_bboxes"))
        
        derived_row = {
            "block_uid": row["block_uid"],
            "page_seq": int(row["page_idx"]) + 1,
            "sub_type": content.get("list_type") if isinstance(content, dict) else None,
            "bbox_norm_x1": nx1,
            "bbox_norm_y1": ny1,
            "bbox_norm_x2": nx2,
            "bbox_norm_y2": ny2,
            "bbox_source": bbox_source,
            "raw_title_level": raw_level if isinstance(raw_level, int) else None,
            "derived_title_level": derived_level,
            "title_path": title_path,
            "parent_block_uid": parent_uid,
            "prev_block_uid": prev_uid,
            "next_block_uid": next_uid,
            "explain_for_block_uid": explain_uid,
            "explain_type": explain_type,
            "table_type": table_type,
            "table_nest_level": content.get("table_nest_level") if isinstance(content, dict) else None,
            "table_html": table_html,
            "math_type": math_type,
            "math_content": math_content,
            "image_path": image_path,
            "caption_block_uid": caption_block_uids[0] if len(caption_block_uids) == 1 else None,
            "caption_block_uids": caption_block_uids or None,
            "caption_bboxes": caption_bboxes or None,
            "footnote_block_uid": footnote_block_uids[0] if len(footnote_block_uids) == 1 else None,
            "footnote_block_uids": footnote_block_uids or None,
            "footnote_bboxes": footnote_bboxes or None,
            "quality_score": None,
            "derived_confidence": confidence,
            "derived_by": derived_by,
            "derive_version": derive_version,
            "parser_version": parser_version,
            "updated_at": ts,
        }
        derived_rows.append(derived_row)
        
        if block_type not in excluded_types:
            if block_type == "list" and not text.strip():
                pass
            else:
                node = {
                    "id": row["block_uid"],
                    "block_uid": row["block_uid"],
                    "block_type": block_type,
                    "page_idx": row["page_idx"],
                    "block_seq": row["block_seq"],
                    "plain_text": text,
                    "bbox": [nx1, ny1, nx2, ny2] if all(v is not None for v in [nx1, ny1, nx2, ny2]) else None,
                    "bbox_source": bbox_source,
                    "derived_level": derived_level,
                    "title_path": title_path,
                    "parent_uid": parent_uid,
                    "derived_by": derived_by,
                    "confidence": confidence,
                    "type_recognition_score": type_recognition_score,
                    "text_recognition_score": text_recognition_score,
                    "image_path": image_path,
                    "table_html": table_html,
                    "math_content": math_content,
                    "caption_block_uid": caption_block_uids[0] if len(caption_block_uids) == 1 else None,
                    "caption_block_uids": caption_block_uids or None,
                    "caption_bboxes": caption_bboxes or None,
                    "caption": caption_text,
                    "footnote_block_uid": footnote_block_uids[0] if len(footnote_block_uids) == 1 else None,
                    "footnote_block_uids": footnote_block_uids or None,
                    "footnote_bboxes": footnote_bboxes or None,
                    "footnote": footnote_text,
                    "table_header_bbox": row.get("table_header_bbox"),
                    "equation_number_bbox": row.get("equation_number_bbox"),
                    "content_json": row.get("content_json"),
                    "page_width": row.get("page_width"),
                    "page_height": row.get("page_height"),
                    "page_bboxes": row.get("page_bboxes"),
                    "merged_from": row.get("merged_from"),
                }
                nodes.append(node)
                node_by_uid[row["block_uid"]] = node
                
                index_row = {
                    "block_uid": row["block_uid"],
                    "block_type": block_type,
                    "page_idx": row["page_idx"],
                    "block_seq": row["block_seq"],
                    "plain_text": text[:500] if text else "",
                    "derived_level": derived_level,
                    "title_path": title_path,
                    "parent_uid": parent_uid,
                    "caption_block_uid": caption_block_uids[0] if len(caption_block_uids) == 1 else None,
                    "caption_block_uids": caption_block_uids or None,
                    "caption_bboxes": caption_bboxes or None,
                    "footnote_block_uid": footnote_block_uids[0] if len(footnote_block_uids) == 1 else None,
                    "footnote_block_uids": footnote_block_uids or None,
                    "footnote_bboxes": footnote_bboxes or None,
                }
                index_rows.append(index_row)
    
    included_uids: set[str] = {n["block_uid"] for n in nodes}
    
    for node in nodes:
        uid = node["block_uid"]
        parent_uid = node.get("parent_uid")
        if parent_uid and parent_uid in included_uids:
            edges.append({
                "id": f"s-parent-{uid}",
                "from": parent_uid,
                "to": uid,
                "kind": "strong",
                "label": "parent",
                "color": "#1d4ed8"
            })
        
        prev_uid = None
        next_uid = None
        for j, r in enumerate(rows):
            if r["block_uid"] == uid:
                if j > 0:
                    prev_uid = rows[j - 1]["block_uid"]
                if j + 1 < len(rows):
                    next_uid = rows[j + 1]["block_uid"]
                break
        
        if prev_uid and prev_uid in included_uids:
            edges.append({
                "id": f"w-prev-{uid}",
                "from": prev_uid,
                "to": uid,
                "kind": "weak",
                "label": "prev_next",
                "color": "#6b7280"
            })
        
        explain_uid = node.get("explain_for_uid")
        if explain_uid and explain_uid in included_uids:
            edges.append({
                "id": f"w-exp-{uid}",
                "from": uid,
                "to": explain_uid,
                "kind": "weak",
                "label": node.get("explain_type") or "explain",
                "color": "#b45309"
            })
    
    stats = {
        "total_blocks": len(rows),
        "nodes_count": len(nodes),
        "edges_count": len(edges),
        "index_rows_count": len(index_rows),
        # 标题 LLM 复核由 solo2json 在建块后、落 jsonl 前调用 title_level_refiner 承担
        # （见 solo2json._review_title_levels_with_llm）；本引擎只产规则层级。
        "llm_status": "disabled",
        "derive_version": derive_version,
        "parser_version": parser_version,
        "toc_pages": list(toc_pages),
        "title_candidates": len([row for row in rows if row.get("block_type") == "title"]),
        "continuation_merges": continuation_merges,
    }
    
    return StructuredResult(
        nodes=nodes,
        edges=edges,
        index_rows=index_rows,
        stats=stats
    )

__all__ = [
    "StructuredResult",
    "build_structured_from_rawfiles",
    "collect_media_related_block_refs",
]
