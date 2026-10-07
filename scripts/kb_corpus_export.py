"""语料包 export（plan-standards-kb-corpus-package Stage D1）。

把一个库组（默认 standards）的完整知识库打成可跨环境导入的包：

<out>/<group>-<date>/
├─ manifest.json      # schema_version/embed_model/page_base=0/库清单/全部落包文件 sha256
├─ registry/rows.json # library_registry + library_groups 行原样（含 collection/sqlite_file 相对路径）
├─ meta/rows.json     # 共享 meta 库里这些库的 nodes + tree_node 行（meta 文件本身不进包，
│                     #   目标环境 meta 里已有别的库，只能随行合并）
├─ files/<相对 data 根原路径>   # 组 sqlite（先 WAL checkpoint）+ libraries/<id>/ 文档树
└─ qdrant/<collection>.snapshot # --no-vectors 跳过（对方自嵌或后续 rebuild_vectors）

embed_model 取导出环境 EMBEDDING_CONFIGS 首项 model 名——import 侧三硬闸之一的对账基准。

用法（本地，需 ANGINEER_DATA_ROOT/.env 就绪）：
    python scripts/kb_corpus_export.py --libs lib-std-road,lib-std-water
    python scripts/kb_corpus_export.py --libs ... --no-vectors --out data/packages/out
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sqlite3
import sys
from contextlib import closing
import tarfile
from datetime import datetime, timezone, timedelta
from pathlib import Path
from urllib import request as urlrequest

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "services" / "docs-core" / "src"))

from docs_core.library_registry import REGISTRY_DB_NAME, resolve_data_root  # noqa: E402

SCHEMA_VERSION = 1
PAGE_BASE = 0  # canonical 页码 0-based，交付说明写死（三雷之一）


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def embed_model_from_env() -> str:
    import os

    raw = os.getenv("EMBEDDING_CONFIGS", "").strip()
    if not raw:
        return ""
    try:
        first = json.loads(raw)[0]
    except (ValueError, IndexError):
        return ""
    return str(first.get("model") or first.get("model_name") or "")


def read_registry(data_root: Path, libs: list[str]) -> tuple[list[dict], list[dict]]:
    # 只读用途开普通连接：URI mode=ro 对非 ASCII 路径（中文用户目录）须百分号编码，实踩打不开
    with closing(sqlite3.connect(data_root / REGISTRY_DB_NAME)) as conn:
        conn.row_factory = sqlite3.Row
        marks = ",".join("?" * len(libs))
        libraries = [dict(r) for r in conn.execute(f"SELECT * FROM library_registry WHERE library_id IN ({marks})", libs)]
        groups_found = sorted({row["group_name"] for row in libraries})
        if not groups_found:
            raise SystemExit(f"registry 里没有这些库: {libs}")
        gmarks = ",".join("?" * len(groups_found))
        groups = [dict(r) for r in conn.execute(f"SELECT * FROM library_groups WHERE group_name IN ({gmarks})", groups_found)]
    missing = set(libs) - {row["library_id"] for row in libraries}
    if missing:
        raise SystemExit(f"registry 缺行: {sorted(missing)}")
    return libraries, groups


def read_meta_rows(data_root: Path, libs: list[str]) -> dict:
    """共享 meta 库里按 library_id 摘 nodes/tree_node 行。"""
    meta_db = data_root / "knowledge" / "knowledge_meta.sqlite"
    if not meta_db.exists():
        raise SystemExit(f"meta 库不存在: {meta_db}")
    with closing(sqlite3.connect(meta_db)) as conn:
        conn.row_factory = sqlite3.Row
        marks = ",".join("?" * len(libs))
        nodes = [dict(r) for r in conn.execute(f"SELECT * FROM nodes WHERE library_id IN ({marks})", libs)]
        tree = [dict(r) for r in conn.execute(f"SELECT * FROM tree_node WHERE scope_id IN ({marks})", libs)]
    return {"nodes": nodes, "tree_nodes": tree}


def collect_files(data_root: Path, out_root: Path, libraries: list[dict]) -> list[str]:
    """把组 sqlite 与 documents 树按原相对路径复制进包 files/。返回相对 data 根的路径清单。"""
    import shutil

    sqlite_files = sorted({row["sqlite_file"] for row in libraries})
    staged: list[str] = []
    for rel in sqlite_files:
        src = data_root / rel
        if not src.exists():
            print(f"  ! 组 sqlite 缺失，跳过: {rel}")
            continue
        conn = sqlite3.connect(src)
        try:
            conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")  # WAL 四坑：不 checkpoint 拷出去缺最近写入
        finally:
            conn.close()  # Windows 上连接不关=文件锁住，后续 copy/清理全挂
        for part in (src, Path(str(src) + "-wal"), Path(str(src) + "-shm")):
            if part.exists() and part.stat().st_size > 0:
                dst = out_root / "files" / part.relative_to(data_root)
                dst.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(part, dst)
        staged.append(rel)
    for row in libraries:
        lib_root = data_root / "knowledge" / "libraries" / row["library_id"]
        if not lib_root.is_dir():
            print(f"  ! 库目录缺失，跳过: {row['library_id']}")
            continue
        rel_root = lib_root.relative_to(data_root).as_posix()
        dst_root = out_root / "files" / rel_root
        shutil.copytree(lib_root, dst_root, dirs_exist_ok=True)
        staged.append(rel_root)
    return staged


def qdrant_snapshot(collection: str, out_dir: Path) -> Path:
    import os

    base = os.getenv("QDRANT_URL", "http://localhost:6333").rstrip("/")
    req = urlrequest.Request(f"{base}/collections/{collection}/snapshots", method="POST")
    with urlrequest.urlopen(req, timeout=60) as resp:
        name = json.load(resp)["result"]["name"]
    target = out_dir / f"{collection}.snapshot"
    target.parent.mkdir(parents=True, exist_ok=True)
    with urlrequest.urlopen(f"{base}/collections/{collection}/snapshots/{name}", timeout=600) as resp, target.open("wb") as fh:
        fh.write(resp.read())
    return target


def build_package(libs: list[str], out_parent: Path, with_vectors: bool, pack_tar: bool) -> Path:
    data_root = resolve_data_root()
    now = datetime.now(timezone(timedelta(hours=8)))
    group = read_registry(data_root, libs)[0][0]["group_name"]
    out_root = out_parent / f"{group}-{now.strftime('%Y%m%d')}-{libs[0]}"

    (out_root / "registry").mkdir(parents=True)
    (out_root / "meta").mkdir(parents=True)
    libraries, groups = read_registry(data_root, libs)
    (out_root / "registry" / "rows.json").write_text(
        json.dumps({"libraries": libraries, "groups": groups}, ensure_ascii=False, indent=1), encoding="utf-8"
    )
    (out_root / "meta" / "rows.json").write_text(
        json.dumps(read_meta_rows(data_root, libs), ensure_ascii=False), encoding="utf-8"
    )
    staged = collect_files(data_root, out_root, libraries)

    collections: list[str] = []
    if with_vectors:
        for col in sorted({row["collection"] for row in libraries}):
            path = qdrant_snapshot(col, out_root / "qdrant")
            print(f"  snapshot {col} → {path.name} ({path.stat().st_size // 1048576}MB)")
            collections.append(col)

    file_index: dict[str, str] = {}
    for f in sorted(out_root.rglob("*")):
        if f.is_file() and f.name != "manifest.json":
            file_index[f.relative_to(out_root).as_posix()] = sha256(f)
    manifest = {
        "schema_version": SCHEMA_VERSION,
        "created_at": now.isoformat(),
        "group": group,
        "embed_model": embed_model_from_env(),
        "page_base": PAGE_BASE,
        "collections": collections,
        "libraries": [{"library_id": r["library_id"], "sqlite_file": r["sqlite_file"], "collection": r["collection"]} for r in libraries],
        "staged_roots": staged,
        "files": file_index,
    }
    (out_root / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"包: {out_root}  文件={len(file_index)}  embed_model={manifest['embed_model'] or '(空!)'}")
    if pack_tar:
        tar_path = out_parent / f"{out_root.name}.tar"
        with tarfile.open(tar_path, "w") as tf:
            tf.add(out_root, arcname=out_root.name)
        print(f"tar: {tar_path} ({tar_path.stat().st_size // 1048576}MB)")
    return out_root


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--libs", required=True, help="逗号分隔 library_id")
    parser.add_argument("--out", default=str(REPO_ROOT / "data" / "scratch" / "corpus-packages"))
    parser.add_argument("--no-vectors", action="store_true", help="不打 qdrant snapshot（目标自嵌向量）")
    parser.add_argument("--tar", action="store_true", help="顺带打 tar 便于 scp")
    args = parser.parse_args()
    build_package([s.strip() for s in args.libs.split(",") if s.strip()], Path(args.out), not args.no_vectors, args.tar)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
