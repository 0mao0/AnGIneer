"""表格内文字差距归因：我们的 table_html vs GT 表格 html 逐格对比。

背景：200 页评测里我们的表格结构 TEDS 0.882（参考模型 0.910，几乎齐平），但表格内文字
Edit_dist 0.5632（参考 0.0682，差 8 倍）。结构与文字的反差说明问题不在"认没认出表格"，
而在单元格层面——可能是错行/错格（内容整体平移），也可能只是写法差异（空白/$/全半角）。

本脚本把每张表解析成网格（复用 step04 的 parse_table_grid，含 rowspan/colspan），逐表分类：
  - dims_diff         行列数不同 → 错行/错格/整表合并的强证据
  - style_only        维度一致，原文差异大但去掉写法差异后一致 → 指标冤枉
  - content_diff      维度一致且去风格后仍不同 → 真实内容差异
  - identical         完全一致

用法：
  python scripts/analyze_table_text_gap.py --state data/evals/omnidocbench/predictions_eval200/state.json \
      --out data/evals/omnidocbench/result_jsonl200/table_gap_analysis.json
"""
import argparse
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "services" / "evals-core" / "src"))
sys.path.insert(0, str(REPO / "services" / "docs-core" / "src"))

from docs_core.step04_structure.shared.table_cells import parse_table_grid  # noqa: E402
from evals_core.parse_eval.corpus import _resolve_doc_dir  # noqa: E402
from evals_core.parse_eval.jsonl_eval import (  # noqa: E402
    _edit_distance,
    eval_page,
    load_gt_page,
    load_pred_blocks,
    norm_latex,
)

DEFAULT_STATE = REPO / "data" / "evals" / "omnidocbench" / "predictions_eval200" / "state.json"
DEFAULT_LIB = REPO / "data" / "knowledge_base" / "libraries" / "omnidocbench" / "documents"
DEFAULT_GT = Path("D:/AI/tools/OmniDocBench_data/OmniDocBench.json")


def _grid_texts(html: str) -> tuple[list[str], int, int]:
    """表格 html → 行主序单元格文本列表 + (行数, 列数)。"""
    parsed = parse_table_grid(html or "")
    cells = parsed.get("cells") or []
    if not cells:
        return [], 0, 0
    rows = max(int(c.get("row") or 0) for c in cells) + 1
    cols = max(int(c.get("col") or 0) for c in cells) + 1
    grid = [["" for _ in range(cols)] for _ in range(rows)]
    for cell in cells:
        r, c = int(cell.get("row") or 0), int(cell.get("col") or 0)
        grid[r][c] = str(cell.get("text") or "")
    return [grid[r][c] for r in range(rows) for c in range(cols)], rows, cols


def _pair_score(gt_cells: list[str], pred_cells: list[str]) -> dict:
    """成对比较：原文相似度、去写法差异相似度（口径见模块 docstring）。"""
    same_len = len(gt_cells) == len(pred_cells)
    if not same_len:  # 网格不同就先按整体拼接比，单元格级逐格比没有意义
        gt_all, pred_all = " ".join(gt_cells), " ".join(pred_cells)
        raw = 1 - _edit_distance(norm_latex(pred_all), norm_latex(gt_all)) / max(len(norm_latex(gt_all)), 1)
        return {"raw_similarity": max(0.0, raw), "style_similarity": None, "n_cells": len(gt_cells)}
    raws, styles = [], []
    for g, p in zip(gt_cells, pred_cells):
        g_norm, p_norm = norm_latex(g), norm_latex(p)
        if not g_norm and not p_norm:
            raws.append(1.0); styles.append(1.0); continue
        raws.append(max(0.0, 1 - _edit_distance(p_norm, g_norm) / max(len(g_norm), len(p_norm), 1)))
        styles.append(raws[-1])
    return {
        "raw_similarity": sum(raws) / len(raws) if raws else None,
        "style_similarity": sum(styles) / len(styles) if styles else None,
        "n_cells": len(gt_cells),
    }


def _classify(rows: int, cols: int, gt_rows: int, gt_cols: int, score: dict) -> str:
    if (rows, cols) != (gt_rows, gt_cols):
        return "dims_diff"
    style = score.get("style_similarity")
    if style is None:
        return "unknown"
    if style >= 0.95:
        return "identical" if (score.get("raw_similarity") or 0) >= 0.95 else "style_only"
    return "content_diff"


def main() -> int:
    ap = argparse.ArgumentParser(description="表格内文字差距归因")
    ap.add_argument("--gt", default=str(DEFAULT_GT))
    ap.add_argument("--state", default=str(DEFAULT_STATE))
    ap.add_argument("--library-dir", default=str(DEFAULT_LIB))
    ap.add_argument("--out", default=str(REPO / "data" / "evals" / "omnidocbench" / "result_jsonl200" / "table_gap_analysis.json"))
    ap.add_argument("--iou-min", type=float, default=0.3)
    args = ap.parse_args()

    state = json.loads(Path(args.state).read_text(encoding="utf-8"))
    lib = Path(args.library_dir)
    samples = json.loads(Path(args.gt).read_text(encoding="utf-8"))

    records = []
    flat_dists = []
    for sample in samples:
        page_id, gt_blocks = load_gt_page(sample)
        doc = _resolve_doc_dir(Path(page_id).stem, state, lib)
        if doc is None:
            continue
        preds = load_pred_blocks(doc)
        result = eval_page(gt_blocks, preds, iou_min=args.iou_min)
        for row in result["rows"]:
            gt = row["gt"]
            if gt.category != "table" or row["cands"] == 0:
                continue
            best = row["teds_cand"]
            gt_cells, gt_rows, gt_cols = _grid_texts(gt.html)
            my_cells, rows, cols = _grid_texts(best.html)
            score = _pair_score(gt_cells, my_cells)
            gt_flat = norm_latex(" ".join(gt_cells))
            my_flat = norm_latex(" ".join(my_cells))
            flat_dist = _edit_distance(my_flat, gt_flat) / max(len(gt_flat), 1)
            flat_dists.append(flat_dist)
            records.append({
                "page_id": page_id,
                "gt_grid": [gt_rows, gt_cols],
                "pred_grid": [rows, cols],
                "gt_cells": len(gt_cells),
                "pred_cells": len(my_cells),
                "flat_edit_dist": flat_dist,
                "verdict": _classify(rows, cols, gt_rows, gt_cols, score),
                **score,
                "gt_head": " | ".join(gt_cells[:8])[:160],
                "pred_head": " | ".join(my_cells[:8])[:160],
            })

    counts: dict[str, int] = {}
    for r in records:
        counts[r["verdict"]] = counts.get(r["verdict"], 0) + 1
    summary = {
        "tables": len(records),
        "verdicts": counts,
        "mean_flat_edit_dist": sum(flat_dists) / len(flat_dists) if flat_dists else None,
        "mean_raw_similarity": sum(r["raw_similarity"] or 0 for r in records) / max(len(records), 1),
    }
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps({"summary": summary, "tables": records}, ensure_ascii=False, indent=1), encoding="utf-8")

    print(f"配对表格数: {summary['tables']}")
    print(f"复算扁平静默编辑距离: {summary['mean_flat_edit_dist']:.4f}（官方口径 0.5632 作对照）")
    print("分类:")
    for k, v in sorted(counts.items(), key=lambda kv: -kv[1]):
        print(f"  {k:14}{v:4d}")
    worst = sorted(records, key=lambda r: -(r["flat_edit_dist"] or 0))[:3]
    for r in worst:
        print(f"\n--- flat_edit_dist={r['flat_edit_dist']:.3f} {r['verdict']} GT网格={r['gt_grid']} 我们网格={r['pred_grid']}  {r['page_id'][:40]}")
        print(f"    GT: {r['gt_head']}")
        print(f"    我们: {r['pred_head']}")
    print(f"\n明细: {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
