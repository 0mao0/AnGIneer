"""FinanceBench 跨域旁证图（README 回答成绩小节用图）。

数据 = 预注册轮 run-53eabc428c89（docs/plan-financebench-arms.md，2026-09-28 回填）：
官方 150 题、84 篇 SEC PDF 自管线入库，主指标 = judge semantic_passed（DeepEval）。
对照两根柱为论文（arXiv 2311.11944）Table 1 人工复核口径——判分引擎不同，
并列呈现不作同尺判定；85% oracle 档按预注册仅上限引用，不入同图对比。

用法：
  python scripts/make_financebench_chart.py [--out docs/images/financebench-compare.png]
"""
import argparse
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]

# (标签, 值%, 分母注记, 层)
BARS = [
    ("AnGIneer 全链（本文）", 58.0, "(87/150 · DeepEval)", "本仓可复现"),
    ("论文现实 RAG 最优档（GPT-4-Turbo 单库）", 50.0, "(人工复核)", "论文公开基线"),
    ("论文 8 配置汇总", 47.0, "(人工复核)", "论文公开基线"),
]
# 带色彩的网格：每层 = 浅色底 + 同色系深色描边与网纹（自证数据不做系统对比，故不用平涂色块）
LAYER_STYLE = {
    "本仓可复现": ("#d9f0e3", "#1f7a4d", "..."),
    "论文公开基线": ("#dbe8fa", "#2f6bbf", "///"),
}


def main() -> int:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    plt.rcParams["font.sans-serif"] = ["Microsoft YaHei", "SimHei"]
    plt.rcParams["axes.unicode_minus"] = False

    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--out", default=str(REPO / "docs" / "images" / "financebench-compare.png"))
    args = ap.parse_args()

    fig, ax = plt.subplots(figsize=(13.2, 6.0), dpi=100)
    xs = range(len(BARS))
    seen = set()
    for x, (label, value, denom, layer) in zip(xs, BARS):
        face, edge, hatch = LAYER_STYLE[layer]
        ax.bar(x, value, width=0.58, zorder=3,
               facecolor=face, edgecolor=edge, linewidth=1.2, hatch=hatch,
               label=layer if layer not in seen else None)
        seen.add(layer)
        ax.annotate(f"{value}%", (x, value), ha="center", va="bottom",
                    fontsize=11, fontweight="bold")
        ax.set_xticks(list(xs))
    ax.set_xticklabels([f"{label}\n{denom}" if denom else label for label, _, denom, _ in BARS],
                       fontsize=10.5)
    ax.set_ylim(0, 105)
    ax.set_ylabel("%", fontsize=11)
    ax.set_title("FinanceBench 跨域旁证 · SEC 文件 150 官方题 / 84 篇 PDF 自管线入库 · 判分口径并列标注",
                 fontsize=12.5)
    ax.legend(loc="lower left", frameon=False, fontsize=10)
    ax.grid(axis="y", alpha=0.25, zorder=0)
    for spine in ("top", "right"):
        ax.spines[spine].set_visible(False)
    # 判分口径脚注：避免「同尺判定」误读（预注册红线）
    fig.text(0.5, 0.015,
             "本仓 = DeepEval 语义判分；论文柱 = 逐题人工复核——判分方式不同，并列呈现非同一把尺；"
             "oracle（金证据页）85% 为上限参照，未与本柱直接对比。",
             ha="center", fontsize=8.5, color="#666666")
    fig.tight_layout(rect=(0, 0.04, 1, 1))
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out)
    print(f"图已生成 → {out}")
    return 0


if __name__ == "__main__":
    import sys

    sys.exit(main())
