"""存量修补：给历史文档补回行内公式的 `$` 定界符（就地改 jsonl + 重建索引，不重跑解析）。

背景（2026-09-17 P0）：`extract_plain_text` 拍平 span 时丢掉了 `equation_inline` 的定界符，
`再算 $20+7=27$ 。` 变成 `再算   20+7=27 。`——markdown 投影与 canonical 文本都分不出公式边界，
官方口径按公式取块时把上下文一起计入（200 页评测：公式 Edit_dist 因此差 1.49pp、文本差 2.42pp）。
修复已进代码，但**只对新解析生效**；历史文档要靠本脚本补。

与其他 repair_* 脚本的区别（重要）：本脚本**只插入 `$`，不改动任何其它字符**——
改写前先校验 `old.replace('$','') == new.replace('$','')`，不等则跳过并计入 skipped。
这样不会像"整体重算 plain_text"那样把当前代码的其它变化夹带进历史文档（避免混合口径）。

口径前提（本机实测 0 命中，仍逐块检查）：markdown/canonical 优先消费 `plain_text_corrected`，
若该字段非空则本脚本**不动**（它是 PoPo 校正产物，无法原地重算），计入 corrected_skipped 并在末尾报告。

用法（不加 --apply 就是 dry-run，只统计不写盘）：
    python scripts/repair_inline_math_delims.py                      # 全量扫描
    python scripts/repair_inline_math_delims.py --libraries lib-7582b086
    python scripts/repair_inline_math_delims.py --apply --reindex \
        --backup-dir /app/data/backups/inline-math-20260917          # 服务器容器内
    # 向量默认不重建：内容本身没变（只多两个 $），检索语义影响可忽略；
    # 确需一致再加 --vectors（每 chunk 一次 embedding 调用，量大）
"""
import argparse
import json
import shutil
import sys
import tarfile
from datetime import datetime
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "services" / "docs-core" / "src"))

DATA_ROOT = Path("/app/data") if Path("/app/data").is_dir() else REPO / "data"
LIBS = DATA_ROOT / "knowledge_base" / "libraries"
SPAN_KEYS = ("paragraph_content", "title_content", "page_header_content",
             "page_footer_content", "page_number_content")


def _needs_delims(node: dict) -> bool:
    """该块是否有"缺 `$` 的行内公式 span"。"""
    content = node.get("content_json")
    if not isinstance(content, dict):
        return False
    for key in SPAN_KEYS:
        spans = content.get(key)
        if not isinstance(spans, list):
            continue
        for span in spans:
            if not isinstance(span, dict):
                continue
            span_type = str(span.get("type") or "")
            text = str(span.get("content") or "")
            if "equation" in span_type and "interline" not in span_type and text.strip() and "$" not in text:
                return True
    return False


def main() -> int:
    ap = argparse.ArgumentParser(description="补回历史文档行内公式的 $ 定界符（就地改 jsonl）")
    ap.add_argument("--libraries", default="", help="逗号分隔库名；留空=全部")
    ap.add_argument("--docs", default="", help="逗号分隔 <库>/<doc_id>；留空=扫描模式")
    ap.add_argument("--apply", action="store_true", help="真的写回 jsonl（否则只统计）")
    ap.add_argument("--reindex", action="store_true", help="补完重建 canonical + FTS（需 --apply）")
    ap.add_argument("--vectors", action="store_true", help="同时重建向量（每 chunk 一次 embedding，慢）")
    ap.add_argument("--backup-dir", default="", help="把修改前的 jsonl 打包存这里（强烈建议）")
    ap.add_argument("--limit", type=int, default=0, help="最多处理多少篇（0=全部）")
    args = ap.parse_args()

    from docs_core.step04_structure.solo_engine import extract_plain_text

    want_libs = {s.strip() for s in args.libraries.split(",") if s.strip()}
    want_docs = {s.strip() for s in args.docs.split(",") if s.strip()}
    targets, scanned = [], 0
    for lib_dir in sorted(p for p in LIBS.iterdir() if p.is_dir()):
        if want_libs and lib_dir.name not in want_libs:
            continue
        docs_dir = lib_dir / "documents"
        if not docs_dir.is_dir():
            continue
        for doc_dir in sorted(docs_dir.iterdir()):
            if not doc_dir.is_dir():
                continue
            if want_docs and f"{lib_dir.name}/{doc_dir.name}" not in want_docs and doc_dir.name not in want_docs:
                continue
            graph = doc_dir / "parsed" / "doc_blocks_graph.jsonl"
            if not graph.is_file():
                continue
            scanned += 1
            nodes = [json.loads(x) for x in graph.read_text(encoding="utf-8").splitlines() if x.strip()]
            hits, corrected, skipped = [], 0, 0
            for i, node in enumerate(nodes):
                if not _needs_delims(node) or "$" in str(node.get("plain_text") or ""):
                    continue
                if str(node.get("plain_text_corrected") or "").strip():
                    corrected += 1          # 有 corrected 时 markdown/canonical 读的是它，本脚本不动
                    continue
                old = str(node.get("plain_text") or "")
                new = extract_plain_text(str(node.get("block_type") or ""), node.get("content_json"))
                # 只认"纯插入 $"：去掉 $ 后必须逐字相同，否则跳过（不夹带其它变化）
                if new and new != old and old.replace("$", "") == new.replace("$", ""):
                    hits.append((i, new))
                else:
                    skipped += 1
            if hits or corrected or skipped:
                targets.append({"library": lib_dir.name, "doc": doc_dir.name, "graph": graph,
                                "nodes": nodes, "hits": hits, "corrected": corrected, "skipped": skipped})
    if args.limit:
        targets = targets[: args.limit]

    total = sum(len(t["hits"]) for t in targets)
    corr_total = sum(t["corrected"] for t in targets)
    skip_total = sum(t["skipped"] for t in targets)
    print(f"扫描 {scanned} 篇 → 待修补 {len(targets)} 篇 / {total} 块"
          f"（另有 corrected 阻挡 {corr_total} 块、非纯插入跳过 {skip_total} 块）")
    for t in targets[:10]:
        print(f"  {t['library']}/{t['doc']}: {len(t['hits'])} 块"
              + (f"，corrected 阻挡 {t['corrected']}" if t["corrected"] else "")
              + (f"，跳过 {t['skipped']}" if t["skipped"] else ""))
    if len(targets) > 10:
        print(f"  …其余 {len(targets) - 10} 篇")
    if not args.apply:
        print("（未加 --apply，未写任何文件）")
        return 0
    if not targets:
        print("没有需要修补的文档")
        return 0

    if args.backup_dir:
        bdir = Path(args.backup_dir)
        bdir.mkdir(parents=True, exist_ok=True)
        tar_path = bdir / f"doc_blocks_graph-inline-math-{datetime.now().strftime('%Y%m%d-%H%M%S')}.tar.gz"
        with tarfile.open(tar_path, "w:gz") as tf:
            for t in targets:
                tf.add(t["graph"], arcname=f"{t['library']}/{t['doc']}/doc_blocks_graph.jsonl")
        print(f"备份 {len(targets)} 个 jsonl → {tar_path}（{tar_path.stat().st_size / 1e6:.1f} MB）")

    patched_docs = patched_blocks = 0
    for t in targets:
        nodes = t["nodes"]
        for i, new in t["hits"]:
            nodes[i]["plain_text"] = new
        tmp = t["graph"].with_suffix(".jsonl.tmp")
        tmp.write_text("".join(json.dumps(n, ensure_ascii=False) + "\n" for n in nodes), encoding="utf-8")
        shutil.move(str(tmp), str(t["graph"]))
        patched_docs += 1
        patched_blocks += len(t["hits"])
        print(f"  已补 {t['library']}/{t['doc']}: {len(t['hits'])} 块")
    print(f"写回完成：{patched_docs} 篇 / {patched_blocks} 块")

    if args.reindex:
        from docs_core.docs_service import get_docs_service
        from docs_core.step05_sqlite_fts.sqlite_index import build_sqlite_index_from_graph

        ds = get_docs_service()
        ok = fail = 0
        for t in targets:
            try:
                build_sqlite_index_from_graph(t["library"], t["doc"])
                if args.vectors:
                    ds.rebuild_document_vectors(t["doc"])
                ok += 1
                print(f"  索引重建 {t['doc']}")
            except Exception as exc:  # noqa: BLE001 单篇失败不阻断整批
                fail += 1
                print(f"  索引重建失败 {t['doc']}: {str(exc)[:140]}")
        print(f"索引重建完成：成功 {ok} / 失败 {fail}"
              + ("" if args.vectors else "（未重建向量：内容未变，只多了 $；需要时单跑 --vectors）"))
    else:
        print("（未加 --reindex：jsonl 已补，canonical/FTS 还是旧的，记得重建）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
