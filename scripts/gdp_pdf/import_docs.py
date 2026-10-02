"""GDP.pdf 语料入库：建 GDP-PDF 库、建绑定 API Key、批量上传解析 100 份 PDF（断点续跑）。

仿 scripts/financebench/import_docs.py，差异：
  - manifest 从 data/gdp_pdf/raw/parquet_a.parquet 现推（pdf_path 列 + 本地 pdfs/ 存在性）；
  - 单阶段提交 stages="all"（专业文档，表格/图都要，走完整解析链），不做 financebench 的两段式预取；
  - 轮询容忍瞬时故障纪律沿用（dev 热重载/网关毛刺连败 <12 次不判死）。

用法（仓库根目录）：
  python scripts/gdp_pdf/import_docs.py --create-only          # 只建库+Key
  python scripts/gdp_pdf/import_docs.py --only-idx 0,1,2 ...   # 只入库指定 parquet 行号（试点）
  python scripts/gdp_pdf/import_docs.py                        # 全量 100 篇
"""
import argparse
import json
import os
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pandas as pd
import requests

REPO = Path(__file__).resolve().parents[2]
DATA = REPO / "data" / "gdp_pdf"
PDF_DIR = DATA / "pdfs"
PARQUET = DATA / "raw" / "parquet_a.parquet"
STATE_FILE = DATA / "ingest" / "import_state.json"
KEYS_FILE = DATA / "ingest" / "keys.json"
DOCS_API = "http://localhost:8790"
LIBRARY_NAME = "GDP-PDF"
KEY_USER_NAME = "gdp-pdf"


def load_env() -> None:
    try:
        from dotenv import load_dotenv

        load_dotenv(REPO / ".env")
    except ImportError:
        pass


def save_json(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def load_state() -> dict:
    if STATE_FILE.exists():
        return json.loads(STATE_FILE.read_text(encoding="utf-8"))
    return {"library_id": "", "library_name": LIBRARY_NAME, "docs": {}}


def advance(state: dict, fname: str, doc_id: str, status: str, error: str = "") -> dict:
    prev = state["docs"].get(fname, {})
    retries = prev.get("retries", 0) + (1 if status == "failed" else 0)
    state["docs"][fname] = {"doc_id": doc_id, "status": status, "retries": retries, "error": error}
    return state


def login(user: str, password: str) -> str:
    resp = requests.post(f"{DOCS_API}/api/v1/auth/login", json={"username": user, "password": password}, timeout=30)
    resp.raise_for_status()
    return resp.json()["token"]


def create_library(token: str) -> str:
    resp = requests.get(f"{DOCS_API}/api/knowledge/libraries", timeout=30)
    resp.raise_for_status()
    for lib in resp.json():
        if lib.get("name") == LIBRARY_NAME:
            return lib["id"]
    resp = requests.post(
        f"{DOCS_API}/api/knowledge/libraries",
        json={"name": LIBRARY_NAME, "description": "GDP.pdf 多模态专业文档语料（Surge AI 官方 100 题自带 PDF，10 域）"},
        timeout=30,
    )
    resp.raise_for_status()
    return resp.json()["id"]


def create_key(token: str, library_id: str) -> str:
    resp = requests.post(
        f"{DOCS_API}/api/api-keys",
        headers={"Authorization": f"Bearer {token}"},
        json={"user_name": KEY_USER_NAME, "scope": "doc", "library_id": library_id},
        timeout=30,
    )
    resp.raise_for_status()
    return resp.json()["api_key"]


def upload(api_key: str, pdf_path: Path) -> str:
    with open(pdf_path, "rb") as fh:
        resp = requests.post(
            f"{DOCS_API}/api/v1/documents/parse",
            headers={"X-API-Key": api_key},
            params={"stages": "all"},
            files={"file": (pdf_path.name, fh, "application/pdf")},
            timeout=120,
        )
    resp.raise_for_status()
    doc_id = resp.json().get("doc_id")
    if not doc_id:
        raise RuntimeError(f"parse 响应缺少 doc_id: {resp.json()}")
    return doc_id


def poll(api_key: str, doc_id: str, timeout: int, interval: int) -> str:
    deadline = time.time() + timeout
    transient = 0
    while time.time() < deadline:
        try:
            resp = requests.get(f"{DOCS_API}/api/v1/documents/{doc_id}/status", headers={"X-API-Key": api_key}, timeout=30)
            resp.raise_for_status()
            transient = 0
        except (requests.RequestException, ValueError):
            transient += 1
            if transient >= 12:
                raise
            time.sleep(max(interval, 10))
            continue
        status = (resp.json().get("status") or "").lower()
        if status == "completed":
            return "succeeded"
        if status == "partial":
            return "partial"
        if status in ("failed", "cancelled"):
            time.sleep(20)
            try:
                status2 = (requests.get(f"{DOCS_API}/api/v1/documents/{doc_id}/status", headers={"X-API-Key": api_key}, timeout=30).json().get("status") or "").lower()
            except requests.RequestException:
                status2 = status
            if status2 == "completed":
                return "succeeded"
            if status2 == "partial":
                return "partial"
            if status2 in ("processing", "queued", "pending"):
                continue
            return "failed"
        time.sleep(interval)
    return "timeout"


def reconcile(api_key: str, library_id: str) -> int:
    """按 import_state 认可的 doc_id 清理库内孤儿/重复副本（软删）。

    场景：进程被中途回收时已上传但未落 state 的孤儿文档，会与本脚本重传形成的
    同 PDF 多份共存，污染检索。以 state 终态 doc_id 集合为准，删除不在其中的 document 节点。
    """
    state = load_state()
    accepted = {v["doc_id"] for v in state.get("docs", {}).values()
                if v.get("status") in ("succeeded", "partial") and v.get("doc_id")}
    resp = requests.get(f"{DOCS_API}/api/knowledge/nodes", params={"library_id": library_id}, timeout=30)
    resp.raise_for_status()
    nodes = resp.json()
    if isinstance(nodes, dict):
        nodes = nodes.get("nodes") or nodes.get("items") or []
    removed = 0
    for node in nodes:
        if node.get("type") not in (None, "", "document", "file", "doc"):
            continue
        nid = node.get("id") or node.get("doc_id")
        if not nid or nid in accepted:
            continue
        d = requests.delete(f"{DOCS_API}/api/v1/documents/{nid}", headers={"X-API-Key": api_key}, timeout=30)
        if d.status_code < 400:
            removed += 1
            print(f"  清理孤儿文档 {nid}", flush=True)
    print(f"reconcile: 认可 {len(accepted)} 篇，清理 {removed} 篇孤儿/重复", flush=True)
    return removed


def main() -> int:
    ap = argparse.ArgumentParser(description="GDP.pdf 语料入库")
    ap.add_argument("--admin-user", default="")
    ap.add_argument("--admin-password", default="")
    ap.add_argument("--create-only", action="store_true")
    ap.add_argument("--reconcile", action="store_true", help="只按 state 认可 doc_id 清理库内孤儿/重复副本")
    ap.add_argument("--only-idx", default="", help="逗号分隔 parquet 行号（试点子集）")
    ap.add_argument("--poll-timeout", type=int, default=3600)
    ap.add_argument("--concurrency", type=int, default=2)
    args = ap.parse_args()
    load_env()
    admin_user = args.admin_user or os.getenv("ADMIN_USER", "")
    admin_password = args.admin_password or os.getenv("ADMIN_PASSWORD", "")
    if not admin_user or not admin_password:
        print("缺少 ADMIN_USER / ADMIN_PASSWORD")
        return 2

    df = pd.read_parquet(PARQUET)
    state = load_state()
    token = login(admin_user, admin_password)
    state["library_id"] = state.get("library_id") or create_library(token)
    api_key = ""
    if KEYS_FILE.exists() and json.loads(KEYS_FILE.read_text(encoding="utf-8")).get("library_id") == state["library_id"]:
        api_key = json.loads(KEYS_FILE.read_text(encoding="utf-8")).get("api_key", "")
    api_key = api_key or create_key(token, state["library_id"])
    save_json(KEYS_FILE, {"library_id": state["library_id"], "api_key": api_key})
    save_json(STATE_FILE, state)
    print(f"library_id={state['library_id']}", flush=True)
    if args.create_only:
        return 0
    if args.reconcile:
        reconcile(api_key, state["library_id"])
        return 0

    want_idx = {int(x) for x in args.only_idx.split(",") if x.strip() != ""} if args.only_idx else None
    pending = []
    for idx, row in df.iterrows():
        if want_idx is not None and idx not in want_idx:
            continue
        fname = Path(row["pdf_path"]).name
        existing = state["docs"].get(fname, {})
        if existing.get("status") in ("succeeded", "partial"):
            continue
        if not (PDF_DIR / fname).exists():
            advance(state, fname, "", "failed", "PDF 缺失")
            continue
        pending.append((idx, fname))
    save_json(STATE_FILE, state)

    state_lock = threading.Lock()

    def finish(entry):
        idx, fname = entry
        doc_id = ""
        last_error = ""
        started = time.time()
        for attempt in range(3):
            if attempt:
                time.sleep(120 * attempt)
            try:
                doc_id = doc_id or upload(api_key, PDF_DIR / fname)
                status = poll(api_key, doc_id, args.poll_timeout, 5)
                with state_lock:
                    advance(state, fname, doc_id, status, "")
                if status in ("succeeded", "partial"):
                    break
                last_error = f"解析终态 {status}"
            except Exception as exc:  # noqa: BLE001
                last_error = str(exc)
        with state_lock:
            if state["docs"].get(fname, {}).get("status") not in ("succeeded", "partial"):
                advance(state, fname, doc_id, "failed", last_error)
            save_json(STATE_FILE, state)
        print(f"[{idx}] {fname[:16]}… {state['docs'][fname]['status']} {time.time()-started:.0f}s", flush=True)

    with ThreadPoolExecutor(max_workers=args.concurrency) as pool:
        list(pool.map(finish, pending))
    counts: dict = {}
    for rec in state["docs"].values():
        counts[rec["status"]] = counts.get(rec["status"], 0) + 1
    print("进度:", counts, flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
