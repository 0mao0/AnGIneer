"""存量文档图描述回填：逐篇从 figure_describe 阶段重试（连带 fts/vectors/graph 重跑）。

stage retry 语义（docs_routes.py）：从指定阶段起连同后续阶段一起重跑，前置产物复用。
因此每篇只需一次 retry figure_describe，即可完成「生成描述 → 重建索引」。

鉴权：
- 触发 retry：/api/knowledge/* 走管理员 Bearer token（ADMIN_USER/ADMIN_PASSWORD，.env）
- 轮询状态：/api/v1/documents/{doc_id}/status 走 X-API-Key（keys.json，绑定 lib-b07ed174）

进度持久化到 backfill_figure_state.json（断点续跑）。
"""
import argparse
import json
import os
import sys
import time
from pathlib import Path

import requests

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from open_ragbench import common  # noqa: E402

STATE_FILE = common.SUBSET_DIR / "backfill_figure_state.json"


def _load_env() -> None:
    try:
        from dotenv import load_dotenv
    except ImportError:
        return
    load_dotenv(common.REPO_ROOT / ".env")


def login_admin(ep: common.Endpoints, username: str, password: str) -> str:
    resp = requests.post(ep.login, json={"username": username, "password": password}, timeout=30)
    resp.raise_for_status()
    return resp.json()["token"]


def trigger_retry(ep: common.Endpoints, token: str, doc_id: str, stage_key: str) -> str:
    resp = requests.post(
        f"{ep.docs_api}/api/knowledge/documents/{doc_id}/stages/{stage_key}/retry",
        headers={"Authorization": f"Bearer {token}"},
        timeout=60,
    )
    if resp.status_code == 400 and "正在解析中" in resp.text:
        raise RuntimeError(f"文档正在解析中，跳过: {doc_id}")
    resp.raise_for_status()
    data = resp.json()
    task_id = data.get("id") or data.get("task_id") or ""
    if not task_id:
        raise RuntimeError(f"retry 响应缺少任务 ID: {data}")
    return task_id


def poll_doc_status(ep: common.Endpoints, api_key: str, doc_id: str, timeout: int, interval: int) -> str:
    deadline = time.time() + timeout
    while time.time() < deadline:
        resp = requests.get(
            ep.status(doc_id), headers={"X-API-Key": api_key}, timeout=30
        )
        resp.raise_for_status()
        status = (resp.json().get("status") or "").lower()
        if status == "completed":
            return "succeeded"
        if status == "partial":
            return "partial"
        if status in ("failed", "cancelled"):
            return "failed"
        time.sleep(interval)
    return "timeout"


def load_state() -> dict:
    if STATE_FILE.exists():
        return common.load_json(STATE_FILE)
    return {"done": {}, "failed": {}}


def save_state(state: dict) -> None:
    common.save_json(STATE_FILE, state)


def main() -> int:
    parser = argparse.ArgumentParser(description="存量文档图描述回填")
    parser.add_argument("--docs-api", default="http://localhost:8790")
    parser.add_argument("--doc-ids", default="", help="逗号分隔子集（默认 import_state 全部 succeeded）")
    parser.add_argument("--poll-timeout", type=int, default=7200)
    parser.add_argument("--poll-interval", type=int, default=10)
    args = parser.parse_args()
    _load_env()

    admin_user = os.getenv("ADMIN_USER", "")
    admin_password = os.getenv("ADMIN_PASSWORD", "")
    if not admin_user or not admin_password:
        print("缺少 ADMIN_USER/ADMIN_PASSWORD")
        return 2
    if not common.KEYS_FILE.exists():
        print("keys.json 不存在，请先运行 import_kb.py")
        return 2
    api_key = common.load_json(common.KEYS_FILE).get("api_key", "")
    if not api_key:
        print("keys.json 缺少 api_key")
        return 2

    if args.doc_ids:
        doc_ids = [d.strip() for d in args.doc_ids.split(",") if d.strip()]
    else:
        state = common.load_json(common.IMPORT_STATE)
        papers = state.get("papers") or {}
        doc_ids = sorted({
            info.get("doc_id") for info in papers.values()
            if isinstance(info, dict) and info.get("status") in ("succeeded", "partial") and info.get("doc_id")
        })

    ep = common.Endpoints(docs_api=args.docs_api)
    token = login_admin(ep, admin_user, admin_password)
    progress = load_state()
    for doc_id in doc_ids:
        if doc_id in progress["done"] or doc_id in progress["failed"]:
            print(f"[{doc_id}] 已处理，跳过", flush=True)
            continue
        try:
            task_id = trigger_retry(ep, token, doc_id, "figure_describe")
            print(f"[{doc_id}] retry 任务 {task_id} 已提交", flush=True)
            status = poll_doc_status(ep, api_key, doc_id, args.poll_timeout, args.poll_interval)
            if status in ("succeeded", "partial"):
                progress["done"][doc_id] = {"task_id": task_id, "status": status}
                print(f"[{doc_id}] {status}", flush=True)
            else:
                progress["failed"][doc_id] = {"task_id": task_id, "status": status}
                print(f"[{doc_id}] 失败: {status}", flush=True)
        except Exception as exc:  # noqa: BLE001
            progress["failed"][doc_id] = {"error": f"{type(exc).__name__}: {exc}"}
            print(f"[{doc_id}] 异常: {exc}", flush=True)
        save_state(progress)

    print(f"回填完成: done={len(progress['done'])} failed={len(progress['failed'])}")
    return 0 if not progress["failed"] else 1


if __name__ == "__main__":
    sys.exit(main())
