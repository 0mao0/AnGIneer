"""一次性重传失败的文档：并行上传剩余正例并轮询到终态。"""
import json
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from open_ragbench import common  # noqa: E402


def _load_env():
    try:
        from dotenv import load_dotenv
    except ImportError:
        return
    load_dotenv(common.REPO_ROOT / ".env")


def load_state():
    return common.load_json(common.IMPORT_STATE) if common.IMPORT_STATE.exists() else {"library_id": "", "papers": {}}


def upload_pdf(ep, api_key, pdf_path, stages):
    with open(pdf_path, "rb") as fh:
        resp = requests.post(
            ep.parse,
            headers={"X-API-Key": api_key},
            params={"stages": stages},
            files={"file": (pdf_path.name, fh, "application/pdf")},
            timeout=120,
        )
    resp.raise_for_status()
    data = resp.json()
    doc_id = data.get("doc_id")
    if not doc_id:
        raise RuntimeError(f"parse 响应缺少 doc_id: {data}")
    return doc_id


def poll_status(ep, api_key, doc_id, timeout, interval):
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            resp = requests.get(ep.status(doc_id), headers={"X-API-Key": api_key}, timeout=30)
            if resp.status_code == 404:
                return "failed", "doc not found"
            resp.raise_for_status()
        except Exception as exc:
            return "failed", str(exc)
        status = (resp.json().get("status") or "").lower()
        if status == "completed":
            return "succeeded", ""
        if status == "partial":
            return "partial", ""
        if status in ("failed", "cancelled"):
            return "failed", f"终态: {status}"
        time.sleep(interval)
    return "timeout", f"轮询超时 {timeout}s"


def process_paper(ep, api_key, paper_id, pdf_path, state_lock, state, poll_timeout=7200):
    """单篇：上传 + 轮询，返回 (paper_id, status, error)。"""
    pdf = pdf_dir = common.PDF_DIR / f"{paper_id}.pdf"
    if not pdf.exists():
        return paper_id, "failed", f"PDF 不存在: {pdf.name}"
    last_error = ""
    for attempt in range(4):
        try:
            doc_id = upload_pdf(ep, api_key, pdf, common.STAGES)
            print(f"[{paper_id}] 第{attempt+1}次上传 -> {doc_id}", flush=True)
            status, err = poll_status(ep, api_key, doc_id, poll_timeout, 10)
            if status in ("succeeded", "partial"):
                with state_lock:
                    state["papers"][paper_id] = {
                        "doc_id": doc_id, "status": status, "retries": attempt, "error": err,
                    }
                    common.save_json(common.IMPORT_STATE, state)
                return paper_id, status, ""
            last_error = err
        except Exception as exc:
            last_error = str(exc)
        print(f"[{paper_id}] 尝试{attempt+1}失败: {last_error}", flush=True)
    with state_lock:
        state["papers"][paper_id] = {
            "doc_id": state.get("papers", {}).get(paper_id, {}).get("doc_id", ""),
            "status": "failed", "retries": 3, "error": last_error,
        }
        common.save_json(common.IMPORT_STATE, state)
    return paper_id, "failed", last_error


def main():
    _load_env()
    keys = common.load_json(common.KEYS_FILE)
    api_key = keys.get("api_key", "")
    if not api_key:
        print("keys.json 缺少 api_key")
        return 2

    manifest = common.load_json(common.SUBSET_MANIFEST)  # v2 manifest 已临时设为默认? 否——手动指定
    manifest_path = Path("data/open_ragbench/subset/subset_manifest_v2.json")
    manifest = common.load_json(manifest_path)

    state = load_state()
    done = {
        pid for pid, info in state.get("papers", {}).items()
        if info.get("status") in ("succeeded", "partial")
    }
    targets = [
        p["paper_id"] for p in manifest["papers"]
        if not p.get("is_hard_negative") and p["paper_id"] not in done
    ]
    print("待上传:", len(targets), targets)
    if not targets:
        print("没有待上传的文档")
        return 0

    import threading
    lock = threading.Lock()
    ep = common.Endpoints()
    with ThreadPoolExecutor(max_workers=min(4, len(targets))) as pool:
        futures = [
            pool.submit(process_paper, ep, api_key, pid, common.PDF_DIR / f"{pid}.pdf", lock, state)
            for pid in targets
        ]
        results = [f.result() for f in futures]
    for pid, status, err in results:
        print(f"[{pid}] -> {status} {err[:100]}", flush=True)
    failed = [r for r in results if r[1] not in ("succeeded", "partial")]
    print("失败:", len(failed), [r[0] for r in failed])
    return 0 if not failed else 1


if __name__ == "__main__":
    sys.exit(main())
