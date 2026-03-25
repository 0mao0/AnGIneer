"""
MinerU 结构化数据生成器 - A1 结构结果对象生成

核心算法：
- 无限深度层级推断
- 编号段落提升
- 公式解释连续下挂
- parent/title_path/explain_for 推断

输出：A1结构结果对象（nodes, edges, index_rows, stats）
"""
import datetime as dt
import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple, TYPE_CHECKING

if TYPE_CHECKING:
    from angineer_core.infra.llm_client import LLMClient


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
    if block_type == "page_number":
        return collect_from_spans(content.get("page_number_content"))
    if block_type == "list":
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
        candidate_text = normalize_match_text(str(candidate.get("plain_text") or candidate.get("text") or "").strip())
        if not candidate_text:
            continue
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


def load_raw(raw_dir: Path) -> tuple[list[list[dict[str, Any]]], dict[int, tuple[float, float]], str, dict[str, Any], Any]:
    """读取解析结果并返回内容、页面尺寸、解析器版本与原始 model 数据。"""
    content_list_path = raw_dir / "content_list_v2.json"
    layout_path = raw_dir / "layout.json"
    model_path = raw_dir / "model.json"
    
    if not content_list_path.exists():
        return [], {}, "", {}, []
    
    parsed_blocks = read_json(content_list_path)
    parser_version = ""
    page_size_map: dict[int, tuple[float, float]] = {}
    layout_payload: dict[str, Any] = {}
    model_payload: Any = []
    
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
    
    return parsed_blocks, page_size_map, parser_version, layout_payload, model_payload


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
    """判断是否为公式说明连续段。"""
    txt = (text or "").strip()
    if not txt:
        return False
    if re.match(r"^\d+(?:\.\d+)*", txt):
        return False
    if txt.startswith(("式中", "其中", "注")):
        return True
    return re.match(r"^[A-Za-zΑ-Ωα-ω][A-Za-z0-9_{}()\\\-]*\s*[—\-–=:：]", txt) is not None


def derive_explain_target(rows: list[Any], idx: int) -> tuple[str | None, str | None, float, str]:
    """为说明性段落回溯关联公式或图表目标。"""
    current = rows[idx]
    if current["block_type"] != "paragraph":
        return None, None, 0.0, "none"
    txt = (current["plain_text"] or "").strip()
    if not txt:
        return None, None, 0.0, "none"
    trigger = txt.startswith("式中") or txt.startswith("其中") or txt.startswith("注")
    if not trigger:
        return None, None, 0.0, "none"
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


def llm_refine_title_levels(
    title_items: list[dict[str, Any]],
    llm_client: Optional["LLMClient"] = None
) -> tuple[dict[str, tuple[int, float]], str]:
    """用LLM细化标题层级并返回状态。"""
    if not llm_client:
        return {}, "not_configured"
    
    if not title_items:
        return {}, "ok"
    
    mini_items: list[dict[str, Any]] = []
    for item in title_items:
        mini_items.append({
            "block_uid": item["block_uid"],
            "text": item["plain_text"][:160],
            "rule_level": item.get("rule_level"),
        })
    
    system_prompt = (
        "你是文档结构分析器。根据标题文本的编号层级判断标题级别(>=1，不限制上限)。"
        "如果是目录项也按编号层级判断。仅返回JSON对象："
        '{"items":[{"block_uid":"...","level":1,"confidence":0.95}]}'
    )
    user_prompt = json.dumps({"items": mini_items}, ensure_ascii=False)
    
    try:
        result_text = llm_client.chat(
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt}
            ],
            temperature=0.0
        )
        
        result = json.loads(result_text)
        arr = result.get("items") if isinstance(result, dict) else result
        refined: dict[str, tuple[int, float]] = {}
        
        if isinstance(arr, list):
            for item in arr:
                if not isinstance(item, dict):
                    continue
                uid = item.get("block_uid")
                level = item.get("level")
                conf = item.get("confidence", 0.8)
                if isinstance(uid, str) and isinstance(level, int) and level >= 1:
                    c = float(conf) if isinstance(conf, (int, float)) else 0.8
                    c = max(0.0, min(1.0, c))
                    refined[uid] = (level, c)
        
        if refined:
            return refined, "ok"
        return {}, "empty_result"
        
    except Exception as e:
        return {}, f"error:{str(e)[:50]}"


@dataclass
class BlockNode:
    """块节点数据结构。"""
    id: str
    block_uid: str
    block_type: str
    page_idx: int
    block_seq: int
    plain_text: str = ""
    content_json: dict = field(default_factory=dict)
    bbox: tuple[float, float, float, float] = (0.0, 0.0, 0.0, 0.0)
    page_width: float = 0.0
    page_height: float = 0.0
    derived_level: int | None = None
    title_path: str | None = None
    parent_uid: str | None = None
    prev_uid: str | None = None
    next_uid: str | None = None
    explain_for_uid: str | None = None
    explain_type: str | None = None
    derived_by: str = "none"
    confidence: float = 0.0
    image_path: str | None = None
    table_html: str | None = None
    math_content: str | None = None
    caption_block_uids: List[str] = field(default_factory=list)
    footnote_block_uids: List[str] = field(default_factory=list)


@dataclass
class GraphEdge:
    """图边数据结构。"""
    id: str
    from_uid: str
    to_uid: str
    kind: str
    label: str
    color: str = "#6b7280"


@dataclass
class IndexRow:
    """索引行数据结构。"""
    block_uid: str
    block_type: str
    page_idx: int
    block_seq: int
    plain_text: str
    derived_level: int | None
    title_path: str | None
    parent_uid: str | None
    caption_block_uids: List[str] = field(default_factory=list)
    footnote_block_uids: List[str] = field(default_factory=list)


@dataclass
class A1StructureResult:
    """A1结构结果对象。"""
    nodes: List[Dict[str, Any]] = field(default_factory=list)
    edges: List[Dict[str, Any]] = field(default_factory=list)
    index_rows: List[Dict[str, Any]] = field(default_factory=list)
    stats: Dict[str, Any] = field(default_factory=dict)


def build_graph_from_mineru(
    parsed_dir: Path,
    doc_id: str,
    doc_name: str = "",
    llm_client: Optional["LLMClient"] = None,
    options: Optional[Dict[str, Any]] = None
) -> A1StructureResult:
    """
    从 MinerU 解析结果构建 A1 结构对象。
    
    Args:
        parsed_dir: 解析结果目录，应包含 mineru_raw/ 子目录
        doc_id: 文档ID
        doc_name: 文档名称
        llm_client: 可选的 LLM 客户端，用于标题层级细化
        options: 可选配置项
            - use_llm: 是否使用 LLM 细化 (默认 True)
            - derive_version: 推导版本标识
    
    Returns:
        A1StructureResult: 包含 nodes, edges, index_rows, stats
    """
    opts = options or {}
    use_llm = opts.get("use_llm", True)
    derive_version = opts.get("derive_version", "v1")
    
    raw_dir = parsed_dir / "mineru_raw"
    if not raw_dir.exists():
        raw_dir = parsed_dir
    
    parsed_blocks, page_size_map, parser_version, layout_payload, model_payload = load_raw(raw_dir)
    layout_candidates = build_layout_candidates(layout_payload)
    model_media_candidates = build_model_media_candidate_map(model_payload)
    
    if not parsed_blocks:
        return A1StructureResult(stats={"error": "no_parsed_blocks", "raw_dir": str(raw_dir)})
    
    ts = now_iso()
    rows: list[dict[str, Any]] = []
    block_seq_global = 0
    
    for page_idx, page_blocks in enumerate(parsed_blocks):
        if not isinstance(page_blocks, list):
            continue
        page_width, page_height = page_size_map.get(page_idx, (0.0, 0.0))
        page_layout_candidates = layout_candidates.get(page_idx, [])
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
                    })
                continue
            
            block_seq_global += 1
            block_uid = f"{doc_id}:{page_idx}:{i}"
            plain_text = extract_plain_text(block_type, content)
            media_bbox_info = enrich_media_content_bboxes(
                block_type,
                content,
                model_media_candidates.get(page_idx, []),
                page_aligned_media_bboxes.get(i)
            )
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
            })
    
    title_candidates: list[dict[str, Any]] = []
    for row in rows:
        if row["block_type"] != "title":
            continue
        content = row["content_json"]
        raw_level = content.get("level") if isinstance(content, dict) else None
        rule_level, _, _ = infer_title_level(row["plain_text"] or "", raw_level)
        title_candidates.append({
            "block_uid": row["block_uid"],
            "plain_text": row["plain_text"] or "",
            "rule_level": rule_level
        })
    
    llm_levels: dict[str, tuple[int, float]] = {}
    llm_status = "disabled"
    if use_llm and llm_client and title_candidates:
        llm_levels, llm_status = llm_refine_title_levels(title_candidates, llm_client)
    
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
    
    nodes: list[dict[str, Any]] = []
    edges: list[dict[str, Any]] = []
    index_rows: list[dict[str, Any]] = []
    derived_rows: list[dict[str, Any]] = []
    
    excluded_types = {"page_header", "page_number"}
    
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
            llm_pred = llm_levels.get(row["block_uid"])
            if llm_pred is not None:
                llm_level, llm_conf = llm_pred
                if derived_level is None or llm_conf >= confidence:
                    derived_level = llm_level
                    confidence = llm_conf
                    derived_by = "llm" if by in ("none", "raw") else "rule+llm"
            
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
        if block_type == "paragraph":
            if explain_uid and explain_type == "equation":
                active_equation_explain_uid = explain_uid
                active_equation_explain_page_idx = row_page_idx
                parent_uid = explain_uid
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
            else:
                active_equation_explain_uid = None
                active_equation_explain_page_idx = None
        elif block_type in ("equation_interline", "title", "table", "image", "page_header", "page_number"):
            active_equation_explain_uid = None
            active_equation_explain_page_idx = None
        
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
                    "image_path": image_path,
                    "table_html": table_html,
                    "math_content": math_content,
                    "caption_block_uid": caption_block_uids[0] if len(caption_block_uids) == 1 else None,
                    "caption_block_uids": caption_block_uids or None,
                    "caption_bboxes": caption_bboxes or None,
                    "footnote_block_uid": footnote_block_uids[0] if len(footnote_block_uids) == 1 else None,
                    "footnote_block_uids": footnote_block_uids or None,
                    "footnote_bboxes": footnote_bboxes or None,
                }
                nodes.append(node)
                
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
        "llm_status": llm_status,
        "derive_version": derive_version,
        "parser_version": parser_version,
        "toc_pages": list(toc_pages),
        "title_candidates": len(title_candidates),
        "base_rows": rows,
        "derived_rows": derived_rows,
    }
    
    return A1StructureResult(
        nodes=nodes,
        edges=edges,
        index_rows=index_rows,
        stats=stats
    )


class MinerUStructureBuilder:
    """
    负责将 MinerU 的原始输出 (model.json, layout.json, content_list.json)
    转换为标准化的 mineru_blocks.json 结构。
    
    算法核心 (A/B/C 融合):
    - Source A (model.json): 提供核心文本、段落结构、基础 bbox。
    - Source B (layout.json): 提供页面尺寸、精细 bbox (图片/表格)。
    - Source C (content_list.json): 提供逻辑目录树 (Level Hierarchy)。
    """

    def __init__(self):
        self.highlight_excluded_types = {'page_header', 'header', 'page_number'}

    def build(
        self,
        model_data: Optional[Dict[str, Any]] = None,
        layout_data: Optional[Dict[str, Any]] = None,
        content_list_data: Optional[Dict[str, Any]] = None,
        other_json_data: Optional[List[Dict[str, Any]]] = None
    ) -> List[Dict[str, Any]]:
        """
        主入口：构建标准化 blocks。
        如果提供了 model/layout/content_list，则使用 A/B/C 融合算法。
        否则 (兼容旧逻辑)，从 other_json_data 中提取并合并。
        """
        if model_data or layout_data:
            return self._build_from_abc(model_data, layout_data, content_list_data)
        
        if other_json_data:
            raw_blocks = []
            for payload in other_json_data:
                source = payload.get('__source_file__', 'unknown.json')
                raw_blocks.extend(self._extract_blocks_from_payload(payload, source))
            return self._finalize_blocks(raw_blocks)
            
        return []

    def _build_from_abc(
        self,
        model_data: Optional[Dict[str, Any]],
        layout_data: Optional[Dict[str, Any]],
        content_list_data: Optional[Dict[str, Any]]
    ) -> List[Dict[str, Any]]:
        """A/B/C 融合算法实现"""
        
        page_dimensions: Dict[int, Dict[str, float]] = {}
        
        if layout_data:
            pages = []
            if isinstance(layout_data, dict):
                if 'pdf_info' in layout_data:
                    pages = layout_data['pdf_info']
                elif 'page_info' in layout_data:
                    pages = layout_data['page_info']
            elif isinstance(layout_data, list):
                pages = layout_data

            for idx, page in enumerate(pages):
                w = self._read_first_numeric(page, ['width', 'w', 'page_width'])
                h = self._read_first_numeric(page, ['height', 'h', 'page_height'])
                
                if w is None or h is None:
                    blocks = page.get('para_blocks') or page.get('blocks') or []
                    max_x, max_y = 0.0, 0.0
                    for b in blocks:
                        bbox = self._normalize_bbox(b)
                        if bbox:
                            max_x = max(max_x, bbox[2])
                            max_y = max(max_y, bbox[3])
                    if max_x > 0 and max_y > 0:
                        w, h = max_x + 50, max_y + 50
                
                if w and h:
                    page_dimensions[idx] = {'width': w, 'height': h}

        raw_blocks = []
        if model_data:
            pages_data = []
            if isinstance(model_data, list):
                pages_data = model_data
            elif isinstance(model_data, dict) and 'model' in model_data:
                pages_data = model_data['model']
            
            for page_idx, page_content in enumerate(pages_data):
                if isinstance(page_content, list):
                    for block in page_content:
                        extracted = self._process_model_block(block, page_idx)
                        raw_blocks.extend(extracted)
                elif isinstance(page_content, dict):
                    blocks = page_content.get('blocks', [])
                    for block in blocks:
                        extracted = self._process_model_block(block, page_idx)
                        raw_blocks.extend(extracted)

        toc_map: Dict[str, int] = {}
        if content_list_data:
            toc_items = []
            if isinstance(content_list_data, list):
                toc_items = content_list_data
            elif isinstance(content_list_data, dict):
                toc_items = content_list_data.get('content_list', [])
            
            flat_toc = []
            if toc_items and isinstance(toc_items[0], list):
                 for page_items in toc_items:
                     flat_toc.extend(page_items)
            else:
                flat_toc = toc_items

            for item in flat_toc:
                level = item.get('level') or item.get('text_level')
                if level is None and isinstance(item.get('content'), dict):
                    level = item['content'].get('level')
                
                text = self._resolve_block_text(item)
                if level is not None and text:
                     toc_map[text.strip()] = int(level)

        for block in raw_blocks:
            text = block.get('text', '').strip()
            if text in toc_map:
                block['level'] = toc_map[text]
                block['type'] = 'title'
            
            p_idx = block.get('page_idx', 0)
            if p_idx in page_dimensions:
                if 'page_width' not in block:
                    block['page_width'] = page_dimensions[p_idx]['width']
                if 'page_height' not in block:
                    block['page_height'] = page_dimensions[p_idx]['height']

        self._build_hierarchy(raw_blocks)

        return self._finalize_blocks(raw_blocks)

    def _assign_category_code(self, block: Dict[str, Any]) -> None:
        """根据 type 分配 0/X/T/F/E 类别标记"""
        btype = block.get('type', 'paragraph')
        
        if btype in ('title', 'header', 'page_header', 'section_header') or block.get('level') is not None:
            block['category_code'] = 'T'
            return
            
        if btype in ('table', 'figure', 'image', 'equation', 'formula', 'chart'):
            block['category_code'] = 'F'
            return
            
        block['category_code'] = 'E'

    def _process_model_block(self, block_data: Dict[str, Any], page_idx: int) -> List[Dict[str, Any]]:
        """处理 model.json 中的单个 block，可能展开为多个 (如 list_items)"""
        results = []
        
        base_block = {
            'id': self._generate_id(),
            'page_idx': page_idx,
            'type': self._normalize_block_type(block_data.get('type')),
            'bbox': self._normalize_bbox(block_data),
            'text': '',
            'content': block_data.get('content')
        }
        
        content = block_data.get('content')
        
        if isinstance(content, str):
            base_block['text'] = content
            results.append(base_block)
            return results

        if isinstance(content, dict):
            if 'title_content' in content:
                fragments = []
                for item in content['title_content']:
                     if isinstance(item, dict) and 'content' in item:
                         fragments.append(item['content'])
                base_block['text'] = ' '.join(fragments)
                if 'level' in content:
                    base_block['level'] = content['level']
                results.append(base_block)
                return results

            if 'paragraph_content' in content:
                fragments = []
                for item in content['paragraph_content']:
                     if isinstance(item, dict) and 'content' in item:
                         fragments.append(item['content'])
                base_block['text'] = ' '.join(fragments)
                results.append(base_block)
                return results

            if 'list_items' in content:
                list_block = base_block.copy()
                list_block['type'] = 'list'
                list_block['text'] = ''
                results.append(list_block)
                
                for item in content['list_items']:
                    item_text = ''
                    if isinstance(item, str):
                        item_text = item
                    elif isinstance(item, dict):
                        ic = item.get('item_content')
                        if isinstance(ic, list):
                            frags = [f.get('content', '') for f in ic if isinstance(f, dict)]
                            item_text = ' '.join(frags)
                        elif isinstance(ic, str):
                            item_text = ic
                    
                    if item_text:
                        item_block = {
                            'id': self._generate_id(),
                            'page_idx': page_idx,
                            'type': 'list_item',
                            'bbox': list_block['bbox'],
                            'text': item_text,
                            'parent_id': list_block['id']
                        }
                        results.append(item_block)
                return results

            if 'html' in content:
                base_block['type'] = 'table'
                base_block['html'] = content['html']
                base_block['text'] = content.get('text', '')
                results.append(base_block)
                return results

        base_block['text'] = self._resolve_block_text(block_data)
        results.append(base_block)
        return results

    def _generate_id(self) -> str:
        import uuid
        return str(uuid.uuid4())

    def _build_hierarchy(self, blocks: List[Dict[str, Any]]) -> None:
        if not blocks:
            return

        pages: Dict[int, List[Dict[str, Any]]] = {}
        for block in blocks:
            page = block.get('page_idx', 0)
            if page not in pages:
                pages[page] = []
            pages[page].append(block)
            block['children'] = []

        for page_idx, page_blocks in pages.items():
            def get_area(b):
                bbox = b.get('bbox')
                if not bbox or len(bbox) < 4:
                    return 0
                return (bbox[2] - bbox[0]) * (bbox[3] - bbox[1])

            sorted_blocks = sorted(page_blocks, key=get_area)

            for i, child in enumerate(sorted_blocks):
                child_bbox = child.get('bbox')
                if not child_bbox or len(child_bbox) < 4:
                    continue
                
                child_area = get_area(child)
                if child_area <= 0:
                    continue

                for parent in sorted_blocks[i+1:]:
                    parent_bbox = parent.get('bbox')
                    if not parent_bbox or len(parent_bbox) < 4:
                        continue
                    
                    is_contained = (
                        parent_bbox[0] <= child_bbox[0] + 0.01 and
                        parent_bbox[1] <= child_bbox[1] + 0.01 and
                        parent_bbox[2] >= child_bbox[2] - 0.01 and
                        parent_bbox[3] >= child_bbox[3] - 0.01
                    )
                    
                    if is_contained:
                        child['parent_id'] = parent['id']
                        if 'children' not in parent:
                            parent['children'] = []
                        parent['children'].append(child['id'])
                        break

    def _read_first_numeric(self, payload: Dict[str, Any], keys: List[str]) -> Optional[float]:
        for key in keys:
            value = payload.get(key)
            if isinstance(value, (int, float)):
                return float(value)
            if isinstance(value, str):
                stripped = value.strip()
                if not stripped:
                    continue
                try:
                    return float(stripped)
                except Exception:
                    continue
        return None

    def _resolve_block_text(self, payload: Dict[str, Any]) -> str:
        text_candidates: List[str] = []
        direct_text = payload.get('text')
        if isinstance(direct_text, str) and direct_text.strip():
            text_candidates.append(direct_text.strip())
        content = payload.get('content')
        if isinstance(content, str) and content.strip():
            text_candidates.append(content.strip())
        if isinstance(content, dict):
            for key in ('text', 'content', 'value'):
                value = content.get(key)
                if isinstance(value, str) and value.strip():
                    text_candidates.append(value.strip())
            for list_key in ('title_content', 'paragraph_content', 'list_content'):
                value = content.get(list_key)
                if isinstance(value, list):
                    fragments = []
                    for item in value:
                        if isinstance(item, dict):
                            piece = item.get('content')
                            if isinstance(piece, str) and piece.strip():
                                fragments.append(piece.strip())
                    if fragments:
                        text_candidates.append(' '.join(fragments))
            
            list_items = content.get('list_items')
            if isinstance(list_items, list):
                list_fragments = []
                for item in list_items:
                    if not isinstance(item, dict):
                        continue
                    item_content = item.get('item_content')
                    if isinstance(item_content, str) and item_content.strip():
                        list_fragments.append(item_content.strip())
                    elif isinstance(item_content, list):
                        for sub in item_content:
                            if isinstance(sub, dict):
                                piece = sub.get('content')
                                if isinstance(piece, str) and piece.strip():
                                    list_fragments.append(piece.strip())
                if list_fragments:
                    text_candidates.append(' '.join(list_fragments))
        for key in ('text_content', 'title', 'heading'):
            value = payload.get(key)
            if isinstance(value, str) and value.strip():
                text_candidates.append(value.strip())
        return text_candidates[0] if text_candidates else ''

    def _normalize_block_type(self, raw_type: str) -> str:
        if not raw_type:
            return 'paragraph'
        normalized = raw_type.strip().lower()
        mapping = {
            'text': 'paragraph',
            'header': 'page_header',
            'interline_equation': 'equation_interline'
        }
        return mapping.get(normalized, normalized)

    def _source_priority(self, source_file: str) -> int:
        normalized = (source_file or '').lower()
        if normalized.endswith('_model.json') or '_model.json' in normalized:
            return 0
        if normalized.endswith('layout.json'):
            return 1
        if 'content_list_v2.json' in normalized:
            return 2
        if normalized.endswith('_content_list.json') or '_content_list.json' in normalized:
            return 3
        return 4

    def _normalize_bbox(self, payload: Dict[str, Any]) -> Optional[List[float]]:
        for key in ('bbox', 'rect', 'box', 'pdf_bbox', 'pdf_rect'):
            value = payload.get(key)
            if isinstance(value, (list, tuple)) and len(value) >= 4:
                coords: List[float] = []
                valid = True
                for item in value[:4]:
                    if isinstance(item, (int, float)):
                        coords.append(float(item))
                    elif isinstance(item, str):
                        stripped = item.strip()
                        if not stripped:
                            valid = False
                            break
                        try:
                            coords.append(float(stripped))
                        except Exception:
                            valid = False
                            break
                    else:
                        valid = False
                        break
                if valid:
                    return coords
        return None

    def _extract_blocks_from_payload(self, payload: Dict[str, Any], source_file: str) -> List[Dict[str, Any]]:
        return []

    def _finalize_blocks(self, raw_blocks: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        finalized = []
        for idx, block in enumerate(raw_blocks):
            normalized = self._normalize_block_for_output(block, idx)
            if normalized:
                self._assign_category_code(normalized)
                finalized.append(normalized)
        return finalized

    def _normalize_block_for_output(self, payload: Dict[str, Any], index: int) -> Optional[Dict[str, Any]]:
        raw_type = str(payload.get('type') or '').strip()
        normalized_type = self._normalize_block_type(raw_type)
        if not normalized_type or normalized_type in self.highlight_excluded_types:
            return None
        bbox = self._normalize_bbox(payload)
        if not bbox:
            return None
        page = self._read_first_numeric(payload, ['page', 'page_no', 'pageNo'])
        page_idx = self._read_first_numeric(payload, ['page_idx', 'page_index'])
        if page is None and page_idx is None:
            return None
        if page is None and page_idx is not None:
            page_idx_int = max(0, int(round(page_idx)))
            page_int = page_idx_int + 1
        elif page is not None and page_idx is None:
            page_int = max(1, int(round(page)))
            page_idx_int = page_int - 1
        else:
            page_int = max(1, int(round(page or 1)))
            page_idx_int = max(0, int(round(page_idx or 0)))
        block_id = payload.get('id')
        if not isinstance(block_id, str) or not block_id.strip():
            block_id = f'mineru-block-{index}'
        
        return {
            'id': block_id,
            'type': normalized_type,
            'page': page_int,
            'page_idx': page_idx_int,
            'bbox': bbox,
            'text': self._resolve_block_text(payload),
            'level': payload.get('level'),
            'content': payload.get('content'),
            'parent_id': payload.get('parent_id'),
            'children': payload.get('children', [])
        }
