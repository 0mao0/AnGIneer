"""分层抽样子集：论文 + 题目 + 硬负例。"""
import argparse
import random
import sys
from pathlib import Path

from open_ragbench import common


def _stable_shuffle(items, seed):
    rnd = random.Random(seed)
    return sorted(items, key=lambda x: rnd.random())


def build_manifest(
    queries,
    qrels,
    answers,
    pdf_urls,
    seed: int = 42,
    min_per_source: int = 10,
    max_questions: int = 120,
    hard_negative_count: int = 6,
):
    doc_queries = {}
    for uid, rel in qrels.items():
        doc_id = rel.get("doc_id") if isinstance(rel, dict) else rel
        if not doc_id:
            continue
        doc_queries.setdefault(doc_id, []).append(uid)

    selected_papers = {}
    question_ids = []

    for idx, source in enumerate(common.SOURCES):
        eligible = [d for d in doc_queries if d in pdf_urls]
        count = 0
        for doc_id in _stable_shuffle(eligible, seed + idx):
            if count >= min_per_source:
                break
            if doc_id in selected_papers:
                continue
            uids = [
                u for u in doc_queries[doc_id]
                if queries.get(u, {}).get("source") == source and u in answers
            ]
            if not uids:
                continue
            selected_papers[doc_id] = uids
            question_ids.extend(uids)
            count += 1

    remaining = [d for d in doc_queries if d in pdf_urls and d not in selected_papers]
    for doc_id in _stable_shuffle(remaining, seed + 99):
        if len(question_ids) >= max_questions:
            break
        uids = [u for u in doc_queries[doc_id] if u in answers and u in queries]
        if not uids:
            continue
        selected_papers[doc_id] = uids
        question_ids.extend(uids)

    positive_ids = set(doc_queries.keys())
    hard_negatives = [pid for pid in pdf_urls if pid not in positive_ids]
    chosen_hn = _stable_shuffle(hard_negatives, seed + 7)[:hard_negative_count]

    papers = [
        {"paper_id": doc_id, "url": pdf_urls[doc_id], "is_hard_negative": False}
        for doc_id in selected_papers
    ]
    papers += [
        {"paper_id": doc_id, "url": pdf_urls[doc_id], "is_hard_negative": True}
        for doc_id in chosen_hn
    ]

    questions = []
    for uid in question_ids:
        q = queries[uid]
        rel = qrels[uid]
        questions.append({
            "uuid": uid,
            "query": q.get("query", ""),
            "type": q.get("type", ""),
            "source": q.get("source", ""),
            "doc_id": rel.get("doc_id") if isinstance(rel, dict) else rel,
            "answer": answers.get(uid, ""),
        })

    return {
        "papers": papers,
        "questions": questions,
        "selection": {
            "seed": seed,
            "min_per_source": min_per_source,
            "max_questions": max_questions,
            "hard_negative_count": hard_negative_count,
            "paper_count": len(papers),
            "question_count": len(questions),
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="分层抽样 Open RAG Benchmark 子集")
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--min-per-source", type=int, default=10)
    parser.add_argument("--max-questions", type=int, default=120)
    parser.add_argument("--hard-negative-count", type=int, default=6)
    parser.add_argument("--out", default=str(common.SUBSET_MANIFEST))
    args = parser.parse_args()

    common.ensure_dirs()
    manifest = build_manifest(
        common.load_json(common.RAW_DIR / "queries.json"),
        common.load_json(common.RAW_DIR / "qrels.json"),
        common.load_json(common.RAW_DIR / "answers.json"),
        common.load_json(common.RAW_DIR / "pdf_urls.json"),
        seed=args.seed,
        min_per_source=args.min_per_source,
        max_questions=args.max_questions,
        hard_negative_count=args.hard_negative_count,
    )
    common.save_json(Path(args.out), manifest)
    print("子集已生成:", manifest["selection"])
    return 0


if __name__ == "__main__":
    sys.exit(main())
