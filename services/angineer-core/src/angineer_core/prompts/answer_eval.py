"""answer_eval 语义评测 prompt（P5 迁移自 evals-core/answer_eval.py）。

用途：LLM 语义评判（评分 + 理由）；语言：中文；版本 v4（v4 增补跨语言/同义改写豁免）。
最后变更：2026-09-30。
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
- 系统答案与标准答案语言不同（如中文作答、英文标准答案）不影响判定：翻译后语义等价
  即视为包含核心信息，不得因语种不同而扣分。
- 同义改写、换用近义术语、调整表述顺序不属于遗漏：只要标准答案的每个核心要点在系统
  答案中有等价表达即视为覆盖，不得要求逐字复述金标措辞。
- 系统答案比标准答案更详细、但已完整包含标准答案核心信息时，应给 1.0 或 0.9；
  不得因详略差异或表述风格不同而扣分。
- 核心结论正确、仅遗漏个别次要数值或细节时，不得判为错误：应给 0.7~0.9 并通过（≥0.65），
  不得因遗漏次要数值/细节而整体判错。

返回 JSON：{{"score": 0.0~1.0, "reason": "简短说明"}}"""


SEMANTIC_EVAL_SYSTEM_PROMPT = "你是一个严格的评测助手，只返回 JSON 格式的评分结果。"


# 该拒题未拒时的二段判定（2026-10-09，report-refusal-3sets-audit-20261009 §4.4）：
# 区分「有据未拒」（证据里确实有答案，拒答前提不成立）与「编造」（真幻觉）。
EVIDENCE_SUPPORT_PROMPT = """\
你是评测助手。判断"系统答案"的核心事实性主张是否被"检索证据"支持。

检索证据：
{evidence}

系统答案：{system_answer}

判定规则：
- 系统答案的核心结论能在检索证据中找到明确依据（同义改写、跨语言、繁简差异均算），
  判 supported=true。
- 核心结论在证据中无依据、与证据矛盾、或答案超出证据覆盖的部分含关键事实性主张，
  判 supported=false。
- 不得因证据与答案详略/措辞不同而判 false；也不得因答案"听起来合理"而判 true。

返回 JSON：{{"supported": true/false, "reason": "简短说明"}}"""


EVIDENCE_SUPPORT_SYSTEM_PROMPT = "你是一个严格的评测助手，只返回 JSON 格式的判定结果。"


register("answer_eval.semantic_eval_prompt", "v4", SEMANTIC_EVAL_PROMPT)
register("answer_eval.semantic_eval_system_prompt", "v1", SEMANTIC_EVAL_SYSTEM_PROMPT)
register("answer_eval.evidence_support_prompt", "v1", EVIDENCE_SUPPORT_PROMPT)
register("answer_eval.evidence_support_system_prompt", "v1", EVIDENCE_SUPPORT_SYSTEM_PROMPT)
