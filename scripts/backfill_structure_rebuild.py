"""按「结构层重建」回填存量文档：structure → figure_describe → fts → vectors。

为什么需要它：解析侧的改动（题注指针 / title 短行提升 / 续接文本重归属）都落在
`structure` 阶段，而**存量文档不会自动更新**。现有的「重试/批量重试」只补**缺失**阶段
（`retry_parse_task`：全部完成后 remaining 为空 → 一个任务都不建），所以对存量无效，
必须显式指定阶段。

为什么跳过 `raw_parse`：`structure` 只校验 `mineru_raw/` 目录存在
（`parse_pipeline.py` 的 `_verify_mineru_raw_input`），MinerU 的产物是留存的 → 不重跑
MinerU（GPU/网络，~13.6–17.5 s/页）。同理不重跑 `popo`（`parsed/popo/` 产物在盘上，
structure 会读它做信号注入）。

为什么必须紧跟 `figure_describe`：`structure` 会重写 `doc_blocks_graph.jsonl`，把 VLM 写的
`figure_description` 抹掉；而描述会在 `fts` 阶段被拼进 canonical 可检索文本。不补跑 = 图那部分
检索文本消失（唯一有损项）。

用法（默认 dry-run，必须显式 --apply 才写盘）：
  python scripts/backfill_structure_rebuild.py --library lib-7582b086
  python scripts/backfill_structure_rebuild.py --library lib-7582b086 --docs od-xxx,od-yyy --apply \
      --backup-dir /app/data/backups/structure-rebuild-20260919

在服务器上执行建议放进 docs-api 容器（代码与数据都在里面）：
  docker cp scripts/backfill_structure_rebuild.py angineer-docs-api:/tmp/
  docker exec -w /app/services/aichat-api angineer-docs-api python /tmp/backfill_structure_rebuild.py ...
"""
import argparse
import json
import shutil
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
for _p in (REPO / "services" / "docs-core" / "src", REPO / "services" / "angineer-core" / "src"):
    if _p.is_dir() and str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import docs_core.paths as paths  # noqa: E402

STAGES = ("structure", "figure_describe", "fts", "vectors")


def _doc_ids(library_id: str, explicit: str, limit: int) -> list[str]:
    if explicit:
        return [d.strip() for d in explicit.split(",") if d.strip()]
    documents_dir = paths.library_root(library_id) / "documents"
    ids = sorted(p.name for p in documents_dir.iterdir() if p.is_dir())
    return ids[:limit] if limit else ids


def _preflight(library_id: str, doc_id: str, skip_figure: bool) -> str | None:
    """返回不可跑的原因（None = 可跑）。所有条件都是 structure 重跑的硬前提。"""
    parsed = paths.get_parsed_dir(library_id, doc_id)
    raw = paths.get_mineru_raw_dir(library_id, doc_id)
    if not (raw / "content_list_v2.json").exists() and not (raw / "content_list.json").exists():
        return "缺 mineru_raw/content_list(_v2).json（只能走完整重解析）"
    # _save_doc_blocks_graph 缺 content.md 会直接抛错
    if not (parsed / "content.md").exists():
        return "缺 parsed/content.md（structure 落盘会抛错）"
    if not paths.get_graph_jsonl_path(library_id, doc_id).exists():
        return "缺 doc_blocks_graph.jsonl（无既有结构产物）"
    if not skip_figure:
        try:
            from docs_core.step04_structure.figure_describer import is_enabled

            if not is_enabled():
                return "图描述未启用（FIGURE_DESCRIBE_ENABLED=0）——structure 会抹掉既有描述，需先开启"
        except Exception as exc:  # noqa: BLE001
            return f"图描述模块不可用: {exc}"
    return None


def _backup(library_id: str, doc_id: str, backup_dir: Path) -> Path:
    src = paths.get_graph_jsonl_path(library_id, doc_id)
    meta = paths.get_graph_meta_path(library_id, doc_id)
    dst_dir = backup_dir / doc_id
    dst_dir.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, dst_dir / "doc_blocks_graph.jsonl")
    if meta.exists():
        shutil.copy2(meta, dst_dir / "doc_blocks_graph_meta.json")
    md = paths.get_parsed_markdown_path(library_id, doc_id)
    if md.exists():
        shutil.copy2(md, dst_dir / "content.md")
    return dst_dir


def _run_structure(library_id: str, doc_id: str) -> dict:
    from docs_core.step04_structure.solo2json_pipeline import build_structured_index_for_doc

    # use_llm=True：与线上一次全新解析同口径（title 层级仲裁/公式表格语义走远程 LLM），
    # 避免同一库里出现两种口径的产物
    result = build_structured_index_for_doc(
        library_id=library_id,
        doc_id=doc_id,
        strategy="doc_blocks_graph_v1",
        options={"use_llm": True, "llm_model": None},
    )
    return result.get("stats") or {}


def _run_figure_describe(library_id: str, doc_id: str) -> dict:
    from docs_core.step04_structure.figure_describer import describe_figures_in_graph

    return describe_figures_in_graph(library_id, doc_id)


def _run_fts(library_id: str, doc_id: str) -> dict:
    from docs_core.step05_sqlite_fts.sqlite_index import build_sqlite_index_from_graph

    return build_sqlite_index_from_graph(library_id, doc_id)


def _run_vectors(doc_id: str) -> None:
    from docs_core.docs_service import get_docs_service

    get_docs_service().rebuild_document_vectors(doc_id)


def _counts(library_id: str, doc_id: str) -> dict:
    """重建前后可比的三项：jsonl 空段落数、title 块数、图块有无描述。"""
    p = paths.get_graph_jsonl_path(library_id, doc_id)
    empty_para = titles = figures = described = 0
    for line in p.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        n = json.loads(line)
        bt = n.get("block_type")
        if bt == "paragraph" and not (n.get("plain_text") or "").strip():
            empty_para += 1
        if bt == "title":
            titles += 1
        if bt in ("image", "chart", "figure"):
            figures += 1
            if str(n.get("figure_description") or "").strip():
                described += 1
    return {"空段落": empty_para, "title块": titles, "图块": figures, "有描述": described}


def main() -> int:
    ap = argparse.ArgumentParser(description="按结构层重建回填存量文档")
    ap.add_argument("--library", required=True)
    ap.add_argument("--docs", default="", help="逗号分隔 doc_id；留空=整库")
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--apply", action="store_true", help="真的写盘（默认 dry-run）")
    ap.add_argument("--backup-dir", default="", help="备份 doc_blocks_graph.jsonl + meta + content.md")
    ap.add_argument("--skip-figure-describe", action="store_true", help="跳过图描述补跑（接受描述丢失）")
    ap.add_argument("--progress", default="", help="进度文件（断点续跑；默认 <backup-dir>/progress.json）")
    args = ap.parse_args()

    doc_ids = _doc_ids(args.library, args.docs, args.limit)
    print(f"库 {args.library}：待处理 {len(doc_ids)} 篇；模式 {'APPLY（会写盘）' if args.apply else 'DRY-RUN'}")

    blocked: list[tuple[str, str]] = []
    runnable: list[str] = []
    for doc_id in doc_ids:
        reason = _preflight(args.library, doc_id, args.skip_figure_describe)
        (blocked.append((doc_id, reason)) if reason else runnable.append(doc_id))
    print(f"可跑 {len(runnable)} 篇；前置不满足 {len(blocked)} 篇")
    for doc_id, reason in blocked[:10]:
        print(f"  跳过 {doc_id}: {reason}")
    if len(blocked) > 10:
        print(f"  …另有 {len(blocked) - 10} 篇同样跳过")

    if not args.apply:
        print("\nDRY-RUN：未执行任何写操作。加 --apply 才真正重建。")
        return 0

    backup_dir = Path(args.backup_dir) if args.backup_dir else None
    if backup_dir is None:
        raise SystemExit("--apply 必须配 --backup-dir（jsonl 是原地重写，需要回滚路径）")
    backup_dir.mkdir(parents=True, exist_ok=True)
    progress_path = Path(args.progress) if args.progress else backup_dir / "progress.json"
    done: dict[str, dict] = {}
    if progress_path.exists():
        done = json.loads(progress_path.read_text(encoding="utf-8"))
        print(f"续跑：进度文件已有 {len(done)} 篇记录")

    for idx, doc_id in enumerate(runnable, 1):
        if done.get(doc_id, {}).get("status") == "done":
            print(f"[{idx}/{len(runnable)}] {doc_id} 已完成，跳过")
            continue
        started = time.time()
        rec: dict = {"status": "running", "stages": {}}
        try:
            before = _counts(args.library, doc_id)
            rec["backup"] = str(_backup(args.library, doc_id, backup_dir))
            rec["stages"]["structure"] = _run_structure(args.library, doc_id)
            if not args.skip_figure_describe:
                rec["stages"]["figure_describe"] = _run_figure_describe(args.library, doc_id)
            rec["stages"]["fts"] = _run_fts(args.library, doc_id)
            _run_vectors(doc_id)
            rec["stages"]["vectors"] = "ok"
            rec["before"] = before
            rec["after"] = _counts(args.library, doc_id)
            rec["status"] = "done"
        except Exception as exc:  # noqa: BLE001
            rec["status"] = "failed"
            rec["error"] = f"{type(exc).__name__}: {exc}"
            print(f"  !! {doc_id} 失败: {rec['error'][:200]}")
        rec["seconds"] = round(time.time() - started, 1)
        done[doc_id] = rec
        progress_path.write_text(json.dumps(done, ensure_ascii=False, indent=1), encoding="utf-8")
        if rec["status"] == "done":
            b, a = rec.get("before", {}), rec.get("after", {})
            print(
                f"[{idx}/{len(runnable)}] {doc_id} 完成 {rec['seconds']}s  "
                f"空段落 {b.get('空段落')}→{a.get('空段落')}  title块 {b.get('title块')}→{a.get('title块')}  "
                f"图描述 {b.get('有描述')}/{b.get('图块')}→{a.get('有描述')}/{a.get('图块')}  "
                f"重归属 {rec['stages']['structure'].get('continuation_text_reattaches')}"
            )

    ok = sum(1 for v in done.values() if v.get("status") == "done")
    failed = [k for k, v in done.items() if v.get("status") == "failed"]
    print(f"\n完成 {ok}/{len(runnable)}；失败 {len(failed)}")
    if failed:
        print("失败清单:", ", ".join(failed[:20]))
    print(f"进度/审计: {progress_path}")
    return 0 if not failed else 1


if __name__ == "__main__":
    sys.exit(main())
