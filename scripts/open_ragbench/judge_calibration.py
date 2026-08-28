"""Judge 校准：导出人工标注工作表，回收后计算 LLM judge 与人类的一致率。

用法：
    python scripts/open_ragbench/judge_calibration.py export --run-id run-xxx [--count 30]
    # → 生成 data/open_ragbench/reports/judge_calibration_worksheet.json，
    #   人工为每条填写 "human_verdict": "correct" | "wrong"
    python scripts/open_ragbench/judge_calibration.py check
    # → 计算 Cohen's κ、混淆矩阵，并给出 semantic_threshold 调整建议
"""
import argparse
import json
import os
import random
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from open_ragbench import common

EVALS_DB = common.REPO_ROOT / "data" / "evals" / "evals.sqlite"
WORKSHEET = common.REPORTS_DIR / "judge_calibration_worksheet.json"
RESULT = common.REPORTS_DIR / "judge_calibration_result.json"


def _load_run_details(run_id: str):
    db = sqlite3.connect(str(EVALS_DB))
    db.row_factory = sqlite3.Row
    try:
        rows = db.execute(
            "SELECT question_id, quality, all_scores, all_predictions FROM eval_run_detail "
            "WHERE run_id = ? AND status = 'completed'",
            (run_id,),
        ).fetchall()
        questions = {
            row["question_id"]: dict(row)
            for row in db.execute(
                "SELECT question_id, question, answer_gold FROM eval_question "
                "WHERE dataset_id = (SELECT dataset_id FROM eval_run WHERE run_id = ?)",
                (run_id,),
            ).fetchall()
        }
    finally:
        db.close()
    details = []
    for row in rows:
        q = questions.get(row["question_id"], {})
        scores = json.loads(row["all_scores"] or "{}")
        predictions = json.loads(row["all_predictions"] or "{}")
        answer_scores = scores.get("answer") or {}
        answer_pred = predictions.get("answer") or {}
        details.append({
            "question_id": row["question_id"],
            "question": q.get("question", ""),
            "gold_answer": (json.loads(q.get("answer_gold") or "{}") if isinstance(q.get("answer_gold"), str) else (q.get("answer_gold") or {})).get("gold_answer", ""),
            "model_answer": answer_pred.get("answer", ""),
            "quality": row["quality"],
            "judge_score": answer_scores.get("semantic_score"),
            "judge_passed": answer_scores.get("semantic_passed"),
            "judge_reason": answer_scores.get("semantic_reason", ""),
            "human_verdict": "",
        })
    return details


def export_worksheet(run_id: str, count: int, seed: int) -> int:
    details = _load_run_details(run_id)
    details = [d for d in details if d["judge_score"] is not None]
    if not details:
        print("该 run 没有带语义判分的题目")
        return 2
    # 分层：一半 judge 判对、一半 judge 判错（不足则全取），重点校准边界
    passed = [d for d in details if d["judge_passed"]]
    failed = [d for d in details if not d["judge_passed"]]
    rnd = random.Random(seed)
    rnd.shuffle(passed)
    rnd.shuffle(failed)
    half = count // 2
    sample = failed[:half] + passed[:count - half]
    remainder = failed[half:] + passed[count - half:]
    rnd.shuffle(remainder)
    sample.extend(remainder[: count - len(sample)])
    rnd.shuffle(sample)
    common.save_json(WORKSHEET, {
        "run_id": run_id,
        "instruction": "为每条填写 human_verdict: correct（回答可用）或 wrong（回答错误/不可信）",
        "items": sample,
    })
    print(f"工作表已生成: {WORKSHEET}（{len(sample)} 条，其中 judge 判错 {min(half, len(failed))} 条）")
    return 0


def _cohens_kappa(pairs):
    """pairs: [(judge_bool, human_bool), ...]"""
    n = len(pairs)
    if n == 0:
        return None
    agree = sum(1 for j, h in pairs if j == h) / n
    j_true = sum(1 for j, _ in pairs if j) / n
    h_true = sum(1 for _, h in pairs if h) / n
    expected = j_true * h_true + (1 - j_true) * (1 - h_true)
    if expected >= 1.0:
        return 1.0
    return round((agree - expected) / (1 - expected), 4)


def check_worksheet() -> int:
    if not WORKSHEET.exists():
        print("工作表不存在，请先运行 export")
        return 2
    sheet = common.load_json(WORKSHEET)
    items = sheet.get("items", [])
    labeled = [i for i in items if i.get("human_verdict") in ("correct", "wrong")]
    if not labeled:
        print("尚无人工标注（human_verdict 为空）")
        return 2
    pairs = [(bool(i["judge_passed"]), i["human_verdict"] == "correct") for i in labeled]
    tp = sum(1 for j, h in pairs if j and h)
    fp = sum(1 for j, h in pairs if j and not h)
    fn = sum(1 for j, h in pairs if not j and h)
    tn = sum(1 for j, h in pairs if not j and not h)
    kappa = _cohens_kappa(pairs)
    accuracy = round((tp + tn) / len(pairs), 4)
    result = {
        "labeled": len(labeled),
        "total": len(items),
        "agreement_accuracy": accuracy,
        "cohens_kappa": kappa,
        "confusion": {"judge_pass_human_pass": tp, "judge_pass_human_wrong": fp,
                       "judge_wrong_human_pass": fn, "judge_wrong_human_wrong": tn},
        "recommendation": (
            "judge 与人类一致性良好" if kappa is not None and kappa >= 0.6
            else "judge 一致性不足：建议人工复核 boundary 样本后调整 semantic_threshold 或 SEMANTIC_EVAL_PROMPT"
        ),
    }
    common.save_json(RESULT, result)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="LLM judge 校准")
    sub = parser.add_subparsers(dest="cmd", required=True)
    p_export = sub.add_parser("export", help="导出人工标注工作表")
    p_export.add_argument("--run-id", required=True)
    p_export.add_argument("--count", type=int, default=30)
    p_export.add_argument("--seed", type=int, default=42)
    sub.add_parser("check", help="回收工作表并计算一致率")
    args = parser.parse_args()
    if args.cmd == "export":
        return export_worksheet(args.run_id, args.count, args.seed)
    return check_worksheet()


if __name__ == "__main__":
    sys.exit(main())
