"""PoPo/Solo 块对齐器（Phase 6 spike 固化，纯新增不改既有行为）。

确定性重放 middle.json 的 PoPo 过滤规则（直接复用 popo 仓库的
``map_mineru_label`` / ``extract_block_content``，避免重新实现漂移），枚举幸存者
后建立 ``source_id {doc_id}:{k} ↔ (page_idx, i)`` 映射；再对 enriched_blocks.json
逐块做三重校验（page_idx 一致 + 归一化 bbox IoU≈1 + 归一化文本相等），
任一配对失败即整篇降级为"无 PoPo 信号"（调用方记 warning，Solo 照常独立跑通）。

Solo 侧锚定约定：``block_uid = {doc_id}:{page_idx}:{i}``（i 为页内 1-based 位置），
与 middle.json ``pdf_info[page_idx].para_blocks[i-1]`` 逐位对应。
"""

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from popo.post_processing.label_normalization import (
    SKIP_TYPE,
    extract_block_content,
    map_mineru_label,
    normalize_bbox_to_unit,
)


def normalize_compare_text(text: Any) -> str:
    """对齐比较用归一化文本：折叠全部空白（OCR 行内间距差异容忍）。"""
    return re.sub(r"\s+", "", str(text or "")).strip()


def _iou(box_a: Any, box_b: Any) -> float:
    """两个归一化 [x0, y0, x1, y1] 框的 IoU。"""
    if not isinstance(box_a, (list, tuple)) or len(box_a) < 4:
        return 0.0
    if not isinstance(box_b, (list, tuple)) or len(box_b) < 4:
        return 0.0
    ax0, ay0, ax1, ay1 = (float(value or 0.0) for value in box_a[:4])
    bx0, by0, bx1, by1 = (float(value or 0.0) for value in box_b[:4])
    ix0, iy0 = max(ax0, bx0), max(ay0, by0)
    ix1, iy1 = min(ax1, bx1), min(ay1, by1)
    inter_w = max(0.0, ix1 - ix0)
    inter_h = max(0.0, iy1 - iy0)
    inter = inter_w * inter_h
    area_a = max(0.0, ax1 - ax0) * max(0.0, ay1 - ay0)
    area_b = max(0.0, bx1 - bx0) * max(0.0, by1 - by0)
    union = area_a + area_b - inter
    return inter / union if union > 0 else 0.0


def replay_popo_filter(
    middle_data: Dict[str, Any],
) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    """按序重放 PoPo ``_read_middle`` 过滤规则。

    Returns (survivors, skipped)：
    - survivors：按 (page_idx, para_index) 序保留的块，第 k 个幸存者 ↔ source_id {doc_id}:{k}
    - skipped：被过滤的块（SKIP_TYPE / 空 text|title|caption），含过滤原因
    """
    survivors: List[Dict[str, Any]] = []
    skipped: List[Dict[str, Any]] = []
    for page in middle_data.get("pdf_info", []):
        page_idx = int(page.get("page_idx", 0))
        page_size = page.get("page_size") or [None, None]
        page_width = page_size[0] if len(page_size) > 0 else None
        page_height = page_size[1] if len(page_size) > 1 else None
        for para_index, item in enumerate(page.get("para_blocks", [])):
            canonical, popo_type = map_mineru_label(str(item.get("type", "text")))
            reason: Optional[str] = None
            if popo_type == SKIP_TYPE:
                reason = "skip_type"
            content = extract_block_content(item)
            if not content and canonical in {"text", "title", "caption"}:
                reason = "empty"
            if reason is not None:
                skipped.append({
                    "page_idx": page_idx,
                    "para_index": para_index,
                    "type": str(item.get("type", "")),
                    "reason": reason,
                    "content": str(content or ""),
                })
                continue
            survivors.append({
                "page_idx": page_idx,
                "para_index": para_index,
                "order": len(survivors),
                "bbox_unit": normalize_bbox_to_unit(
                    item.get("bbox", [0, 0, 0, 0]),
                    page_width,
                    page_height,
                ),
                "content": str(content or ""),
                "content_norm": normalize_compare_text(content),
                "type": canonical,
                "popo_type": popo_type,
            })
    return survivors, skipped


@dataclass
class AlignmentResult:
    """对齐结果：映射表 + 逐对三重校验 + 降级判定。"""

    doc_id: str
    pairs: List[Dict[str, Any]] = field(default_factory=list)
    mapping: Dict[str, Tuple[int, int]] = field(default_factory=dict)
    solo_block_uid_map: Dict[str, str] = field(default_factory=dict)
    skipped_middle: List[Dict[str, Any]] = field(default_factory=list)
    status: str = "aligned"
    reasons: List[str] = field(default_factory=list)

    @property
    def degraded(self) -> bool:
        return self.status != "aligned"


def align_popo_blocks(
    doc_id: str,
    middle_data: Dict[str, Any],
    enriched_blocks: List[Dict[str, Any]],
) -> AlignmentResult:
    """middle.json + enriched_blocks.json → 映射表 + 三重校验报告。"""
    survivors, skipped = replay_popo_filter(middle_data)
    result = AlignmentResult(doc_id=doc_id, skipped_middle=skipped)

    if len(enriched_blocks) != len(survivors):
        result.reasons.append(
            f"块数不一致：enriched={len(enriched_blocks)} survivors={len(survivors)}"
        )

    for index, survivor in enumerate(survivors):
        source_id = f"{doc_id}:{index}"
        page_idx, solo_i = survivor["page_idx"], survivor["para_index"] + 1
        result.mapping[source_id] = (page_idx, solo_i)
        result.solo_block_uid_map[source_id] = f"{doc_id}:{page_idx}:{solo_i}"

    for index, enriched in enumerate(enriched_blocks):
        source_id = f"{doc_id}:{index}"
        survivor = survivors[index] if index < len(survivors) else None
        checks: Dict[str, Any] = {
            "source_id_ok": str(enriched.get("source_id") or "") == source_id,
            "page_ok": False,
            "bbox_iou": 0.0,
            "text_ok": False,
        }
        if survivor is not None:
            checks["page_ok"] = (int(enriched.get("page", 1)) - 1) == survivor["page_idx"]
            checks["bbox_iou"] = round(_iou(enriched.get("bbox"), survivor["bbox_unit"]), 4)
            if survivor["type"] == "table":
                # 表格内容为 HTML，两侧序列化可能不同（旧数据可能为空串）；
                # 对齐只依赖 page + bbox，不做文本比对。
                checks["text_ok"] = True
            else:
                checks["text_ok"] = normalize_compare_text(enriched.get("content") or "") == survivor["content_norm"]
        passed = (
            survivor is not None
            and checks["source_id_ok"]
            and checks["page_ok"]
            and checks["bbox_iou"] >= 0.95
            and checks["text_ok"]
        )
        if not passed:
            result.reasons.append(
                f"{source_id} 校验失败: {checks}"
            )
        result.pairs.append({
            "source_id": source_id,
            "order": index,
            "page_idx": survivor["page_idx"] if survivor else None,
            "solo_i": survivor["para_index"] + 1 if survivor else None,
            "checks": checks,
            "passed": passed,
        })

    if result.reasons:
        result.status = "degraded"
    return result


def align_document(
    doc_id: str,
    middle_path: Path,
    enriched_path: Path,
) -> AlignmentResult:
    """从磁盘读取 middle.json + enriched_blocks.json 并对齐。"""
    middle_data = json.loads(Path(middle_path).read_text(encoding="utf-8"))
    enriched = json.loads(Path(enriched_path).read_text(encoding="utf-8"))
    return align_popo_blocks(doc_id, middle_data, enriched)


__all__ = [
    "AlignmentResult",
    "align_document",
    "align_popo_blocks",
    "normalize_compare_text",
    "replay_popo_filter",
]
