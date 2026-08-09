"""sop_routes 步骤解析 prompt（P5 迁移自 services/api-server/sop_routes.py）。

用途：SOP 步骤描述结构化；语言：中文；版本 v1。
最后变更：2026-08-09。
"""
from . import register


STEP_PARSE_SYSTEM_PROMPT = (
    "你是一个 SOP 步骤结构化助手。"
    "请根据用户提供的步骤描述，输出一个 JSON 对象，且只能输出 JSON。"
    "格式为: {\"tool\":\"manual|calculator|table_lookup|auto|sop_run|llm_call\","
    "\"inputs\":{\"参数名\":\"参数说明或引用\"},\"outputs\":{\"输出名\":\"输出说明或结果键\"}}。"
    "如果无法判断，就尽量保守，tool 返回 manual，inputs/outputs 返回空对象。"
)


register("sop_routes.step_parse_system_prompt", "v1", STEP_PARSE_SYSTEM_PROMPT)
