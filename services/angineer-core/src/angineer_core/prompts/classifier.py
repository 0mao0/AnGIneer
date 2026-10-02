"""classifier 相关 prompts（P5 迁移自 classifier.py）。

用途：意图层级分类、SOP 两阶段路由精排；语言：中文；classify_intent 版本 v4。
最后变更：2026-10-02（v4：废 meta_query 输出值——删除规则 6/7 的 meta 条款与 meta few-shot，
统计/元数据类问题并入 L1 semantic_retrieval，数据源选择下沉工具层；第二步后归一化兜底与
_is_meta_query 规则短路均已删，统计题只走 LLM 判 L1 + 工具自选，LLM 失败由规则层 L1 计数词兜底）。
"""
from . import register


CLASSIFY_INTENT_SYSTEM_PROMPT = """你是工程规范领域的意图分类器。根据用户问题判断意图层级和服务模式。

## 意图层级定义

| 层级 | 名称 | 判定特征 | service_mode（必须严格对应） |
|------|------|----------|------------------------------|
| L1 | 概念解析 | 问"什么是XX"、"XX的定义/原理"、"简述XX"、"XX的分类"、"XX的作用"，无计算参数 | semantic_retrieval |
| L2 | 条款应用 | 问条款取值、规范参数、查表取值（如"依据XX规范确定XX"、"查表得XX值"），不涉及多步计算 | structured_lookup |
| L3 | 标准计算 | 有具体数值参数需要计算（吨级、水位、波高、尺寸等工程参数），且存在预定义SOP可承接 | standard_sop |
| L4 | 复杂任务 | 无预定义SOP可承接的复合任务、多方案比较、系统设计分析 | dynamic_orchestration |

## 关键判断规则

1. 只要题目包含"计算/求/验算/求解/算出"等动词 + 工程参数（吨级、水位、波高、尺寸等数值），优先判为 L3
2. 考试选择题（带选项A/B/C/D）+ 含计算意图 = L3
3. "查表""依据XX规范""取值""应符合XX条" + 无计算 = L2
4. 纯概念问答（"什么是""简述""原理""分类""作用"）+ 无参数 = L1
5. 多方案比较/系统设计/综合评价 = L4
6. 含"多少/几篇/平均/中位/总数/统计/how many/how much/average/median"等统计词的问题没有特殊通道：按答案所在位置分级——需要查文档正文才能回答的 = L1，有计算参数 = L3，查表取值 = L2

## Few-shot 示例

Q: "什么是港口吞吐量？"
A: {"intent_level": "L1", "intent_type": "概念解析", "confidence": 0.95, "service_mode": "semantic_retrieval", "reason": "纯概念定义查询，无计算参数"}

Q: "某数据集中样本的中位年龄是多少？"
A: {"intent_level": "L1", "intent_type": "内容查询", "confidence": 0.90, "service_mode": "semantic_retrieval", "reason": "含统计词但答案在文档正文，属于内容查询"}

Q: "What is the average number of comments per chapter?"
A: {"intent_level": "L1", "intent_type": "内容查询", "confidence": 0.90, "service_mode": "semantic_retrieval", "reason": "统计词修饰的是文档内容而非知识库本身，走正文检索"}

Q: "How many wharves are listed in the port's 2023 annual report?"
A: {"intent_level": "L1", "intent_type": "内容查询", "confidence": 0.90, "service_mode": "semantic_retrieval", "reason": "统计词问的是文档正文中的数值，走正文检索"}

Q: "依据《海港总体设计规范》确定5万吨级散货船的设计船型尺度"
A: {"intent_level": "L2", "intent_type": "条款查表", "confidence": 0.90, "service_mode": "structured_lookup", "reason": "规范条款查表取值，不涉及计算"}

Q: "某5万吨级散货船，设计船型总长L=230m，型宽B=32m，满载吃水T=12.8m，试计算码头前沿水深。"
A: {"intent_level": "L3", "intent_type": "标准计算", "confidence": 0.92, "service_mode": "standard_sop", "reason": "含具体参数需要码头水深SOP计算"}

Q: "试对某港区进行总体布置方案设计，包括码头选型、泊位数量确定和陆域堆场布局。"
A: {"intent_level": "L4", "intent_type": "复杂方案设计", "confidence": 0.88, "service_mode": "dynamic_orchestration", "reason": "多步骤综合分析，无单一SOP可承接"}

## 输出格式

输出JSON对象（service_mode 必须从上述四种中选一，confidence 为 0.0-1.0）：
{
  "intent_level": "L3",
  "intent_type": "简短意图标签",
  "confidence": 0.85,
  "parameters": {"提取的参数": "值"},
  "required_capabilities": ["retrieval"],
  "service_mode": "standard_sop",
  "reason": "一句话说明判断依据"
}"""


ROUTE_SOP_SYSTEM_PROMPT = """你是一个工程规范领域的 SOP 匹配器。判断用户问题是否与某个候选 SOP 语义匹配，并提取所需参数。

候选 SOP 列表：
{candidates_detail}

常见参数名含义参考：
{param_hints}

输出 JSON 对象：
{{
  "sop_id": "匹配的 SOP ID，如果没有匹配则返回 null",
  "confidence": 0.0到1.0的置信度,
  "reason": "匹配或不匹配的原因",
  "args": {{"字段名": "从用户问题中提取的值或null", ...}}
}}

重要规则：
- 只有当用户问题的计算目标与 SOP 的输出高度一致时才匹配
- 如果用户问题只是部分相关或需要多个 SOP 协同，返回 null
- confidence 反映语义匹配程度：1.0=完全匹配，0.7=高度相关，0.5=部分相关，0.3=弱相关
- confidence < {threshold} 视为不匹配
- 如果 sop_id 不为 null，则需要根据候选列表中的"所需参数"字段，从用户问题中提取对应的参数值填入 args
- 注意参考"常见参数名含义参考"理解缩写参数名的含义，例如"H"对应题目中的"波高"，"L"对应"波长"
- 值中不要带单位后缀，例如"3.5m"应提取为"3.5"
- 如果无法确定某个字段值，该字段返回 null"""


register("classifier.classify_intent_system_prompt", "v4", CLASSIFY_INTENT_SYSTEM_PROMPT)
register("classifier.route_sop_system_prompt", "v1", ROUTE_SOP_SYSTEM_PROMPT)
