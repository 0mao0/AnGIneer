"""重算历史公式块的"符号校正"：删掉把下标删掉的错误修正（2026-09-14 生产 462 块）。

背景：step04 `_build_symbol_corrections` 的旧规则会拿说明段的泛指参数（无下标的
F、a）当真相源，把公式里的 F_{1}/a_{1} 改成 F/a——下标被当噪声删掉。代码守卫已
修（aa541d6），但存量 jsonl 里的 math_content_corrected / plain_text_corrected
还是改坏版，chunk 与向量用的正是 corrected 字段。本脚本按新规则重算：
  · 修正剩余 → 重写 corrected 字段；修正清空 → 删除 corrected/symbol_mismatch 字段
  · corrected_by=="user" 的节点不动；无 formula_semantics 的节点跳过并计数
重算只依赖节点自带的 formula_semantics.formula_params + 原始 math_content，
容器里是旧代码也没关系：用旧函数算出全部修正后，过滤"删下标"项（等价于新守卫）。

用法（服务器容器内；不加 --apply 即 dry-run）：
    python3 /app/data/ops/repair_symbol_corrections.py
    python3 /app/data/ops/repair_symbol_corrections.py --apply --reindex \
        --backup-dir /app/data/backups/symbol-fix-20260915
"""
import argparse
import json
import shutil
import sys
import tarfile
from datetime import datetime
from pathlib import Path

DATA_ROOT = Path("/app/data") if Path("/app/data").is_dir() else Path(__file__).resolve().parents[1] / "data"
LIBS = DATA_ROOT / "knowledge_base" / "libraries"

CORRECTED_FIELDS = (
    "math_content_corrected", "plain_text_corrected",
    "symbol_mismatch", "corrected_by", "corrected_at",
)


def _drops_subscript(corr: dict, extract_sub) -> bool:
    """修正把下标删掉了 → 该修正作废（等价 aa541d6 守卫，容器旧代码下同样成立）。"""
    original = str(corr.get("original") or "")
    corrected = str(corr.get("corrected") or "")
    return extract_sub(original) is not None and extract_sub(corrected) is None


def _recompute_node(node: dict, build_corr, apply_corr, extract_sub, should_write) -> str:
    """重算单个 mismatch 节点的 corrected 字段；返回 cleared|rewritten|same|skipped_*。"""
    if not should_write(node):
        return "skipped_user"
    semantics = node.get("formula_semantics")
    if not isinstance(semantics, dict):
        return "skipped_no_semantics"
    src = str(node.get("math_content") or node.get("plain_text") or "")
    corrections = [
        c for c in build_corr(src, semantics.get("formula_params") or [])
        if not _drops_subscript(c, extract_sub)
    ]
    core = ("math_content_corrected", "plain_text_corrected", "symbol_mismatch", "corrected_by")
    before = json.dumps({k: node.get(k) for k in core}, sort_keys=True, ensure_ascii=False)
    orig_at = node.get("corrected_at")
    for key in CORRECTED_FIELDS:
        node.pop(key, None)
    if corrections:
        node["math_content_corrected"] = apply_corr(src, corrections)
        raw_plain = str(node.get("plain_text") or "")
        if raw_plain.strip():
            corrected_plain = apply_corr(raw_plain, corrections)
            if corrected_plain != raw_plain:
                node["plain_text_corrected"] = corrected_plain
        node["symbol_mismatch"] = True
        node["corrected_by"] = "llm"
    after = json.dumps({k: node.get(k) for k in core}, sort_keys=True, ensure_ascii=False)
    if before == after:
        if corrections and orig_at is not None:
            node["corrected_at"] = orig_at
        return "same"
    if corrections:
        node["corrected_at"] = datetime.now().isoformat()
        return "rewritten"
    return "cleared"


def main() -> int:
    ap = argparse.ArgumentParser(description="重算公式符号校正，删除删下标的错误修正")
    ap.add_argument("--libraries", default="", help="逗号分隔库名；留空=全部")
    ap.add_argument("--apply", action="store_true", help="写回 jsonl（否则只统计）")
    ap.add_argument("--reindex", action="store_true", help="改过的文档重建 fts/向量（需 --apply）")
    ap.add_argument("--backup-dir", default="", help="改前的 jsonl 打包到这里")
    ap.add_argument("--limit", type=int, default=0)
    args = ap.parse_args()

    from docs_core.step04_structure.shared.formula_semantics import (
        _apply_symbol_replacements,
        _build_symbol_corrections,
        _extract_subscript_tex,
        _should_write_llm_correction,
    )

    want_libs = {s.strip() for s in args.libraries.split(",") if s.strip()}
    stats = {"docs_scanned": 0, "nodes_scanned": 0, "mismatch_nodes": 0,
             "cleared": 0, "rewritten": 0, "same": 0,
             "skipped_user": 0, "skipped_no_semantics": 0}
    targets = []
    for lib_dir in sorted(p for p in LIBS.iterdir() if p.is_dir()):
        if want_libs and lib_dir.name not in want_libs:
            continue
        docs_dir = lib_dir / "documents"
        if not docs_dir.is_dir():
            continue
        for doc_dir in sorted(p for p in docs_dir.iterdir() if p.is_dir()):
            graph = doc_dir / "parsed" / "doc_blocks_graph.jsonl"
            if not graph.is_file():
                continue
            stats["docs_scanned"] += 1
            nodes = [json.loads(x) for x in graph.read_text(encoding="utf-8").splitlines() if x.strip()]
            stats["nodes_scanned"] += len(nodes)
            dirty = []
            for i, node in enumerate(nodes):
                if not node.get("symbol_mismatch"):
                    continue
                stats["mismatch_nodes"] += 1
                outcome = _recompute_node(node, _build_symbol_corrections, _apply_symbol_replacements,
                                          _extract_subscript_tex, _should_write_llm_correction)
                stats[outcome] = stats.get(outcome, 0) + 1
                if outcome in ("cleared", "rewritten"):
                    dirty.append(i)
            if dirty:
                targets.append({"library": lib_dir.name, "doc": doc_dir.name,
                                "graph": graph, "nodes": nodes, "dirty": dirty})
    if args.limit:
        targets = targets[: args.limit]

    print("扫描统计:", json.dumps(stats, ensure_ascii=False))
    print(f"待写回 {len(targets)} 篇 / {sum(len(t['dirty']) for t in targets)} 块")
    for t in targets[:6]:
        print(f"  {t['library']}/{t['doc']}: {len(t['dirty'])} 块")
    if len(targets) > 6:
        print(f"  …其余 {len(targets) - 6} 篇")
    if not args.apply:
        print("（未加 --apply，未写任何文件）")
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

    for t in targets:
        tmp = t["graph"].with_suffix(".jsonl.tmp")
        tmp.write_text("".join(json.dumps(n, ensure_ascii=False) + "\n" for n in t["nodes"]), encoding="utf-8")
        shutil.move(str(tmp), str(t["graph"]))
        print(f"  已写回 {t['library']}/{t['doc']}: {len(t['dirty'])} 块")
    print(f"写回完成：{len(targets)} 篇")

    if args.reindex:
        from docs_core.docs_service import get_docs_service
        from docs_core.step05_sqlite_fts.sqlite_index import build_sqlite_index_from_graph

        ds = get_docs_service()

        def _points(doc_id: str) -> int:
            try:
                from qdrant_client import models
                vs = ds.vector_store
                r = vs._get_client().count(
                    collection_name=vs._collection,
                    count_filter=models.Filter(must=[models.FieldCondition(
                        key="doc_id", match=models.MatchValue(value=doc_id))]),
                    exact=True)
                return int(r.count)
            except Exception:  # noqa: BLE001 计数失败不阻断
                return -1

        ok = fail = 0
        for t in targets:
            try:
                build_sqlite_index_from_graph(t["library"], t["doc"])
                ds.rebuild_document_vectors(t["doc"])
                pts = _points(t["doc"])
                if pts == 0:
                    raise RuntimeError("重建后向量点数为 0（静默失败收口前最后一道人工闸）")
                ok += 1
                print(f"  索引重建 {t['doc']}: points={pts}")
            except Exception as exc:  # noqa: BLE001 单篇失败不阻断整批
                fail += 1
                print(f"  索引重建失败 {t['doc']}: {str(exc)[:140]}")
        print(f"索引重建完成：成功 {ok} / 失败 {fail}")
        if fail:
            return 1
    else:
        print("（未加 --reindex：jsonl 已改，但索引还是旧的）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
