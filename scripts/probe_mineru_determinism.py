"""MinerU 解析确定性探针：同一页图重复解析，比对表格 HTML 结构签名是否逐次一致。

来历：2026-09-23 表格 TEDS 排查（docs/plan-parse-regression-entry.md 后续）。当时用临时脚本
（D:/AI/rerun_mineru_probe.py）对 3 张高风险页各跑 3 轮，结论"确定性成立、错误是稳定复现的
结构缺陷"。本脚本是它的正式版：改动 MinerU 端（补丁/版本/并发参数）前后都可以跑一遍，
**同一页跨 run 签名不一致即不确定性**（exit 1），一致则只报告"稳定复现出的表格形状"。

用法：
  python scripts/probe_mineru_determinism.py                    # 默认 3 页 × 3 轮（走 .env 的 dgx 端点）
  python scripts/probe_mineru_determinism.py --pages a.png,b.jpg --runs 5
  python scripts/probe_mineru_determinism.py --out-dir data/evals/parse_regression/determinism_probe

退出码：0=全部页跨 run 签名一致；1=存在跨 run 漂移；2=端点/配置问题跑不起来。
不依赖 GT，不打分——它回答"稳不稳"，不回答"对不对"（对不对走 run_parse_regression A①）。
"""
import argparse
import hashlib
import io
import json
import os
import re
import sys
import zipfile
from datetime import datetime
from pathlib import Path

import requests

REPO = Path(__file__).resolve().parents[1]

# 默认探针页：09-18 归档中表格结构出错的高风险页（相邻表合并、colspan 塌缩、rowspan 误并各一型）
DEFAULT_PAGES = [
    "page-dca64e05-1ce6-49ee-857a-9b5d05a87357.png",   # GT 14+14 行 → 预测 28 行合并 + colspan="101"
    "notes_1ba14cb325bc448f7201b20502ecf2b5_74.jpg",   # 拆两行 + rowspan="2"
    "notes_1ba14cb325bc448f7201b20502ecf2b5_60.jpg",   # 前三格清空 + rowspan="3"
]


def _resolve_endpoint(cli_url: str) -> tuple:
    """端点与密钥：--url/--api-key 优先，否则读 .env 的 MINERU_CONFIGS 里 name=dgx 的那条。"""
    if cli_url:
        return cli_url.rstrip("/"), os.getenv("MINERU_API_KEY", "")
    from dotenv import load_dotenv
    load_dotenv(REPO / ".env")
    cfg = json.loads(os.getenv("MINERU_CONFIGS") or "[]")
    ep = next((c for c in cfg if c.get("name") == "dgx"), cfg[0] if cfg else None)
    if not ep or not ep.get("url"):
        raise SystemExit("MINERU_CONFIGS 未配置且未给 --url，无法确定端点")
    return ep["url"].rstrip("/"), ep.get("api_key", "")


def _page_to_pdf(path: Path) -> bytes:
    from PIL import Image
    Image.MAX_IMAGE_PIXELS = None
    with Image.open(path) as img:
        if img.mode not in ("RGB", "L"):
            img = img.convert("RGB")
        buf = io.BytesIO()
        img.save(buf, format="PDF")
        return buf.getvalue()


def _parse_once(url: str, key: str, backend: str, pdf: bytes, name: str) -> dict:
    resp = requests.post(
        url, headers={"Authorization": f"Bearer {key}"} if key else {},
        files={"files": (name, pdf, "application/pdf")},
        data={"return_md": "true", "return_content_list": "true", "return_middle_json": "true",
              "response_format_zip": "true", "backend": backend,
              "formula_enable": "true", "table_enable": "true", "is_async": "false"},
        timeout=300, verify=False,
    )
    if resp.status_code != 200:
        return {"error": f"HTTP {resp.status_code}: {resp.text[:200]}"}
    zf = zipfile.ZipFile(io.BytesIO(resp.content))
    tables = []
    cl_name = next((n for n in zf.namelist() if n.endswith("content_list.json")), None)
    if cl_name:
        for it in json.loads(zf.read(cl_name).decode("utf-8")):
            if isinstance(it, dict) and "table" in str(it.get("type", "")).lower():
                tables.append(str(it.get("table_body") or it.get("html") or it.get("table_html") or ""))
    if not tables:  # content_list 缺表时退回 markdown 里的 <table>
        md_name = next((n for n in zf.namelist() if n.endswith(".md")), None)
        if md_name:
            md = zf.read(md_name).decode("utf-8", errors="replace")
            tables = re.findall(r"<table.*?</table>", md, re.S)
    ver = ""
    mj = next((n for n in zf.namelist() if n.endswith("middle.json")), None)
    if mj:
        try:
            m = json.loads(zf.read(mj).decode("utf-8"))
            ver = str(m.get("_version_name") or "")
        except Exception:
            pass
    return {"tables": tables, "version": ver}


def _sig(html: str) -> str:
    return hashlib.md5(re.sub(r"\s+", "", html).encode("utf-8")).hexdigest()[:10]


def main() -> int:
    ap = argparse.ArgumentParser(description="MinerU 重复解析结构签名一致性探针（不打分，只判稳）")
    ap.add_argument("--pages", default="", help="逗号分隔的图片文件名；默认内置 3 张高风险表格页")
    ap.add_argument("--data-dir", default="", help="页图目录；默认 D:/AI/tools/OmniDocBench_data/images")
    ap.add_argument("--runs", type=int, default=3, help="每页重复解析次数（默认 3）")
    ap.add_argument("--url", default="", help="file_parse 端点覆盖（默认读 .env MINERU_CONFIGS name=dgx）")
    ap.add_argument("--backend", default="", help="MinerU backend；默认 .env MINERU_BACKEND 或 hybrid-engine")
    ap.add_argument("--out-dir", default="", help="漂移时把不一致的表格 HTML 存到此目录（默认不存）")
    args = ap.parse_args()

    url, key = _resolve_endpoint(args.url)
    if not url.endswith("/file_parse"):
        url += "/file_parse"
    import logging
    logging.getLogger("urllib3").disabled = True
    import urllib3
    urllib3.disable_warnings()
    backend = (args.backend or os.getenv("MINERU_BACKEND", "hybrid-engine")).strip().lower()
    data_dir = Path(args.data_dir) if args.data_dir else Path("D:/AI/tools/OmniDocBench_data/images")
    pages = [p.strip() for p in args.pages.split(",") if p.strip()] or DEFAULT_PAGES
    print(f"端点 {url}  backend={backend}  runs={args.runs}  页图 {data_dir}")

    drift = 0
    for page in pages:
        path = data_dir / page
        print("=" * 72)
        if not path.is_file():
            print(f"PAGE {page}: 文件不存在，跳过")
            drift = max(drift, 1)
            continue
        pdf = _page_to_pdf(path)
        sigs, versions = [], set()
        for i in range(1, args.runs + 1):
            try:
                r = _parse_once(url, key, backend, pdf, page)
            except Exception as exc:
                print(f"  run{i}: 调用失败 {exc!r}")
                sigs.append("EXC")
                continue
            if r.get("error"):
                print(f"  run{i}: {r['error']}")
                sigs.append("ERR")
                continue
            versions.add(r.get("version", ""))
            tab_sigs = tuple(_sig(t) for t in r["tables"])
            sigs.append(tab_sigs)
            shape = " ".join(f"{_sig(t)}({len(re.findall('<t[dh]', t))}格)" for t in r["tables"]) or "无表"
            print(f"  run{i}: {shape}")
        stable = len(set(map(str, sigs))) == 1
        if versions:
            print(f"  版本: {'; '.join(sorted(versions))}")
        print(f"  ==> {'一致（稳定复现）' if stable else '跨 run 漂移！'}")
        if not stable:
            drift = 1
            if args.out_dir:
                dump = Path(args.out_dir) / datetime.now().strftime("%Y%m%d-%H%M") / page
                dump.mkdir(parents=True, exist_ok=True)
                # 重新解析一遍只为落盘留证（漂移本身就说明结果不可复制，落的是"这一遍"的）
                for i in range(1, args.runs + 1):
                    r = _parse_once(url, key, backend, pdf, page)
                    for j, t in enumerate(r.get("tables") or []):
                        (dump / f"run{i}_table{j}.html").write_text(t, encoding="utf-8")
                print(f"  已留证: {dump}")
    print("=" * 72)
    print("结论:", "全部页跨 run 结构一致（确定性成立）" if drift == 0 else "存在漂移，见上")
    return drift


if __name__ == "__main__":
    sys.exit(main())
