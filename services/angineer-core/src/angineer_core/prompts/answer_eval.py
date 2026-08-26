"""answer_eval 语义评测 prompt（P5 迁移自 evals-core/answer_eval.py）。

用途：LLM 语义评判（评分 + 理由）；语言：中文；版本 v1。
最后变更：2026-08-09。
"""
from . import register


SEMANTIC_EVAL_PROMPT = """\
你是评测助手。判断"系统答案"是否在语义上等价于或包含了"标准答案"的核心信息。

标准答案：{gold_answer}
{keyword_hint}系统答案：{system_answer}

评分标准：
- 1.0：系统答案完整包含标准答案的核心信息，语义等价
- 0.7-0.9：系统答案包含大部分核心信息，但有少量遗漏或不精确
- 0.4-0.6：系统答案包含部分核心信息，但有明显遗漏或偏差
- 0.0-0.3：系统答案与标准答案核心信息不符或缺失严重

判定规则：
- 当标准答案是简短的是/否判断（如 "Yes"/"是的"/"No"）时：系统答案首句给出同义结论
  （是/否/Yes/No/不是）即视为命中核心信息；答案展开解释或末尾带追问句不属于扣分项，不参与语义判定。
- 系统答案比标准答案更详细、但已完整包含标准答案核心信息时，应给 1.0 或 0.9；
  不得因详略差异或表述风格不同而扣分。

返回 JSON：{{"score": 0.0~1.0, "reason": "简短说明"}}"""


SEMANTIC_EVAL_SYSTEM_PROMPT = "你是一个严格的评测助手，只返回 JSON 格式的评分结果。"


register("answer_eval.semantic_eval_prompt", "v2", SEMANTIC_EVAL_PROMPT)
register("answer_eval.semantic_eval_system_prompt", "v1", SEMANTIC_EVAL_SYSTEM_PROMPT)
