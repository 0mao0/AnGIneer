"""Open RAG Bench 题集 gold 自动标注：用金标答案在金标文档内定位答案承载块，回填 section/chunk/target 级标注。

背景：convert_evals.py 只填 gold_doc_ids，导致 hit@1/3/5(sec) 与 citation_hit 恒为 0（无标注可算）。
本脚本对每道题，在该题金标文档的全部 canonical chunks 上计算金标答案 token 覆盖率，
覆盖达标的 chunk 的 section_path / chunk_id / citation_target_id 回填为 gold，
使块级检索质量（换 embedding 模型后最该盯的指标）变得可观测。

用法：
    python scripts/open_ragbench/annotate_gold_targets.py            # dry-run，只打印统计
    python scripts/open_ragbench/annotate_gold_targets.py --yes      # 写回题集 JSON（自动备份）
    python scripts/open_ragbench/annotate_gold_targets.py --yes --import-evals  # 写回并同步导入 evals 库
"""
import argparse
import json
import re
import shutil
import sys
from collections import Counter
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_BUNDLE = REPO_ROOT / "data" / "evals" / "datasets" / "open-ragbench-subset-v2.json"

STOP_WORDS = set(
    "the a an and or of in on for to with by is are was were be been as at from that this these those it its".split()
)


def gold_tokens(text: str) -> set:
    """金标答案的内容词：≥4 字母的单词 + 数字，去停用词。"""
    toks = re.findall(r"[A-Za-z]{4,}|\d+(?:\.\d+)?", (text or "").lower())
    return {t for t in toks if t not in STOP_WORDS}


def coverage(text: str, tokens: set) -> float:
    if not tokens:
        return 0.0
    low = (text or "").lower()
    return sum(1 for t in tokens if t in low) / len(tokens)


def annotate_bundle(bundle: dict, *, threshold: float, max_sections: int, min_coverage: float) -> dict:
    """对题集逐项回填 gold_section_paths/gold_chunk_ids/gold_target_ids。返回统计。

    定位 token 取金标答案内容词；答案为 Yes/No 等无内容词时回退用问题内容词
    （二元题定位"问题主题所在章节"，仍有检索观测价值）。
    """
    from docs_core.docs_service import get_docs_service

    kp = get_docs_service()
    stats = Counter()
    chunk_cache: dict = {}

    for item in bundle.get("items", []):
        retrieval = item.get("retrieval") or {}
        answer = (item.get("answer") or {}).get("gold_answer") or ""
        gold_doc_ids = [str(d or "").strip() for d in (retrieval.get("gold_doc_ids") or []) if str(d or "").strip()]
        tokens = gold_tokens(answer)
        if len(tokens) < 3:
            tokens |= gold_tokens(item.get("question") or "")
        if not gold_doc_ids or not tokens:
            stats["skipped_no_gold"] += 1
            continue
        doc_id = gold_doc_ids[0]
        if doc_id not in chunk_cache:
            chunk_cache[doc_id] = kp.list_canonical_chunks(doc_id, limit=100000)
        chunks = chunk_cache[doc_id]
        if not chunks:
            stats["no_chunks"] += 1
            continue

        scored = []
        for chunk in chunks:
            text = f"{chunk.section_path}\n{chunk.text}"
            cov = coverage(text, tokens)
            if cov >= threshold:
                scored.append((cov, chunk))
        scored.sort(key=lambda pair: pair[0], reverse=True)
        if not scored or scored[0][0] < min_coverage:
            stats["below_threshold"] += 1
            continue

        section_paths: list = []
        chunk_ids: list = []
        target_ids: list = []
        target_types: list = []
        for cov, chunk in scored:
            section = str(chunk.section_path or "").strip()
            if section and section not in section_paths and len(section_paths) < max_sections:
                section_paths.append(section)
            chunk_ids.append(chunk.chunk_id)
            if chunk.citation_targets:
                target_id = str(chunk.citation_targets[0].target_id or "").strip()
                target_type = str(chunk.citation_targets[0].target_type or "").strip()
                if target_id and target_id not in target_ids:
                    target_ids.append(target_id)
                if target_type and target_type not in target_types:
                    target_types.append(target_type)
        retrieval["gold_section_paths"] = section_paths
        retrieval["gold_chunk_ids"] = chunk_ids[:20]
        retrieval["gold_target_ids"] = target_ids[:20]
        retrieval["gold_target_types"] = target_types or (["content"] if chunk_ids else [])
        item["retrieval"] = retrieval
        stats["annotated"] += 1
        stats[f"sections_{len(section_paths)}"] += 1
    return stats


def main() -> int:
    parser = argparse.ArgumentParser(description="gold section/chunk/target 自动标注")
    parser.add_argument("--bundle", default=str(DEFAULT_BUNDLE), help="题集 JSON 路径")
    parser.add_argument("--threshold", type=float, default=0.3, help="chunk 入选覆盖率阈值（默认 0.3）")
    parser.add_argument("--min-coverage", type=float, default=0.15, help="最佳块覆盖率低于此值则放弃标注（默认 0.15）")
    parser.add_argument("--max-sections", type=int, default=3, help="每题最多标注章节数（默认 3）")
    parser.add_argument("--yes", action="store_true", help="确认写回题集（自动备份原文件）")
    parser.add_argument("--import-evals", action="store_true", help="写回后同步导入 evals 库（INSERT OR REPLACE）")
    args = parser.parse_args()

    bundle_path = Path(args.bundle)
    bundle = json.load(open(bundle_path, encoding="utf-8"))
    stats = annotate_bundle(
        bundle,
        threshold=args.threshold,
        max_sections=args.max_sections,
        min_coverage=args.min_coverage,
    )
    total = len(bundle.get("items", []))
    print(f"题数={total} 统计={dict(stats)}")

    if not args.yes:
        print("DRY RUN：加 --yes 才会写回题集")
        return 0

    backup = bundle_path.with_suffix(bundle_path.suffix + ".bak-" + datetime.now().strftime("%Y%m%d-%H%M%S"))
    shutil.copy2(bundle_path, backup)
    bundle_path.write_text(json.dumps(bundle, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"已写回 {bundle_path}（备份 {backup.name}）")

    if args.import_evals:
        from evals_core.dataset.manager import import_bundle

        meta = import_bundle(bundle, source_file=str(bundle_path))
        print(f"已导入 evals 库: dataset={meta.get('dataset_id')} questions={meta.get('question_count')}")
    else:
        print("如需同步到 evals 库：加 --import-evals，或之后用 run_eval.py --import-only")
    return 0


if __name__ == "__main__":
    sys.exit(main())
