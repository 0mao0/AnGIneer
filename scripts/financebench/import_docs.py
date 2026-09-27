"""FinanceBench 语料入库：建库、建绑定 API Key、批量上传解析（断点续跑）。

仿 scripts/open_ragbench/import_kb.py，差异：manifest = data/financebench/raw/pdf_manifest.json
（download_pdfs.py 产物，每篇含 doc/status/bytes/blob_sha/pages/link），PDF 在 data/financebench/pdfs/。

用法（本地，仓库根目录）：
  python scripts/financebench/import_docs.py                 # 全量（84 篇）
  python scripts/financebench/import_docs.py --limit 5       # 小批试解析估耗时
  python scripts/financebench/import_docs.py --create-only   # 只建库+Key
"""
import argparse
import json
import os
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import requests

REPO = Path(__file__).resolve().parents[2]
DATA = REPO / "data" / "financebench"
MANIFEST = DATA / "raw" / "pdf_manifest.json"
PDF_DIR = DATA / "pdfs"
STATE_FILE = DATA / "ingest" / "import_state.json"
KEYS_FILE = DATA / "ingest" / "keys.json"
DOCS_API = "http://localhost:8790"
LIBRARY_NAME = "FinanceBench-Open"
KEY_USER_NAME = "financebench-open"
STAGES = "all"


def load_env() -> None:
    try:
        from dotenv import load_dotenv

        load_dotenv(REPO / ".env")
    except ImportError:
        pass


def save_json(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(data, fh, ensure_ascii=False, indent=2)


def load_state() -> dict:
    if STATE_FILE.exists():
        with open(STATE_FILE, encoding="utf-8") as fh:
            return json.load(fh)
    return {"library_id": "", "library_name": LIBRARY_NAME, "docs": {}}


def advance(state: dict, doc: str, doc_id: str, status: str, error: str = "") -> dict:
    prev = state["docs"].get(doc, {})
    retries = prev.get("retries", 0) + (1 if status == "failed" else 0)
    state["docs"][doc] = {"doc_id": doc_id, "status": status, "retries": retries, "error": error}
    return state


def login(token_ep: str, user: str, password: str) -> str:
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
        json={"name": LIBRARY_NAME, "description": "FinanceBench 开源子集语料（84 篇 SEC PDF，官方 doc_link）"},
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


def upload(api_key: str, pdf_path: Path, stages: str = STAGES) -> str:
    with open(pdf_path, "rb") as fh:
        resp = requests.post(
            f"{DOCS_API}/api/v1/documents/parse",
            headers={"X-API-Key": api_key},
            params={"stages": stages},
            files={"file": (pdf_path.name, fh, "application/pdf")},
            timeout=60,
        )
    resp.raise_for_status()
    doc_id = resp.json().get("doc_id")
    if not doc_id:
        raise RuntimeError(f"parse 响应缺少 doc_id: {resp.json()}")
    return doc_id


def poll_raw_parse(api_key: str, doc_id: str, timeout: int, interval: int) -> bool:
    """预取段：轮询 /api/knowledge/documents/{doc_id}/stages 的 raw_parse 是否 completed。
    company ~90s/篇、dgx 挂死兜底最迟 ~620s，timeout 给到 1500s。"""
    deadline = time.time() + timeout
    transient = 0
    while time.time() < deadline:
        try:
            resp = requests.get(f"{DOCS_API}/api/knowledge/documents/{doc_id}/stages", headers={"X-API-Key": api_key}, timeout=30)
            resp.raise_for_status()
            rows = resp.json().get("stages") or []
            transient = 0
        except (requests.RequestException, ValueError) as exc:
            transient += 1
            if transient >= 12:
                return False
            time.sleep(max(interval, 10))
            continue
        by_stage = {r.get("stage"): (r.get("status") or "").lower() for r in rows}
        st = by_stage.get("raw_parse")
        if st == "completed":
            return True
        if st in ("failed", "cancelled"):
            return False
        time.sleep(interval)
    return False


def resume_remaining(api_key: str, doc_id: str) -> bool:
    """从 popo 起调度剩余全链（复用 raw_parse 产物）。
    不用 /resume 端点：它按原始提交 stages 子集算续跑范围（预取篇的原始范围只有
    raw_parse → remaining 空 → 假 completed 不调度任何任务，2026-09-27 实踩）。
    正确入口 = cancel 僵尸 task → stages/popo/retry（管理面板同款语义：N 起重跑，前置产物复用）。"""
    import sqlite3 as _sq

    con = _sq.connect(str(REPO / "data" / "parse_records.sqlite"))
    row = con.execute(
        "SELECT task_id FROM parse_records WHERE doc_id=? ORDER BY id DESC LIMIT 1", (doc_id,)
    ).fetchone()
    con.close()
    task_id = row[0] if row else ""
    if task_id and not task_id.startswith("pending-"):
        try:
            requests.post(f"{DOCS_API}/api/knowledge/parse/{task_id}/cancel",
                          headers={"X-API-Key": api_key}, timeout=30)
        except requests.RequestException:
            pass
    resp = requests.post(f"{DOCS_API}/api/knowledge/documents/{doc_id}/stages/popo/retry",
                         headers={"X-API-Key": api_key}, timeout=60)
    resp.raise_for_status()
    return True


def poll(api_key: str, doc_id: str, timeout: int, interval: int) -> str:
    """轮询容忍瞬时故障（dev 热重载/网关毛刺）：连败 <12 次不判死，run_eval.poll_run 同纪律。
    注意：docs-api 热重载会掐断在跑的解析，服务端 startup_recovery 会续跑同 doc_id，
    因此轮询失败重连后仍查同一 doc_id 是正确的，不要改成重新上传。"""
    deadline = time.time() + timeout
    transient = 0
    while time.time() < deadline:
        try:
            resp = requests.get(f"{DOCS_API}/api/v1/documents/{doc_id}/status", headers={"X-API-Key": api_key}, timeout=30)
            resp.raise_for_status()
            transient = 0
        except (requests.RequestException, ValueError) as exc:
            transient += 1
            if transient >= 12:
                raise
            print(f"  [poll] 瞬时失败 x{transient}: {exc}", flush=True)
            time.sleep(max(interval, 10))
            continue
        status = (resp.json().get("status") or "").lower()
        if status == "completed":
            return "succeeded"
        if status == "partial":
            return "partial"
        if status in ("failed", "cancelled"):
            # docs-api 重启窗口里 startup_recovery 会续跑被判 failed 的任务并翻转状态；
            # 等 30s 复核一次，防误判死导致整篇重新上传（实测竞态 2026-09-27）。
            time.sleep(30)
            try:
                resp2 = requests.get(f"{DOCS_API}/api/v1/documents/{doc_id}/status", headers={"X-API-Key": api_key}, timeout=30)
                status2 = (resp2.json().get("status") or "").lower()
            except requests.RequestException:
                status2 = status
            if status2 in ("completed",):
                return "succeeded"
            if status2 == "partial":
                return "partial"
            if status2 in ("processing", "queued", "pending"):
                continue
            return "failed"
        time.sleep(interval)
    return "timeout"


def main() -> int:
    parser = argparse.ArgumentParser(description="FinanceBench 语料入库")
    parser.add_argument("--admin-user", default=os.getenv("ADMIN_USER", ""))
    parser.add_argument("--admin-password", default=os.getenv("ADMIN_PASSWORD", ""))
    parser.add_argument("--limit", type=int, default=0, help="只处理前 N 篇（试解析用）")
    parser.add_argument("--only", default="", help="逗号分隔 doc 名白名单（试解析指定篇目）")
    parser.add_argument("--create-only", action="store_true")
    parser.add_argument("--poll-timeout", type=int, default=3600, help="单篇解析轮询上限秒数（549 页 10-K 含 PoPo 留足）")
    parser.add_argument("--concurrency", type=int, default=2, help="文档级并发（需配合 .env POPO/MINERU_MAX_CONCURRENCY）")
    parser.add_argument("--prefetch", action="store_true", default=True, help="先全量预取 raw_parse 再跑后段（默认开）")
    parser.add_argument("--no-prefetch", dest="prefetch", action="store_false")
    parser.add_argument("--prefetch-concurrency", type=int, default=4, help="预取段并发（服务端 MinerU 信号量另有上限）")
    args = parser.parse_args()
    load_env()
    args.admin_user = args.admin_user or os.getenv("ADMIN_USER", "")
    args.admin_password = args.admin_password or os.getenv("ADMIN_PASSWORD", "")
    if not args.admin_user or not args.admin_password:
        print("缺少 ADMIN_USER / ADMIN_PASSWORD")
        return 2

    # manifest = pdf_manifest.json：{doc_name: {doc,status,bytes,blob_sha,pages,link}}
    manifest_map = json.loads(MANIFEST.read_text(encoding="utf-8"))
    manifest = sorted(manifest_map.values(), key=lambda r: r["doc"])
    state = load_state()
    token = login(DOCS_API, args.admin_user, args.admin_password)
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

    only = {s.strip() for s in args.only.split(",") if s.strip()}
    pending = []
    for rec in manifest:
        doc = rec["doc"]
        if only and doc not in only:
            continue
        if rec.get("status") != "ok":
            print(f"[{doc}] 跳过：下载状态 {rec.get('status')}", flush=True)
            continue
        existing = state["docs"].get(doc, {})
        if existing.get("status") in ("succeeded", "partial"):
            continue
        pending.append(rec)
    if args.limit:
        pending = pending[: args.limit]

    state_lock = threading.Lock()

    def prefetch(rec) -> None:
        """阶段 1：把 raw_parse（MinerU）尽快提交到 company 端点跑完，
        不被后段 PoPo（DGX）慢速串行拖住提交节奏（2026-09-27 实测解耦提速）。"""
        doc = rec["doc"]
        entry = state["docs"].get(doc, {})
        doc_id = entry.get("doc_id") or ""
        if doc_id and poll_raw_parse(api_key, doc_id, 60, 5):
            return
        pdf_path = PDF_DIR / f"{doc}.pdf"
        if not pdf_path.exists():
            with state_lock:
                advance(state, doc, "", "failed", f"PDF 不存在: {pdf_path.name}")
                save_json(STATE_FILE, state)
            return
        for attempt in range(2):
            try:
                doc_id = upload(api_key, pdf_path, stages="source_prep,convert,raw_parse")
                with state_lock:
                    advance(state, doc, doc_id, "prefetched" if attempt == 0 else "pending", "")
                    save_json(STATE_FILE, state)
                if poll_raw_parse(api_key, doc_id, 1500, 5):
                    print(f"[{doc}] raw_parse 预取完成 ({attempt + 1})", flush=True)
                    return
            except Exception as exc:  # noqa: BLE001
                print(f"[{doc}] 预取异常 ({attempt + 1}): {exc}", flush=True)

    def finish(rec) -> None:
        """阶段 2：从 raw_parse 断点续跑剩余阶段（resume 跳过 completed），轮询终态。"""
        doc = rec["doc"]
        entry = state["docs"].get(doc, {})
        doc_id = entry.get("doc_id") or ""
        if not doc_id:
            return  # 预取失败（PDF 缺失等）已由 prefetch 标 failed
        last_error = ""
        started = time.time()
        for attempt in range(3):
            if attempt:
                # 文档级退避重试（请求级重试已关，防在共享 GPU 上放大故障；DGX 2026-09-27）
                time.sleep(120 * attempt)
            try:
                if not poll_raw_parse(api_key, doc_id, 60, 5):
                    last_error = "raw_parse 未完成"
                    continue
                resume_remaining(api_key, doc_id)
                status = poll(api_key, doc_id, args.poll_timeout, 5)
                with state_lock:
                    advance(state, doc, doc_id, status, "")
                if status in ("succeeded", "partial"):
                    break
                last_error = f"解析终态: {status}"
            except Exception as exc:  # noqa: BLE001
                last_error = str(exc)
        with state_lock:
            if state["docs"].get(doc, {}).get("status") not in ("succeeded", "partial"):
                advance(state, doc, doc_id, "failed", last_error)
            save_json(STATE_FILE, state)
        print(f"[{doc}] {state['docs'][doc]['status']} 用时 {time.time() - started:.0f}s", flush=True)

    # 启动对账：worker 曾判死但服务端（startup_recovery 续跑）实际已完成的篇目，
    # 直接采纳实况终态，避免整篇重新上传重解析（2026-09-27 竞态教训）。
    try:
        resp = requests.get(f"{DOCS_API}/api/knowledge/nodes", params={"library_id": state["library_id"]}, timeout=30)
        nodes = resp.json()
        if isinstance(nodes, dict):
            nodes = nodes.get("nodes") or nodes.get("items") or []
        for node in nodes:
            title = (node.get("title") or "").removesuffix(".pdf")
            nstatus = (node.get("status") or "").lower()
            if node.get("type") not in (None, "", "document", "file", "doc"):
                continue
            if title in state["docs"] and state["docs"][title]["status"] == "failed" and nstatus in ("completed", "partial"):
                advance(state, title, node.get("id") or state["docs"][title].get("doc_id", ""), "partial" if nstatus == "partial" else "succeeded", "启动对账采纳服务端实况")
        save_json(STATE_FILE, state)
    except requests.RequestException as exc:
        print(f"启动对账跳过（查询失败）: {exc}", flush=True)
    # 阶段级假死采纳：node.status 滞后/误判，但 doc_parse_stages 显示核心链
    # （raw_parse/structure/fts/vectors）全部完成 → 采纳 partial，不再 resume/重传。
    # （2026-09-27 三篇 COCACOLA/BOEING 因 poll 时序 + resume 409 被误标 failed 的教训）
    import sqlite3 as _sqlite3

    try:
        from docs_core.paths import resolve_knowledge_meta_db_path
    except ImportError:
        sys.path.insert(0, str(REPO / "services" / "docs-core" / "src"))
        from docs_core.paths import resolve_knowledge_meta_db_path

    _con = _sqlite3.connect(str(resolve_knowledge_meta_db_path()))
    _con.row_factory = _sqlite3.Row
    for _doc, _v in list(state["docs"].items()):
        if _v.get("status") in ("failed", "pending", "timeout") and _v.get("doc_id"):
            _d = {r["stage"]: r["status"] for r in _con.execute(
                "SELECT stage,status FROM doc_parse_stages WHERE doc_id=?", (_v["doc_id"],))}
            if all(_d.get(x) in ("completed", "skipped") for x in ("raw_parse", "structure", "fts", "vectors")):
                advance(state, _doc, _v["doc_id"], "partial", "阶段级采纳：核心链完成，软阶段失败不算死")
    save_json(STATE_FILE, state)
    pending = [rec for rec in pending if state["docs"].get(rec["doc"], {}).get("status") not in ("succeeded", "partial")]

    if args.prefetch:
        # 两段式：先把所有 pending 的 raw_parse（company）全部预取完，再进 PoPo 后段
        with ThreadPoolExecutor(max_workers=args.prefetch_concurrency) as pool:
            list(pool.map(prefetch, pending))
    with ThreadPoolExecutor(max_workers=args.concurrency) as pool:
        list(pool.map(finish, pending))
    counts = {}
    for rec in state["docs"].values():
        counts[rec["status"]] = counts.get(rec["status"], 0) + 1
    print("进度:", counts, flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
