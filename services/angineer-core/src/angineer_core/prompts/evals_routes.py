"""evals_routes 对比分析 prompt（P5 迁移自 services/api-server/evals_routes.py）。

用途：两次评测同题差异分析；语言：中文；版本 v1。
最后变更：2026-08-09。
"""
from . import register


COMPARE_ANALYSIS_SYSTEM_PROMPT = "你是评测结果分析专家，请用简洁的中文回答。"

COMPARE_ANALYSIS_USER_TEMPLATE = (
    "你是评测结果分析专家。请分析以下两次评测中同一道题目的差异。\n\n"
    "题目ID: {question_id}\n\n"
    "评测1 (运行 {run_id_a}):\n"
    "- 结果: {quality_a}\n"
    "- 评分: {scores_a}\n"
    "- 系统输出: {prediction_a}\n\n"
    "评测2 (运行 {run_id_b}):\n"
    "- 结果: {quality_b}\n"
    "- 评分: {scores_b}\n"
    "- 系统输出: {prediction_b}\n\n"
    "请分析:\n"
    "1. 两次评测的计算过程是否一致？\n"
    "2. 如果不一致，差异在哪里？\n"
    "3. 可能的原因是什么？\n\n"
    "请用简洁的中文回答，不超过200字。"
)


register("evals_routes.compare_analysis_system_prompt", "v1", COMPARE_ANALYSIS_SYSTEM_PROMPT)
register("evals_routes.compare_analysis_user_template", "v1", COMPARE_ANALYSIS_USER_TEMPLATE)
