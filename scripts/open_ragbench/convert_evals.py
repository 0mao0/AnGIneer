"""子集题目 → EvalBundleV2 题集。"""
import argparse
import os
import sys
from pathlib import Path

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from open_ragbench import common


def build_eval_bundle(manifest, library_id: str, doc_id_map=None, dataset_id: str = None, title: str = None):
    """子集题目 → EvalBundleV2。

    doc_id_map: arxiv paper_id → 内部 doc_id（来自 import_state.json）。
    gold_doc_ids 必须填内部 doc_id，否则检索指标与 retrieved_doc_ids 无法对齐。
    """
    doc_id_map = doc_id_map or {}
    items = []
    for q in manifest.get("questions", []):
        arxiv_doc_id = q.get("doc_id", "")
        internal_doc_id = doc_id_map.get(arxiv_doc_id, arxiv_doc_id)
        items.append({
            "question_id": q["uuid"],
            "question": q["query"],
            "task_type": "rag",
            "intent_level": "L1",
            "library_id": library_id,
            "doc_ids": [],
            "difficulty": "medium",
            "tags": [q.get("source", ""), q.get("type", ""), arxiv_doc_id],
            "question_family": "",
            "canonical_question_id": "",
            "variant_type": "canonical",
            "perturbation_tags": [],
            "retrieval": {
                "gold_section_paths": [],
                "gold_chunk_ids": [],
                "gold_doc_ids": [internal_doc_id],
                "gold_target_ids": [],
                "gold_target_types": [],
                "question_type": "definition_qa",
                "notes": f"arxiv:{arxiv_doc_id}",
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
            "dataset_id": dataset_id or common.DATASET_ID,
            "title": title or "Open RAG Benchmark 子集 v1",
            "category": "knowledge",
            "description": "Open RAG Benchmark 子集，端到端评测 AnGIneer",
            "schema_version": "eval.bundle.v2",
            "version": "1.1",
            "library_id": library_id,
        },
        "items": items,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="子集题目转 EvalBundleV2")
    parser.add_argument("--manifest", default=str(common.SUBSET_MANIFEST), help="子集 manifest 路径")
    parser.add_argument("--dataset-id", default=common.DATASET_ID, help="题集 ID")
    parser.add_argument("--title", default="", help="题集标题")
    parser.add_argument("--out", default=str(common.EVAL_DATASET_FILE))
    args = parser.parse_args()

    manifest = common.load_json(Path(args.manifest))
    if not common.IMPORT_STATE.exists():
        print("import_state.json 不存在，请先运行 import_kb.py")
        return 2
    import_state = common.load_json(common.IMPORT_STATE)
    library_id = import_state.get("library_id", "")
    if not library_id:
        print("import_state.json 缺少 library_id，请先运行 import_kb.py")
        return 2
    papers = import_state.get("papers") or {}
    doc_id_map = {
        paper_id: info.get("doc_id", "")
        for paper_id, info in papers.items()
        if isinstance(info, dict) and info.get("doc_id")
    }
    bundle = build_eval_bundle(
        manifest, library_id,
        doc_id_map=doc_id_map,
        dataset_id=args.dataset_id,
        title=args.title or None,
    )
    out_path = Path(args.out)
    common.save_json(out_path, bundle)
    print("题集已生成:", out_path, "题目数:", len(bundle["items"]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
