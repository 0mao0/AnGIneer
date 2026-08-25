"""子集题目 → EvalBundleV2 题集。"""
import argparse
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from open_ragbench import common


def build_eval_bundle(manifest, library_id: str):
    items = []
    for q in manifest.get("questions", []):
        items.append({
            "question_id": q["uuid"],
            "question": q["query"],
            "task_type": "rag",
            "intent_level": "L1",
            "library_id": library_id,
            "doc_ids": [],
            "difficulty": "medium",
            "tags": [q.get("source", ""), q.get("type", ""), q.get("doc_id", "")],
            "question_family": "",
            "canonical_question_id": "",
            "variant_type": "canonical",
            "perturbation_tags": [],
            "retrieval": {
                "gold_section_paths": [],
                "gold_chunk_ids": [],
                "gold_doc_ids": [q.get("doc_id", "")],
                "gold_target_ids": [],
                "gold_target_types": [],
                "question_type": "definition_qa",
                "notes": "",
                "must_include_terms": [],
                "must_exclude_terms": [],
                "hard_negative_target_ids": [],
                "robustness_tags": [],
            },
            "answer": {
                "gold_answer": q.get("answer", ""),
                "correctness_checks": [],
                "semantic_threshold": 0.65,
                "must_cite_target_ids": [],
                "must_cite_section_paths": [],
                "refusal_expected": False,
            },
        })
    return {
        "dataset": {
            "dataset_id": common.DATASET_ID,
            "title": "Open RAG Benchmark 子集 v1",
            "category": "knowledge",
            "description": "Open RAG Benchmark 子集（30 篇论文、约 90-120 题），端到端评测 AnGIneer",
            "schema_version": "eval.bundle.v2",
            "version": "1.0",
            "library_id": library_id,
        },
        "items": items,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="子集题目转 EvalBundleV2")
    parser.add_argument("--out", default=str(common.EVAL_DATASET_FILE))
    args = parser.parse_args()

    manifest = common.load_json(common.SUBSET_MANIFEST)
    if not common.IMPORT_STATE.exists():
        print("import_state.json 不存在，请先运行 import_kb.py")
        return 2
    import_state = common.load_json(common.IMPORT_STATE)
    library_id = import_state.get("library_id", "")
    if not library_id:
        print("import_state.json 缺少 library_id，请先运行 import_kb.py")
        return 2
    bundle = build_eval_bundle(manifest, library_id)
    common.save_json(common.EVAL_DATASET_FILE, bundle)
    print("题集已生成:", common.EVAL_DATASET_FILE, "题目数:", len(bundle["items"]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
