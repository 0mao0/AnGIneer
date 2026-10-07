"""存量 nodes.file_path 相对化清洗（plan-standards-kb-corpus-package Stage A4）。

把各知识库 meta 库里 data 根之下的绝对 file_path 收敛为相对 data 根的 POSIX 相对路径，
与 register_document 写入口定版口径一致（docs_core.paths.to_data_relative 单一真相源）。

- 默认 dry-run，只报数不动库；--apply 才 UPDATE。
- data 根之外的旧路径（如旧前缀 data\\knowledge_base\\ 已搬走的行）原样保留，
  解析侧由 source_prep 规范目录兜底（test_source_file_fallback.py 锁契约）。
- 可重入：换算结果与旧值相同的行跳过。

用法：
    python scripts/relativize_node_file_paths.py            # dry-run 对账
    python scripts/relativize_node_file_paths.py --apply    # 落库
"""
from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "services" / "docs-core" / "src"))

from docs_core.library_registry import resolve_data_root  # noqa: E402
from docs_core.paths import to_data_relative  # noqa: E402


def iter_meta_dbs(data_root: Path) -> list[Path]:
    kb = data_root / "knowledge"
    dbs: list[Path] = []
    for candidate in (kb / "knowledge_meta.sqlite",):
        if candidate.exists():
            dbs.append(candidate)
    dbs.extend(sorted((kb / "libraries").glob("*/knowledge_meta.sqlite")))
    dbs.extend(sorted((kb / "groups").glob("*.sqlite")))
    return dbs


def relativize(db: Path, apply: bool) -> tuple[int, int]:
    """返回 (换算行数, 库外保留行数)。"""
    with sqlite3.connect(db) as conn:
        conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        try:
            rows = conn.execute("SELECT id, file_path FROM nodes WHERE file_path IS NOT NULL AND file_path != ''").fetchall()
        except sqlite3.OperationalError:
            return (0, 0)  # 无 nodes 表的库跳过
        converted = kept = 0
        updates: list[tuple[str, str]] = []
        for doc_id, old in rows:
            new = to_data_relative(old)
            if new == old:
                if Path(old).is_absolute() or (len(old) > 1 and old[0].isalpha() and old[1] == ":"):
                    kept += 1  # 绝对且换算不动 = 库外旧路径，保留
                continue
            updates.append((new, doc_id))
            converted += 1
        if apply and updates:
            conn.executemany("UPDATE nodes SET file_path = ? WHERE id = ?", updates)
        return (converted, kept)


def sync_tree_mirror(db: Path, apply: bool) -> int:
    """tree_node.extra_json.file_path 镜像对齐 nodes.file_path（nodes 是真相源）。

    upsert_node 每次写节点都会重落一份镜像（fix_node_file_paths.py 同款约定），
    直接 UPDATE nodes 不会碰它 → 知识树/预览拿旧绝对路径回拼 /api/files。
    只改「镜像与 nodes 文件名相同、形态不同」的行（同文件不同口径），文件名不同
    = 数据本身分叉，绝不猜测。镜像表不存在（非 meta 库）跳过。
    """
    import re

    def base(value: str) -> str:
        return re.split(r"[\\/]", value.rstrip("\\/"))[-1] if value else ""

    synced = 0
    with sqlite3.connect(db) as conn:
        try:
            rows = conn.execute(
                "SELECT n.id, n.file_path, t.extra_json FROM nodes n "
                "JOIN tree_node t ON t.node_id = n.id "
                "WHERE n.file_path IS NOT NULL AND n.file_path != '' AND t.extra_json IS NOT NULL"
            ).fetchall()
        except sqlite3.OperationalError:
            return 0
        writes: list[tuple[str, str]] = []
        for doc_id, node_path, extra_json in rows:
            try:
                extra = json.loads(extra_json)
            except (TypeError, ValueError):
                continue
            if not isinstance(extra, dict) or "file_path" not in extra:
                continue
            mirror = str(extra.get("file_path") or "")
            if mirror and mirror != node_path and base(mirror) == base(node_path):
                extra["file_path"] = node_path
                writes.append((json.dumps(extra, ensure_ascii=False), doc_id))
        if apply and writes:
            conn.executemany("UPDATE tree_node SET extra_json = ? WHERE node_id = ?", writes)
        return len(writes)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true", help="真正 UPDATE，默认 dry-run")
    args = parser.parse_args()

    data_root = resolve_data_root()
    total_conv = total_kept = total_mirror = 0
    for db in iter_meta_dbs(data_root):
        conv, kept = relativize(db, args.apply)
        mirror = sync_tree_mirror(db, args.apply)
        total_conv += conv
        total_kept += kept
        total_mirror += mirror
        if conv or kept or mirror:
            print(f"{'APPLIED' if args.apply else 'DRY'}  {db.relative_to(data_root)}  换算={conv}  库外保留={kept}  镜像对齐={mirror}")
    print(f"合计: 换算={total_conv}  库外保留={total_kept}  镜像对齐={total_mirror}  data_root={data_root}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
