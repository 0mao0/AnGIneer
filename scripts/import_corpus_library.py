"""语料目录批量导入知识库：子目录→库内文件夹，逐文件 上传 + 触发解析。

plan：先建库（POST /libraries），再跑本脚本。可重跑续传（manifest 记录已上传项）。
解析由 docs-api 编排器异步执行（管理端全阶段：source_prep→…→fts→vectors→graph），
脚本只负责上传与建解析任务；任务排队/并发由编排器管。
**入队顺序 = 文件大小升序**（小册先做：前半程快速出量、厚册沉底；2026-10-13 业主定规）。

用法：
    python scripts/import_corpus_library.py --library std-water --root "资料/正式规范/水运工程"
    python scripts/import_corpus_library.py --library std-water --root ... --dry-run
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import datetime
from pathlib import Path

import requests

REPO_ROOT = Path(__file__).resolve().parents[1]
DOC_EXTS = {".pdf", ".doc", ".docx"}
DEFAULT_MANIFEST = REPO_ROOT / "data" / "scratch" / "corpus_import_manifest.jsonl"


def _session() -> requests.Session:
    s = requests.Session()
    s.trust_env = False  # 绕系统代理（localhost 劫走旧坑，同 eec9438）
    return s


def _log(msg: str) -> None:
    print(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}", flush=True)


def _ensure_tier_folder(session: requests.Session, api: str, library: str, title: str) -> str:
    """库根下找/建层级文件夹，返回 node id。"""
    resp = session.get(f"{api}/api/knowledge/nodes", params={"library_id": library}, timeout=30)
    resp.raise_for_status()
    for node in resp.json():
        if node.get("type") == "folder" and node.get("title") == title and not node.get("parent_id"):
            return node["id"]
    resp = session.post(
        f"{api}/api/knowledge/nodes",
        json={"library_id": library, "title": title, "node_type": "folder"},
        timeout=30,
    )
    resp.raise_for_status()
    return resp.json()["id"]


def _load_done(manifest: Path) -> set:
    done = set()
    if manifest.exists():
        for line in manifest.read_text(encoding="utf-8").splitlines():
            try:
                entry = json.loads(line)
            except json.JSONDecodeError:
                continue
            if entry.get("upload") == "ok":
                done.add(entry["rel"])
    return done


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--library", required=True, help="目标知识库 id（需已存在）")
    ap.add_argument("--root", required=True, help="语料根目录（其子目录=库内文件夹）")
    ap.add_argument("--api", default="http://127.0.0.1:8790", help="docs-api 基地址")
    ap.add_argument("--manifest", default=str(DEFAULT_MANIFEST))
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    root = Path(args.root)
    if not root.is_absolute():
        root = REPO_ROOT / root
    if not root.is_dir():
        print(f"语料目录不存在: {root}")
        return 1

    session = _session()
    api = args.api.rstrip("/")

    resp = session.get(f"{api}/api/knowledge/libraries/{args.library}", timeout=20)
    if resp.status_code != 200:
        print(f"目标库不存在（先建库）: {args.library} → HTTP {resp.status_code}")
        return 1
    _log(f"目标库 {args.library} 就绪（{resp.json().get('name')}）")

    tiers = sorted([d for d in root.iterdir() if d.is_dir()])
    files: list[tuple[Path, str]] = []
    for tier in tiers:
        for f in sorted(tier.rglob("*")):
            if f.is_file() and f.suffix.lower() in DOC_EXTS:
                files.append((f, tier.name))
    # 按文件大小升序排队（小册先做掉）：解析队列按入队序执行，排序即决定解析顺序。
    # 动机（2026-10-13 业主定规）：大批量导入若按文件名序，后半程常剩厚册单篇 1~3 小时，
    # 完成数长时间走平、观感像卡死；小文件先行则前半程快速出量、厚册沉底、总量不变。
    files.sort(key=lambda x: x[0].stat().st_size)
    if files:
        sizes_mb = sorted(f.stat().st_size / 1e6 for f, _ in files)
        mid = sizes_mb[len(sizes_mb) // 2]
        _log(f"排队次序：按文件大小升序（最小 {sizes_mb[0]:.1f}MB / 中位 {mid:.1f}MB / 最大 {sizes_mb[-1]:.1f}MB）")
    _log(f"语料清点：{len(tiers)} 个层级目录，{len(files)} 个文档「{'、'.join(t.name for t in tiers)}」")
    if args.dry_run:
        return 0

    manifest = Path(args.manifest)
    manifest.parent.mkdir(parents=True, exist_ok=True)
    done = _load_done(manifest)
    _log(f"续传基线：manifest 已有 {len(done)} 条成功")

    folder_ids = {tier.name: _ensure_tier_folder(session, api, args.library, tier.name) for tier in tiers}
    _log(f"层级文件夹就绪：{folder_ids}")

    ok = fail = skipped = 0
    for idx, (f, tier) in enumerate(files, 1):
        rel = f.relative_to(root).as_posix()
        if rel in done:
            skipped += 1
            continue
        entry = {"rel": rel, "tier": tier, "at": datetime.now().isoformat(timespec="seconds")}
        try:
            with f.open("rb") as fh:
                up = session.post(
                    f"{api}/api/knowledge/upload",
                    data={"library_id": args.library, "parent_id": folder_ids[tier]},
                    files={"file": (f.name, fh)},
                    timeout=300,
                )
            up.raise_for_status()
            up_json = up.json()
            entry.update({"doc_id": up_json["doc_id"], "file_path": up_json.get("file_path", ""), "upload": "ok"})
            ok += 1
        except Exception as exc:  # noqa: BLE001
            entry.update({"upload": "fail", "error": str(exc)[:300]})
            fail += 1
            _log(f"  !! {rel} 上传失败: {exc}")
        # 解析失败不翻回 upload 状态（否则续跑会重复上传）；失败项可单独重试
        if entry.get("upload") == "ok":
            try:
                pr = session.post(
                    f"{api}/api/knowledge/parse",
                    json={
                        "library_id": args.library,
                        "doc_id": entry["doc_id"],
                        "file_path": entry.get("file_path", ""),
                    },
                    timeout=60,
                )
                pr.raise_for_status()
                entry["parse"] = "ok"
                entry["parse_task"] = pr.json().get("task_id") or pr.json().get("id") or "queued"
            except Exception as exc:  # noqa: BLE001
                entry["parse"] = "fail"
                entry["parse_error"] = str(exc)[:300]
                _log(f"  ~~ {rel} 解析任务创建失败（可重试）: {exc}")
        with manifest.open("a", encoding="utf-8") as mf:
            mf.write(json.dumps(entry, ensure_ascii=False) + "\n")
        if idx % 20 == 0 or idx == len(files):
            _log(f"进度 {idx}/{len(files)}（成功 {ok} 失败 {fail} 跳过 {skipped}）")
        time.sleep(0.05)

    _log(f"完成：上传成功 {ok}，失败 {fail}，续传跳过 {skipped}；manifest={manifest}")
    _log("解析任务已入队（编排器异步执行）；解析全部完成需较长时间，可用管理台「知识→详解」观察状态。")
    return 0 if fail == 0 else 2


if __name__ == "__main__":
    sys.exit(main())
