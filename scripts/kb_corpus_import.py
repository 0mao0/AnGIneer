"""v2 语料包导入 CLI（单库 zip / 外层 bundle zip）。

v2 包只有两种输入：外层 bundle zip（多库）或单库小包 zip。v1 的目录/tar 形态
已不再支持；收到旧包会直接报错，要求用 v2 重新导出。

预检与落位全部由 ``docs_core.corpus_package.apply_import`` 执行：
- embed 模型对账（v2 无 reembed：不一致直接拒收，避免跨模型向量静默错乱）；
- 冲突闸（library_id / nodes.id / collection / index.sqlite / 闭包实体重名）；
- 两层 sha256 完整性；
- 独立桶落位、doc_catalog、图谱 FK OFF 合并、qdrant 快照、逐表对账。

用法（默认 dry-run，不动任何数据）：
    python scripts/kb_corpus_import.py --package <包.zip> --group evals --dry-run
    python scripts/kb_corpus_import.py --package <包.zip> --group evals --apply
    python scripts/kb_corpus_import.py --package <单库.zip> --only lib-a --no-vectors --apply

目标组必须与包内 ``files/`` 根一致（knowledge 包用 knowledge 组，evals 包用 evals 组）；
``--group`` 省略时沿用包内原组。
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "services" / "docs-core" / "src"))

from docs_core.corpus_package import BundleError, apply_import  # noqa: E402
from docs_core.library_registry import resolve_data_root  # noqa: E402


def _split_ids(raw: str) -> list[str]:
    return [x.strip() for x in (raw or "").split(",") if x.strip()]


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--package", required=True, help="v2 外层 bundle zip 或单库 zip")
    parser.add_argument("--group", default="", help="目标组 slug（省略=沿用包内组；须与包 files 根一致）")
    parser.add_argument("--group-display-name", default="", help="自定义组显示名（仅新组生效）")
    parser.add_argument("--only", default="", help="只导入这些库，逗号分隔 library_id")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--dry-run", action="store_true", help="只预检（默认行为）")
    mode.add_argument("--apply", action="store_true", help="执行落位")
    parser.add_argument("--no-vectors", action="store_true", help="跳过快照恢复与向量对账")
    parser.add_argument("--qdrant-url", default="", help="覆盖 QDRANT_URL（默认读环境变量）")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    libs = _split_ids(args.only)
    try:
        result = apply_import(
            args.package,
            data_root=resolve_data_root(),
            group_name=args.group,
            group_display_name=args.group_display_name,
            libraries=libs or None,
            apply=args.apply,
            with_vectors=not args.no_vectors,
            qdrant_url=args.qdrant_url or None,
        )
    except BundleError as exc:
        print(f"导入失败: {exc}", file=sys.stderr)
        return 1

    if result.get("mode") == "dry-run":
        print("dry-run 预检通过（未写任何数据）：")
        for lib in result.get("libraries", []):
            counts = lib.get("counts") or {}
            print(
                f"  - {lib['library_id']}: group={lib['group_name']} "
                f"collection={lib['collection']} files={lib['files']} "
                f"bytes={lib.get('bytes', 0)} "
                f"docs={counts.get('docs', 0)} chunks={counts.get('chunks', 0)} "
                f"vectors={counts.get('vectors', 0)}\n"
                f"    index={lib['index_path']}"
            )
        print("确认后加 --apply。")
        return 0

    print("导入应用完成：" + ", ".join(result.get("libraries", [])))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
