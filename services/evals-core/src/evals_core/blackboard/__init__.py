"""对话黑板 M0 离线壳：题集、三臂组装、离线图、干跑度量。

对应施工单 docs/plan-blackboard-arms.md（下称 arms）：
- ``cases.py``  —— arms §3 的 22 题主集（原文 + 出处 session/seq），带 DB 保真校验；
- ``graph.py``  —— **确定性**离线图（cites 边 = arms/BB §3.2 的 [KTE]×cite join；
  value 节点 = 正则 + 原文回查）＋ 子图召回 ＋ 固定版式渲染；
- ``arms.py``   —— 三臂 prompt 组装与分段度量（闸 A 斜率 / 闸 B 子图段上限）；
- ``runner.py`` —— 干跑（不调 LLM）：产出可归因的 prompt 级读数 + 指针在场率。

设计纪律（与 arms §1 一致）：
- 臂 1/臂 2 用**生产同一段代码**（``agent_configs.make_budget_transformer``）只切开关；
- 臂 3 是 M0 的离线替身（生产读路径要到 M2 才有），其通道 1（指针回引）**必须自带**——
  这里直连 store 层的 ``list_blocks_by_clause_refs`` 语义由 ``graph.recall`` 表达；
- 本包**不调 LLM**：判分跑（要真实模型作答）另行触发，且需业主先冻结题集。
"""
