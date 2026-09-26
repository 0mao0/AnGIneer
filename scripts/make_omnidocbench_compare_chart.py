"""A① 三方同尺对比图 + 1000 页现行基线成绩单（README 首页用图）。

数据源 = 各方官方评测产物目录（predictions_quick_match_metric_result.json），
经 parse_regression.load_official_metrics 扁平化；Edit_dist 转 `1−x` 百分制、
TEDS/CDM 原值百分制——六个指标统一"越高越好"。基线图另读 struct_chain.json
的 A② 结构层指标（蓝柱，自建口径，与 A① 官方口径颜色区分）。

用法（默认路径即 2026-09-26 1000 页基线的产物目录）：
  python scripts/make_omnidocbench_compare_chart.py
  # 可选：--ours/--mineru/--ref <官方产物目录> --struct <struct_chain.json>
  #       --title-suffix "1000 页 / seed=42" --out <png> --baseline-out <png>
"""
import argparse
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "services" / "evals-core" / "src"))

from evals_core.parse_regression import load_official_metrics  # noqa: E402

# (标签, 键, 是否 Edit_dist 转百分制)
METRICS = [
    ("文本准确度", "text_edit", True),
    ("表格 TEDS", "table_teds", False),
    ("表内文字准确度", "table_edit", True),
    ("公式 CDM", "formula_cdm", False),
    ("公式准确度", "formula_edit", True),
    ("阅读顺序准确度", "order_edit", True),
]
SERIES = [  # (图例, 默认产物目录, 颜色)
    ("参考模型 mu936-GRPO", REPO.parent / "omnidocbench_dl" / "ref_result_1000", "#a6a6a6"),
    ("MinerU 3.4.5 单独", REPO.parent / "omnidocbench_dl" / "mineru_only_result_1000", "#4a90e2"),
    ("AnGIneer 全链", REPO / "data" / "evals" / "parse_regression" / "20260926-1305" / "official", "#2fa870"),
]


def to_score(metrics: dict, key: str, invert: bool) -> float | None:
    v = metrics.get(key)
    if v is None:
        return None
    return (1.0 - v if invert else v) * 100.0


def make_baseline_chart(struct_metrics: dict, official: dict, out: Path, title_suffix: str) -> None:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    plt.rcParams["font.sans-serif"] = ["Microsoft YaHei", "SimHei"]
    plt.rcParams["axes.unicode_minus"] = False

    # (标签, 值, 颜色)：绿=A① 官方 markdown 口径；蓝=A② 结构层（自建口径）
    bars = [(label, to_score(official, key, inv), "#2fa870") for label, key, inv in METRICS]
    struct_bars = [
        ("块召回率", struct_metrics.get("block_recall"), "#4a90e2"),
        ("块文本相似度\n（命中项）", struct_metrics.get("text_similarity_matched"), "#4a90e2"),
    ]
    bars += [(label, v * 100.0 if v is not None else None, c) for label, v, c in struct_bars]

    fig, ax = plt.subplots(figsize=(13.0, 6.0), dpi=100)
    for i, (label, score, color) in enumerate(bars):
        if score is None:
            continue
        rect = ax.bar(i, score, width=0.62, color=color, zorder=3)[0]
        ax.annotate(f"{score:.1f}", (rect.get_x() + rect.get_width() / 2, score),
                    ha="center", va="bottom", fontsize=10)
    ax.set_xticks(range(len(bars)))
    ax.set_xticklabels([b[0] for b in bars], fontsize=10)
    ax.set_ylim(70, 100)
    ax.set_ylabel("得分（越高越好）", fontsize=11)
    ax.set_title(f"文档解析现行基线 · {title_suffix}（绿=A① 官方 markdown 口径，蓝=A② 结构层自建口径）",
                 fontsize=12.5)
    ax.grid(axis="y", alpha=0.25, zorder=0)
    for spine in ("top", "right"):
        ax.spines[spine].set_visible(False)
    fig.tight_layout()
    out.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out)
    print(f"基线图已生成 → {out}")


def main() -> int:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    plt.rcParams["font.sans-serif"] = ["Microsoft YaHei", "SimHei"]
    plt.rcParams["axes.unicode_minus"] = False

    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--ours", default=str(SERIES[2][1]))
    ap.add_argument("--mineru", default=str(SERIES[1][1]))
    ap.add_argument("--ref", default=str(SERIES[0][1]))
    ap.add_argument("--title-suffix", default="1000 页 / seed=42")
    ap.add_argument("--out", default=str(REPO / "docs" / "images" / "omnidocbench-compare.png"))
    ap.add_argument("--struct", default=str(REPO / "data" / "evals" / "parse_regression" / "20260926-1305" / "struct_chain.json"))
    ap.add_argument("--baseline-out", default=str(REPO / "docs" / "images" / "omnidocbench-baseline-1000.png"))
    args = ap.parse_args()

    dirs = {"ref": Path(args.ref), "mineru": Path(args.mineru), "ours": Path(args.ours)}
    series = [
        (SERIES[0][0], dirs["ref"], SERIES[0][2]),
        (SERIES[1][0], dirs["mineru"], SERIES[1][2]),
        (SERIES[2][0], dirs["ours"], SERIES[2][2]),
    ]
    data, missing = [], []
    for label, d, color in series:
        m = load_official_metrics(d)
        scores = [to_score(m, k, inv) for _, k, inv in METRICS]
        if all(s is None for s in scores):
            missing.append(f"{label}（{d}）")
        data.append((label, scores, color))
    if missing:
        print("!! 缺官方产物，对应系列将为空：", "; ".join(missing))

    fig, ax = plt.subplots(figsize=(13.8, 6.2), dpi=100)
    width, gap = 0.26, 0.0
    xs = range(len(METRICS))
    for i, (label, scores, color) in enumerate(data):
        pos = [x + (i - 1) * (width + gap) for x in xs]
        vals = [s if s is not None else 0 for s in scores]
        bars = ax.bar(pos, vals, width=width, label=label, color=color, zorder=3)
        for rect, s in zip(bars, scores):
            if s is not None:
                ax.annotate(f"{s:.1f}", (rect.get_x() + rect.get_width() / 2, s),
                            ha="center", va="bottom", fontsize=9)
    ax.set_xticks(list(xs))
    ax.set_xticklabels([label for label, _, _ in METRICS], fontsize=11)
    ax.set_ylim(70, 100)
    ax.set_ylabel("得分（越高越好）", fontsize=11)
    ax.set_title(f"OmniDocBench v1.6 markdown 口径 · {args.title_suffix} 同尺对比"
                 f"（Edit_dist 已转 1−x 百分制）", fontsize=13)
    ax.legend(loc="lower left", ncol=3, frameon=False, fontsize=10)
    ax.grid(axis="y", alpha=0.25, zorder=0)
    for spine in ("top", "right"):
        ax.spines[spine].set_visible(False)
    fig.tight_layout()
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out)
    print(f"图已生成 → {out}")
    for (label, _, _), (_, scores, _) in zip(series, data):
        printable = " / ".join("—" if s is None else f"{s:.2f}" for s in scores)
        print(f"  {label}: {printable}")

    from evals_core.parse_regression import load_structure_metrics
    struct_path = Path(args.struct)
    struct_metrics = load_structure_metrics(struct_path) if struct_path.is_file() else {}
    if struct_metrics:
        ours_metrics = load_official_metrics(dirs["ours"])
        make_baseline_chart(struct_metrics, ours_metrics, Path(args.baseline_out), args.title_suffix)
    else:
        print(f"!! 跳过基线图：struct_chain.json 不存在或无指标（{struct_path}）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
