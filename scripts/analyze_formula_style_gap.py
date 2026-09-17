"""P0 公式口径排查：我们的公式 Edit_dist 差在哪（风格 vs 内容）。

背景（2026-09-17 一键入口首次跑）：A① 公式 Edit_dist 我们 0.1119 vs MinerU 0.0976、
参考模型 0.0687，但 A② 公式相似度两边**完全同分**（67.21%，同源直通）。
A② 的口径是"去空白/花括号后串比对"，A① 官方口径只去空白与 `$$`/`\\[`，**不动 \\prime 这类记号**
——所以同一批文本在两种口径下结论相反。

本脚本读官方逐样本产物（含 gt / pred / norm_gt / norm_pred / edit / upper_len），
按"差异可归因的模式"统计，估算每类风格的收益，供决定改不改、先改哪个。

用法：
  python scripts/analyze_formula_style_gap.py <official_result.json> [--top 10]
"""
import argparse
import collections
import json
import re

# 候选风格差异（正则 → 紧凑写法）。
# 官方归一化已去掉空白、`\[ \] $$`，并把 `{{x}}` 折成 `{x}`——所以只统计**符号级**差异。
# 模式里的空白用 \s* 容忍：源文本实际是 `^ {\prime}`（有空格）。
STYLE_PATTERNS = {
    r"\^\s*\{\\prime\}": "'",        # ^{\prime} → '（GT 用撇号；我们取 MinerU content_list 原文）
    r"\\ldots": "\\dots",           # \ldots vs \dots
    r"\\cdots": "\\dots",           # \cdots vs \dots
}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("result_json", help="官方 *_display_formula_result.json")
    ap.add_argument("--top", type=int, default=8, help="打印最差样本数")
    args = ap.parse_args()

    records = json.load(open(args.result_json, encoding="utf-8"))
    per_page = collections.defaultdict(list)
    for r in records:
        per_page[r["image_name"]].append(r)

    print(f"公式样本 {len(records)} 个，页 {len(per_page)} 个\n")

    # ① 每个模式：命中多少样本、其中 GT 采用紧凑写法多少、估算对页均值的收益
    for style, compact in STYLE_PATTERNS.items():
        rx = re.compile(style)          # 键本身就是正则（含 \s* 容忍空格）
        hits = gt_hits = 0
        gain = 0.0
        for page, rows in per_page.items():
            d = 0.0
            for r in rows:
                pred, gt = str(r.get("pred") or ""), str(r.get("gt") or "")
                found = rx.findall(pred)
                if not found:
                    continue
                hits += 1
                if compact in gt:
                    gt_hits += 1
                    ul = r.get("upper_len") or 1
                    d += (len(found) * (len(style) - len(compact))) / ul / len(rows)
            gain += d
        print(f"[{style!r} → {compact!r}] 命中样本 {hits}（GT 用紧凑写法的 {gt_hits}）"
              f" → A① 公式 Edit_dist 估算下降 {gain / len(per_page):.4f}")

    # ② 最差样本三方对照（人工核对用）
    print(f"\n=== Edit 最高的 {args.top} 个样本 ===")
    for r in sorted(records, key=lambda r: -float(r.get("edit") or 0))[: args.top]:
        print(f"edit={float(r['edit']):.4f} page={r['image_name'][:40]}")
        print(f"  GT   : {str(r.get('gt'))[:120]}")
        print(f"  PRED : {str(r.get('pred'))[:120]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
