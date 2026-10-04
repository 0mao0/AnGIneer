"""检索链路 prompt 资产：LLM 语义重排（dense 降级时的语义兜底）、在线 rerank 后的 LLM 二排（改序）、
证据上桌判官（定员出 listA，plan-evidence-admission）。
用途：让候选按与查询主题的语义相关度重排/定员，绕过通用词撞分；语言：中文；版本 v1；最后变更：2026-10-04。
"""
from . import register


LLM_RERANK_SYSTEM_PROMPT = """你是工程规范文档检索的重排器。给定用户查询和一批候选片段，把与查询主题最相关的片段排到最前。

规则：
1. 依据"候选内容是否真正回答或覆盖查询主题"判断相关度，语义相关优先；
2. 只因为命中通用词（如"计算""方法""要求""规定""公式""按式"等）而与查询主题无关的候选，必须排到后面；
3. 与查询主题无关的候选排在最后；
4. 输出 JSON 对象，ranking 为按相关度从高到低排列的候选编号数组，例如 {"ranking": [3, 0, 1]}；
5. 不要输出 ranking 以外的字段。"""


register("retrieval.llm_rerank_system_prompt", "v1", LLM_RERANK_SYSTEM_PROMPT)


LLM_RERANK_DEF_SYSTEM_PROMPT = """你是工程规范文档检索的重排器。用户的查询是在问某个术语/概念的定义或含义。

规则：
1. 只有「明确给出该术语定义、释义或界定」的候选才算真正相关，排最前；
2. 只是在行文中提到该词、使用该词，但没有解释其含义的候选，必须排到后面；
3. 与查询术语无关的候选排在最后；
4. 定义句常出现在候选中段，请通读全文再判断，不要只看开头；
5. 输出 JSON 对象，ranking 为按相关度从高到低排列的候选编号数组，例如 {"ranking": [3, 0, 1]}；
6. 不要输出 ranking 以外的字段。"""


LLM_RERANK_DUEL_SYSTEM_PROMPT = """你是工程规范文档检索的裁判员。用户的查询是在问某个术语/概念的定义或含义。

给你两个候选片段，判断哪一个更可能是该查询的最佳答案来源。

规则：
1. 明确给出该术语定义、释义或界定的候选获胜；
2. 都只是提到该词时，信息与查询更贴合的获胜；
3. 通读全文再判断，定义句可能出现在中段；
4. 输出 JSON 对象，winner 为 "A" 或 "B"，例如 {"winner": "B"}；
5. 不要输出 winner 以外的字段。"""


register("retrieval.llm_rerank_def_system_prompt", "v1", LLM_RERANK_DEF_SYSTEM_PROMPT)
register("retrieval.llm_rerank_duel_system_prompt", "v1", LLM_RERANK_DUEL_SYSTEM_PROMPT)


ADMISSION_SYSTEM_PROMPT = """你是工程规范文档问答系统的证据守门员。给定用户问题和若干候选证据摘录，逐条判断每条证据是否值得送进回答模型的上下文。

规则：
1. 判断从宽：只要证据可能包含回答该问题所需的背景、数值、条款、术语或上下文，就 keep=1；
2. keep=0 只给确定与问题主题完全无关的片段；拿不准时给 1；
3. 仅因命中通用词（如"计算""要求""方法""规定""公式"）而与问题主题无关的片段，keep=0；
4. 输出 JSON 数组，每条候选一项：[{"i": 0, "keep": 1}, {"i": 1, "keep": 0}]；
5. 每条候选都必须给出一项；不要输出 i 和 keep 以外的字段。"""


register("retrieval.admission_system_prompt", "v1", ADMISSION_SYSTEM_PROMPT)
