"""结构层评测的语料级汇总：逐页评测 → 按类目/文档类型聚合 → 渲染报告。

页与文档的对应关系来自 predict 产物目录的 state.json（page_id → doc_id）；
拿不到时退化用 source/ 目录里的文件名 stem 匹配。
"""
from __future__ import annotations

import json
import statistics
from collections import defaultdict
from pathlib import Path

from evals_core.parse_struct.categories import GT_TO_OURS, UNMAPPED_OURS
from evals_core.parse_struct.mineru_raw import load_mineru_blocks
from evals_core.parse_struct.jsonl_eval import (
    GtBlock,
    PredBlock,
    _edit_distance,
    eval_page,
    load_gt_page,
    load_pred_blocks,
)
from evals_core.parse_struct._vendor.omnidocbench.table_metric import TEDS

_TEDS = TEDS()
_PRED_TYPES_TO_GT = {ours: gt for gt, types in GT_TO_OURS.items() for ours in types}


def _score_text(pred: str, gt: str) -> float | None:
    """归一化编辑距离相似度，分母取两侧较长者 → 恒在 0–1（GT 无文本则不计）。

    分母用 max 而非 GT 长度：我们的块常比 GT 块长（多行公式数组被合成一个块时更明显），
    除以 GT 长度会算出负相似度，报表里没有可读性。
    """
    if not gt:
        return None
    if not pred:
        return 0.0
    return max(0.0, 1.0 - _edit_distance(pred, gt) / max(len(gt), len(pred), 1))


def _as_document(fragment: str) -> str:
    """官方 TEDS 走 `xpath('body/table')`，裸 `<table>` 片段（连自己比自己）都会得 0.0，
    必须包成完整文档才能拿到真实分数（2026-09-12 实测：裸片段 0.0 / 包裹后 1.0）。
    """
    text = (fragment or "").strip()
    if not text or "<html" in text.lower():
        return text
    return f"<html><body>{text}</body></html>"


def _score_teds(pred_html: str, gt_html: str) -> float | None:
    if not gt_html:
        return None
    if not pred_html:
        return 0.0
    try:
        return float(_TEDS.evaluate(_as_document(pred_html), _as_document(gt_html)))
    except Exception:  # noqa: BLE001 — 畸形 HTML 不该中断整批评测
        return 0.0


def _resolve_doc_dir(page_id: str, state: dict, library_dir: Path) -> Path | None:
    doc_id = (state.get(page_id) or {}).get("doc_id")
    if doc_id:
        candidate = library_dir / str(doc_id) / "parsed" / "doc_blocks_graph.jsonl"
        if candidate.exists():
            return candidate
    for src in library_dir.glob("*/source/*"):
        if src.stem == page_id:
            candidate = src.parent.parent / "parsed" / "doc_blocks_graph.jsonl"
            if candidate.exists():
                return candidate
    return None


def _mean(values: list[float]) -> float | None:
    return statistics.fmean(values) if values else None


def run_eval(
    gt_json: Path,
    state_json: Path | None,
    library_dir: Path,
    iou_min: float = 0.3,
    page_prefix: str = "",
    limit: int = 0,
    pred_source: str = "chain",
) -> dict:
    """跑完整个语料，返回可直接序列化的结果字典。"""
    gt_samples = json.loads(gt_json.read_text(encoding="utf-8"))
    state = json.loads(state_json.read_text(encoding="utf-8")) if state_json and state_json.exists() else {}

    pages = []
    for sample in gt_samples:
        page_id, gt_blocks = load_gt_page(sample)
        if page_prefix and not page_id.startswith(page_prefix):
            continue
        if limit and len(pages) >= limit:
            break
        doc_path = _resolve_doc_dir(Path(page_id).stem, state, library_dir)
        if doc_path is None:
            continue
        if pred_source == "mineru":
            raw = doc_path.parent / "mineru_raw" / "content_list.json"
            if not raw.exists():
                continue
            preds = load_mineru_blocks(raw)
        else:
            preds = load_pred_blocks(doc_path)
        result = eval_page(gt_blocks, preds, iou_min=iou_min)
        data_source = ((sample.get("page_info") or {}).get("page_attribute") or {}).get("data_source") or "unknown"
        pages.append(
            {
                "page_id": page_id,
                "doc_id": doc_path.parent.parent.name,
                "data_source": data_source,
                "gt_blocks": gt_blocks,
                "preds": preds,
                "result": result,
            }
        )

    result = _aggregate(pages, iou_min=iou_min, gt_json=gt_json, library_dir=library_dir)
    result["meta"]["pred_source"] = pred_source
    return result


def _aggregate(pages: list[dict], iou_min: float, gt_json: Path, library_dir: Path) -> dict:
    per_category: dict[str, dict] = defaultdict(
        lambda: {"gt": 0, "matched": 0, "text": [], "text_matched": [], "teds": [], "formula": []}
    )
    per_source: dict[str, dict] = defaultdict(
        lambda: {"pages": 0, "gt": 0, "matched": 0, "text": [], "teds": [], "tau": [], "adj": []}
    )
    used_pred = 0
    all_matched_text: list[float] = []
    scored_pred = 0
    taus: list[float] = []
    adjs: list[float] = []
    page_rows = []

    for page in pages:
        rows = page["result"]["rows"]
        used_ids = page["result"]["used"]
        preds: list[PredBlock] = page["preds"]
        scored = [p for p in preds if p.block_type not in UNMAPPED_OURS and p.block_type in _PRED_TYPES_TO_GT]
        scored_pred += len(scored)
        used_pred += sum(1 for p in scored if id(p) in used_ids)
        source = per_source[page["data_source"]]
        source["pages"] += 1
        if page["result"]["order_tau"] is not None:
            taus.append(page["result"]["order_tau"])
            source["tau"].append(page["result"]["order_tau"])
        if page["result"]["order_adjacent"] is not None:
            adjs.append(page["result"]["order_adjacent"])
            source["adj"].append(page["result"]["order_adjacent"])

        page_text, page_teds = [], []
        # 文本/公式按"覆盖分组"评分（组内两侧各自拼接后再比，见 jsonl_eval._build_groups）
        for group in page["result"]["groups"]:
            cat = per_category[group["category"]]
            score = _score_text(group["pred_text"], group["gt_text"])
            if score is None:
                continue
            cat["text"].append(score)
            source["text"].append(score)
            page_text.append(score)
            if group["matched"]:
                cat["text_matched"].append(score)
                all_matched_text.append(score)
            if group["category"] == "equation_isolated":
                cat["formula"].append(score)
        # 命中与表格按 GT 块逐块统计
        for row in rows:
            gt: GtBlock = row["gt"]
            cat = per_category[gt.category]
            cat["gt"] += 1
            source["gt"] += 1
            if row["cands"] == 0:
                continue
            cat["matched"] += 1
            source["matched"] += 1
            if gt.category == "table":
                score = _score_teds(row["teds_cand"].html if row["teds_cand"] else "", gt.html)
                if score is not None:
                    cat["teds"].append(score)
                    source["teds"].append(score)
                    page_teds.append(score)
        page_rows.append(
            {
                "page_id": page["page_id"],
                "data_source": page["data_source"],
                "gt_scored": len(rows),
                "matched": sum(1 for r in rows if r["cands"]),
                "text_mean": _mean(page_text),
                "teds_mean": _mean(page_teds),
                "order_tau": page["result"]["order_tau"],
                "order_adjacent": page["result"]["order_adjacent"],
            }
        )

    total_gt = sum(v["gt"] for v in per_category.values())
    total_matched = sum(v["matched"] for v in per_category.values())
    all_text = [s for v in per_category.values() for s in v["text"]]
    all_teds = [s for v in per_category.values() for s in v["teds"]]
    all_formula = per_category["equation_isolated"]["formula"]

    def _fmt_cat(name: str, v: dict) -> dict:
        return {
            "category": name,
            "gt_blocks": v["gt"],
            "matched": v["matched"],
            "recall": (v["matched"] / v["gt"]) if v["gt"] else None,
            "text_similarity": _mean(v["text"]),
            "text_n": len(v["text"]),
            "text_similarity_matched": _mean(v["text_matched"]),
            "text_n_matched": len(v["text_matched"]),
            "teds": _mean(v["teds"]),
            "teds_n": len(v["teds"]),
            "formula_similarity": _mean(v["formula"]),
        }

    return {
        "meta": {
            "gt_json": str(gt_json),
            "library_dir": str(library_dir),
            "pages_evaluated": len(pages),
            "pages_missing_doc": len(json.loads(gt_json.read_text(encoding="utf-8"))) - len(pages),
            "iou_min": iou_min,
            "metric_scope": "结构层自定义口径（块级几何对齐），非 OmniDocBench 官方分数",
        },
        "overall": {
            "gt_blocks": total_gt,
            "matched": total_matched,
            "block_recall": (total_matched / total_gt) if total_gt else None,
            "pred_blocks_scored": scored_pred,
            "pred_blocks_used": used_pred,
            "pred_used_ratio": (used_pred / scored_pred) if scored_pred else None,
            "text_similarity": _mean(all_text),
            "text_n": len(all_text),
            "text_similarity_matched": _mean(all_matched_text),
            "text_n_matched": len(all_matched_text),
            "teds": _mean(all_teds),
            "teds_n": len(all_teds),
            "formula_similarity": _mean(all_formula),
            "formula_n": len(all_formula),
            "order_adjacent_accuracy": _mean(adjs),
            "order_kendall_tau": _mean(taus),
            "order_pages": len(adjs),
        },
        "by_category": [_fmt_cat(k, v) for k, v in sorted(per_category.items(), key=lambda kv: -kv[1]["gt"])],
        "by_data_source": [
            {
                "data_source": k,
                "pages": v["pages"],
                "gt_blocks": v["gt"],
                "block_recall": (v["matched"] / v["gt"]) if v["gt"] else None,
                "text_similarity": _mean(v["text"]),
                "teds": _mean(v["teds"]),
                "order_adjacent_accuracy": _mean(v["adj"]),
                "order_kendall_tau": _mean(v["tau"]),
            }
            for k, v in sorted(per_source.items(), key=lambda kv: -kv[1]["pages"])
        ],
        "pages": page_rows,
    }


def render_report(result: dict) -> str:
    """把结果渲染成 markdown 报告。"""
    meta, overall = result["meta"], result["overall"]
    pct = lambda v: "—" if v is None else f"{v * 100:.1f}%"
    num = lambda v: "—" if v is None else f"{v:.4f}"

    lines = [
        "# 结构层解析评测报告（jsonl 口径）",
        "",
        f"- GT：`{meta['gt_json']}`",
        f"- 产物库：`{meta['library_dir']}`",
        f"- 评测页数：{meta['pages_evaluated']}（GT 中无对应产物的页：{max(0, meta['pages_missing_doc'])}）",
        f"- 匹配阈值：IoU ≥ {meta['iou_min']} 或预测块中心落在 GT 框内",
        f"- 口径说明：{meta['metric_scope']}",
        "",
        "## 总览",
        "",
        "| 指标 | 值 | 说明 |",
        "| --- | --- | --- |",
        f"| 块召回率 | {pct(overall['block_recall'])} | GT 待评块 {overall['gt_blocks']} 个中被覆盖比例 |",
        f"| 块命中数 | {overall['matched']} | |",
        f"| 预测块被解释率 | {pct(overall['pred_used_ratio'])} | 我们 {overall['pred_blocks_scored']} 个可评块中参与匹配的比例（低=多出块） |",
        f"| 块文本相似度（全部） | {num(overall['text_similarity'])} | 漏检块按 0 计入，n={overall['text_n']} |",
        f"| 块文本相似度（命中项） | {num(overall['text_similarity_matched'])} | 只看匹配上的块＝识别质量，n={overall['text_n_matched']} |",
        f"| 表格 TEDS | {num(overall['teds'])} | HTML↔HTML 直接算，n={overall['teds_n']} |",
        f"| 公式相似度 | {num(overall['formula_similarity'])} | LaTeX 去风格化串比对（**非 CDM**；多行数组表示约定差异会压低），n={overall['formula_n']} |",
        f"| 阅读顺序相邻对正确率 | {pct(overall['order_adjacent_accuracy'])} | 相邻 GT 块顺序一致比例，{overall['order_pages']} 页 |",
        f"| 阅读顺序 Kendall tau | {num(overall['order_kendall_tau'])} | |",
        "",
        "## 按类目",
        "",
        "| GT 类目 | GT 块数 | 命中 | 召回率 | 文本相似度(命中项) | 表格 TEDS | 公式相似度 |",
        "| --- | --- | --- | --- | --- | --- | --- |",
    ]
    for c in result["by_category"]:
        lines.append(
            f"| {c['category']} | {c['gt_blocks']} | {c['matched']} | {pct(c['recall'])} | "
            f"{num(c['text_similarity_matched'])} (n={c['text_n_matched']}) | {num(c['teds'])} | {num(c['formula_similarity'])} |"
        )
    lines += [
        "",
        "## 按文档类型",
        "",
        "| data_source | 页数 | GT 块 | 召回率 | 文本相似度 | 表格 TEDS | 顺序相邻对 |",
        "| --- | --- | --- | --- | --- | --- | --- |",
    ]
    for s in result["by_data_source"]:
        lines.append(
            f"| {s['data_source']} | {s['pages']} | {s['gt_blocks']} | {pct(s['block_recall'])} | "
            f"{num(s['text_similarity'])} | {num(s['teds'])} | {pct(s['order_adjacent_accuracy'])} |"
        )
    return "\n".join(lines) + "\n"
