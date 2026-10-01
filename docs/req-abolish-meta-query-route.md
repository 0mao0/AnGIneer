# 废 meta_query 路由（意图识别改造）设计

状态：设计中（2026-10-02 立项讨论定稿，未动代码）
来源：FinanceBench 评测 E 类「路由性空召回」根因——meta_query 误路由稳定复现（run-77b37dd521d2 / run-87f822a3948a 各 3 道），且分类器 reason 与输出自相矛盾（reason 推出「应归 semantic_retrieval」输出仍是 meta_query）

## 1. 需求

废掉 meta_query 这条「路由即数据源绑定」的特权岔道：路由只定编排深度（level），数据源选择下沉工具层由模型自选。

### 1.1 三个实测病灶

| 病灶 | 证据 |
|---|---|
| 定义边界学不会 | 「问知识库本身 vs 问文档正文」规则 2 与规则 7 在 prompt 里互相打架；financebench_id_01319/01328 三次 run 稳定误路由，分类器 reason 里自己推出「应归 semantic_retrieval」但输出仍是 meta_query——prompt 对抗导致的输出漂移，加示例治不好 |
| 路由即数据源绑定 | 判错后工具箱里没有 knowledge_search（meta 档只有 knowledge_stats），连自救都不能，唯一指望是兜底回退 |
| 兜底条件可被绕过 | meta 通道答 "0" 能通过 `_meta_answer_usable` 检查 → 不回退 → 错答直接出库（01319/01328 实踩，答 "0" 无检索） |

## 2. 设计

### 2.1 改造前整体路由（`agent_policy.build_attempts`）

```
classifier 输出 {level, service_mode}
        │
        ▼
┌─ service_mode == "meta_query"?（优先于一切 level）──────────┐
│ 是 │                                                         │
│    ▼                                                         │
│  [meta档: tools=[knowledge_stats] 单工具独木桥,               │
│   success_check=_meta_answer_usable("0"也能过),               │
│    → L1档(enforce_evidence=False) 双段回退兜底]               │
└────┼─────────────────────────────────────────────────────────┘
     │ 否
     ├─ L0/casual_chat ─► [L0 闲聊直答档]（无工具）
     ├─ L2/structured_lookup ─► [L2档: table_search 首位+首轮注入, → L1档回退]
     ├─ L3/L4/sop/complex ────► [complex档: 全工具箱, max_turns=8, requires_tools]
     └─ 默认(L1) ─────────────► [L1档: knowledge_search+table_search+entity_search,
                                  max_turns=3, requires_tools, evidence闸]
```

### 2.2 改造后整体架构

```
classifier 输出 {level}（service_mode 退出路由；_is_meta_query 短路删除）
        │
        ├─ L0 ────────────────► [L0 闲聊直答档]（无工具）          ← 不变
        │
        ├─ L1（含原 meta 题）──► [L1档: 统一工具箱, max_turns=3,
        │                          requires_tools, evidence闸]
        │      工具箱 = knowledge_search   ← 问文档内容
        │               table_search      ← 问表格/数值
        │               entity_search     ← 问实体
        │               knowledge_stats ★ ← 问知识库本身（本次下沉）
        │      模型按工具描述自选；选错=一次无效调用，可换
        │
        ├─ L2 ────────────────► [L2档(table首位+首轮注入) → L1档回退] ← 不变
        │
        └─ L3/L4 ─────────────► [complex档, max_turns=8, requires_tools] ← 不变

删除物：meta 档(build_meta_config)、meta→L1 双段回退、
        _meta_answer_usable/_META_NON_ANSWER_PATTERNS 特判、
        classifier 的 meta_query 输出值与规则2/7
```

核心变化：数据源决策从「分类器一次拍板、错了进死胡同」变成「模型在统一工具箱里选、错了能换」。

### 2.3 各档工具箱对照

| 档 | 改造前工具箱 | 改造后 |
|---|---|---|
| L0 | 无 | 无（不变） |
| meta 档 | 仅 knowledge_stats | 整档删除 |
| L1 | knowledge_search, table_search, entity_search | + knowledge_stats ★唯一变化 |
| L2 | table_search 首位 + 同 L1 三件套 | 不变 |
| L3/L4 complex | 全工具箱 | 不变 |

真 meta 题（「知识库里有多少篇文档」）新走法：classifier 判 L1 → L1 档 → 模型看 knowledge_stats 描述（「只在问知识库本身的数量/分布时用」）自选 → 调用即算 used_tools，evidence 闸天然通过，无需任何特判。

### 2.4 改动清单

| 处 | 动作 |
|---|---|
| `classifier.py` | 删 `_is_meta_query` 前置短路（:127-129, :915）与 `META_QUERY_TARGETS`；真 meta 题由 LLM 分类自然落 L1 |
| `prompts/classifier.py` | 删规则 2/7 的 meta 对抗条款，prompt 瘦身 |
| `agent_configs.py` | 删 meta 档 build_meta_config（:243-275）；knowledge_stats 进 L1 工具箱（build_qa_config），工具描述写清用途边界 |
| `agent_policy.py` | 删 `_META_NON_ANSWER_PATTERNS`/`_meta_answer_usable`（:43-62）与 meta→L1 双段回退分支（:170-176）；format_route_note 的 meta 文案同步清理 |
| evidence 闸 | 无需改动：knowledge_stats 调用产生 tool 消息，requires_tools 天然满足 |

注意点：meta 档原有的 budget transformer 保护注释（agent_configs.py:314，「knowledge_stats 当轮统计结果在真 user 之后」）随档删除；knowledge_stats 进 L1 后走 qa 档的 transformer，需确认统计结果不被预算裁剪（protect_current_run 语义核对）。

### 2.5 范围边界

- 只拔 meta_query 这一颗钉子，不动 mode 轴整体（calculation/dynamic_orchestration 保留）——拆轴触发点仍是「第二通道（GIS/CAD/报告）立项」，本次控制爆炸半径
- 不碰 level 判定逻辑本身

## 3. 验收

- [ ] financebench_id_01319 / 01328 / 00822 回放：retrieved_items 非空、不再答 "0"（这三道是改造的前置失败测试，先红后绿）
- [ ] 真 meta 题回归：现有 `tests/angineer-core/test_meta_query.py` 全过 + 手写 3-5 道真 meta 题回放（应走 L1 档自选 knowledge_stats，答案正确）
- [ ] 全量回归：pos-regress-60 + financebench-open-150 各跑一次，miss 数不升、ttft 不升（误路由题省掉失败回退应更快；真 meta 题可能多一轮工具选择，可接受）
- [ ] angineer-core 全量单测过
