"""结构层解析评测 CLI：拿 pipeline 的 doc_blocks_graph.jsonl 与 OmniDocBench GT 对齐打分。

与 `run_omnidocbench_eval.py` 的分工：
- run_omnidocbench_eval.py：官方 markdown 口径（predict 出 content.md → 官方镜像评分），
  量的是"markdown 交付面"，需要 18GB 镜像；
- 本脚本：结构层口径（直接比 bbox/类目/表格 HTML/块序），量的是 RAG 检索真正吃的那层，
  **不需要镜像、不需要 GPU、不重跑解析**（读已落盘的 jsonl）。

用法：
  python scripts/eval_parse_structure.py \
      --gt D:/AI/tools/OmniDocBench_data/OmniDocBench.json \
      --state data/evals/omnidocbench/predictions_eval200/state.json \
      --library-dir data/knowledge_base/libraries/omnidocbench/documents \
      --out data/evals/omnidocbench/result_jsonl200

输出：控制台总览 + <out>/structure_result.json（全量明细）+ <out>/structure_report.md（报告）。
"""
import argparse
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "services" / "evals-core" / "src"))

from evals_core.parse_eval.corpus import render_report, run_eval  # noqa: E402

DEFAULT_GT = Path("D:/AI/tools/OmniDocBench_data/OmniDocBench.json")
DEFAULT_LIBRARY = REPO / "data" / "knowledge_base" / "libraries" / "omnidocbench" / "documents"


def main() -> int:
    parser = argparse.ArgumentParser(description="结构层解析评测（jsonl 口径，无需镜像）")
    parser.add_argument("--gt", default=str(DEFAULT_GT), help="OmniDocBench.json 路径")
    parser.add_argument("--state", default="", help="predict 产物的 state.json（page_id → doc_id）")
    parser.add_argument("--library-dir", default=str(DEFAULT_LIBRARY), help="documents 目录（内含 <doc_id>/parsed/doc_blocks_graph.jsonl）")
    parser.add_argument("--out", default=str(REPO / "data" / "evals" / "omnidocbench" / "result_jsonl"), help="输出目录")
    parser.add_argument("--iou-min", type=float, default=0.3, help="几何匹配 IoU 阈值")
    parser.add_argument("--pred-source", choices=["chain", "mineru"], default="chain",
                        help="块来源：chain=我们的 doc_blocks_graph.jsonl（默认）；mineru=MinerU 原生 content_list")
    parser.add_argument("--filter-prefix", default="", help="只评文件名以该前缀开头的页")
    parser.add_argument("--limit", type=int, default=0, help="最多评多少页（0=全部）")
    args = parser.parse_args()

    gt_json = Path(args.gt)
    if not gt_json.exists():
        raise SystemExit(f"GT 不存在: {gt_json}")
    library_dir = Path(args.library_dir)
    if not library_dir.exists():
        raise SystemExit(f"产物库不存在: {library_dir}")

    result = run_eval(
        gt_json=gt_json,
        state_json=Path(args.state) if args.state else None,
        library_dir=library_dir,
        iou_min=args.iou_min,
        page_prefix=args.filter_prefix,
        limit=args.limit,
        pred_source=args.pred_source,
    )

    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "structure_result.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=1), encoding="utf-8"
    )
    report = render_report(result)
    (out_dir / "structure_report.md").write_text(report, encoding="utf-8")

    overall = result["overall"]
    fmt = lambda v, pct=False: "—" if v is None else (f"{v * 100:.1f}%" if pct else f"{v:.4f}")
    print(f"评测页数: {result['meta']['pages_evaluated']}（块来源: {result['meta'].get('pred_source')}）")
    print(f"块召回率: {fmt(overall['block_recall'], pct=True)}  命中 {overall['matched']}/{overall['gt_blocks']}")
    print(f"预测块被解释率: {fmt(overall['pred_used_ratio'], pct=True)}  ({overall['pred_blocks_used']}/{overall['pred_blocks_scored']})")
    print(f"块文本相似度: 全部 {fmt(overall['text_similarity'])} / 命中项 {fmt(overall['text_similarity_matched'])} (n={overall['text_n_matched']})")
    print(f"表格 TEDS: {fmt(overall['teds'])} (n={overall['teds_n']})")
    print(f"公式相似度: {fmt(overall['formula_similarity'])} (n={overall['formula_n']})")
    print(f"阅读顺序: 相邻对正确率 {fmt(overall['order_adjacent_accuracy'], pct=True)} / Kendall tau {fmt(overall['order_kendall_tau'])}")
    print("\n按类目（召回率 / 文本相似度命中项）：")
    for c in result["by_category"]:
        print(
            f"  {c['category']:20} {fmt(c['recall'], pct=True):>7}  "
            f"文本 {fmt(c['text_similarity_matched']):>7}  TEDS {fmt(c['teds']):>7}  GT块={c['gt_blocks']}"
        )
    print(f"\n报告: {out_dir / 'structure_report.md'}")
    print(f"明细: {out_dir / 'structure_result.json'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
