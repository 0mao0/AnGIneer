"""语料包 v2 导出 CLI —— 大包套每库自包含小包，流式落盘。

核心逻辑在 ``docs_core.corpus_package``（管理后台流式导出共用同一套）。
本文件只做参数解析与打印。

包结构（v2）：
    <out>/<组名>-<YYYYMMDD>.zip          # 外层 bundle（ZIP_STORED，流式嵌套）
    ├─ manifest.json                     # kind=bundle；libraries[]（entry/sha256/bytes/counts）
    └─ libraries/<library_id>.zip        # 每库自包含小包（可单独交付/单独导入）
         ├─ manifest.json / registry/rows.json / meta/rows.json
         ├─ index/index.sqlite           # 组 sqlite 按库切片（FTS 随行）
         ├─ files/knowledge/libraries/<lib>/…   # 文档树（默认砍 parsed/{mineru_raw,popo}）
         ├─ qdrant/vectors.snapshot      # --no-vectors 跳过
         └─ graph/graph.sqlite           # 本库图谱闭包切片

embed_model 取导出环境 EMBEDDING_CONFIGS 首项 model 名——import 侧对账基准（v2 不一致即阻断）。

用法（本地，需 ANGINEER_DATA_ROOT/.env 就绪）：
    python scripts/kb_corpus_export.py --libs std-highway
    python scripts/kb_corpus_export.py --libs std-highway,std-municipal --no-vectors --out data/packages/out
    python scripts/kb_corpus_export.py --libs std-highway --exclude-doc-dirs ""   # 全树全拷（含 mineru_raw/popo）
"""
from __future__ import annotations

import argparse
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "services" / "docs-core" / "src"))

from docs_core.corpus_package import build_bundle, read_registry  # noqa: E402
from docs_core.library_registry import resolve_data_root  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--libs", required=True, help="逗号分隔 library_id（每库一个小包，可跨组）")
    parser.add_argument("--out", default=str(REPO_ROOT / "data" / "scratch" / "corpus-packages"))
    parser.add_argument("--no-vectors", action="store_true", help="不打 qdrant snapshot（目标自嵌向量）")
    parser.add_argument("--tar", action="store_true", help="顺带打 tar 便于 scp")
    parser.add_argument("--exclude-doc-dirs", default="mineru_raw,popo",
                        help="documents/<doc_id>/parsed/ 下要跳过的子目录（逗号分隔；默认砍只供重解析的中间产物，"
                             "检索链不读它们，省 ~2.2GB/库；传空串=整树全拷）")
    args = parser.parse_args()
    exclude = [d.strip() for d in (args.exclude_doc_dirs or "").split(",") if d.strip()]
    libs = [s.strip() for s in args.libs.split(",") if s.strip()]

    data_root = resolve_data_root()
    libraries, _groups = read_registry(data_root, libs)
    group = (libraries[0]["group_name"] or "corpus") if libraries else "corpus"
    date_str = datetime.now(timezone(timedelta(hours=8))).strftime("%Y%m%d")
    out_path = Path(args.out) / f"{group}-{date_str}.zip"

    build_bundle(
        libs,
        out_path,
        with_vectors=not args.no_vectors,
        exclude_dirs=exclude,
        data_root=data_root,
        on_stage=lambda stage, msg: print(f"  [{stage}] {msg}"),
    )
    print(f"包: {out_path}  ({out_path.stat().st_size // 1048576}MB)")

    if args.tar:
        import tarfile
        tar_path = out_path.with_suffix(".tar")
        with tarfile.open(tar_path, "w") as tf:
            tf.add(out_path, arcname=out_path.name)
        print(f"tar: {tar_path} ({tar_path.stat().st_size // 1048576}MB)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
