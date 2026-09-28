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

# 对比图形态（2026-09-28 定版）：一根主柱（AnGIneer 紫，logo 色系）+ 两根浅色系论文基线柱，
# 紧贴成组、共享同一坐标轴——这是对比图，不是三根独立柱。
# (图例, 值%, 颜色)
BARS = [
    ("AnGIneer 全链（87/150 · DeepEval 判分）", 58.0, "#8b5cf6"),
    ("论文现实 RAG 最优档（GPT-4-Turbo 单库 · 人工复核）", 50.0, "#9dc3e6"),
    ("论文 8 配置汇总（人工复核）", 47.0, "#a9d9be"),
]


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
    width = 0.22
    positions = [(i - 1) * (width + 0.02) for i in range(len(BARS))]
    for pos, (label, value, color) in zip(positions, BARS):
        ax.bar(pos, value, width=width, zorder=3, color=color, label=label)
        ax.annotate(f"{value}%", (pos, value), ha="center", va="bottom",
                    fontsize=11.5, fontweight="bold")
    # 头条差距标注：AnGIneer vs 现实 RAG 最优档
    x0, x1 = positions[0], positions[1]
    ax.plot([x0, x1], [61.5, 61.5], color="#666666", lw=1.0, zorder=4)
    ax.annotate("+8pp", ((x0 + x1) / 2, 61.5), ha="center", va="bottom",
                fontsize=10.5, color="#444444")
    ax.set_xticks([0.0])
    ax.set_xticklabels(["FinanceBench 官方 150 题 · 84 篇 SEC PDF 自管线入库"], fontsize=11)
    ax.set_xlim(-0.45, 0.45)
    ax.set_ylim(0, 70)
    ax.set_ylabel("%", fontsize=11)
    ax.set_title("FinanceBench 跨域旁证 · AnGIneer 全链 vs 论文公开基线（arXiv 2311.11944 Table 1）· 判分口径并列标注",
                 fontsize=12.5)
    ax.legend(loc="upper right", frameon=False, fontsize=10)
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
