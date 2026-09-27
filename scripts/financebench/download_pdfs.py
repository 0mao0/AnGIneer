"""下载 FinanceBench 150 题所需 84 篇 SEC 申报文件（官方 doc_link 优先，jsdelivr 回退）。

来源（2026-09-26 核实）：
- 题集/文档注册表 = patronus-ai/financebench@main（data/*.jsonl，已落 data/financebench/raw/）
- 正文 = 注册表 doc_link（SEC 申报原文镜像，实测与仓库 pdfs/ 字节一致）
- 回退 = cdn.jsdelivr.net/gh/patronus-ai/financebench@main/pdfs/<doc_name>.pdf

用法：python scripts/financebench/download_pdfs.py
产物：data/financebench/pdfs/<doc_name>.pdf + data/financebench/raw/pdf_manifest.json
manifest 含 git blob sha（与官方仓库 git tree 逐字节对账用）与页数。断点续跑：
已存在且魔数/页数校验通过的文件跳过。
"""
import concurrent.futures as cf
import hashlib
import io
import json
import re
import sys
import time
from pathlib import Path

import fitz
import requests

REPO = Path(__file__).resolve().parents[2]
RAW = REPO / "data" / "financebench" / "raw"
PDF_DIR = REPO / "data" / "financebench" / "pdfs"
MANIFEST = RAW / "pdf_manifest.json"

UA = {"User-Agent": "Mozilla/5.0 (research; contact: research@angineer.cn)"}


def blob_sha(data: bytes) -> str:
    h = hashlib.sha1()
    h.update(b"blob %d\0" % len(data))
    h.update(data)
    return h.hexdigest()


def needed_docs() -> list[str]:
    qs = [json.loads(l) for l in open(RAW / "financebench_open_source.jsonl", encoding="utf-8")]
    return sorted({q["doc_name"] for q in qs})


def doc_links() -> dict[str, str]:
    out = {}
    for l in open(RAW / "financebench_document_information.jsonl", encoding="utf-8"):
        d = json.loads(l)
        out[d["doc_name"]] = d["doc_link"]
    return out


def valid_pdf(path: Path) -> bool:
    if not path.exists() or path.stat().st_size < 10_000:
        return False
    if path.read_bytes()[:5] != b"%PDF-":
        return False
    try:
        with fitz.open(path) as d:
            return d.page_count > 0
    except Exception:
        return False


def fetch(url: str, timeout: int = 180) -> bytes:
    r = requests.get(url, headers=UA, timeout=timeout, stream=True)
    r.raise_for_status()
    return r.content


def download_one(doc: str, link: str) -> dict:
    path = PDF_DIR / f"{doc}.pdf"
    if valid_pdf(path):
        data = path.read_bytes()
    else:
        data = None
        last_err = ""
        for url in (link, f"https://cdn.jsdelivr.net/gh/patronus-ai/financebench@main/pdfs/{doc}.pdf",
                    f"https://raw.githubusercontent.com/patronus-ai/financebench/main/pdfs/{doc}.pdf"):
            for _ in range(2):
                try:
                    blob = fetch(url)
                    if blob[:5] == b"%PDF-" and len(blob) > 10_000:
                        data = blob
                        break
                    last_err = f"{url} 魔数/大小不符 ({len(blob)}B)"
                except Exception as exc:
                    last_err = str(exc)
                    time.sleep(2)
            if data:
                break
        if not data:
            return {"doc": doc, "status": "failed", "error": last_err}
        path.write_bytes(data)
        if not valid_pdf(path):
            path.unlink(missing_ok=True)
            return {"doc": doc, "status": "failed", "error": "落盘后校验失败"}
    with fitz.open(path) as d:
        pages = d.page_count
    return {"doc": doc, "status": "ok", "bytes": len(data), "blob_sha": blob_sha(data),
            "pages": pages, "link": link}


def main() -> int:
    PDF_DIR.mkdir(parents=True, exist_ok=True)
    docs, links = needed_docs(), doc_links()
    todo = [d for d in docs if not valid_pdf(PDF_DIR / f"{d}.pdf")]
    print(f"需 {len(docs)} 篇，缺 {len(todo)} 篇", flush=True)
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8")) if MANIFEST.exists() else {}
    with cf.ThreadPoolExecutor(max_workers=6) as pool:
        futs = {pool.submit(download_one, d, links.get(d, "")): d for d in todo}
        for fut in cf.as_completed(futs):
            rec = fut.result()
            doc = futs[fut]
            manifest[doc] = rec
            print(f"[{rec['status']}] {doc} "
                  f"{rec.get('pages', '')}页 {rec.get('bytes', 0)}B {rec.get('error', '')}", flush=True)
            MANIFEST.write_text(json.dumps(manifest, ensure_ascii=False, indent=1), encoding="utf-8")
    ok = [r for r in manifest.values() if r.get("status") == "ok"]
    total_pages = sum(r.get("pages", 0) for r in ok)
    print(f"完成: {len(ok)}/{len(docs)} 篇，总页数 {total_pages}", flush=True)
    failed = [d for d, r in manifest.items() if r.get("status") != "ok"]
    if failed:
        print("失败清单:", failed, flush=True)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
