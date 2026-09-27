"""FinanceBench 试点集（10 题）→ financebench-pilot-10-v1，仅用于管道健康检查。

预注册纪律（docs/plan-financebench-arms.md 公平性 1）：试点只看管道健康
（判分失败率、hit@doc、答案目检），不据此改配方、不进主报告。
抽样：question_type 分层随机（seed=42），只取已入库文档的题。
注册：evals_core.dataset.manager.import_bundle（题行进 evals.sqlite，json 落 data/evals/datasets/）。
"""
import json
import random
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "services" / "evals-core" / "src"))
sys.path.insert(0, str(REPO / "services" / "angineer-core" / "src"))

import importlib.util as _ilu  # noqa: E402

_spec = _ilu.spec_from_file_location("fb_build_bundle", Path(__file__).with_name("build_bundle.py"))
_mod = _ilu.module_from_spec(_spec)
_spec.loader.exec_module(_mod)
numeric_keywords = _mod.numeric_keywords

QUESTIONS = REPO / "data" / "financebench" / "raw" / "financebench_open_source.jsonl"
STATE = REPO / "data" / "financebench" / "ingest" / "import_state.json"

PILOT_ID = "financebench-pilot-10-v1"
SEED = 42
N_PER_BUCKET = {"metrics-generated": 4, "domain-relevant": 3, "novel-generated": 3}


def main() -> int:
    state = json.loads(STATE.read_text(encoding="utf-8"))
    library_id = state.get("library_id") or ""
    done = {d: r["doc_id"] for d, r in state.get("docs", {}).items()
            if r.get("status") in ("succeeded", "partial") and r.get("doc_id")}
    rows = [json.loads(l) for l in QUESTIONS.read_text(encoding="utf-8").splitlines() if l.strip()]

    buckets: dict = {}
    for row in rows:
        doc = row["doc_name"]
        if doc not in done:
            continue
        buckets.setdefault(row.get("question_type") or "unknown", []).append(row)

    rng = random.Random(SEED)
    picked = []
    for qtype, n in N_PER_BUCKET.items():
        pool = buckets.get(qtype, [])
        rng.shuffle(pool)
        picked.extend(pool[:n])
    if len(picked) < 10:
        print(f"可用题不足：分层后仅 {len(picked)} 题（各桶池 { {k: len(v) for k, v in buckets.items()} }）")
        return 2

    items = []
    for row in picked:
        doc = row["doc_name"]
        answer = str(row.get("answer") or "").strip()
        checks = []
        kws = numeric_keywords(answer)
        if kws:
            checks = [{"type": "contains_any", "keywords": kws}]
        items.append({
            "question_id": row["financebench_id"],
            "question": row["question"],
            "task_type": "rag",
            "intent_level": "L1",
            "library_id": library_id,
            "doc_ids": [done[doc]],
            "difficulty": "medium",
            "tags": [row.get("question_type") or "", row.get("company") or "", doc],
            "question_family": row.get("question_reasoning") or "",
            "canonical_question_id": row["financebench_id"],
            "variant_type": "canonical",
            "perturbation_tags": [],
            "retrieval": {
                "gold_doc_ids": [done[doc]],
                "question_type": "definition_qa",
                "notes": json.dumps(
                    [{"page": ev.get("evidence_page_num")} for ev in row.get("evidence") or []],
                    ensure_ascii=False),
            },
            "answer": {
                "gold_answer": answer,
                "correctness_checks": checks,
                "semantic_threshold": 0.65,
                "must_cite_target_ids": [],
                "must_cite_section_paths": [],
                "refusal_expected": False,
            },
        })

    bundle = {
        "dataset": {
            "dataset_id": PILOT_ID,
            "title": "FinanceBench 试点（10 题，管道健康检查）",
            "category": "knowledge",
            "description": (
                f"预注册 {PILOT_ID.replace('-pilot-10-v1', '-open-150-v1')} 的试点抽样：question_type 分层随机"
                f"（seed={SEED}，4/3/3），只取已入库文档。仅看判分失败率/hit@doc/答案目检，不进主报告。"
            ),
            "schema_version": "eval.bundle.v2",
            "version": "1.0",
            "library_id": library_id,
        },
        "items": items,
    }
    from evals_core.dataset import manager
    existing = manager.get_dataset(PILOT_ID)
    if existing:
        manager.delete_dataset(PILOT_ID)
    res = manager.import_bundle(bundle, source_file="scripts/financebench/build_pilot.py")
    print(f"已注册 {PILOT_ID}: {len(items)} 题, dataset={res.get('dataset', res)}")
    for it in items:
        print("  ", it["question_id"], "|", it["tags"][0], "|", it["tags"][2], "|", it["question"][:60])
    return 0


if __name__ == "__main__":
    sys.exit(main())
