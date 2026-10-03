# -*- coding: utf-8 -*-
"""OfficeQA Pro 133 → eval.bundle.v2 + 筛库清单（只改格式，不改判分）。

输入（业主 HF gated 获批后落盘，见 docs/plan-officeqa-arms.md §6）：
  data/officeqa/raw/officeqa_pro.csv   （官方列：uid,question,answer,source_docs,source_files,difficulty）

输出：
  data/evals/datasets/officeqa-pro-133-v1.json   题集 bundle（numeric 金标块，tolerance 0.0＝官方主榜尺）
  data/officeqa/corpus_manifest.json             按题筛库清单（source_files 去重册 → PDF 文件名 + 年代分布）

注册是独立动作（§9 坑：build 脚本只写 bundle 不注册进 evals.sqlite）：
  from evals_core.dataset import manager; manager.import_bundle("data/evals/datasets/officeqa-pro-133-v1.json")
  然后手验 eval_question 行数 == 133。

金标块约定：
  numeric = {"answer": 官方 ground truth 原文, "tolerance": 0.0, "gold_stems": [...]}
  - numeric_eval 判分器只读 answer/tolerance；gold_stems 是入库对账用观测字段
    （官方 PDF 与 parsed 文件共享的 basename，入库后据此回填 doc_ids/retrieval.gold_doc_ids）。
"""
import csv
import json
import re
import sys
from collections import Counter
from pathlib import Path

# 官方 README 说 source_files 用 ';' 分隔（V2 文档），Pro 实测是 CRLF 换行分隔——两种都收，
# 只按 ';' 切会把多册题合成一个假 stem（10-03 实踩：123 假册 vs 真实册数、PDF 下载缺 65）。
STEM_SPLIT_RE = re.compile(r"[;\r\n]+")

ROOT = Path(__file__).resolve().parents[1]
RAW_CSV = ROOT / "data" / "officeqa" / "raw" / "officeqa_pro.csv"
OUT_BUNDLE = ROOT / "data" / "evals" / "datasets" / "officeqa-pro-133-v1.json"
OUT_MANIFEST = ROOT / "data" / "officeqa" / "corpus_manifest.json"

DATASET_ID = "officeqa-pro-133-v1"
LIBRARY_ID = "lib-officeqa"
STEM_RE = re.compile(r"treasury_bulletin_(\d{4})_\d{2}")

# 公开锚点（引用带档位与日期；数字真相源 docs/plan-officeqa-arms.md §2，2026-10-03 easyocr 官方图逐柱核实）
LEADERBOARD = [
    {"label": "Claude Opus 5 / Claude Fable 5（全能力 agent，2026-08-02 批次）", "score": "60.9%",
     "note": "官方最新 harness 榜首；带联网+全库 697 册，闭卷筛库不可同表对比"},
    {"label": "GPT-5.6 Sol / GPT-5.5（2026-07-20 批次）", "score": "60.2% / 57.1%", "note": "同上口径"},
    {"label": "Claude Opus 4.6（arXiv 2603.08655，2026-03 口径）", "score": "48.1%",
     "note": "3 月技术报告全库最高档；官方已按最新题集重跑至 51.1，引哪档写哪档日期"},
]

PURPOSE_DRAFT = "历史档案大海捞针：扫描件检索、表格抽数与多步计算（判分零判官）"


def main() -> int:
    if not RAW_CSV.exists():
        print(f"[缺输入] {RAW_CSV}\n先完成 HF gated 申请（gated=auto，登录即批）并下载 officeqa_pro.csv 到该路径。")
        return 1

    with RAW_CSV.open(encoding="utf-8-sig", newline="") as f:
        rows = list(csv.DictReader(f))
    if len(rows) != 133:
        print(f"[对账失败] officeqa_pro.csv 实读 {len(rows)} 题，官方 Pro=133 题——先查下载完整性，不出半成品 bundle。")
        return 1
    missing = [r["uid"] for r in rows if not (r.get("answer") or "").strip() or not (r.get("question") or "").strip()]
    if missing:
        print(f"[对账失败] 题干/答案缺失 uid: {missing[:10]}")
        return 1

    stems: Counter = Counter()
    items = []
    for r in rows:
        raw_stems = [s.strip() for s in STEM_SPLIT_RE.split(r.get("source_files") or "") if s.strip()]
        stem_basenames = sorted({Path(s).name for s in raw_stems})  # schema 已证带 .txt 后缀
        stems.update(stem_basenames)
        decades = sorted({m.group(1)[:3] + "0s" for s in stem_basenames if (m := STEM_RE.search(s))})
        uid = str(r["uid"]).strip()
        items.append({
            "question_id": uid,
            "question": r["question"].strip(),
            "task_type": "rag",
            "intent_level": "L1",
            "library_id": LIBRARY_ID,
            "doc_ids": [],
            "difficulty": (r.get("difficulty") or "hard").strip() or "hard",
            "tags": ["officeqa", *decades, *(["multi_doc"] if len(stem_basenames) > 1 else [])],
            "question_family": "officeqa_pro",
            "canonical_question_id": uid,
            "variant_type": "canonical",
            "perturbation_tags": [],
            "retrieval": {"gold_doc_ids": [], "notes": "doc_ids 待入库后按 corpus_manifest stem→node 回填（FinanceBench 同款对账）"},
            "numeric": {"answer": r["answer"].strip(), "tolerance": 0.0, "gold_stems": stem_basenames},
        })

    bundle = {
        "dataset": {
            "dataset_id": DATASET_ID,
            "title": "【档案压力】OfficeQA Pro 133题",
            "category": "knowledge",
            "description": "美国财政部公报（1939–2025）扫描件大海捞针检索+表格数值计算；官方确定性数值容差判分，零判官。",
            "schema_version": "eval.bundle.v2",
            "version": "1.0",
            "library_id": LIBRARY_ID,
            "meta": {
                "publisher": "Databricks",
                "mode": "整体RAG",
                "domain": "历史档案检索（美国财政部公报）",
                "purpose": PURPOSE_DRAFT,
                "source_url": "https://github.com/databricks/officeqa",
                "source_note": "官方 HF gated 数据集 officeqa_pro.csv 133 题零自出；语料按 source_files 筛库（官方明示法），"
                               "口径≠官方全库 697 册，成绩与官方榜并列引用不成表；判分器 vendored @ 7b9a3c154ef9",
                "leaderboard": LEADERBOARD,
            },
        },
        "items": items,
    }
    OUT_BUNDLE.parent.mkdir(parents=True, exist_ok=True)
    OUT_BUNDLE.write_text(json.dumps(bundle, ensure_ascii=False, indent=2), encoding="utf-8")

    manifest = {
        "corpus": "U.S. Treasury Bulletins（官方 treasury_bulletin_pdfs/，PDF 名 = stem 换 .pdf）",
        "n_volumes": len(stems),
        "volumes": sorted(stems),
        "by_decade": dict(sorted(Counter(
            (STEM_RE.search(s).group(1)[:3] + "0s") for s in stems if STEM_RE.search(s)
        ).items())),
        "note": "筛库依据=Pro 133 题 source_files 并集；下载用 hf CLI：huggingface-cli download databricks/officeqa "
                "--repo-type dataset --include 'treasury_bulletin_pdfs/<stem>.pdf'（逐个或拼 glob；gated 需 HF_TOKEN）",
    }
    OUT_MANIFEST.parent.mkdir(parents=True, exist_ok=True)
    OUT_MANIFEST.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")

    multi = sum(1 for i in items if "multi_doc" in i["tags"])
    print(f"[出账] bundle 133 题 → {OUT_BUNDLE}")
    print(f"[筛库] 引用 {len(stems)} 册 → {OUT_MANIFEST}；年代分布 {manifest['by_decade']}")
    print(f"[观测] multi_doc 题 {multi}/133")
    print("[下一步] 语料入库 lib-officeqa → stem→node 对账回填 doc_ids/gold_doc_ids → "
          "manager.import_bundle 注册 → 手验 eval_question 行数==133（脚本不注册！）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
