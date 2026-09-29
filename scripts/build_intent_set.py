# -*- coding: utf-8 -*-
"""构建 intent-router-v1 题集：100 题专用意图识别测试集（L0-L4 分层 + 陷阱族 + 金标可审计）。

为什么是脚本而不是手写 JSON：题集要可复现、可校验。本脚本
  ① 持有全部题面与金标（唯一真相源）；
  ② 跑机械校验（结构不变量 + 与主仓库规则层的一致性），不通过就拒绝出题集；
  ③ 产出 data/evals/datasets/intent-router-v1.json（eval.bundle.v2，item 带 intent 金标块）。

金标依据：services/angineer-core/src/angineer_core/prompts/classifier.py（v3 层级表与规则 1-7）
+ agent_policy.build_attempts 的实际路由优先级。每条都带 rationale（为什么是这个层级）与
trap（这条在考什么），使复核者不必回读 prompt 就能审计。

用法：
  python scripts/build_intent_set.py            # 生成 + 校验，写 bundle
  python scripts/build_intent_set.py --check    # 只校验不写盘

2026-09-29 相对首版（开发机 cases100.json）的质量改进：
  ① 消除灰区题：3 条「两者区别/异同」改写为只问结构/定义差异（原措辞同时命中 L1 关键词
     「区别」与规则 5「多方案比较=L4」，读法不同会反转头名，见 docs §10.6）；
  ② 新增 3 个陷阱族：L1_stdcode_trap（标准号≠L2）、L1_numbered（有数值≠L3）、
     L3_mixed_signal（依据规范+计算 → L3）；
  ③ 每题补 trap / rationale；
  ④ 机械校验：与上游规则层（_check_l0_intent / _is_meta_query / 条款号快路径）对账，
     并记录 rule_hit —— 生产链上该题会被规则前置拦下，还是真的会进分类模型。
"""
import argparse
import json
import sys
from collections import Counter
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
OUT = REPO / "data" / "evals" / "datasets" / "intent-router-v1.json"

LEVELS = ("L0", "L1", "L2", "L3", "L4")
MODES = ("casual_chat", "semantic_retrieval", "meta_query", "structured_lookup",
         "standard_sop", "dynamic_orchestration")

# (id, question, level, mode, family, trap, rationale, source)
ITEMS = [
    # ---------------- L0 闲聊（12）→ route L0 ----------------
    ("ir-l0-pure-01", "你好", "L0", "casual_chat", "L0_pure", "纯问候", "闲聊/问候/与工程无关的寒暄，无实质工程内容 → L0"),
    ("ir-l0-pure-02", "谢谢啦，辛苦了", "L0", "casual_chat", "L0_pure", "道谢无诉求", "同上：纯寒暄，无实质内容 → L0"),
    ("ir-l0-pure-03", "今天天气真不错", "L0", "casual_chat", "L0_pure", "非工程话题", "与工程无关的日常寒暄 → L0"),
    ("ir-l0-pure-04", "给我讲个笑话吧", "L0", "casual_chat", "L0_pure", "闲聊请求",
     "闲聊请求，不涉及知识库内容 → L0（注意：该题不含 L0 规则关键词，生产链上会落到分类模型，是 L0 覆盖的活口）"),
    ("ir-l0-pure-05", "在吗", "L0", "casual_chat", "L0_pure", "试探性招呼", "纯招呼，无实质内容 → L0"),
    ("ir-l0-pure-06", "晚安，明天见", "L0", "casual_chat", "L0_pure", "告别语", "告别寒暄 → L0"),
    ("ir-l0-amb-01", "你是谁呀", "L0", "casual_chat", "L0_ambiguous", "身份询问",
     "询问助手身份，非知识库内容 → L0（生产由 L0_AMBIGUOUS_KEYWORDS 规则前置拦截）"),
    ("ir-l0-amb-02", "你叫什么名字", "L0", "casual_chat", "L0_ambiguous", "身份询问", "同上 → L0"),
    ("ir-l0-amb-03", "你能做什么", "L0", "casual_chat", "L0_ambiguous", "能力询问", "询问助手能力，非内容查询 → L0"),
    ("ir-l0-amb-04", "帮我", "L0", "casual_chat", "L0_ambiguous", "残缺请求",
     "只有求助词、无实质内容 → L0（一旦补上实质内容即转 L1，见 ir-l1-polite-*）"),
    ("ir-l0-amb-05", "这个怎么用", "L0", "casual_chat", "L0_ambiguous", "产品使用询问",
     "询问产品用法而非知识库内容 → L0"),
    ("ir-l0-amb-06", "在吗？帮我个忙呗", "L0", "casual_chat", "L0_ambiguous", "招呼+空请求", "招呼加空请求，仍无实质内容 → L0"),

    # ---------------- L1 正文语义（28）→ route L1 ----------------
    ("ir-l1-def-01", "疏浚土的分类有哪些？", "L1", "semantic_retrieval", "L1_def", "概念枚举", "纯概念/分类查询，无计算参数、无取值要求 → L1（规则 4）"),
    ("ir-l1-def-02", "什么是设计低水位？", "L1", "semantic_retrieval", "L1_def", "定义", "问定义 → L1（规则 4）"),
    ("ir-l1-def-03", "港口吞吐量的定义是什么？", "L1", "semantic_retrieval", "L1_def", "定义", "问定义 → L1（规则 4）"),
    ("ir-l1-def-04", "简述航道等级的划分", "L1", "semantic_retrieval", "L1_def", "简述", "简述型概念题 → L1（规则 4）"),
    ("ir-l1-def-05", "抛石基床的作用是什么？", "L1", "semantic_retrieval", "L1_def", "作用", "问作用 → L1（规则 4）"),
    ("ir-l1-def-06", "什么是乘潮水位？", "L1", "semantic_retrieval", "L1_def", "定义", "问定义 → L1（规则 4）"),
    ("ir-l1-def-07", "波浪要素包括哪些？", "L1", "semantic_retrieval", "L1_def", "组成", "问构成要素 → L1（规则 4）"),
    ("ir-l1-def-08", "高桩码头由哪些部分组成？", "L1", "semantic_retrieval", "L1_def", "组成", "问构成 → L1（规则 4）"),

    ("ir-l1-stat-01", "某规范中各类海港的平均等级是怎么划分的？", "L1", "semantic_retrieval", "L1_trap_stat",
     "统计词陷阱", "含「平均」但答案在文档正文 → L1 semantic_retrieval（规则 7），不是 meta_query"),
    ("ir-l1-stat-02", "某论文中实验样本的中位波高是多少？", "L1", "semantic_retrieval", "L1_trap_stat",
     "统计词陷阱", "含「中位」但答案在某篇论文正文 → L1（规则 7）"),
    ("ir-l1-stat-03", "数据集里平均每章有多少条评论？", "L1", "semantic_retrieval", "L1_trap_stat",
     "统计词陷阱", "含「平均多少」但答案在文档正文 → L1（规则 7）"),
    ("ir-l1-stat-04", "某星表中星系的中位红移是多少？", "L1", "semantic_retrieval", "L1_trap_stat",
     "统计词陷阱", "prompt few-shot 正例的同类 → L1（规则 7）"),
    ("ir-l1-stat-05", "某表中最大的设计船型吨位是多少？", "L1", "semantic_retrieval", "L1_trap_stat",
     "统计词陷阱", "含「最大」但答案是某张表里的内容 → L1（规则 7）"),
    ("ir-l1-stat-06", "What is the average number of comments per chapter?", "L1", "semantic_retrieval",
     "L1_trap_stat", "统计词陷阱+英文", "英文统计词但修饰文档内容 → L1（prompt few-shot 原句同型）"),

    ("ir-l1-polite-01", "你好，请问疏浚土的分类有哪些？", "L1", "semantic_retrieval", "L1_politeness",
     "礼貌前缀", "有问候语但带实质概念问题 → L1；问候语不得吞掉实质意图（区别于 L0）"),
    ("ir-l1-polite-02", "谢谢，那乘潮水位的定义能再说一遍吗？", "L1", "semantic_retrieval", "L1_politeness",
     "礼貌前缀+追问", "道谢+实质追问 → L1"),
    ("ir-l1-polite-03", "在吗？我想了解抛石基床的作用", "L1", "semantic_retrieval", "L1_politeness",
     "礼貌前缀", "招呼+实质请求 → L1"),

    ("ir-l1-cmp-01", "重力式码头与高桩码头在结构构造上有什么不同？", "L1", "semantic_retrieval",
     "L1_concept_compare", "概念对比 vs 方案比选",
     "只问结构构造差异，不要求选型建议/方案论证 → L1（规则 4）；对照 L4 的「适用条件比较+选型建议」"),
    ("ir-l1-cmp-02", "乘潮水位与设计高水位在定义上有什么异同？", "L1", "semantic_retrieval",
     "L1_concept_compare", "概念对比 vs 方案比选", "只问定义异同 → L1（规则 4）"),
    ("ir-l1-cmp-03", "绞吸式与耙吸式挖泥船在作业方式上的区别有哪些？", "L1", "semantic_retrieval",
     "L1_concept_compare", "概念对比 vs 方案比选", "只问作业方式区别，无选型诉求 → L1（规则 4）"),

    ("ir-l1-en-01", "How do pinching antennas improve uplink communication systems?", "L1",
     "semantic_retrieval", "L1_english", "英文概念题", "英文学术语料概念问答 → L1（open-ragbench 语料同型）"),
    ("ir-l1-en-02", "What are the limitations of conventional MOSFETs in modern electronics?", "L1",
     "semantic_retrieval", "L1_english", "英文概念题", "英文概念问答 → L1"),

    ("ir-l1-real-01", "In what type of settings should foundation models be evaluated to demonstrate their usefulness?",
     "L1", "semantic_retrieval", "L1_real", "真实生产题", "eval_question 抽样（open-ragbench），代表在分布流量 → L1"),
    ("ir-l1-real-02", "How does noise intensity affect the firing frequency of neurons in a network?",
     "L1", "semantic_retrieval", "L1_real", "真实生产题", "eval_question 抽样 → L1"),
    ("ir-l1-real-03", "Does conformal prediction guarantee unconditional coverage?",
     "L1", "semantic_retrieval", "L1_real", "真实生产题", "eval_question 抽样 → L1"),

    ("ir-l1-std-01", "JTS 181 是什么规范？", "L1", "semantic_retrieval", "L1_stdcode_trap",
     "标准号≠L2", "问规范的「是什么」= 概念解析 → L1；标准号本身不构成 L2（L2 是依据规范取值/查表）"),
    ("ir-l1-std-02", "GB 50010-2010 的适用范围是什么？", "L1", "semantic_retrieval", "L1_stdcode_trap",
     "标准号≠L2", "问规范适用范围 = 概念解析 → L1"),

    ("ir-l1-num-01", "什么是5万吨级散货船？设计船型是怎么定义的？", "L1", "semantic_retrieval",
     "L1_numbered", "有数值≠L3", "含吨级数值但问的是定义 → L1；数值只描述对象、不构成计算（规则 1 需「计算动作」）"),

    # ---------------- L1 meta_query（10）→ route meta ----------------
    ("ir-meta-dir-01", "知识库里有多少篇文档？", "L1", "meta_query", "meta_direct", "库自身统计", "问知识库规模 → meta_query（规则 6）"),
    ("ir-meta-dir-02", "系统里有哪些知识库？", "L1", "meta_query", "meta_direct", "库清单", "问有哪些库 → meta_query（规则 6）"),
    ("ir-meta-dir-03", "各库的文档格式分布如何？", "L1", "meta_query", "meta_direct", "格式分布", "问库内格式分布 → meta_query（规则 6）"),
    ("ir-meta-dir-04", "上传的文档总量是多少？", "L1", "meta_query", "meta_direct", "总量", "问上传总量 → meta_query（规则 6）"),
    ("ir-meta-dir-05", "知识库的文档总页数是多少？", "L1", "meta_query", "meta_direct", "页数统计", "问库页数统计 → meta_query（规则 6）"),
    ("ir-meta-dir-06", "最近一个月文档上传趋势如何？", "L1", "meta_query", "meta_direct", "上传趋势", "问上传趋势 → meta_query（规则 6）"),
    ("ir-meta-ref-01", "目前一共支持哪些文件格式？", "L1", "meta_query", "meta_rephrase", "换措辞的元数据",
     "同一「问库自身」语义，避开 few-shot 原句 → meta_query（规则 6）"),
    ("ir-meta-ref-02", "这个平台现在存了多少资料？", "L1", "meta_query", "meta_rephrase", "换措辞的元数据", "问库内总量 → meta_query"),
    ("ir-meta-ref-03", "知识库最近一次更新是什么时候？", "L1", "meta_query", "meta_rephrase", "换措辞的元数据", "问库更新时间（库自身元数据）→ meta_query"),
    ("ir-meta-ref-04", "我上传的文档现在都入库了吗，总共几篇？", "L1", "meta_query", "meta_rephrase", "换措辞的元数据",
     "问入库状态与篇数（库自身）→ meta_query"),

    # ---------------- L2 条款/查表（22）→ route L2 ----------------
    ("ir-l2-look-01", "依据《海港总体设计规范》确定5万吨级散货船的设计船型尺度", "L2", "structured_lookup",
     "L2_lookup", "依据规范查表", "依据规范确定参数，无多步计算 → L2（规则 3）"),
    ("ir-l2-look-02", "查表得C40混凝土的容重取值", "L2", "structured_lookup", "L2_lookup", "查表取值", "查表取值 → L2（规则 3）"),
    ("ir-l2-look-03", "《疏浚与吹填工程设计规范》中计算超深的取值是多少？", "L2", "structured_lookup",
     "L2_lookup", "术语含「计算」", "「计算超深」是技术术语，问的是取值、无数值参数需推算 → L2（规则 3）"),
    ("ir-l2-look-04", "查表确定设计高水位的重现期标准", "L2", "structured_lookup", "L2_lookup", "查表取标准", "查表取标准值 → L2"),
    ("ir-l2-look-05", "依据规范确定码头前沿设计水深的取值", "L2", "structured_lookup", "L2_lookup", "依据规范取值", "依据规范取值 → L2"),
    ("ir-l2-look-06", "土工织物的等效孔径要求取多少？", "L2", "structured_lookup", "L2_lookup", "要求取值", "问规范要求取值 → L2"),
    ("ir-l2-look-07", "护面块体的稳定重量应查哪张表？", "L2", "structured_lookup", "L2_lookup", "查表定位", "问查哪张表取重量 → L2"),
    ("ir-l2-look-08", "码头前沿堆货荷载的标准值是多少？", "L2", "structured_lookup", "L2_lookup", "标准值", "问标准值 → L2"),
    ("ir-l2-look-09", "船舶撞击力的允许值是怎么规定的？", "L2", "structured_lookup", "L2_lookup", "允许值规定", "问允许值规定 → L2"),
    ("ir-l2-look-10", "沉箱干舷高度应满足什么规定？", "L2", "structured_lookup", "L2_lookup", "应满足规定", "问应满足的规定值，无计算 → L2"),

    ("ir-l2-clause-01", "营运中码头的船舶荷载应符合哪条规范规定？", "L2", "structured_lookup", "L2_clause_number",
     "问出处非内容", "问条款出处（符合哪条）→ L2；生产由条款号快路径规则直达 L2（§5.3 靶子，35B 曾漏成 L1）"),
    ("ir-l2-clause-02", "重力式码头抗滑稳定性验算应符合哪条规范要求？", "L2", "structured_lookup", "L2_clause_number",
     "问出处非内容+含计算词", "问条款出处；「验算」在此是题中术语、无参数 → L2"),
    ("ir-l2-clause-03", "集装箱码头装卸桥轨距应符合哪条规定？", "L2", "structured_lookup", "L2_clause_number",
     "问出处非内容", "问条款出处 → L2"),
    ("ir-l2-clause-04", "高桩码头基桩的入土深度应满足哪条规定？", "L2", "structured_lookup", "L2_clause_number",
     "问出处非内容", "问条款出处 → L2"),
    ("ir-l2-clause-05", "防波堤护面块体的设计在哪条规范里？", "L2", "structured_lookup", "L2_clause_number",
     "问出处非内容", "问规范出处 → L2"),
    ("ir-l2-clause-06", "码头面高程的确定应符合哪条标准？", "L2", "structured_lookup", "L2_clause_number",
     "问出处非内容", "问标准出处 → L2"),

    ("ir-l2-std-01", "依据JTS 181规范确定航道宽度的取值", "L2", "structured_lookup", "L2_stdcode",
     "点名规范号+取值", "点名规范号 + 取值 → L2（对照 ir-l1-std-* ：只问规范是什么仍是 L1）"),
    ("ir-l2-std-02", "JTS 165-2013 中关于码头前沿停泊水域宽度的规定是什么？", "L2", "structured_lookup",
     "L2_stdcode", "点名规范号+规定", "点名规范号 + 查规定 → L2"),
    ("ir-l2-std-03", "GB 50010-2010 对混凝土保护层厚度的要求是多少？", "L2", "structured_lookup",
     "L2_stdcode", "点名规范号+要求值", "点名规范号 + 要求值 → L2"),

    ("ir-l2-nc-01", "5万吨级散货船的船型尺度在规范中取值是多少？", "L2", "structured_lookup", "L2_trap_noncalc",
     "有数值≠L3", "含吨级数值但只是查表取值 → L2（规则 3），不是 L3"),
    ("ir-l2-nc-02", "波浪重现期50年对应的设计波高标准值是多少？", "L2", "structured_lookup", "L2_trap_noncalc",
     "有数值≠L3", "含数值但只是查表取标准值 → L2"),
    ("ir-l2-nc-03", "C40混凝土的轴心抗压强度设计值查表是多少？", "L2", "structured_lookup", "L2_trap_noncalc",
     "有数值≠L3", "含强度等级但只是查表取值 → L2"),

    # ---------------- L3 标准计算（16）→ route complex ----------------
    ("ir-l3-calc-01", "某5万吨级散货船，设计船型总长L=230m，型宽B=32m，满载吃水T=12.8m，试计算码头前沿水深。",
     "L3", "standard_sop", "L3_calc", "多参数计算", "含具体参数 + 计算动作 → L3（规则 1）"),
    ("ir-l3-calc-02", "已知波高H=3.5m、周期T=8s，计算斜坡堤上的波浪爬高。", "L3", "standard_sop", "L3_calc",
     "参数计算", "参数 + 计算 → L3（规则 1）"),
    ("ir-l3-calc-03", "计算疏浚工程量：断面面积120平方米，挖槽长度2公里。", "L3", "standard_sop", "L3_calc",
     "工程量计算", "参数 + 计算 → L3"),
    ("ir-l3-calc-04", "验算重力式码头抗滑稳定性：已知水平推力850kN、摩擦系数0.6、垂直力2100kN。",
     "L3", "standard_sop", "L3_calc", "验算", "参数 + 验算 → L3（规则 1）"),
    ("ir-l3-calc-05", "计算某泊位的年通过能力：单船载货量5万吨、年作业300天。", "L3", "standard_sop", "L3_calc",
     "能力计算", "参数 + 计算 → L3"),
    ("ir-l3-calc-06", "求抛石基床的厚度：已知地基应力与基床顶面应力分别为180kPa和150kPa。", "L3", "standard_sop",
     "L3_calc", "求解", "参数 + 求值 → L3"),
    ("ir-l3-calc-07", "计算沉箱的吃水：长宽高分别为20m、15m、12m，混凝土重度24kN/m3。", "L3", "standard_sop",
     "L3_calc", "吃水计算", "参数 + 计算 → L3"),
    ("ir-l3-calc-08", "计算航道挖深：设计水深8.5m，富余水深0.4m，备淤深度0.6m。", "L3", "standard_sop", "L3_calc",
     "多参数求和", "三个数值参数 + 计算 → L3"),
    ("ir-l3-calc-09", "水流力计算：已知流速2.5m/s、挡水面积15平方米，计算作用于墩柱的水流力。", "L3", "standard_sop",
     "L3_calc", "公式计算", "参数 + 公式计算 → L3"),

    ("ir-l3-mcq-01", "设计船型尺度计算题，泊位长度L=船长+富裕长度，船长210m，富裕长度取15%，问泊位长度是多少？ A)225m B)242m C)231m D)220m",
     "L3", "standard_sop", "L3_mcq", "选择题+计算", "带 A/B/C/D 选项 + 含计算 → L3（规则 2）"),
    ("ir-l3-mcq-02", "某防波堤堤顶高程计算：设计高水位3.2m，波浪爬高2.1m，超高0.5m，则堤顶高程为？ A)5.3m B)5.8m C)4.9m D)6.1m",
     "L3", "standard_sop", "L3_mcq", "选择题+计算", "带选项 + 计算 → L3（规则 2）"),
    ("ir-l3-mcq-03", "航道通过能力计算：单船载重8000t，年通航300天，装卸效率500t/h，问年通过能力？ A)960万吨 B)1152万吨 C)800万吨 D)1440万吨",
     "L3", "standard_sop", "L3_mcq", "选择题+计算", "带选项 + 计算 → L3（规则 2）"),

    ("ir-l3-unit-01", "已知流速v=1.8m/s，水流力系数取0.73，挡水面积12m²，水的密度取1.025t/m³，求水流力。",
     "L3", "standard_sop", "L3_units", "符号参数+量纲", "符号化参数 + 求值 → L3"),
    ("ir-l3-unit-02", "混凝土挡墙底面宽3.5米、高6米、重度24千牛每立方米，求每延米墙底最大压应力。",
     "L3", "standard_sop", "L3_units", "中文单位计算", "中文单位参数 + 求值 → L3"),
    ("ir-l3-unit-03", "疏浚土方量计算：挖槽上口宽45米、下口宽30米、平均深度6米、长度1500米，求疏浚方量（万方）。",
     "L3", "standard_sop", "L3_units", "中文单位+指定单位换算", "多参数 + 计算 + 单位换算 → L3"),

    ("ir-l3-mixed-01", "依据JTS 181的规定，验算某沉箱的抗倾覆稳定性：已知倾覆力矩1200kN·m、抗倾覆力矩1800kN·m。",
     "L3", "standard_sop", "L3_mixed_signal", "依据规范+计算（混合信号）",
     "同时含「依据规范」（L2 信号）与具体参数+验算 → L3（规则 1：计算+参数优先）"),

    # ---------------- L4 复杂任务（12）→ route complex ----------------
    ("ir-l4-design-01", "试对某港区进行总体布置方案设计，包括码头选型、泊位数量确定和陆域堆场布局。",
     "L4", "dynamic_orchestration", "L4_design", "方案设计", "复合方案设计，无预定义 SOP 可承接 → L4（规则 5）"),
    ("ir-l4-design-02", "对某港口改扩建工程进行综合影响评估。", "L4", "dynamic_orchestration", "L4_design",
     "综合评价", "综合评价 → L4（规则 5）"),
    ("ir-l4-design-03", "为某航道整治工程制定完整的施工组织方案。", "L4", "dynamic_orchestration", "L4_design",
     "施工组织", "编制完整施工组织方案 → L4"),
    ("ir-l4-design-04", "设计某散货码头的装卸工艺流程系统。", "L4", "dynamic_orchestration", "L4_design",
     "系统设计", "系统设计 → L4（规则 5）"),
    ("ir-l4-design-05", "评估某防波堤方案对海洋生态的影响并提出改进措施。", "L4", "dynamic_orchestration",
     "L4_design", "评估+改进", "评估并提出措施（复合）→ L4"),
    ("ir-l4-design-06", "针对某港区淤泥质海岸，编制地基处理总体方案并论证技术经济合理性。",
     "L4", "dynamic_orchestration", "L4_design", "方案+论证", "方案编制 + 技术经济论证 → L4"),

    ("ir-l4-cmp-01", "比较重力式、高桩式和板桩式码头的适用条件，并给出选型建议。",
     "L4", "dynamic_orchestration", "L4_compare", "多方案比选+选型建议",
     "要求适用条件比较 + 选型建议 → L4（规则 5）；对照 L1_concept_compare 只问概念差异"),
    ("ir-l4-cmp-02", "离岸式码头与岸式码头两方案比选，给出论证。", "L4", "dynamic_orchestration", "L4_compare",
     "两方案比选", "明确两方案比选 + 论证 → L4"),
    ("ir-l4-cmp-03", "某集装箱码头装卸工艺在岸边集装箱起重机方案与自动化轨道吊方案之间比选。",
     "L4", "dynamic_orchestration", "L4_compare", "工艺方案比选", "两工艺方案比选 → L4"),
    ("ir-l4-cmp-04", "疏浚弃土处置方案比选：海洋倾倒、陆域吹填与资源化利用三方案技术经济比较。",
     "L4", "dynamic_orchestration", "L4_compare", "三方案技术经济比较", "三方案技术经济比较 → L4（规则 5 明列）"),

    ("ir-l4-multi-01", "先分析某港区现状吞吐能力，再预测2030年需求，最后提出扩建分期实施建议。",
     "L4", "dynamic_orchestration", "L4_multi", "多步编排", "先…再…最后的多步复合 → L4"),
    ("ir-l4-multi-02", "首先梳理某防波堤损坏原因，然后核算修复工程量，最后编制修复施工方案与工期安排。",
     "L4", "dynamic_orchestration", "L4_multi", "多步编排", "多步复合（含一步计算但整体是编排）→ L4"),
]


def derive_route(level: str, mode: str) -> str:
    """镜像 agent_policy.build_attempts 的路由优先级（与 evals_core.runner.intent_eval 同源）。"""
    if mode == "meta_query":
        return "meta"
    if level == "L0" or mode == "casual_chat":
        return "L0"
    if level in ("L3", "L4") or mode in ("standard_sop", "dynamic_orchestration"):
        return "complex"
    if level == "L2" or mode == "structured_lookup":
        return "L2"
    return "L1"


def rule_hit_for(question: str) -> str:
    """生产链上该题会被哪条规则前置拦下（不进分类模型）。仅作元数据，不做金标断言。"""
    try:
        sys.path.insert(0, str(REPO / "services" / "angineer-core" / "src"))
        sys.path.insert(0, str(REPO / "services" / "ai-inference" / "src"))
        from angineer_core.classifier import _check_l0_intent, _is_clause_number_query, _is_meta_query
        from angineer_core.classifier import _clause_fastpath_enabled
    except Exception:  # noqa: BLE001
        return "unknown"
    if _check_l0_intent(question):
        return "rule_L0"
    if _is_meta_query(question):
        return "rule_meta"
    if _clause_fastpath_enabled() and _is_clause_number_query(question):
        return "rule_clause"
    return "model"


def build() -> dict:
    items = []
    for row in ITEMS:
        qid, question, level, mode, family, trap, rationale = row[:7]
        source = row[7] if len(row) > 7 else "crafted"
        items.append({
            "question_id": qid,
            "question": question,
            "task_type": "definition",
            "intent_level": level,          # 金标层级（summary 的 by_level 分组也用这个）
            "library_id": "default",
            "difficulty": "easy",
            "tags": ["intent-router-v1", f"family:{family}"],
            "question_family": family,
            "intent": {
                "level": level,
                "mode": mode,
                "route": derive_route(level, mode),
                "family": family,
                "trap": trap,
                "rationale": rationale,
                "strict_level": False,      # route 恒致命；level/mode 默认仅记录（见 intent_eval 模块头）
                "strict_mode": False,
                "xfail": False,
                "source": source,
                # 生产链上该题会被哪条规则前置拦下（还是真的进分类模型）。
                # 由 build() 盖章而非 validate() 的副作用：CLI 的 --model-only 与入库都依赖它。
                "rule_hit": rule_hit_for(question),
            },
        })
    return {
        "dataset": {
            "dataset_id": "intent-router-v1",
            "title": "意图路由测试集 v1（100 题 L0-L4 分层）",
            "category": "knowledge",
            "description": "专用意图识别测试集：100 题覆盖 L0-L4，每题带陷阱族/金标依据/路由桶；"
                           "只跑分类器路由断言，不跑检索、生成与判官。",
            "schema_version": "eval.bundle.v2",
            "version": "1.0",
            "library_id": "default",
        },
        "items": items,
    }


def validate(bundle: dict) -> list:
    """机械校验：结构不变量 + 与规则层的一致性。返回问题清单（空 = 通过）。"""
    problems = []
    items = bundle["items"]
    seen = set()
    fam_counter = Counter()

    if len(items) != 100:
        problems.append(f"题数 {len(items)} ≠ 100")

    for it in items:
        qid = it["question_id"]
        g = it["intent"]
        lv, md = g["level"], g["mode"]
        if qid in seen:
            problems.append(f"{qid}: question_id 重复")
        seen.add(qid)
        if lv not in LEVELS:
            problems.append(f"{qid}: 非法 level {lv}")
        if md not in MODES:
            problems.append(f"{qid}: 非法 mode {md}")
        if not it["question"].strip():
            problems.append(f"{qid}: 题面为空")
        if g["route"] != derive_route(lv, md):
            problems.append(f"{qid}: route 字段与派生规则不一致（{g['route']} vs {derive_route(lv, md)}）")
        if it["intent_level"] != lv:
            problems.append(f"{qid}: item.intent_level 与金标 level 不一致")
        if lv == "L0" and md != "casual_chat":
            problems.append(f"{qid}: L0 必须配 casual_chat")
        if md == "casual_chat" and lv != "L0":
            problems.append(f"{qid}: casual_chat 必须配 L0")
        if md == "meta_query" and lv != "L1":
            problems.append(f"{qid}: meta_query 的 level 按分类法只能是 L1")
        if not g["trap"] or not g["rationale"]:
            problems.append(f"{qid}: 缺 trap / rationale（题集必须自证金标）")
        fam_counter[g["family"]] += 1

    dup_q = [q for q, c in Counter(i["question"] for i in items).items() if c > 1]
    if dup_q:
        problems.append(f"题面重复: {dup_q}")

    # 分层面与设计一致（分层被改动时强制复核，防止悄悄漂移）
    by_level = Counter(i["intent"]["level"] for i in items)
    by_route = Counter(i["intent"]["route"] for i in items)
    expect_level = {"L0": 12, "L1": 38, "L2": 22, "L3": 16, "L4": 12}
    expect_route = {"L0": 12, "L1": 28, "meta": 10, "L2": 22, "complex": 28}
    if dict(by_level) != expect_level:
        problems.append(f"分层面变动：{dict(by_level)} ≠ {expect_level}")
    if dict(by_route) != expect_route:
        problems.append(f"分层 route 变动：{dict(by_route)} ≠ {expect_route}")

    # 条款号族的定义就是「生产条款号快路径能认出的问句」，该族必须真被快路径命中。
    # meta 族的规则覆盖比分类法窄（实测 10 题里 3 题落模型），那是产品事实不是题集错误，故只报不断言。
    for it in items:
        hit = it["intent"]["rule_hit"]
        if it["intent"]["family"] == "L2_clause_number" and hit != "rule_clause":
            problems.append(f"{it['question_id']}: 条款号族未被条款号快路径命中（rule_hit={hit}）")
    return problems


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true", help="只校验不写盘")
    args = ap.parse_args()

    bundle = build()
    problems = validate(bundle)
    items = bundle["items"]

    print("题数:", len(items))
    print("by level:", dict(sorted(Counter(i["intent"]["level"] for i in items).items())))
    print("by route:", dict(sorted(Counter(i["intent"]["route"] for i in items).items())))
    print("by rule_hit:", dict(sorted(Counter(i["intent"]["rule_hit"] for i in items).items())))
    print("family 数:", len({i["intent"]["family"] for i in items}))

    # meta 族规则覆盖缺口：分类法说这些是 meta_query，但生产 meta 规则认不出 → 会落到分类模型。
    # 如实报出（这是题集发现的产品事实，不是题集的错）。
    meta_items = [i for i in items if i["intent"]["family"].startswith("meta_")]
    meta_model = [i["question_id"] for i in meta_items if i["intent"]["rule_hit"] != "rule_meta"]
    print(f"meta 族 {len(meta_items)} 题：meta 规则命中 {len(meta_items) - len(meta_model)} / 落模型 {len(meta_model)}")
    if meta_model:
        print(f"  落模型: {meta_model}（规则覆盖缺口，已是好题面，保留）")

    if problems:
        print("\n== 校验未通过 ==")
        for p in problems:
            print("  -", p)
        return 1
    print("\n校验通过（结构不变量 + 规则层对账）")

    if not args.check:
        OUT.parent.mkdir(parents=True, exist_ok=True)
        OUT.write_text(json.dumps(bundle, ensure_ascii=False, indent=1), encoding="utf-8")
        print("已写", OUT)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
