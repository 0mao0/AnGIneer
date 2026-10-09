"""语料包 export（plan-standards-kb-corpus-package Stage D1）——CLI 入口。

核心逻辑在 ``docs_core.corpus_package``（管理后台流式导出共用同一套）。
本文件只做参数解析与打印。

包结构：
    <out>/<group>-<date>-<libs>/
    ├─ manifest.json      # schema_version/embed_model/page_base=0/库清单/全部落包文件 sha256
    ├─ registry/rows.json # library_registry + library_groups 行原样
    ├─ meta/rows.json     # 共享 meta 库里这些库的 nodes + tree_node 行（meta 文件本身不进包）
    ├─ files/<相对 data 根原路径>   # 组 sqlite（先 WAL checkpoint）+ libraries/<id>/ 文档树
    └─ qdrant/<collection>.snapshot # --no-vectors 跳过（对方自嵌或后续 rebuild_vectors）

embed_model 取导出环境 EMBEDDING_CONFIGS 首项 model 名——import 侧三硬闸之一的对账基准。

用法（本地，需 ANGINEER_DATA_ROOT/.env 就绪）：
    python scripts/kb_corpus_export.py --libs std-highway
    python scripts/kb_corpus_export.py --libs std-highway,std-municipal --no-vectors --out data/packages/out
    python scripts/kb_corpus_export.py --libs std-highway --exclude-doc-dirs ""   # 全树全拷（含 mineru_raw/popo）
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "services" / "docs-core" / "src"))

from docs_core.corpus_package import build_package  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--libs", required=True, help="逗号分隔 library_id")
    parser.add_argument("--out", default=str(REPO_ROOT / "data" / "scratch" / "corpus-packages"))
    parser.add_argument("--no-vectors", action="store_true", help="不打 qdrant snapshot（目标自嵌向量）")
    parser.add_argument("--tar", action="store_true", help="顺带打 tar 便于 scp")
    parser.add_argument("--exclude-doc-dirs", default="mineru_raw,popo",
                        help="documents/<doc_id>/parsed/ 下要跳过的子目录（逗号分隔；默认砍只供重解析的中间产物，"
                             "检索链不读它们，省 ~2.2GB/库；传空串=整树全拷）")
    args = parser.parse_args()
    exclude = [d.strip() for d in (args.exclude_doc_dirs or "").split(",") if d.strip()]
    build_package(
        [s.strip() for s in args.libs.split(",") if s.strip()],
        Path(args.out),
        with_vectors=not args.no_vectors,
        pack_tar=args.tar,
        exclude_dirs=exclude,
        on_stage=lambda stage, msg: print(f"  [{stage}] {msg}"),
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
