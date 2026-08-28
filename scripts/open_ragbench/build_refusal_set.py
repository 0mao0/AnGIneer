"""拒答题集构建：抽取 gold 文档未入库的题目，期望系统拒答。

原理：Open RAG Bench 全量 1000 篇论文中仅子集入库，凡 doc_id 未入库的题目
在库内无证据，正确行为是拒答（refusal_expected=true）。用于度量
"不可答幻觉率"——用户信任的核心指标。
"""
import argparse
import os
import random
import sys
from pathlib import Path

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from open_ragbench import common


def build_refusal_bundle(
    queries,
    qrels,
    answers,
    pdf_urls,
    imported_doc_ids,
    library_id: str,
    count: int = 25,
    seed: int = 42,
    dataset_id: str = None,
):
    """从未入库论文的题目中分层抽样拒答题。"""
    candidates = []
    for uid, rel in qrels.items():
        doc_id = rel.get("doc_id") if isinstance(rel, dict) else rel
        if not doc_id or doc_id in imported_doc_ids:
            continue
        if doc_id not in pdf_urls:
            continue
        query = queries.get(uid) or {}
        if not query.get("query") or uid not in answers:
            continue
        candidates.append({
            "uuid": uid,
            "query": query["query"],
            "type": query.get("type", ""),
            "source": query.get("source", ""),
            "doc_id": doc_id,
            "answer": answers.get(uid, ""),
        })

    # 按题型（source）分层，保持与全集相近的分布
    by_source = {}
    for item in candidates:
        by_source.setdefault(item["source"] or "unknown", []).append(item)
    rnd = random.Random(seed)
    selected = []
    sources = sorted(by_source.keys())
    total = len(candidates)
    for source in sources:
        items = by_source[source]
        rnd.shuffle(items)
        quota = max(1, round(count * len(items) / total)) if total else 0
        selected.extend(items[:quota])
    rnd.shuffle(selected)
    selected = selected[:count]

    items = []
    for q in selected:
        items.append({
            "question_id": f"refusal-{q['uuid']}",
            "question": q["query"],
            "task_type": "rag",
            "intent_level": "L1",
            "library_id": library_id,
            "doc_ids": [],
            "difficulty": "medium",
            "tags": [q["source"], q["type"], q["doc_id"], "refusal"],
            "question_family": "unanswerable",
            "canonical_question_id": "",
            "variant_type": "canonical",
            "perturbation_tags": [],
            # gold 文档未入库：不做检索评测，仅验证拒答行为
            "retrieval": None,
            "answer": {
                "gold_answer": q["answer"],
                "correctness_checks": [],
                "semantic_threshold": 0.65,
                "must_cite_target_ids": [],
                "must_cite_section_paths": [],
                "refusal_expected": True,
            },
        })
    return {
        "dataset": {
            "dataset_id": dataset_id or common.REFUSAL_DATASET_ID,
            "title": "Open RAG Benchmark 拒答题集 v1",
            "category": "knowledge",
            "description": (
                "gold 文档未入库的不可答题，期望系统拒答；"
                "用于度量不可答幻觉率（refusal_accuracy / hallucination_on_unanswerable）"
            ),
            "schema_version": "eval.bundle.v2",
            "version": "1.0",
            "library_id": library_id,
        },
        "items": items,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="构建拒答题集（gold 文档未入库）")
    parser.add_argument("--count", type=int, default=25)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--dataset-id", default=common.REFUSAL_DATASET_ID)
    parser.add_argument("--out", default=str(common.REFUSAL_DATASET_FILE))
    args = parser.parse_args()

    if not common.IMPORT_STATE.exists():
        print("import_state.json 不存在，请先运行 import_kb.py")
        return 2
    import_state = common.load_json(common.IMPORT_STATE)
    library_id = import_state.get("library_id", "")
    if not library_id:
        print("import_state.json 缺少 library_id，请先运行 import_kb.py")
        return 2
    papers = import_state.get("papers") or {}
    imported_doc_ids = {
        paper_id
        for paper_id, info in papers.items()
        if isinstance(info, dict) and info.get("status") == "succeeded"
    }

    bundle = build_refusal_bundle(
        common.load_json(common.RAW_DIR / "queries.json"),
        common.load_json(common.RAW_DIR / "qrels.json"),
        common.load_json(common.RAW_DIR / "answers.json"),
        common.load_json(common.RAW_DIR / "pdf_urls.json"),
        imported_doc_ids,
        library_id,
        count=args.count,
        seed=args.seed,
        dataset_id=args.dataset_id,
    )
    out_path = Path(args.out)
    common.save_json(out_path, bundle)
    print("拒答题集已生成:", out_path, "题目数:", len(bundle["items"]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
