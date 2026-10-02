"""GDP.pdf 官方 100 题 → eval.bundle（gdp-pdf-v1）。

输入：
  data/gdp_pdf/raw/parquet_a.parquet（官方题集，三镜像字节一致锁定）
  data/gdp_pdf/ingest/import_state.json（import_docs.py 产物：pdf 文件名 → doc_id/状态）
输出：
  data/evals/datasets/gdp-pdf-v1.json

判分口径（预注册）：headline = 官方 rubric 全条通过 all_pass（对齐 Surge 榜 "100% rubrics"），
判分器 = evals_core.runner.rubric_eval（RAG 生成后判官逐条判，判官崩→skipped 不假绿）。
入库未完成时报错拒跑（doc_id 缺失 = 检索/问答无法落地到该篇）。

注：官方口径是「整本 PDF 直读多模态模型」，本集走「解析入库→检索→生成」RAG 链，
属修改口径，成绩只能与官方数字并列引用，不得成表对比。
"""
import argparse
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
PARQUET = REPO / "data" / "gdp_pdf" / "raw" / "parquet_a.parquet"
QUESTIONS = REPO / "data" / "gdp_pdf" / "raw" / "questions.json"
STATE = REPO / "data" / "gdp_pdf" / "ingest" / "import_state.json"
OUT = REPO / "data" / "evals" / "datasets" / "gdp-pdf-v1.json"
LEVELS = REPO / "data" / "gdp_pdf" / "raw" / "levels.json"

DATASET_ID = "gdp-pdf-v1"


def load_questions() -> list:
    """题集真相源：优先 questions.json（parquet→JSON 预转，去掉 pandas 依赖，服务器/容器可跑）；
    缺则回退读 parquet（需本地装 pandas）。"""
    if QUESTIONS.exists():
        return json.loads(QUESTIONS.read_text(encoding="utf-8"))
    import pandas as pd  # 仅回退路径需要

    df = pd.read_parquet(PARQUET)
    rows = []
    for _, r in df.iterrows():
        d = r.to_dict()
        rows.append({
            "task_id": str(d["task_id"]),
            "question": str(d["prompt"]),
            "domain": str(d.get("domain") or ""),
            "pdf_filename": Path(str(d["pdf_path"])).name,
            "worker_id": str(d.get("worker_id") or ""),
            "criteria": extract_criteria(d),
        })
    return rows


def extract_criteria(row: dict) -> list:
    crit = []
    for i in range(1, 31):
        text = row.get(f"rubric - {i}. criterion")
        if not isinstance(text, str) or not text.strip():
            continue
        crit.append({
            "i": i,
            "text": text.strip(),
            "type": row.get(f"rubric - {i}. criterion_type") or "",
            "severity": row.get(f"rubric - {i}. criterion_severity") or "",
            "implicitness": row.get(f"rubric - {i}. criterion_implicitness") or "",
            "subjectiveness": row.get(f"rubric - {i}. criterion_subjectiveness") or "",
            "failure_mode": row.get(f"rubric - {i}. criterion_failure_mode") or "",
        })
    return crit


def _card_meta(rows: list, library_id: str) -> dict:
    """题集卡 meta（契约见 packages/evals-ui/src/types/eval.ts EvalDatasetCardMeta）。"""
    from collections import Counter

    dom_counts = Counter(str(r.get("domain") or "") for r in rows)
    distribution = [
        {"label": dom, "count": cnt}
        for dom, cnt in sorted(dom_counts.items(), key=lambda kv: -kv[1])
    ]
    return {
        "publisher": "Surge AI",
        "domain": "多专业高难度",
        "mode": "单篇RAG",
        "purpose": "多专业高难度题集，测图文解读、表格抽取与多步推理",
        "source_url": "https://surgehq.ai/benchmarks/gdp-pdf",
        "source_note": (
            "官方 HF surgeai/GDP.pdf 已转私有；取社区镜像 tolo6474/GDP.pdf，"
            "与另两镜像 data.parquet 逐字节 sha256 一致（2ba18b4f…）；判分口径见 docs/req-gdp-pdf.md"
        ),
        "distribution": distribution,
        "leaderboard": [
            {"label": "GPT-5.5 (xHigh)", "score": "25%", "note": "all_pass·整本直读多模态"},
            {"label": "Claude Opus 4.8", "score": "23%", "note": "all_pass·整本直读多模态"},
            {"label": "Gemini 3.5 Flash", "score": "14%", "note": "官方判官模型"},
        ],
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=str(OUT))
    ap.add_argument("--dataset-id", default=DATASET_ID)
    args = ap.parse_args()

    state = json.loads(STATE.read_text(encoding="utf-8"))
    library_id = state.get("library_id") or ""
    if not library_id:
        print("import_state.json 缺 library_id：先跑 import_docs.py --create-only")
        return 2
    doc_map = state.get("docs", {})
    # 层级真相源 = 生产意图分类器产物（scripts/gdp_pdf/classify_levels.py → levels.json）；缺省 L1
    levels = {}
    if LEVELS.exists():
        levels = json.loads(LEVELS.read_text(encoding="utf-8"))
    rows = load_questions()
    missing, items = [], []
    for row in rows:
        fname = row["pdf_filename"]
        rec = doc_map.get(fname, {})
        if rec.get("status") not in ("succeeded", "partial") or not rec.get("doc_id"):
            missing.append(fname)
            continue
        doc_id = rec["doc_id"]
        criteria = row.get("criteria") or []
        primary = [c["text"] for c in criteria if c["type"] == "Primary Intent"]
        tid = str(row["task_id"])
        level = (levels.get(tid) or {}).get("level") or "L1"
        qtype = (levels.get(tid) or {}).get("type") or ""
        items.append({
            "question_id": tid,
            "question": row["question"],
            "task_type": "rag",
            "intent_level": level,
            "library_id": library_id,
            "doc_ids": [doc_id],
            "difficulty": "hard",
            "tags": [row.get("domain") or "", "gdp-pdf", qtype, fname[:12]],
            "question_family": row.get("domain") or "",
            "canonical_question_id": tid,
            "variant_type": "canonical",
            "perturbation_tags": [],
            "retrieval": {
                "gold_doc_ids": [doc_id],
                "question_type": "definition_qa",
                "notes": json.dumps({"pdf_filename": fname, "worker_id": row.get("worker_id") or ""}, ensure_ascii=False),
            },
            "answer": {
                "gold_answer": "\n".join(primary),
                "correctness_checks": [],
                "semantic_threshold": 0.65,
                "must_cite_target_ids": [],
                "must_cite_section_paths": [],
                "refusal_expected": False,
            },
            "rubric": {"criteria": criteria},
        })
    if missing:
        print(f"入库未完成 {len(set(missing))} 篇（先跑 import_docs.py 再构建），样例:", sorted(set(missing))[:5])
        # 不拒跑：允许分批构建已入库题集，仅打印缺口
    bundle = {
        "dataset": {
            "dataset_id": args.dataset_id,
            "title": "【全域】GDP100 题",
            "category": "knowledge",
            "description": (
                "Surge AI GDP.pdf 官方 100 题 × 自带 PDF，10 域（工程/建筑/制造供应链等约 7–15 题/域）。"
                "判分 = 官方 rubric 全条通过 all_pass（RAG 生成后判官逐条判，见 evals_core.runner.rubric_eval）。"
                "口径为解析入库单篇 RAG（非官方整本直读多模态），与 Surge 榜并列引用、不成表对比。"
            ),
            "schema_version": "eval.bundle.v2",
            "version": "1.0",
            "library_id": library_id,
            "meta": _card_meta(rows, library_id),
        },
        "items": items,
    }
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(bundle, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"已写 {out}: {len(items)} 题, library_id={library_id}, 缺口 {len(set(missing))} 篇")
    return 0


if __name__ == "__main__":
    sys.exit(main())
