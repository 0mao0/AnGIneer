"""库组注册表种子：把 knowledge_meta.sqlite 的 libraries 表灌进 data/registry.sqlite。

组归属是业务判断不猜——内置已知库的默认映射表，未识别的库必须用 --map 显式指定
（缺省 DRY RUN 打印提案，人工核对后 --yes 落盘）。

用法（本机或 docs-api 容器内）：
    python scripts/seed_library_registry.py                      # DRY RUN 预览分组
    python scripts/seed_library_registry.py --yes                # 落盘（collection 保持旧全局值，路由零切换）
    python scripts/seed_library_registry.py --yes --map lib-xxx:dredgeai
    python scripts/seed_library_registry.py --flip               # 对账通过后：collection 翻转为组默认（原子切换点）

零停机切换口径：--yes 落盘时 collection 一律写当前全局 QDRANT_COLLECTION（路由不变），
qdrant 拆桶 + 对账完成后 --flip 一次翻转，等价 plan §4.2 的「注册表原子切换」。
"""
import argparse
import os
import sys
from pathlib import Path

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

# 已知库的组归属默认映射（本地+服务器同源口径；新库一律 --map 显式指定）
BUILTIN_GROUP_MAP = {
    # 评测组：financebench / omnidocbench / openragbench / GDP / officeqa
    "omnidocbench": "evals",
    "lib-officeqa": "evals",
    "lib-cf08e666": "evals",       # FinanceBench-Open
    "lib-0a1f1335": "evals",       # GDP-PDF
    "lib-b07ed174": "evals",       # OpenRAGBenchmark-Subset
    # 施组组
    "lib-DredgeAI-a5e1": "dredgeai",
    "lib-7582b086": "dredgeai",    # DredgeAI施组
    "lib-261558be": "dredgeai",    # 公司施组
    # 系统组（生产默认；2026-10-09 由 standards 换名为 system）
    "default": "system",
    "lib-39109792": "system",      # DredgeAI规范库（库名含"规范"，但归属系统组）
}


def main() -> int:
    parser = argparse.ArgumentParser(description="library_registry 种子（DRY RUN 缺省）")
    parser.add_argument("--yes", action="store_true", help="确认落盘（缺省为 DRY RUN）")
    parser.add_argument(
        "--map",
        action="append",
        default=[],
        metavar="LIB:GROUP",
        help="显式指定库分组（可多次）；覆盖内置映射",
    )
    parser.add_argument(
        "--flip",
        action="store_true",
        help="把已注册行的 collection 翻转为组默认（拆桶对账通过后的原子切换）",
    )
    args = parser.parse_args()

    from docs_core import library_registry as registry

    if args.flip:
        flipped = 0
        for record in registry.list_libraries(include_retired=True):
            target = registry.GROUP_DEFAULTS.get(record.group_name, {}).get(
                "collection", record.group_name
            )
            if record.collection == target:
                continue
            registry.register_library(
                record.library_id,
                name=record.name,
                description=record.description,
                group_name=record.group_name,
                sqlite_file=record.sqlite_file,
                collection=target,
                status=record.status,
            )
            flipped += 1
            print(f"[flip] {record.library_id}: {record.collection} → {target}", flush=True)
        print(f"[flip] 完成：{flipped} 行翻转", flush=True)
        return 0

    overrides = {}
    for item in args.map:
        if ":" not in item:
            print(f"[seed] --map 格式错误: {item!r}（应为 LIB:GROUP）", flush=True)
            return 1
        lib, group = item.split(":", 1)
        overrides[lib.strip()] = group.strip()

    from docs_core import library_registry as registry
    from docs_core.paths import resolve_knowledge_meta_db_path

    mapping = {**BUILTIN_GROUP_MAP, **overrides}
    meta_path = resolve_knowledge_meta_db_path()
    if not meta_path.exists():
        print(f"[seed] knowledge_meta 不存在: {meta_path}", flush=True)
        return 1

    import sqlite3

    with sqlite3.connect(f"file:{meta_path}?mode=ro", uri=True) as conn:
        rows = conn.execute(
            "SELECT id, name FROM libraries ORDER BY created_at ASC"
        ).fetchall()

    unknown = [lib for lib, _ in rows if lib not in mapping]
    print(f"[seed] meta 库共 {len(rows)} 个，注册表: {registry.resolve_registry_db_path()}", flush=True)
    for lib, name in rows:
        group = mapping.get(lib, "<未识别>")
        marker = "" if lib in mapping else "  ← 需 --map 显式指定"
        print(f"[seed]   {lib:<24} {group:<10} {name}{marker}", flush=True)
    if unknown:
        print(f"[seed] 有 {len(unknown)} 个库未识别组归属，DRY RUN 终止；用 --map 指定后重跑", flush=True)
        return 2
    if not args.yes:
        print("[seed] DRY RUN：加 --yes 才会落盘", flush=True)
        return 2

    from docs_core.step06_vectors.config import get_qdrant_collection

    current_collection = get_qdrant_collection()
    seeded = registry.seed_from_meta(meta_path, mapping, collection_override=current_collection)
    print(
        f"[seed] 已登记 {len(seeded)} 行（已存在的行不覆盖）；"
        f"collection 一律暂挂旧全局值 {current_collection}（路由零切换，拆桶对账后 --flip）",
        flush=True,
    )
    for record in registry.list_libraries():
        print(
            f"[seed]   {record.library_id:<24} {record.group_name:<10} "
            f"{record.collection:<16} {record.status}",
            flush=True,
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
