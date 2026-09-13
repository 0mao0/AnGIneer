"""A/B 对比：markdown 投影的表格写法（管道表 vs HTML 表）对官方指标的影响。

只跑有表格的页（改动只影响表格），用官方评测器量，不重跑解析（预测由已落盘的 jsonl 重新投影）。
用法：
  python scripts/ab_markdown_tables.py --state data/evals/omnidocbench/predictions_eval200/state.json \
      --out D:/AI/omnidocbench_dl/ab_tables
"""
import argparse
import json
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "services" / "docs-core" / "src"))
sys.path.insert(0, str(REPO / "services" / "evals-core" / "src"))

from docs_core.step04_structure.shared.markdown_projection import build_faithful_markdown  # noqa: E402
from evals_core.parse_struct.corpus import _resolve_doc_dir  # noqa: E402

DEFAULT_STATE = REPO / "data" / "evals" / "omnidocbench" / "predictions_eval200" / "state.json"
DEFAULT_LIB = REPO / "data" / "knowledge_base" / "libraries" / "omnidocbench" / "documents"
GT_DIR = Path("D:/AI/tools/OmniDocBench_data")


def _load_nodes(doc_path: Path) -> list[dict]:
    return [json.loads(line) for line in doc_path.read_text(encoding="utf-8").splitlines() if line.strip()]


def main() -> int:
    ap = argparse.ArgumentParser(description="表格写法 A/B（管道表 vs HTML 表）")
    ap.add_argument("--state", default=str(DEFAULT_STATE))
    ap.add_argument("--library-dir", default=str(DEFAULT_LIB))
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    state = json.loads(Path(args.state).read_text(encoding="utf-8"))
    lib = Path(args.library_dir)
    out = Path(args.out)
    dirs = {False: out / "pipe", True: out / "html"}
    for d in dirs.values():
        d.mkdir(parents=True, exist_ok=True)

    pages = 0
    for page_id, meta in state.items():
        doc_path = _resolve_doc_dir(page_id, state, lib)
        if doc_path is None:
            continue
        nodes = _load_nodes(doc_path)
        if not any(n.get("block_type") == "table" for n in nodes):
            continue
        pages += 1
        for html_tables, target in dirs.items():
            md, _ = build_faithful_markdown(nodes, build_id="ab", html_tables=html_tables)
            # 预测里不要 build_id 头（评测器会把它当正文，见 run_omnidocbench_eval._strip_build_id_header）
            if md.startswith("<!-- build_id"):
                md = md.split("\n", 1)[1].lstrip("\n")
            (target / f"{page_id}.md").write_text(md, encoding="utf-8")

    print(f"有表格的页: {pages}；已生成两套预测 → {out}/pipe、{out}/html")
    results = {}
    for variant, target in dirs.items():
        res_dir = out / f"result_{'html' if variant else 'pipe'}"
        cmd = [sys.executable, str(REPO / "scripts" / "run_omnidocbench_eval.py"), "eval",
               "--data-dir", str(GT_DIR), "--predictions", str(target), "--out", str(res_dir)]
        print(f"\n=== 评测 {'HTML 表' if variant else '管道表'} ===")
        subprocess.run(cmd, check=False)
        metric = sorted(res_dir.glob("*_metric_result.json"))
        if metric:
            data = json.loads(metric[0].read_text(encoding="utf-8"))
            table = (data.get("table") or {}).get("all") or {}
            results[variant] = {
                "TEDS": (table.get("TEDS") or {}).get("all"),
                "TEDS_structure_only": (table.get("TEDS_structure_only") or {}).get("all"),
                "table_Edit_dist": (table.get("Edit_dist") or {}).get("ALL_page_avg"),
                "text_Edit_dist": (((data.get("text_block") or {}).get("all") or {}).get("Edit_dist") or {}).get("ALL_page_avg"),
            }

    print("\n=== A/B 汇总 ===")
    f = lambda v: "—" if v is None else f"{v:.4f}"
    print(f"{'指标':24}{'管道表':>10}{'HTML 表':>10}{'Δ':>10}")
    for key in ("TEDS", "TEDS_structure_only", "table_Edit_dist", "text_Edit_dist"):
        a, b = (results.get(False) or {}).get(key), (results.get(True) or {}).get(key)
        if a is None and b is None:
            continue
        delta = "—" if (a is None or b is None) else f"{b - a:+.4f}"
        print(f"{key:24}{f(a):>10}{f(b):>10}{delta:>10}")
    (out / "ab_summary.json").write_text(json.dumps(results, ensure_ascii=False, indent=1), encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
