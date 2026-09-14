"""B 路线：就地补齐历史文档被吃掉的块文本，然后重建索引（不重跑 MinerU/PoPo/structure）。

背景：2026-09-12 修的 `extract_plain_text` 缺 5 类分支（chart / page_footnote /
page_aside_text / code / algorithm）——那之前解析的文档里，这些块的 `plain_text` 是空的，
于是 canonical/chunk/向量里都没有这段内容，检索不到。全量实测 160 篇 / 1958 块。

为什么不重跑 structure：结构层其余部分与当前代码的差异不在本次修复范围内，重跑要按页计费
（160 篇 13433 页 ≈ 14 小时）；本脚本只补这一个字段（同样的修复函数），再重建索引，
耗时按篇计（≈ 每分钟 1 篇）。代价是这些文档的结构层保持"旧版 + 本次修补"的混合状态，
后续如需与当前代码全量对齐，仍应走一次 structure 重跑。

用法（服务器上，容器内跑；不加 --apply 就是 dry-run，只统计不写盘）：
    python scripts/repair_plain_text.py                                   # 只统计
    python scripts/repair_plain_text.py --apply --reindex \
        --backup-dir /app/data/backups/plaintext-20260914
"""
import argparse
import json
import shutil
import sqlite3
import sys
import tarfile
from datetime import datetime
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "services" / "docs-core" / "src"))

DATA_ROOT = Path("/app/data") if Path("/app/data").is_dir() else REPO / "data"
LIBS = DATA_ROOT / "knowledge_base" / "libraries"


def _affected_blocks(nodes: list, extract) -> list:
    """返回需要补 plain_text 的块索引。"""
    hits = []
    for i, n in enumerate(nodes):
        if str(n.get("plain_text") or "").strip():
            continue
        content = n.get("content_json")
        if not isinstance(content, dict) or not content:
            continue
        text = ""
        try:
            text = extract(str(n.get("block_type") or ""), content) or ""
        except Exception:  # noqa: BLE001 解析链的抽取函数异常不该影响整批
            continue
        if text.strip():
            hits.append(i)
    return hits


def main() -> int:
    ap = argparse.ArgumentParser(description="补齐历史文档被吃掉的块文本并重建索引（B 路线）")
    ap.add_argument("--libraries", default="", help="逗号分隔库名；留空=全部")
    ap.add_argument("--docs", default="", help="逗号分隔 doc_id；留空=扫库")
    ap.add_argument("--apply", action="store_true", help="真的写回 jsonl（否则只统计）")
    ap.add_argument("--reindex", action="store_true", help="补完重建 fts/vectors（需 --apply）")
    ap.add_argument("--with-graph", action="store_true", help="同时重建图谱（更慢，默认不建）")
    ap.add_argument("--backup-dir", default="", help="把修改前的 jsonl 打包存到这里（强烈建议）")
    ap.add_argument("--limit", type=int, default=0, help="最多处理多少篇（0=全部）")
    args = ap.parse_args()

    from docs_core.step04_structure.solo_engine import extract_plain_text

    want_libs = {s.strip() for s in args.libraries.split(",") if s.strip()}
    want_docs = {s.strip() for s in args.docs.split(",") if s.strip()}

    targets = []
    scanned = 0
    for lib_dir in sorted(p for p in LIBS.iterdir() if p.is_dir()):
        if want_libs and lib_dir.name not in want_libs:
            continue
        if not (lib_dir / "documents").is_dir():
            continue          # 非知识库目录（如工作区残留）
        for doc_dir in sorted((lib_dir / "documents").iterdir()):
            if not doc_dir.is_dir():
                continue
            if want_docs and doc_dir.name not in want_docs:
                continue
            graph = doc_dir / "parsed" / "doc_blocks_graph.jsonl"
            if not graph.is_file():
                continue
            scanned += 1
            nodes = [json.loads(x) for x in graph.read_text(encoding="utf-8").splitlines() if x.strip()]
            hits = _affected_blocks(nodes, extract_plain_text)
            if hits:
                targets.append({"library": lib_dir.name, "doc": doc_dir.name, "graph": graph,
                                "hits": hits, "nodes": nodes})
    if args.limit:
        targets = targets[: args.limit]

    total_blocks = sum(len(t["hits"]) for t in targets)
    print(f"扫描 {scanned} 篇 → 待修补 {len(targets)} 篇 / {total_blocks} 块")
    for t in targets[:8]:
        print(f"  {t['library']}/{t['doc']}: {len(t['hits'])} 块")
    if len(targets) > 8:
        print(f"  …其余 {len(targets) - 8} 篇")
    if not args.apply:
        print("（未加 --apply，未写任何文件）")
        return 0
    if not targets:
        print("没有需要修补的文档")
        return 0

    if args.backup_dir:
        bdir = Path(args.backup_dir)
        bdir.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        tar_path = bdir / f"doc_blocks_graph-{stamp}.tar.gz"
        with tarfile.open(tar_path, "w:gz") as tf:
            for t in targets:
                tf.add(t["graph"], arcname=f"{t['library']}/{t['doc']}/doc_blocks_graph.jsonl")
        print(f"备份 {len(targets)} 个 jsonl → {tar_path}（{tar_path.stat().st_size / 1e6:.1f} MB）")

    patched_docs = patched_blocks = 0
    for t in targets:
        nodes = t["nodes"]
        for i in t["hits"]:
            nodes[i]["plain_text"] = extract_plain_text(str(nodes[i].get("block_type") or ""),
                                                        nodes[i].get("content_json"))
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
                res = build_sqlite_index_from_graph(t["library"], t["doc"])
                ds.rebuild_document_vectors(t["doc"])
                if args.with_graph:
                    from docs_core.step07_graph.push_to_graph import push_to_graph

                    push_to_graph(t["library"], t["doc"])
                ok += 1
                print(f"  索引重建 {t['doc']}: {res.get('canonical_blocks_count')} blocks")
            except Exception as exc:  # noqa: BLE001 单篇失败不阻断整批
                fail += 1
                print(f"  索引重建失败 {t['doc']}: {str(exc)[:140]}")
        print(f"索引重建完成：成功 {ok} / 失败 {fail}")
    else:
        print("（未加 --reindex：jsonl 已补，但索引还是旧的，记得重建）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
