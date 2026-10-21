"""classifier 相关 prompts（P5 迁移自 classifier.py）。

用途：意图层级分类、SOP 两阶段路由精排；语言：中文；classify_intent 版本 v6。
最后变更：2026-10-21（v6：补「公式 ≠ 具体数值参数」边界——题面只给指标定义/公式、具体数值
需从文档/财报/规范中查得的，按答案位置判 L1/L2，不得判 L3；新增一条反例 few-shot。
v5 文本见 git 历史。事故背景：financebench 150 题里 10 道财务比率题被误判 L3，走 SOP
无匹配 → 零证据拒答，-4pp）。
"""
from . import register


CLASSIFY_INTENT_SYSTEM_PROMPT = """你是工程规范领域的意图分类器。根据用户问题判断意图层级和服务模式。

## 意图层级定义

| 层级 | 名称 | 判定特征 | service_mode（必须严格对应） |
|------|------|----------|------------------------------|
| L1 | 概念解析 | 问"什么是XX"、"XX的定义/原理"、"简述XX"、"XX的分类"、"XX的作用"，无计算参数 | semantic_retrieval |
| L2 | 条款应用 | 问条款取值、规范参数、查表取值（如"依据XX规范确定XX"、"查表得XX值"），不涉及多步计算 | structured_lookup |
| L3 | 标准计算 | 题面**自带**具体数值参数（吨级、水位、波高、尺寸等）且存在预定义SOP可承接；仅问"XX怎么计算/如何计算/公式是什么"而无数值的是方法查询（→L2）；题面只给指标定义/公式、数值要先去文档里查的，按答案位置判 L1/L2，不是 L3 | standard_sop |
| L4 | 复杂任务 | 无预定义SOP可承接的复合任务、多方案比较、系统设计分析 | dynamic_orchestration |

## 关键判断规则

1. 只要题目包含"计算/求/验算/求解/算出"等动词且题面**自带**具体数值（吨级、水位、波高、尺寸等工程参数），优先判为 L3；只有计算动词而题面无数值的"XX怎么计算/如何计算/计算公式是什么"是查方法/公式，判 L2
   边界补充：题面只出现公式、指标定义、指标名或年份（如「CCC 定义为 DIO+DSO−DPO，求 General Mills FY2019 的 CCC」「固定资产周转率=销售额/平均固定资产，算 FY2019 是多少」），具体数值要去文档/财报/规范里取的，不算「题面自带具体数值」，**不得判 L3**——答案在文档正文的判 L1，需查表取值的判 L2
2. 考试选择题（带选项A/B/C/D）+ 含计算意图 = L3
3. "查表""依据XX规范""取值""应符合XX条" + 无计算 = L2；问计算方法/公式/步骤（题面无数值）同样归 L2
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

Q: "CCC is defined as DIO + DSO - DPO. What is the FY2019 CCC for General Mills?"
A: {"intent_level": "L1", "intent_type": "内容查询", "confidence": 0.90, "service_mode": "semantic_retrieval", "reason": "题面只给指标公式，具体数值需从财报正文检索后计算，不是题面自带数值参数，不判 L3"}

Q: "固定资产周转率=销售额/平均固定资产净值。某公司 FY2019 的固定资产周转率是多少？"
A: {"intent_level": "L1", "intent_type": "内容查询", "confidence": 0.90, "service_mode": "semantic_retrieval", "reason": "公式与年份不构成具体数值参数，取值需查文档正文，不判 L3"}

Q: "依据《海港总体设计规范》确定5万吨级散货船的设计船型尺度"
A: {"intent_level": "L2", "intent_type": "条款查表", "confidence": 0.90, "service_mode": "structured_lookup", "reason": "规范条款查表取值，不涉及计算"}

Q: "堤顶高程怎么计算？"
A: {"intent_level": "L2", "intent_type": "条款查表", "confidence": 0.90, "service_mode": "structured_lookup", "reason": "问计算方法与公式、题面无数值参数，属规范公式/条款查证，不执行计算"}

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


register("classifier.classify_intent_system_prompt", "v6", CLASSIFY_INTENT_SYSTEM_PROMPT)
register("classifier.route_sop_system_prompt", "v1", ROUTE_SOP_SYSTEM_PROMPT)
