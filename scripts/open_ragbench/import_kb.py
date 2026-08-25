"""建库、建绑定 API Key、批量上传解析。"""
import argparse
import json
import os
import sys
import time
from pathlib import Path

import requests

from open_ragbench import common


def load_or_init_state():
    if common.IMPORT_STATE.exists():
        return common.load_json(common.IMPORT_STATE)
    return {"library_id": "", "papers": {}}


def advance_state(state, paper_id, doc_id, status, error=""):
    next_state = json.loads(json.dumps(state))
    papers = next_state.setdefault("papers", {})
    prev = papers.get(paper_id, {})
    retries = prev.get("retries", 0)
    if status == "failed":
        retries += 1
    papers[paper_id] = {"doc_id": doc_id, "status": status, "retries": retries, "error": error}
    return next_state


def login_admin(ep: common.Endpoints, username: str, password: str) -> str:
    resp = requests.post(ep.login, json={"username": username, "password": password}, timeout=30)
    resp.raise_for_status()
    return resp.json()["token"]


def create_library(ep: common.Endpoints, name: str) -> str:
    resp = requests.post(ep.libraries, json={"name": name, "description": "Open RAG Benchmark 子集"}, timeout=30)
    resp.raise_for_status()
    return resp.json()["library_id"]


def create_key(ep: common.Endpoints, token: str, library_id: str) -> str:
    resp = requests.post(
        ep.api_keys,
        headers={"Authorization": f"Bearer {token}"},
        json={"user_name": common.KEY_USER_NAME, "scope": "doc", "library_id": library_id},
        timeout=30,
    )
    resp.raise_for_status()
    return resp.json()["api_key"]


def upload_pdf(ep: common.Endpoints, api_key: str, pdf_path: Path, stages: str) -> str:
    with open(pdf_path, "rb") as fh:
        resp = requests.post(
            ep.parse,
            headers={"X-API-Key": api_key},
            params={"stages": stages},
            files={"file": (pdf_path.name, fh, "application/pdf")},
            timeout=60,
        )
    resp.raise_for_status()
    data = resp.json()
    doc_id = data.get("doc_id")
    if not doc_id:
        raise RuntimeError(f"parse 响应缺少 doc_id: {data}")
    return doc_id


def poll_status(ep: common.Endpoints, api_key: str, doc_id: str, timeout: int, interval: int) -> str:
    deadline = time.time() + timeout
    while time.time() < deadline:
        resp = requests.get(ep.status(doc_id), headers={"X-API-Key": api_key}, timeout=30)
        resp.raise_for_status()
        status = (resp.json().get("status") or "").lower()
        if status == "completed":
            return "succeeded"
        if status in ("failed", "cancelled"):
            return "failed"
        time.sleep(interval)
    return "timeout"


def run_import(
    ep: common.Endpoints,
    admin_user: str,
    admin_password: str,
    manifest,
    state,
    stages: str = common.STAGES,
    pdf_dir: Path = common.PDF_DIR,
    poll_interval: int = 5,
    poll_timeout: int = 1800,
    api_key: str = "",
):
    state = json.loads(json.dumps(state))
    token = login_admin(ep, admin_user, admin_password)
    library_id = state.get("library_id") or create_library(ep, common.LIBRARY_NAME)
    state["library_id"] = library_id
    api_key = api_key or create_key(ep, token, library_id)

    for paper in manifest.get("papers", []):
        paper_id = paper["paper_id"]
        if paper.get("is_hard_negative"):
            continue
        existing = state.get("papers", {}).get(paper_id)
        if existing and existing.get("status") == "succeeded":
            continue
        pdf_path = pdf_dir / f"{paper_id}.pdf"
        if not pdf_path.exists():
            state = advance_state(state, paper_id, "", "failed", f"PDF 不存在: {pdf_path.name}")
            continue
        state = advance_state(state, paper_id, "", "pending", "")
        last_error = ""
        for _ in range(3):
            try:
                doc_id = upload_pdf(ep, api_key, pdf_path, stages)
                state = advance_state(state, paper_id, doc_id, "pending", "")
                status = poll_status(ep, api_key, doc_id, poll_timeout, poll_interval)
                state = advance_state(state, paper_id, doc_id, status, "")
                if status == "succeeded":
                    break
                last_error = f"解析终态: {status}"
            except Exception as exc:
                last_error = str(exc)
        if state["papers"][paper_id]["status"] != "succeeded":
            state = advance_state(state, paper_id, state["papers"][paper_id].get("doc_id", ""), "failed", last_error)
    return state, api_key


def main() -> int:
    parser = argparse.ArgumentParser(description="建库并导入 Open RAG Benchmark 子集")
    parser.add_argument("--docs-api", default="http://localhost:8790")
    parser.add_argument("--admin-user", default=os.getenv("ADMIN_USER", ""))
    parser.add_argument("--admin-password", default=os.getenv("ADMIN_PASSWORD", ""))
    args = parser.parse_args()
    if not args.admin_user or not args.admin_password:
        print("缺少管理员凭据：请设置 ADMIN_USER / ADMIN_PASSWORD 或传 --admin-user/--admin-password")
        return 2

    common.ensure_dirs()
    manifest = common.load_json(common.SUBSET_MANIFEST)
    state = load_or_init_state()
    existing_key = ""
    if common.KEYS_FILE.exists():
        saved = common.load_json(common.KEYS_FILE)
        if saved.get("library_id") == state.get("library_id"):
            existing_key = saved.get("api_key", "")
    state, api_key = run_import(
        common.Endpoints(args.docs_api),
        args.admin_user,
        args.admin_password,
        manifest,
        state,
        api_key=existing_key,
    )
    common.save_json(common.IMPORT_STATE, state)
    common.save_json(common.KEYS_FILE, {"library_id": state["library_id"], "api_key": api_key})
    print("导入进度:", common.load_json(common.IMPORT_STATE))
    return 0


if __name__ == "__main__":
    sys.exit(main())
