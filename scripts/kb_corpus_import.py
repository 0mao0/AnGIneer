"""语料包 import（plan-standards-kb-corpus-package Stage D2）。

把 kb_corpus_export 产出的包导入本环境 data 根。预检三硬闸任一不过即中止：

1. embed 对账：manifest.embed_model 必须等于现网 EMBEDDING_CONFIGS 首项 model；
   不等时仅 --reembed（导入后自嵌向量、跳过快照恢复）才放行；
2. 冲突：包内 library_id / nodes.id 与目标库重名即拒绝（覆盖不可逆）；
3. schema_version：不认识的包版本直接拒收。

外加文件完整性闸：manifest.files 全量 sha256 复核，缺文件/被改动都中止。

落盘顺序：files/ 按相对 data 根路径放回 → meta 行 INSERT → registry 行 INSERT
→ qdrant snapshot 恢复（--reembed 时跳过并提示 rebuild_vectors.py）→ 打印验收清单
（重启 aichat-api + 逐库探针——生产读穿未发版，现行 SOP 必须重启）。

用法（生产在容器内跑，env 已就绪）：
    python scripts/kb_corpus_import.py --package /path/to/standards-20261007-xxx --dry-run
    python scripts/kb_corpus_import.py --package ... --apply
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sqlite3
import sys
import tarfile
from contextlib import closing
from pathlib import Path
from urllib import request as urlrequest

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "services" / "docs-core" / "src"))

from docs_core.library_registry import REGISTRY_DB_NAME, resolve_data_root  # noqa: E402

SUPPORTED_SCHEMA = {1}


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


# ---- 三硬闸 + 完整性（纯函数，tests/unit/test_unit_kb_corpus_import.py 锁契约） ----

def check_schema_gate(manifest: dict) -> None:
    if manifest.get("schema_version") not in SUPPORTED_SCHEMA:
        raise SystemExit(f"不支持的包 schema_version={manifest.get('schema_version')}，先升级导入脚本")


def embed_model_from_env() -> str:
    raw = os.getenv("EMBEDDING_CONFIGS", "").strip()
    if not raw:
        return ""
    try:
        first = json.loads(raw)[0]
    except (ValueError, IndexError):
        return ""
    return str(first.get("model") or first.get("model_name") or "")


def check_embed_gate(manifest: dict, env_model: str, allow_reembed: bool) -> bool:
    """返回 True = 需要重嵌（跳过快照）。模型对不上又没授权重嵌 → 中止。"""
    pkg_model = str(manifest.get("embed_model") or "")
    if not pkg_model:
        raise SystemExit("包 manifest 没记录 embed_model，无法对账——重出包")
    if pkg_model == env_model:
        return False
    if not allow_reembed:
        raise SystemExit(
            f"embed 模型不一致：包={pkg_model} 现网={env_model or '(EMBEDDING_CONFIGS 未设置)'}。"
            "向量跨模型复用=检索静默错乱。要么对齐模型，要么 --reembed 用现网模型自嵌。"
        )
    return True


def check_conflict_gate(target_conn: sqlite3.Connection, package_libraries: list[dict], package_node_ids: list[str]) -> list[str]:
    """按传入的两类键查冲突；空键类别跳过（不同键住在不同库：registry.sqlite / 共享 meta）。"""
    clashes: list[str] = []
    if package_libraries:
        lib_marks = ",".join("?" * len(package_libraries))
        existing_libs = {
            r[0]
            for r in target_conn.execute(
                f"SELECT library_id FROM library_registry WHERE library_id IN ({lib_marks})",
                [row["library_id"] for row in package_libraries],
            )
        }
        clashes += sorted(existing_libs)
    if package_node_ids:
        id_marks = ",".join("?" * len(package_node_ids))
        existing_nodes = {
            r[0] for r in target_conn.execute(f"SELECT id FROM nodes WHERE id IN ({id_marks})", package_node_ids)
        }
        clashes += sorted(existing_nodes)
    return clashes


def check_package_files(package_root: Path, manifest: dict) -> None:
    files = manifest.get("files") or {}
    if not files:
        raise SystemExit("manifest.files 为空——包不完整")
    for rel, digest in files.items():
        f = package_root / rel
        if not f.is_file():
            raise SystemExit(f"缺文件: {rel}")
        if sha256(f) != digest:
            raise SystemExit(f"sha256 不符: {rel}（传输损坏或包被改动）")


# ---- 落盘 ----

def stage_files(package_root: Path, data_root: Path) -> int:
    count = 0
    files_dir = package_root / "files"
    for src in sorted(p for p in files_dir.rglob("*") if p.is_file()):
        dst = data_root / src.relative_to(files_dir)
        dst.parent.mkdir(parents=True, exist_ok=True)
        import shutil

        shutil.copy2(src, dst)
        count += 1
    return count


def insert_rows(package_root: Path, data_root: Path) -> tuple[int, int]:
    registry_rows = json.loads((package_root / "registry" / "rows.json").read_text("utf-8"))
    meta_rows = json.loads((package_root / "meta" / "rows.json").read_text("utf-8"))
    meta_db = data_root / "knowledge" / "knowledge_meta.sqlite"

    with closing(sqlite3.connect(meta_db)) as conn:
        n_nodes = n_tree = 0
        for row in meta_rows["nodes"]:
            cols = ", ".join(row)
            marks = ", ".join("?" * len(row))
            conn.execute(f"INSERT INTO nodes ({cols}) VALUES ({marks})", list(row.values()))
            n_nodes += 1
        for row in meta_rows["tree_nodes"]:
            cols = ", ".join(row)
            marks = ", ".join("?" * len(row))
            conn.execute(f"INSERT INTO tree_node ({cols}) VALUES ({marks})", list(row.values()))
            n_tree += 1
        conn.commit()

    reg_db = data_root / REGISTRY_DB_NAME
    with closing(sqlite3.connect(reg_db)) as conn:
        for row in registry_rows["groups"]:
            cols = ", ".join(row)
            marks = ", ".join("?" * len(row))
            conn.execute(f"INSERT OR IGNORE INTO library_groups ({cols}) VALUES ({marks})", list(row.values()))
        for row in registry_rows["libraries"]:
            cols = ", ".join(row)
            marks = ", ".join("?" * len(row))
            conn.execute(f"INSERT INTO library_registry ({cols}) VALUES ({marks})", list(row.values()))
        conn.commit()
    return n_nodes, n_tree


def restore_snapshot(package_root: Path, collection: str) -> None:
    base = os.getenv("QDRANT_URL", "http://localhost:6333").rstrip("/")
    snap = package_root / "qdrant" / f"{collection}.snapshot"
    # qdrant REST：先 upload snapshot 再 recover 为目标 collection 名（跨环境 collection 名可不同）
    url = f"{base}/snapshots/upload"
    boundary = "----angineer"
    body = (
        f"--{boundary}\r\nContent-Disposition: form-data; name=\"snapshot\"; filename=\"{snap.name}\"\r\n"
        "Content-Type: application/octet-stream\r\n\r\n"
    ).encode() + snap.read_bytes() + f"\r\n--{boundary}--\r\n".encode()
    req = urlrequest.Request(url, data=body, headers={"Content-Type": f"multipart/form-data; boundary={boundary}"}, method="POST")
    with urlrequest.urlopen(req, timeout=600) as resp:
        uploaded = json.load(resp)["result"]["name"]
    req = urlrequest.Request(f"{base}/snapshots/{uploaded}/recover", method="POST", data=b"{}")
    with urlrequest.urlopen(req, timeout=600) as resp:
        print(f"  snapshot recover {collection}: {json.load(resp).get('status')}")


def load_package(package_arg: str) -> tuple[Path, dict]:
    p = Path(package_arg)
    if p.suffix == ".tar" or p.name == ".":
        raise SystemExit("先解包（--package 指目录；tar 用 --package-dir 指定解出目录）")
    return p, json.loads((p / "manifest.json").read_text("utf-8"))


def run(package_arg: str, apply: bool, reembed: bool, package_dir: str) -> int:
    if package_dir:
        tar_path = Path(package_arg)
        out_dir = Path(package_dir)
        out_dir.mkdir(parents=True, exist_ok=True)
        with tarfile.open(tar_path) as tf:
            tf.extractall(out_dir)
        pkg_dir = next(p for p in out_dir.iterdir() if (p / "manifest.json").exists())
    else:
        pkg_dir = Path(package_arg)
    manifest = json.loads((pkg_dir / "manifest.json").read_text("utf-8"))

    check_schema_gate(manifest)
    check_package_files(pkg_dir, manifest)
    need_reembed = check_embed_gate(manifest, embed_model_from_env(), allow_reembed=reembed)

    data_root = resolve_data_root()
    registry_rows = json.loads((pkg_dir / "registry" / "rows.json").read_text("utf-8"))
    meta_rows = json.loads((pkg_dir / "meta" / "rows.json").read_text("utf-8"))

    # 冲突闸分两库查：registry 行在 registry.sqlite，nodes 在共享 meta 库（单连接两表是测试夹具形态）
    with closing(sqlite3.connect(data_root / REGISTRY_DB_NAME)) as reg_conn:
        clashes = check_conflict_gate(reg_conn, registry_rows["libraries"], [])
    with closing(sqlite3.connect(data_root / "knowledge" / "knowledge_meta.sqlite")) as meta_conn:
        clashes += check_conflict_gate(meta_conn, [], [r["id"] for r in meta_rows["nodes"]])
    if clashes:
        raise SystemExit(f"目标已存在同名库/节点，拒绝覆盖: {clashes[:10]}{' …' if len(clashes) > 10 else ''}")

    print(f"包={pkg_dir.name} 库={[r['library_id'] for r in registry_rows['libraries']]} "
          f"节点={len(meta_rows['nodes'])} 组文件+文档树文件见 manifest.files({len(manifest['files'])})")
    if not apply:
        print("dry-run 结束（预检全过）。确认后加 --apply。")
        return 0

    n_files = stage_files(pkg_dir, data_root)
    n_nodes, n_tree = insert_rows(pkg_dir, data_root)
    print(f"落盘: 文件={n_files} nodes={n_nodes} tree_node={n_tree}")

    if manifest.get("collections") and not need_reembed:
        for col in manifest["collections"]:
            restore_snapshot(pkg_dir, col)
    elif need_reembed:
        print("  跳过 snapshot 恢复；导入后立即执行: python scripts/rebuild_vectors.py（用现网模型自嵌）")
    print(
        "\n验收清单:\n"
        "  1) docker compose up -d aichat-api（读穿修复未发版，现行 SOP 必须重建）\n"
        "  2) 逐库检索探针：knowledge_search 命中该库 doc 且 items[].text 带《doc_title》前缀\n"
        "  3) 溯源：GET /api/knowledge/documents/<doc_id>/pdf 返回 200\n"
        "  4) 既有库回归一条老题（组化不串 collection）"
    )
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--package", required=True, help="解包目录或 tar")
    parser.add_argument("--package-dir", default="", help="tar 时解出到此目录")
    parser.add_argument("--dry-run", action="store_true", help="只预检（默认行为，显式给出便于脚本化）")
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--reembed", action="store_true", help="embed 模型不一致时授权用现网模型自嵌")
    args = parser.parse_args()
    return run(args.package, args.apply, args.reembed, args.package_dir)


if __name__ == "__main__":
    raise SystemExit(main())
