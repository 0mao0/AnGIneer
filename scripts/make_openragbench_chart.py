"""Open RAG Bench v4 基线图（README 回答成绩小节用图）：分层着色 + 按层排序。

数据 = 2026-09-24 钉住的 nightly v4 门禁基线（1040 题/188 篇，DeepEval 判分），
与 docs/README 的数字一一对应；柱序按「检索层 → 答题层 → 拒答层」排列，
让「检索不是瓶颈、拒答才是主要失分项」的读数顺序自明。

用法：
  python scripts/make_openragbench_chart.py [--out docs/images/openragbench-baseline.png]
"""
import argparse
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]

# (标签, 值%, 分母注记, 层)
BARS = [
    ("检索 hit@5(doc)", 96.5, "", "检索层"),
    ("引用命中", 92.1, "", "检索层"),
    ("可答题正确率", 88.6, "(1001)", "答题层"),
    ("整体正确率", 84.9, "(883/1040)", "答题层"),
    ("拒答正确率", 56.4, "(22/39)", "拒答层"),
]
LAYER_COLOR = {"检索层": "#4a90e2", "答题层": "#2fa870", "拒答层": "#e28743"}
LAYER_LEGEND = {"检索层": "检索层", "答题层": "答题层", "拒答层": "拒答层（当前主要失分项）"}


def main() -> int:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    plt.rcParams["font.sans-serif"] = ["Microsoft YaHei", "SimHei"]
    plt.rcParams["axes.unicode_minus"] = False

    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--out", default=str(REPO / "docs" / "images" / "openragbench-baseline.png"))
    args = ap.parse_args()

    fig, ax = plt.subplots(figsize=(13.2, 6.0), dpi=100)
    xs = range(len(BARS))
    seen = set()
    for x, (label, value, denom, layer) in zip(xs, BARS):
        bar = ax.bar(x, value, width=0.58, color=LAYER_COLOR[layer], zorder=3,
                     label=LAYER_LEGEND[layer] if layer not in seen else None)
        seen.add(layer)
        ax.annotate(f"{value}%", (x, value), ha="center", va="bottom",
                    fontsize=11, fontweight="bold")
        ax.set_xticks(list(xs))
    ax.set_xticklabels([f"{label}\n{denom}" if denom else label for label, _, denom, _ in BARS],
                       fontsize=10.5)
    ax.set_ylim(0, 105)
    ax.set_ylabel("%", fontsize=11)
    ax.set_title("Open RAG Bench v4 基线 · 官方 3045 题分层抽样 1040 题 / 188 篇 · DeepEval 判分（nightly 门禁）",
                 fontsize=12.5)
    ax.legend(loc="lower left", frameon=False, fontsize=10)
    ax.grid(axis="y", alpha=0.25, zorder=0)
    for spine in ("top", "right"):
        ax.spines[spine].set_visible(False)
    fig.tight_layout()
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out)
    print(f"图已生成 → {out}")
    return 0


if __name__ == "__main__":
    import sys

    sys.exit(main())
