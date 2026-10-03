"""FinanceBench 开源子集 150 题 → eval.bundle（financebench-open-150-v1）。

输入：
  data/evals/originals/financebench/raw/financebench_open_source.jsonl（官方题集）
  data/evals/originals/financebench/ingest/import_state.json（import_docs.py 产物：doc_name → doc_id / 状态）
输出：
  data/evals/datasets/financebench-open-150-v1.json

配方真相源 = docs/plan-financebench-arms.md（预注册，勿在此随意加料）。
入库未完成时报错拒跑（doc_id 映射缺失 = 检索 gold 无法落地）。
"""
import json
import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
QUESTIONS = REPO / "data" / "evals" / "originals" / "financebench" / "raw" / "financebench_open_source.jsonl"
STATE = REPO / "data" / "evals" / "originals" / "financebench" / "ingest" / "import_state.json"
OUT = REPO / "data" / "evals" / "datasets" / "financebench-open-150-v1.json"

DATASET_ID = "financebench-open-150-v1"

# 纯数值答案（可带 $ / % / 千分位）→ contains_any 裸数字断言（判分失败兜底用；
# normalize_eval_text 去逗号与货币符，故裸数字即可匹配 "1,577"/"$1577.00" 等写法）
NUMERIC_ANSWER = re.compile(r"^\s*[-+]?\$?\d[\d,]*\.?\d*\s*%?\s*$")


def numeric_keywords(answer: str) -> list:
    """归一化后 "1577.00" 与 "1577" 是不同串（模型可能答 "$1,577 million"），
    contains_any 同时收两种写法。"""
    if not NUMERIC_ANSWER.match(answer or ""):
        return []
    digits = re.sub(r"[^\d.]", "", answer).rstrip(".")
    if not digits:
        return []
    variants = [digits]
    if "." in digits:
        head, _, tail = digits.partition(".")
        if tail and set(tail) <= {"0"} and head:
            variants.append(head)
    return variants


def main() -> int:
    state = json.loads(STATE.read_text(encoding="utf-8"))
    library_id = state.get("library_id") or ""
    if not library_id:
        print("import_state.json 缺 library_id：先跑 import_docs.py --create-only")
        return 2
    doc_map = {doc: rec for doc, rec in state.get("docs", {}).items()}
    missing = []
    rows = [json.loads(line) for line in QUESTIONS.read_text(encoding="utf-8").splitlines() if line.strip()]
    items = []
    for row in rows:
        doc = row["doc_name"]
        rec = doc_map.get(doc, {})
        if rec.get("status") not in ("succeeded", "partial") or not rec.get("doc_id"):
            missing.append(doc)
            continue
        doc_id = rec["doc_id"]
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
            "doc_ids": [doc_id],
            "difficulty": "medium",
            "tags": [row.get("question_type") or "", row.get("company") or "", doc],
            "question_family": row.get("question_reasoning") or "",
            "canonical_question_id": row["financebench_id"],
            "variant_type": "canonical",
            "perturbation_tags": [],
            "retrieval": {
                "gold_doc_ids": [doc_id],
                "question_type": "definition_qa",
                "notes": json.dumps(
                    [{"page": ev.get("evidence_page_num")} for ev in row.get("evidence") or []],
                    ensure_ascii=False,
                ),
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
    if missing:
        print(f"入库未完成的文档 {len(set(missing))} 篇（先跑 import_docs.py 再构建）：", sorted(set(missing))[:10])
        return 3
    bundle = {
        "dataset": {
            "dataset_id": DATASET_ID,
            "title": "FinanceBench 开源子集（150 题）",
            "category": "knowledge",
            "description": (
                "patronus-ai/financebench 开源 150 题（metrics-generated/domain-relevant/novel-generated 各 50），"
                "语料 = 官方 doc_link 下载 84 篇 SEC PDF（blob_sha 与仓库对账）。"
                "预注册配方与判据见 docs/plan-financebench-arms.md。判分口径与论文不同（DeepEval vs 人工），并列呈现。"
            ),
            "schema_version": "eval.bundle.v2",
            "version": "1.0",
            "library_id": library_id,
        },
        "items": items,
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(bundle, ensure_ascii=False, indent=2), encoding="utf-8")
    n_kw = sum(1 for it in items if it["answer"]["correctness_checks"])
    print(f"已写 {OUT}: {len(items)} 题（数值断言 {n_kw} 题），library_id={library_id}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
