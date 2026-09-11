"""订正 nodes.file_path 里"另一台机器"的绝对路径（历史批量导入把开发机路径写进了库）。

背景：server_kb_snapshot 导入把开发机路径原样写进 nodes.file_path
（``D:\\AI\\AnGIneer\\data\\knowledge_base\\libraries\\...``），该路径在 Linux 容器里
恒 ``exists()=False``。解析管线本身不依赖它（source_prep 优先用规范 source 目录），
但任何拿它做存在性判断的入口都会失败：修复前 ``POST /api/knowledge/parse`` 直接
404「源文件不存在」，而原件就在 ``libraries/<lib>/documents/<doc>/source/`` 下。

本脚本把这类路径改写成服务器规范路径，并同步 ``tree_node.extra_json`` 里的同名字段
镜像（``upsert_node`` 每次写节点都会重新落一份，两处必须一致）。只改"原件确实存在"
的行；解析不到的原样保留并列出原因，绝不猜测。

路径口径固定走 ``docs_core.paths``，所以必须在应用所在环境执行（容器内），
否则算出来的规范路径与运行时不一致：

    docker exec -i angineer-docs-api python - < scripts/fix_node_file_paths.py --dry-run
    docker exec -i angineer-docs-api python - < scripts/fix_node_file_paths.py --apply

写进镜像 allowlist 后可直接 ``python /app/scripts/fix_node_file_paths.py``。

注意：服务进程把 nodes 缓存在内存里（``docs_service._load_from_db``），改完库必须重启
docs-api（或走一次部署）才会对外生效；重启前若对同一行触发 ``update_node``，
内存里的旧值会把本次订正覆盖回去。
"""
from __future__ import annotations

import argparse
import json
import re
import shutil
import sqlite3
import sys
from datetime import datetime
from pathlib import Path

from docs_core import paths as kb_paths

DRIVE_RE = re.compile(r"^[A-Za-z]:[\\/]")


def looks_foreign(value: str) -> bool:
    """带盘符或含反斜杠的类 Windows 路径：本机（服务器）不可能解析到的形态。"""
    return bool(DRIVE_RE.match(value)) or "\\" in value


def resolve_canonical(library_id: str, doc_id: str, old_path: str) -> tuple[Path | None, str]:
    """在规范 source 目录里找旧路径对应的原件；找不到返回 (None, 原因)。"""
    source_dir = kb_paths.get_source_dir(library_id, doc_id)
    if not source_dir.is_dir():
        return None, "no_source_dir"
    files = sorted(path for path in source_dir.iterdir() if path.is_file())
    if not files:
        return None, "empty_source_dir"
    want = re.split(r"[\\/]", old_path)[-1]
    for path in files:
        if path.name == want:
            return path, ""
    if len(files) == 1:
        return files[0], ""
    return None, "ambiguous:" + "|".join(path.name for path in files[:3])


def plan_changes(db: Path) -> tuple[list[dict], dict[str, int], int]:
    """只读扫描：返回 (可订正清单, 跳过原因计数, 命中外来路径总数)。"""
    with sqlite3.connect(f"file:{db}?mode=ro", uri=True) as conn:
        rows = conn.execute(
            "SELECT id, library_id, file_path FROM nodes "
            "WHERE deleted = 0 AND file_path IS NOT NULL AND file_path <> ''"
        ).fetchall()

    changes: list[dict] = []
    skipped: dict[str, int] = {}
    foreign_total = 0
    for doc_id, library_id, old_path in rows:
        if not looks_foreign(str(old_path)):
            continue
        foreign_total += 1
        resolved, reason = resolve_canonical(library_id, doc_id, str(old_path))
        if resolved is None:
            skipped[reason.split(":")[0]] = skipped.get(reason.split(":")[0], 0) + 1
            changes.append({"doc_id": doc_id, "library_id": library_id, "new": None, "reason": reason})
            continue
        changes.append(
            {
                "doc_id": doc_id,
                "library_id": library_id,
                "old": str(old_path),
                "new": str(resolved),
                "reason": "",
            }
        )
    return changes, skipped, foreign_total


def patch_tree_mirror(conn: sqlite3.Connection, doc_id: str, old_path: str, new_path: str) -> int:
    """同步 tree_node.extra_json.file_path 镜像；值不匹配或解析失败则不动。"""
    row = conn.execute("SELECT extra_json FROM tree_node WHERE node_id = ?", (doc_id,)).fetchone()
    if not row or not row[0]:
        return 0
    try:
        extra = json.loads(row[0])
    except (TypeError, ValueError):
        return 0
    if not isinstance(extra, dict) or extra.get("file_path") != old_path:
        return 0
    extra["file_path"] = new_path
    conn.execute(
        "UPDATE tree_node SET extra_json = ? WHERE node_id = ?",
        (json.dumps(extra, ensure_ascii=False), doc_id),
    )
    return 1


def apply_changes(db: Path, changes: list[dict]) -> tuple[int, int]:
    """写入 nodes.file_path + tree_node 镜像；返回 (节点行数, 镜像行数)。"""
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    backup = db.parent / f"{db.name}.bak-filepath-{stamp}"
    shutil.copy2(db, backup)
    print(f"  备份: {backup}")

    node_rows = mirror_rows = 0
    conn = sqlite3.connect(str(db), timeout=30)
    try:
        conn.execute("PRAGMA busy_timeout = 30000")
        for item in changes:
            if not item.get("new"):
                continue
            cur = conn.execute(
                "UPDATE nodes SET file_path = ? WHERE id = ? AND file_path = ?",
                (item["new"], item["doc_id"], item["old"]),
            )
            node_rows += cur.rowcount
            mirror_rows += patch_tree_mirror(conn, item["doc_id"], item["old"], item["new"])
        conn.commit()
    finally:
        conn.close()
    return node_rows, mirror_rows


def main() -> int:
    parser = argparse.ArgumentParser(description="订正 nodes.file_path 里的外来机绝对路径")
    parser.add_argument("--apply", action="store_true", help="真正写入（默认只做 dry-run）")
    parser.add_argument("--dry-run", action="store_true", help="只预览不写入（默认行为，显式给出便于脚本化）")
    parser.add_argument("--db", default="", help="覆盖 meta 库路径（默认按 docs_core.paths 解析）")
    parser.add_argument("--show", type=int, default=10, help="打印多少条明细")
    args = parser.parse_args()

    db = Path(args.db) if args.db else Path(kb_paths.resolve_knowledge_meta_db_path())
    print(f"知识库根: {kb_paths.resolve_knowledge_base_dir()}")
    print(f"meta 库  : {db}")
    if not db.is_file():
        print("meta 库不存在，退出", file=sys.stderr)
        return 2

    changes, skipped, foreign_total = plan_changes(db)
    pending = [item for item in changes if item.get("new")]

    print(f"\n外来路径命中: {foreign_total}  可订正: {len(pending)}  保留: {foreign_total - len(pending)}")
    if skipped:
        print("保留原因:", ", ".join(f"{k}={v}" for k, v in sorted(skipped.items())))
    for item in pending[: args.show]:
        print(f"  ✓ {item['library_id']:16s} {item['doc_id']:20s} → {Path(item['new']).name}")
    for item in [i for i in changes if not i.get("new")][: args.show]:
        print(f"  · {item['library_id']:16s} {item['doc_id']:20s} 跳过({item['reason']})")

    if not args.apply:
        print("\ndry-run 结束（未写入）。确认无误后加 --apply。")
        return 0

    if not pending:
        print("\n无可订正项，未写入。")
        return 0

    node_rows, mirror_rows = apply_changes(db, changes)
    print(f"\n已写入: nodes {node_rows} 行, tree_node 镜像 {mirror_rows} 行")

    after, _, remaining = plan_changes(db)
    print(f"复查: 剩余外来路径 {remaining} 条（含保留项 {remaining - len([i for i in after if i.get('new')])} 条）")
    print("\n提醒：改库不会立刻对外生效，需重启 docs-api（或走一次部署）重载内存缓存。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
