"""规范库归位规划（plan-standards-kb-corpus-package Stage B）。

按文件名标准代号把 `资料/正式规范/**` 的 2348 册映射到目标库（专业=未来的知识库，
层级=库内文件夹），默认只出 CSV 清单交用户裁决，--apply 才移动文件。

目标布局：资料/正式规范/<专业>/<层级>/<原文件名>
专业枚举：公路 水运 水利 市政 建筑 电力 铁路 其他行业 综合（含待裁决的人工归宿）
层级枚举：国家标准 行业标准 地方标准 团体标准 国际标准 法规制度

用法：
    python scripts/kb_std_plan.py --out data/scratch/std-plan.csv     # 出清单（不动文件）
    # 用户在 CSV 里把「待裁决」行改判（library 列改成目标专业）后：
    python scripts/kb_std_plan.py --apply data/scratch/std-plan.csv   # 按 CSV 移动
"""
from __future__ import annotations

import argparse
import csv
import re
import shutil
import sys
from dataclasses import dataclass
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_ROOT = REPO_ROOT / "资料" / "正式规范"

DOC_EXTS = {".pdf", ".doc", ".docx"}
TARGET_LIBS = {"公路", "水运", "水利", "市政", "建筑", "电力", "铁路", "其他行业", "综合"}
TIERS = {"国家标准", "行业标准", "地方标准", "团体标准", "国际标准", "法规制度"}

# 代号前缀 → 专业。按前缀长度降序匹配（JTG 必须先于 JT 命中）。
_LIB_PREFIX = [
    ("JTG", "公路"), ("JTJ", "公路"), ("JT", "公路"),
    ("JTS", "水运"),
    ("SL", "水利"),
    ("CJJ", "市政"), ("CJ", "市政"),
    ("JGJ", "建筑"), ("JG", "建筑"),
    ("DGJ", "建筑"), ("DG", "建筑"), ("DBJ", "建筑"), ("DBJT", "建筑"),
    ("DL", "电力"), ("NB", "电力"),
    ("TB", "铁路"),
    ("HY", "其他行业"), ("LY", "其他行业"), ("JC", "其他行业"), ("YS", "其他行业"),
    ("JB", "其他行业"), ("SH", "其他行业"), ("HG", "其他行业"), ("MH", "其他行业"),
    ("SY", "其他行业"), ("YD", "其他行业"), ("HJ", "其他行业"), ("GA", "其他行业"),
    ("CH", "其他行业"), ("JJG", "其他行业"),
]

# T/团标代号主体 → 专业（认不出进待裁决）
_T_GROUP_LIB = {"JT": "公路", "JTJ": "公路", "JTG": "公路", "JTS": "水运", "SL": "水利"}

_INDUSTRY_PREFIXES = {p for p, _ in _LIB_PREFIX}
_INTERNATIONAL = ("ISO", "EN", "BS", "DIN", "ASTM", "JIS", "IEC", "BSI")
_GROUP_BODY = ("CECS", "CCES", "CIAS", "RISN", "CES")

# 代号 token：首部字母段，可带一个 /T 或 /数字 段（DG/TJ08、GB/T、DB11/T…）
_CODE_RE = re.compile(r"^\s*([A-Za-z]{1,6})(?:[/／]?([A-Za-z0-9]{0,3}))?")


@dataclass(frozen=True)
class RouteResult:
    library: str      # TARGET_LIBS 之一，或 "待裁决"
    code: str         # 识别出的代号 token（可空，仅备查）


def _code_token(name: str) -> tuple[str, str]:
    """返回 (主段, 副段)，已大写归一。无代号返回 ("", "")。"""
    m = _CODE_RE.match(name)
    if not m:
        return "", ""
    return m.group(1).upper(), (m.group(2) or "").upper()


def route(name: str) -> RouteResult:
    main, _sub = _code_token(name)
    if not main:
        return RouteResult("待裁决", "")
    if main in ("GB", "GBJ", "GBU"):
        return RouteResult("待裁决", main)
    if main == "DB":  # 纯地标须人工按省份/行业改判
        return RouteResult("待裁决", main)
    if main == "T":
        # 团标：T/主体（文件名里 / 常被写成 _ 或空格，三种分隔都认）
        m = re.match(r"^\s*T[/／_ ]?([A-Za-z]{1,6})", name)
        body = m.group(1).upper() if m else ""
        return RouteResult(_T_GROUP_LIB.get(body, "待裁决"), f"T/{body}")
    if main in _GROUP_BODY:
        return RouteResult("待裁决", main)
    if main in _INTERNATIONAL:
        return RouteResult("综合", main)
    for prefix, lib in sorted(_LIB_PREFIX, key=lambda x: -len(x[0])):
        if main.startswith(prefix):
            return RouteResult(lib, main)
    return RouteResult("待裁决", main)


def tier_of_filename(name: str) -> str:
    main, sub = _code_token(name)
    if not main:
        return ""
    if main in ("GB", "GBJ", "GBU"):
        return "国家标准"
    if re.match(r"^\s*D[GD][/／_ ]?TJ", name):  # DG/TJ08 沪地标，/ 常被写成 _ 或空格
        return "地方标准"
    if main == "DB" or main.startswith("DB"):
        return "地方标准"
    if main in ("DGJ", "DBJ"):
        return "地方标准"
    if main == "T" or main in _GROUP_BODY:
        return "团体标准"
    if main in _INTERNATIONAL:
        return "国际标准"
    if main in _INDUSTRY_PREFIXES:
        return "行业标准"
    return ""


def scan(root: Path) -> list[dict]:
    rows: list[dict] = []
    for dirpath, _dirs, files in os_walk(root):
        rel_dir = Path(dirpath).relative_to(root)
        for f in sorted(files):
            if Path(f).suffix.lower() not in DOC_EXTS:
                continue
            r = route(f)
            tier = "法规制度" if rel_dir.parts and rel_dir.parts[0] == "法律法规" else tier_of_filename(f)
            rows.append({
                "source": str(Path(dirpath) / f),
                "filename": f,
                "library": r.library,
                "tier": tier or "待裁决",
                "code": r.code,
                "status": "auto" if r.library != "待裁决" else "adjudicate",
            })
    return rows


def os_walk(root: Path):
    import os

    for dirpath, dirs, files in os.walk(root):
        dirs[:] = [d for d in dirs if d != "__pycache__"]
        yield dirpath, dirs, files


def write_csv(rows: list[dict], out: Path) -> None:
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w", newline="", encoding="utf-8-sig") as fh:
        writer = csv.DictWriter(fh, fieldnames=["source", "filename", "library", "tier", "code", "status"])
        writer.writeheader()
        writer.writerows(rows)


def apply_csv(rows: list[dict], root: Path, log: Path) -> tuple[int, int, list[str]]:
    """把 CSV 行按 <专业>/<层级>/ 移动。返回 (移动数, 跳过数, 告警)。"""
    import os

    moves = skips = 0
    warnings: list[str] = []
    log.parent.mkdir(parents=True, exist_ok=True)
    with log.open("w", encoding="utf-8") as logf:
        for row in rows:
            src = Path(row["source"])
            lib, tier = row["library"].strip(), row["tier"].strip()
            if not src.is_file():
                skips += 1  # 已移动过的行（幂等重跑）
                continue
            if lib not in TARGET_LIBS or tier not in TIERS:
                warnings.append(f"非法归宿跳过: {row['filename']} → {lib}/{tier}")
                skips += 1
                continue
            dst_dir = root / lib / tier
            dst_dir.mkdir(parents=True, exist_ok=True)
            dst = dst_dir / src.name
            if dst.exists():
                warnings.append(f"目标重名跳过: {src.name}")
                skips += 1
                continue
            shutil.move(str(src), str(dst))
            logf.write(f"{src} -> {dst}\n")
            moves += 1
        # 空的旧层级目录列出来，由用户手删（脚本不 rmdir，防误伤）
    return moves, skips, warnings


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", default=str(DEFAULT_ROOT))
    parser.add_argument("--out", default=str(REPO_ROOT / "data" / "scratch" / "std-plan.csv"))
    parser.add_argument("--apply", metavar="CSV", default="", help="按（用户裁决过的）CSV 移动文件")
    parser.add_argument("--log", default=str(REPO_ROOT / "data" / "scratch" / "std-move.log"))
    args = parser.parse_args()

    root = Path(args.root)
    if args.apply:
        with open(args.apply, newline="", encoding="utf-8-sig") as fh:
            rows = list(csv.DictReader(fh))
        moves, skips, warnings = apply_csv(rows, root, Path(args.log))
        print(f"移动={moves} 跳过={skips}")
        for w in warnings[:20]:
            print("  !", w)
        return 0 if not warnings else 1

    rows = scan(root)
    write_csv(rows, Path(args.out))
    auto = sum(1 for r in rows if r["status"] == "auto")
    by_lib: dict[str, int] = {}
    for r in rows:
        by_lib[r["library"]] = by_lib.get(r["library"], 0) + 1
    print(f"总={len(rows)} 自动归位={auto} 待裁决={len(rows) - auto}")
    for lib, n in sorted(by_lib.items(), key=lambda x: -x[1]):
        print(f"  {lib}: {n}")
    print(f"清单: {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
