"""下载 Open RAG Benchmark 元数据与子集 PDF。"""
import argparse
import concurrent.futures
import os
import sys
import time
from pathlib import Path

import requests

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from open_ragbench import common

HF_BASE = "https://hf-mirror.com/datasets/vectara/open_ragbench/resolve/main"


def hf_url(rel_path: str) -> str:
    return f"{HF_BASE}/{rel_path}"


def validate_meta(raw_dir: Path, min_queries: int = 3000):
    queries = common.load_json(raw_dir / "queries.json")
    qrels = common.load_json(raw_dir / "qrels.json")
    answers = common.load_json(raw_dir / "answers.json")
    pdf_urls = common.load_json(raw_dir / "pdf_urls.json")
    if not isinstance(queries, dict) or len(queries) < min_queries:
        raise ValueError(f"queries 数量异常: {len(queries)}")
    if not isinstance(qrels, dict) or not qrels:
        raise ValueError("qrels 为空")
    if not isinstance(answers, dict) or not answers:
        raise ValueError("answers 为空")
    if not isinstance(pdf_urls, dict) or not pdf_urls:
        raise ValueError("pdf_urls 为空")
    return {
        "queries": len(queries),
        "qrels": len(qrels),
        "answers": len(answers),
        "pdf_urls": len(pdf_urls),
    }


def download_meta(mirror: str = "https://hf-mirror.com", force: bool = False) -> None:
    common.ensure_dirs()
    base = mirror.rstrip("/")
    for filename, rel in common.HF_FILES.items():
        dest = common.RAW_DIR / filename
        if dest.exists() and dest.stat().st_size > 0 and not force:
            print(f"跳过已存在: {dest.name}")
            continue
        url = f"{base}/datasets/vectara/open_ragbench/resolve/main/{rel}"
        resp = requests.get(url, timeout=60)
        resp.raise_for_status()
        dest.write_bytes(resp.content)
        print(f"已下载: {dest.name} ({dest.stat().st_size} bytes)")
    counts = validate_meta(common.RAW_DIR)
    print("元数据校验通过:", counts)


def _looks_like_pdf(path: Path) -> bool:
    try:
        with open(path, "rb") as fh:
            return fh.read(5) == b"%PDF-"
    except OSError:
        return False


def _download_one(paper, timeout: int = 180, retries: int = 3) -> str:
    paper_id = paper["paper_id"]
    url = paper.get("url", "")
    dest = common.PDF_DIR / f"{paper_id}.pdf"
    if dest.exists() and _looks_like_pdf(dest):
        return f"跳过: {dest.name}"
    if not url:
        return f"缺少链接: {paper_id}"
    last_error = ""
    for attempt in range(retries):
        try:
            resp = requests.get(url, timeout=timeout)
            resp.raise_for_status()
            dest.write_bytes(resp.content)
            if not _looks_like_pdf(dest):
                raise ValueError(f"非 PDF 内容: {resp.headers.get('Content-Type', '')}")
            return f"已下载: {dest.name} ({dest.stat().st_size} bytes)"
        except Exception as exc:
            last_error = str(exc)
            time.sleep(min(2 ** attempt, 30))
    return f"失败: {paper_id} ({last_error})"


def download_pdfs(manifest_path: Path, workers: int = 4, timeout: int = 180, retries: int = 3) -> None:
    common.ensure_dirs()
    manifest = common.load_json(manifest_path)
    papers = manifest.get("papers", [])
    with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as pool:
        results = list(pool.map(lambda p: _download_one(p, timeout, retries), papers))
    for line in results:
        print(line)
    failed = [r for r in results if r.startswith("失败")]
    if failed:
        print(f"共失败 {len(failed)} 个:")
        for line in failed:
            print(" -", line)


def main() -> int:
    parser = argparse.ArgumentParser(description="下载 Open RAG Benchmark 数据")
    sub = parser.add_subparsers(dest="command", required=True)

    meta = sub.add_parser("meta", help="下载元数据 JSON")
    meta.add_argument("--mirror", default="https://hf-mirror.com")
    meta.add_argument("--force", action="store_true")

    pdfs = sub.add_parser("pdfs", help="下载子集 PDF")
    pdfs.add_argument("--manifest", default=str(common.SUBSET_MANIFEST))
    pdfs.add_argument("--workers", type=int, default=4)
    pdfs.add_argument("--retries", type=int, default=3)
    pdfs.add_argument("--timeout", type=int, default=180)

    args = parser.parse_args()
    if args.command == "meta":
        download_meta(args.mirror, args.force)
    elif args.command == "pdfs":
        download_pdfs(Path(args.manifest), workers=args.workers, timeout=args.timeout, retries=args.retries)
    return 0


if __name__ == "__main__":
    sys.exit(main())
