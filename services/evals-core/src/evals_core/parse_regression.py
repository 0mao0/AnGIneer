"""A 层解析回归：指标扁平化 / 页集合判定 / Δ 计算 / 归档（口径见 docs/parse-struct-eval.md）。

A 层量的是"解析结果质量"，两个口径并列报（A① 官方 markdown、A② ParseStruct 结构层）。
本模块只做**编排所需的纯逻辑与文件 I/O**：不碰 DB、不碰网络、不调评测器（subprocess 留在
`scripts/run_parse_regression.py`），因此可整体单测。

三件事：
  flatten_*   两种评测器的产物 → "指标名 → 数值"（summary 与 Δ 共用同一套键）
  page_set_*  页集合提取与关系判定（页集合不同的两次分不可比，Δ 的前提）
  compare     与基线逐指标比 Δ；页集合为子集时可按交集重算（标注"非官方重跑口径"）

归档布局（<root> = data/evals/parse_regression，本机 gitignored）：
  <root>/latest.json               最近一次 run 指针
  <root>/baseline.json             钉住的基线指针（人工 --set-baseline 更新）
  <root>/<run_id>/{meta.json,summary.md,struct_chain.json,struct_mineru.json,official/}
"""
import json
import shutil
from pathlib import Path
from typing import Optional

# 越大越好的指标（Δ 的方向标注用）；不在表内的按"越小越好"处理
HIGHER_IS_BETTER = {
    "table_teds", "table_teds_struct", "table_teds_structure_only", "formula_cdm",
    "block_recall", "pred_used_ratio", "text_similarity", "text_similarity_matched",
    "teds", "formula_similarity", "order_adjacent_accuracy", "order_kendall_tau",
}
METRIC_LABELS = {
    "text_edit": "文本 Edit_dist",
    "text_edit_whole": "文本 Edit_dist(整篇)",
    "table_teds": "表格 TEDS",
    "table_teds_struct": "表格 TEDS(仅结构)",
    "table_edit": "表格文字 Edit_dist",
    "formula_edit": "公式 Edit_dist",
    "formula_cdm": "公式 CDM",
    "order_edit": "阅读顺序 Edit_dist",
    "block_recall": "块召回率",
    "pred_used_ratio": "预测块被解释率",
    "text_similarity": "块文本相似度",
    "text_similarity_matched": "块文本相似度(命中项)",
    "teds": "表格 TEDS(A②)",
    "formula_similarity": "公式相似度",
    "order_adjacent_accuracy": "相邻对正确率",
    "order_kendall_tau": "阅读顺序 Kendall tau",
}
# 表格/图表里的固定指标顺序（后端算结论与前端渲染共用同一份）
OFFICIAL_ORDER = ("text_edit", "table_teds", "table_teds_struct", "table_edit",
                  "formula_edit", "formula_cdm", "order_edit")
STRUCT_ORDER = ("block_recall", "pred_used_ratio", "text_similarity_matched", "text_similarity",
                "teds", "formula_similarity", "order_adjacent_accuracy", "order_kendall_tau")
# A① 逐页/逐表产物 → (文件名片段, 取值方式)；用于子集时的交集重算
# 取值方式：mean=该键的值就是数值；teds / teds_structure_only=值本身是 {TEDS, TEDS_structure_only}
OFFICIAL_DETAILS = {
    "text_edit": ("text_block_per_page_edit", "mean"),
    "table_edit": ("table_per_page_edit", "mean"),
    "formula_edit": ("display_formula_per_page_edit", "mean"),
    "order_edit": ("reading_order_per_page_edit", "mean"),
    "formula_cdm": ("display_formula_per_sample_CDM", "mean"),
    "table_teds": ("table_per_table_TEDS", "TEDS"),
    "table_teds_struct": ("table_per_table_TEDS", "TEDS_structure_only"),
}
# 归档时从官方产物目录整包拷走的文件（前缀通配）
OFFICIAL_COPY_GLOBS = (
    "*_metric_result.json", "*_per_page_edit.json", "*_per_table_TEDS.json",
    "*_per_sample_CDM.json", "*_run_summary.json", "*_runtime_environment.json",
    "*_stage_execution.json", "filtered_gt.json", "custom.yaml",
)
_PAGE_EXTS = (".png", ".jpg", ".jpeg", ".pdf", ".PNG", ".JPG", ".JPEG")


def norm_page(name) -> str:
    """页名归一：去图片扩展名（评测器产物带 .png，predict 的 state.json 不带）。"""
    s = str(name or "").strip()
    for ext in _PAGE_EXTS:
        if s.endswith(ext):
            return s[: -len(ext)]
    return s


def _page_of_key(key) -> str:
    """逐页/逐表/逐样本产物的键 → 页名。

    逐表键形如 `page-xxx.png_[0]`（同页多表带序号），逐页键就是 `page-xxx.png`。
    """
    s = str(key or "")
    if s.endswith("]") and "_[" in s:
        s = s.rsplit("_[", 1)[0]
    return norm_page(s)


def _dig(data, *path):
    cur = data
    for key in path:
        if not isinstance(cur, dict):
            return None
        cur = cur.get(key)
    return cur


def _num(value) -> Optional[float]:
    return float(value) if isinstance(value, (int, float)) and not isinstance(value, bool) else None


# ---------------------------------------------------------------- 指标扁平化

def flatten_official(metric_result: dict) -> dict:
    """官方 metric_result.json → 扁平指标（键与 METRIC_LABELS 对齐）。

    真实层级（2026-09-17 照 full_html_result 实测，不是推断）：
      <模块> → "all" → <指标名> → "ALL_page_avg"（edit 类）| "all"（TEDS/CDM）
    模块名：text_block / table / display_formula / reading_order（另有 match_debug 无关）。
    """
    mr = metric_result if isinstance(metric_result, dict) else {}
    raw = {
        "text_edit": _dig(mr, "text_block", "all", "Edit_dist", "ALL_page_avg"),
        "text_edit_whole": _dig(mr, "text_block", "all", "Edit_dist", "edit_whole"),
        "table_teds": _dig(mr, "table", "all", "TEDS", "all"),
        "table_teds_struct": _dig(mr, "table", "all", "TEDS_structure_only", "all"),
        "table_edit": _dig(mr, "table", "all", "Edit_dist", "ALL_page_avg"),
        "formula_edit": _dig(mr, "display_formula", "all", "Edit_dist", "ALL_page_avg"),
        "formula_cdm": _dig(mr, "display_formula", "all", "CDM", "all"),
        "order_edit": _dig(mr, "reading_order", "all", "Edit_dist", "ALL_page_avg"),
    }
    return {k: _num(v) for k, v in raw.items()}


def flatten_structure(result: dict) -> dict:
    """A② structure_result.json → 扁平指标（取 overall）。"""
    o = (result or {}).get("overall") or {}
    keys = ("block_recall", "pred_used_ratio", "text_similarity", "text_similarity_matched",
            "teds", "formula_similarity", "order_adjacent_accuracy", "order_kendall_tau")
    return {k: _num(o.get(k)) for k in keys}


def find_metric_result(official_dir: Path) -> Optional[Path]:
    files = sorted(Path(official_dir).glob("*_metric_result.json"))
    return files[0] if files else None


def load_official_metrics(official_dir: Path) -> dict:
    """官方产物目录 → 扁平指标；目录不存在/无产物时全 None（该步跳过要写明理由）。"""
    path = find_metric_result(official_dir)
    if path is None:
        return flatten_official({})
    try:
        return flatten_official(json.loads(path.read_text(encoding="utf-8")))
    except (OSError, ValueError):
        return flatten_official({})


def load_structure_metrics(result_path: Path) -> dict:
    try:
        return flatten_structure(json.loads(Path(result_path).read_text(encoding="utf-8")))
    except (OSError, ValueError):
        return flatten_structure({})


# ---------------------------------------------------------------- 页集合

def official_page_set(official_dir: Path) -> set:
    """A① 实际参与评分的页集合：逐页/逐表/逐样本产物的键并集（带扩展名，已归一）。"""
    pages = set()
    for _, (frag, _) in OFFICIAL_DETAILS.items():
        for path in Path(official_dir).glob(f"*_{frag}.json"):
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue
            if isinstance(data, dict):
                pages |= {_page_of_key(k) for k in data}
    return pages


def structure_page_set(result: dict) -> set:
    return {norm_page(p.get("page_id")) for p in ((result or {}).get("pages") or []) if p.get("page_id")}


def predict_page_set(state_path: Path) -> set:
    """predict 成功的页（state.json 里 status=done）。"""
    try:
        state = json.loads(Path(state_path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return set()
    return {norm_page(k) for k, v in state.items() if str((v or {}).get("status")) == "done"}


def page_ids_hash(pages) -> str:
    import hashlib

    joined = "\n".join(sorted(str(p) for p in pages))
    return hashlib.sha1(joined.encode("utf-8")).hexdigest()[:12]


def page_set_relation(cur, base) -> dict:
    """页集合关系：equal/subset/superset + 差集明细（少评几页会让分数虚高或虚低）。"""
    cur, base = set(cur), set(base)
    return {
        "equal": cur == base,
        "subset": cur < base,
        "superset": cur > base,
        "cur_count": len(cur), "base_count": len(base),
        "intersection": len(cur & base),
        "cur_only": sorted(cur - base), "base_only": sorted(base - cur),
    }


# ---------------------------------------------------------------- Δ

def compare(cur: dict, base: dict) -> list:
    """逐指标比 Δ；任一侧缺失（None）则不出 Δ（只列数值）。"""
    rows = []
    for key in sorted(set(cur) | set(base)):
        c, b = cur.get(key), base.get(key)
        rows.append({
            "metric": key,
            "label": METRIC_LABELS.get(key, key),
            "cur": c, "base": b,
            "delta": None if (c is None or b is None) else round(c - b, 6),
            "higher_is_better": key in HIGHER_IS_BETTER,
        })
    return rows


def recompute_official_by_intersection(official_dir: Path, pages) -> dict:
    """在给定页集合上重算 A① 指标（逐页/逐表/逐样本算术平均）。

    官方 ALL_page_avg 本就是"有该类内容的页取平均"，因此按交集取平均 ≈ 对该子集重跑官方
    评测器的结果；但毕竟不是重跑，调用方必须标注"非官方重跑口径"（方案 §4.4 第 3 条）。
    """
    want = {norm_page(p) for p in pages}
    out = {}
    for metric, (frag, how) in OFFICIAL_DETAILS.items():
        values = []
        for path in Path(official_dir).glob(f"*_{frag}.json"):
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue
            for key, val in (data.items() if isinstance(data, dict) else []):
                if _page_of_key(key) not in want:
                    continue
                if how == "mean":
                    num = _num(val)
                else:
                    num = _num((val or {}).get(how)) if isinstance(val, dict) else None
                if num is not None:
                    values.append(num)
        out[metric] = round(sum(values) / len(values), 6) if values else None
    return out


# ---------------------------------------------------------------- 归档

def run_id_for(ts: str, tag: str = "") -> str:
    return f"{ts}-{tag}" if tag else ts


def write_json(path: Path, payload) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8")
    return path


def copy_official(official_src: Path, official_dst: Path) -> int:
    """把官方产物原样拷进归档（~2MB）：metric_result + 逐页/逐表明细 + 环境记录。"""
    official_src, official_dst = Path(official_src), Path(official_dst)
    if not official_src.is_dir():
        return 0
    official_dst.mkdir(parents=True, exist_ok=True)
    copied = 0
    for pattern in OFFICIAL_COPY_GLOBS:
        for path in sorted(official_src.glob(pattern)):
            if path.is_file():
                shutil.copy2(path, official_dst / path.name)
                copied += 1
    return copied


def write_pointer(root: Path, name: str, payload: dict) -> Path:
    return write_json(Path(root) / name, payload)


def read_pointer(root: Path, name: str) -> Optional[dict]:
    path = Path(root) / name
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def resolve_baseline(root: Path, spec: str) -> Optional[Path]:
    """基线目录解析：baseline（指针，默认）| latest | none | <run_id> | 目录路径。"""
    root = Path(root)
    spec = (spec or "baseline").strip()
    if spec in ("", "none"):
        return None
    if spec in ("baseline", "latest"):
        pointer = read_pointer(root, f"{spec}.json")
        if not pointer or not pointer.get("dir"):
            return None
        path = root / str(pointer["dir"])
        return path if path.is_dir() else None
    path = Path(spec)
    if path.is_dir():
        return path
    candidate = root / spec
    return candidate if candidate.is_dir() else None


def load_run(run_dir: Path) -> dict:
    """读回一次 run 的归档（meta + 两组指标），供 Δ 使用。"""
    run_dir = Path(run_dir)
    meta = {}
    try:
        meta = json.loads((run_dir / "meta.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        meta = {}
    official = load_official_metrics(run_dir / "official")
    struct_chain = load_structure_metrics(run_dir / "struct_chain.json")
    struct_mineru = load_structure_metrics(run_dir / "struct_mineru.json")
    return {"dir": str(run_dir), "meta": meta, "official": official,
            "struct_chain": struct_chain, "struct_mineru": struct_mineru}


# ---------------------------------------------------------------- summary 渲染

def fmt_metric(value, higher_is_better: bool = False) -> str:
    if value is None:
        return "—"
    if 0 <= value <= 1:
        return f"{value * 100:.2f}%" if higher_is_better else f"{value:.4f}"
    return f"{value:.4f}"


def fmt_delta(row: dict) -> str:
    """Δ 单元格：带符号数值 + 数值方向箭头；方向变差再加 ⚠（语义按指标定，不按箭头猜）。

    分数类指标给 pp，其余给绝对值；edit 类越小越好，所以"↓"是好事、"↑ ⚠"才是回归。
    """
    d = row.get("delta")
    if d is None:
        return "—"
    if d == 0:
        return "0"
    cur = row.get("cur")
    body = f"{d * 100:+.2f}pp" if (cur is not None and 0 <= cur <= 1) else f"{d:+.4f}"
    arrow = "↑" if d > 0 else "↓"
    worse = (d > 0) != bool(row.get("higher_is_better"))
    return f"{body} {arrow}{' ⚠' if worse else ''}"


def render_summary(meta: dict, official: dict, struct_chain: dict, struct_mineru: dict,
                   official_mineru: Optional[dict] = None, official_ref: Optional[dict] = None,
                   delta: Optional[dict] = None, conclusions: Optional[dict] = None) -> str:
    """人读留档：本次环境 + A① 三方表 + A② 两方表 + Δ 表 + 跳过项。"""
    lines = [f"# 解析回归 {meta.get('run_id', '')}", ""]
    if meta.get("note"):
        lines += [f"> {meta['note']}", ""]
    env = meta.get("environment") or {}
    args = meta.get("args") or {}
    lines += [
        "## 本次环境", "",
        f"- 抽样：limit={args.get('limit')} seed={args.get('seed')} 实际评分页 {meta.get('pages_scored')}",
        f"- 代码：{env.get('git_describe', '—')}（branch {env.get('git_branch', '—')}）",
        f"- 阶段：{meta.get('stages', '—')}",
        f"- MinerU 版本：{meta.get('mineru_version', '—')}",
        f"- 页集合 hash：{meta.get('page_ids_hash', '—')}",
        f"- 耗时：{_timing_text(meta.get('timing') or {})}",
        "",
    ]
    if meta.get("skipped"):
        lines += ["## 跳过/失败项", ""] + [f"- {s}" for s in meta["skipped"]] + [""]

    lines += ["## A① 官方 markdown 口径（三方）", "",
              "| 指标 | 参考模型 | MinerU 单独 | 我们全链 |", "|---|---|---|---|"]
    for key in ("text_edit", "table_teds", "table_edit", "formula_edit", "formula_cdm", "order_edit"):
        higher = key in HIGHER_IS_BETTER
        row = [METRIC_LABELS.get(key, key)]
        for src in (official_ref, official_mineru, official):
            row.append(fmt_metric((src or {}).get(key), higher))
        lines.append("| " + " | ".join(row) + " |")
    if not official_ref or not official_mineru:
        lines += ["", "（参考模型/MinerU 单独两列缺：跑时未提供 `sources`；两者是固定基线，不随本次 run 变）"]
    lines += ["", "## A② 结构层口径（两方）", "",
              "| 指标 | MinerU 原生 content_list | 我们全链 |", "|---|---|---|"]
    for key in ("block_recall", "pred_used_ratio", "text_similarity", "text_similarity_matched",
                "teds", "formula_similarity", "order_adjacent_accuracy", "order_kendall_tau"):
        lines.append("| " + " | ".join(
            [METRIC_LABELS.get(key, key), fmt_metric(struct_mineru.get(key), True),
             fmt_metric(struct_chain.get(key), True)]) + " |")

    concl = conclusions or {}
    if concl.get("official") or concl.get("struct"):
        lines += ["", "## 结论（往哪改）", ""]
        for block in ("official", "struct"):
            data = concl.get(block) or {}
            if not data.get("headline"):
                continue
            lines.append(f"- {data['headline']}")
            for row in data.get("worse", []):
                lines.append(f"  - {row['label']}：我们 {_fmt_metric(row['metric'], row['ours'])} vs "
                             f"{row['rival_name']} {_fmt_metric(row['metric'], row['rival'])}"
                             f"（差 {row['gap'] * 100:.2f}pp）——{row.get('hint', '')}")
            for cat in data.get("weak_categories", []):
                lines.append(f"  - 最差类目 {cat['name']}：召回率 {cat['recall'] * 100:.1f}%"
                             + _rival_note(cat.get("mineru")))
            for src in data.get("weak_sources", []):
                lines.append(f"  - 最差文档类型 {src['name']}：召回率 {src['recall'] * 100:.1f}%"
                             + _rival_note(src.get("mineru")))
        if concl.get("noise_note"):
            lines += ["", f"（{concl['noise_note']}）"]

    if delta:
        lines += ["", f"## Δ vs 基线 {delta.get('baseline_id', '')}", ""]
        if delta.get("gate") == "none":
            lines += [f"- 不出 Δ：{delta.get('reason', '')}"]
        else:
            rel = delta.get("relation") or {}
            if not rel.get("equal"):
                lines += [f"- **页集合不同**（本次 {rel.get('cur_count')} / 基线 {rel.get('base_count')} / 交集 "
                          f"{rel.get('intersection')}）——Δ 按交集重算，**非官方重跑口径**"]
            if delta.get("note"):
                lines += [f"- {delta['note']}"]
            for group, title in (("official", "A① 官方口径"), ("struct_chain", "A② 我们全链")):
                rows = (delta.get("groups") or {}).get(group) or []
                if not rows:
                    continue
                lines += ["", f"### {title}", "", "| 指标 | 本次 | 基线 | Δ |", "|---|---|---|---|"]
                for row in rows:
                    lines.append("| " + " | ".join([row["label"], fmt_metric(row["cur"], row["higher_is_better"]),
                                                    fmt_metric(row["base"], row["higher_is_better"]),
                                                    fmt_delta(row)]) + " |")
    lines += ["", "---", "", "口径定义见 docs/parse-struct-eval.md；本文件由 run_parse_regression.py 生成。", ""]
    return "\n".join(lines)


# 各指标"该往哪查"的固定提示（只指方向，不断言根因——根因要另做定位）
METRIC_HINTS = {
    "text_edit": "量 markdown 文本与 GT 的编辑距离：查文本块识别与 markdown 投影环节（投影已剥 build_id 头）",
    "text_edit_whole": "整篇编辑距离：单页文本顺序/漏字会放大它",
    "table_teds": "量表格结构（HTML↔HTML）：查表格识别、合并单元格与相邻表切分",
    "table_teds_struct": "只看表格骨架：结构对但文字错时，与 TEDS 的差就是文字部分",
    "table_edit": "量表格内文字：注意我们的 table_html 是 MinerU HTML 原文搬运，此列注定与 MinerU 同分",
    "formula_edit": "量公式 LaTeX 串：查去风格化与多行数组表示约定（非 CDM，别当绝对值）",
    "formula_cdm": "公式语义相似度：比串相似更接近真实质量，优先看它",
    "order_edit": "量块序：查多栏/长文档的 block_seq 重建（research_report/book 是历史短板）",
    "block_recall": "块没被 GT 覆盖：看逐类目表，哪类召回低就往哪类的捕获/类目映射查",
    "pred_used_ratio": "我们多出来的块没被解释：幻觉块/重复块会拉低它",
    "text_similarity": "块文本识别质量（漏检按 0 计入）",
    "text_similarity_matched": "只看匹配上的块＝识别质量本身",
    "teds": "A② 表格结构（不过 markdown 投影）",
    "formula_similarity": "公式串相似（非 CDM）",
    "order_adjacent_accuracy": "相邻块顺序正确率",
    "order_kendall_tau": "全局块序一致性",
}
# 差距小于它就当持平：没测过噪声底（方案 D5 未做），小差距不足以判优劣
NOISE_EPS = 0.005
NOISE_NOTE = ("未测噪声底（未跑 50 页×2）：差距 <0.005（<0.5pp）一律按持平处理，"
              "不作优劣或回归判据。")


def _rival_note(rival) -> str:
    """最差项附 MinerU 同项：两边都低 = 类目本身难（不是我们的短板），我们低得多才是。"""
    if rival is None:
        return ""
    return f"（MinerU 同项 {rival * 100:.1f}%）"


def _fmt_metric(key: str, value) -> str:
    if value is None:
        return "—"
    return f"{value * 100:.2f}%" if key in HIGHER_IS_BETTER else f"{value:.4f}"


def _rank_rows(keys, ours: dict, rivals: dict, eps: float = NOISE_EPS) -> dict:
    """逐指标比较我方与各对手：返回 {best, worse, rows}（worse 按差距从大到小）。

    rivals: {对手名: {指标: 值}}；方向由 HIGHER_IS_BETTER 决定。
    """
    rows, best_keys, worse = [], [], []
    for key in keys:
        cur = ours.get(key)
        if cur is None:
            continue
        cand = [(name, vals.get(key)) for name, vals in rivals.items() if vals.get(key) is not None]
        if not cand:
            continue
        higher = key in HIGHER_IS_BETTER
        holder, rival_best = (max(cand, key=lambda x: x[1]) if higher else min(cand, key=lambda x: x[1]))
        gap = (rival_best - cur) if higher else (cur - rival_best)   # >0 表示我们落后
        row = {"metric": key, "label": METRIC_LABELS.get(key, key), "ours": cur,
               "rival": rival_best, "rival_name": holder, "gap": round(gap, 6),
               "verdict": "worse" if gap > eps else ("tie" if abs(gap) <= eps else "better")}
        rows.append(row)
        if row["verdict"] == "worse":
            worse.append(row)
        elif row["verdict"] != "worse":
            best_keys.append(key)
    worse.sort(key=lambda r: -r["gap"])
    return {"rows": rows, "best": best_keys, "worse": worse}


def _breakdown_gaps(ours: Optional[list], rival: Optional[list], key_name: str,
                    value_key: str, eps: float = NOISE_EPS) -> dict:
    """逐类目/逐文档类型 与 MinerU 的差：谁好谁坏要以同口径对手为参照，不能拍阈值。"""
    ours = ours or []
    rival_map = {r.get(key_name): r for r in (rival or [])}
    rows = []
    for row in ours:
        name = row.get(key_name)
        other = (rival_map.get(name) or {}).get(value_key)
        cur = row.get(value_key)
        if cur is None or other is None:
            continue
        gap = cur - other                     # 召回率/相似度都是越大越好
        rows.append({"name": name, "ours": cur, "rival": other, "gap": round(gap, 6),
                     "verdict": "better" if gap > eps else ("worse" if gap < -eps else "tie")})
    rows.sort(key=lambda r: r["gap"])
    return {"rows": rows, "worse": [r for r in rows if r["verdict"] == "worse"],
            "better": [r for r in rows if r["verdict"] == "better"]}


def build_conclusions(official: dict, struct_chain: dict, struct_mineru: dict,
                      official_ref: Optional[dict] = None, official_mineru: Optional[dict] = None,
                      by_category: Optional[list] = None, by_data_source: Optional[list] = None,
                      mineru_category: Optional[list] = None, mineru_source: Optional[list] = None) -> dict:
    """按数字生成"往哪改"的结论（A① 三方 / A② 两方各一段）。

    规则化而非文案化：谁最优、我们落后几项、差距最大的是哪项（附该项量什么、往哪查），
    以及 A② 下钻出的最差类目/文档类型。根因定位不在这一步，只指方向。
    """
    official = official or {}
    struct_chain = struct_chain or {}
    out: dict = {"noise_note": NOISE_NOTE}

    # ── A① 官方 markdown 口径 ──
    ref_rank = _rank_rows(OFFICIAL_ORDER, official,
                          {"参考模型": official_ref or {}, "MinerU 单独": official_mineru or {}})
    if ref_rank["rows"]:
        total = len(ref_rank["rows"])
        n_best = total - len(ref_rank["worse"])
        # 用 total（实际有值的指标数），不写死 7：指标缺失时写死会把"3 项里 1 项"说成"7 项里 1 项"
        head = f"A① 官方 markdown 口径：{total} 项里我们最优（或持平）{n_best}/{total} 项"
        if ref_rank["worse"]:
            top = ref_rank["worse"][0]
            head += (f"；差距最大的是{top['label']}——我们 {_fmt_metric(top['metric'], top['ours'])}，"
                     f"最佳 {_fmt_metric(top['metric'], top['rival'])}（{top['rival_name']}），差 "
                     f"{top['gap'] * 100:.2f}pp")
        else:
            head += "；没有落后项"
        out["official"] = {
            "headline": head,
            "worse": [{**r, "hint": METRIC_HINTS.get(r["metric"], "")} for r in ref_rank["worse"]],
            "best": [METRIC_LABELS.get(k, k) for k in ref_rank["best"]],
        }

    # ── A② 结构层口径 ──
    our_rank = _rank_rows(STRUCT_ORDER, struct_chain, {"MinerU 原生": struct_mineru or {}})
    if our_rank["rows"]:
        wins = [r for r in our_rank["rows"] if r["verdict"] == "better"]
        losses = [r for r in our_rank["rows"] if r["verdict"] == "worse"]
        head = (f"A② 结构层口径：对 MinerU 原生 content_list 我们领先 {len(wins)} 项、"
                f"落后 {len(losses)} 项、持平 {len(our_rank['rows']) - len(wins) - len(losses)} 项")
        if losses:
            top = losses[0]
            head += (f"；落后最多的是{top['label']}（我们 {_fmt_metric(top['metric'], top['ours'])} vs "
                     f"{_fmt_metric(top['metric'], top['rival'])}）")
        cats = sorted([c for c in (by_category or []) if c.get("recall") is not None],
                      key=lambda c: c["recall"])[:3]
        srcs = sorted([s for s in (by_data_source or []) if s.get("block_recall") is not None],
                      key=lambda s: s["block_recall"])[:3]
        cat_rival = {r.get("category"): r for r in (mineru_category or [])}
        src_rival = {r.get("data_source"): r for r in (mineru_source or [])}
        cat_gap = _breakdown_gaps(by_category, mineru_category, "category", "recall")
        src_gap = _breakdown_gaps(by_data_source, mineru_source, "data_source", "block_recall")
        total_cat = len(cat_gap["rows"])
        tied_cat = total_cat - len(cat_gap["worse"]) - len(cat_gap["better"])
        if total_cat:
            head += f"；逐类目 {total_cat} 项里我们落后 {len(cat_gap['worse'])} 项、与 MinerU 同分 {tied_cat} 项"
        out["struct"] = {
            "headline": head,
            "worse": [{**r, "hint": METRIC_HINTS.get(r["metric"], "")} for r in losses],
            "best": [r["label"] for r in wins],
            # 附上 MinerU 同项：光看绝对值会把"两边都没接住的类目"误读成"我们的短板"
            "weak_categories": [
                {"name": c["category"], "recall": c["recall"],
                 "mineru": (cat_rival.get(c["category"]) or {}).get("recall")} for c in cats],
            "weak_sources": [
                {"name": s["data_source"], "recall": s["block_recall"],
                 "mineru": (src_rival.get(s["data_source"]) or {}).get("block_recall")} for s in srcs],
            # 逐类目/逐文档类型的"好还是坏"要对着 MinerU 同口径看，绝对值本身没有判据
            "category_vs_mineru": cat_gap,
            "source_vs_mineru": src_gap,
        }
    return out


def _date_from_ts(ts) -> str:
    """`20260917-0837` → `2026-09-17`；解析不出来就原样返回（看板按字符串排序，不炸）。"""
    raw = str(ts or "")
    if len(raw) >= 8 and raw[:8].isdigit():
        return f"{raw[:4]}-{raw[4:6]}-{raw[6:8]}"
    return raw


def run_date_from_tag(tag: str, ts: str) -> str:
    """入档模式的 run_date：优先取 --tag 里的 YYYYMMDD（baseline-20260913 → 2026-09-13），
    否则用当前时间——否则"离线基线"会被按导入时刻排到最新。"""
    import re as _re

    match = _re.search(r"(\d{4})(\d{2})(\d{2})", str(tag or ""))
    if match:
        return f"{match.group(1)}-{match.group(2)}-{match.group(3)}"
    return _date_from_ts(ts)


def metric_meta() -> dict:
    """前端渲染用的指标元信息：中文名 + 越大越好 + 是否按百分比显示（值域 0–1）。"""
    keys = set(METRIC_LABELS)
    return {k: {"label": METRIC_LABELS[k], "higher_is_better": k in HIGHER_IS_BETTER, "ratio": True}
            for k in keys}


# 发布到服务器看板的白名单：本机跑出来的"结论层"文件（合计 ~140KB），
# 不含 predictions/（每页 md）、official/（官方全套产物）、gt_subset.json——那些是复现用的，留在本机
PUBLISH_FILES = ("meta.json", "summary.md", "publish.json", "struct_chain.json", "struct_mineru.json",
                 "struct_chain_report.md", "struct_mineru_report.md")


def build_publish_payload(meta: dict, official: dict, struct_chain: dict, struct_mineru: dict,
                          delta: Optional[dict] = None, official_ref: Optional[dict] = None,
                          official_mineru: Optional[dict] = None, chain_result: Optional[dict] = None,
                          conclusions: Optional[dict] = None, mineru_result: Optional[dict] = None) -> dict:
    """服务器看板要的全部信息：一次跑的结果 + Δ + 渲染元信息（前端不重算任何东西）。

    数字都在本机用本模块算好（同一份代码），服务器只读不算——避免"两个版本各算一遍"漂移。
    """
    env = meta.get("environment") or {}
    args = meta.get("args") or {}
    return {
        "schema": 1,
        "run_id": meta.get("run_id"), "ts": meta.get("ts"), "kind": meta.get("kind", "run"),
        # run_date = 这批判代表的结果日期（看板列表按它排序，不按目录名字典序——
        # "baseline-xxx" 会排在 "2026xxxx" 之前，让人以为离线基线是最新的）
        "run_date": meta.get("run_date") or _date_from_ts(meta.get("ts")),
        "note": meta.get("note", ""),
        "limit": args.get("limit"), "seed": args.get("seed"),
        "predict_mode": args.get("predict_mode"), "skip_predict": args.get("skip_predict"),
        "skip_official": args.get("skip_official"),
        "pages_scored": meta.get("pages_scored"), "pages_sampled": meta.get("pages_sampled"),
        "pages_official": meta.get("pages_official"), "pages_struct_chain": meta.get("pages_struct_chain"),
        "page_ids_hash": meta.get("page_ids_hash"),
        "git": env.get("git_describe", ""), "branch": env.get("git_branch", ""),
        "python": env.get("python", ""), "eval_image": env.get("eval_image", ""),
        "mineru_version": meta.get("mineru_version", ""),
        "stages": meta.get("stages", ""), "timing": meta.get("timing") or {},
        "skipped": meta.get("skipped") or [],
        "metrics": {
            "official": official, "official_ref": official_ref or {}, "official_mineru": official_mineru or {},
            "struct_chain": struct_chain, "struct_mineru": struct_mineru,
        },
        "metric_meta": metric_meta(),
        "delta": delta or {},
        "by_category": (chain_result or {}).get("by_category") or [],
        "by_data_source": (chain_result or {}).get("by_data_source") or [],
        # MinerU 同口径的逐类目/逐文档类型：没有它，单序列的绝对值图读不出好坏
        "by_category_mineru": (mineru_result or {}).get("by_category") or [],
        "by_data_source_mineru": (mineru_result or {}).get("by_data_source") or [],
        # 结论由本机按数字算好并随载荷入档（前端只渲染，不各算一遍）
        "conclusions": conclusions if conclusions is not None else build_conclusions(
            official, struct_chain, struct_mineru, official_ref, official_mineru,
            (chain_result or {}).get("by_category"), (chain_result or {}).get("by_data_source"),
            (mineru_result or {}).get("by_category"), (mineru_result or {}).get("by_data_source")),
    }


def write_publish(run_dir: Path, payload: dict) -> Path:
    return write_json(Path(run_dir) / "publish.json", payload)


def _timing_text(timing: dict) -> str:
    parts = [f"{k} {v:.0f}s" for k, v in timing.items() if isinstance(v, (int, float))]
    return " / ".join(parts) if parts else "—"
