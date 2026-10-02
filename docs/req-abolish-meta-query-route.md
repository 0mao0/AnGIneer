# 废 meta_query 路由（意图识别改造）设计

状态：设计中（2026-10-02 立项讨论定稿，未动代码；同日三轮评审修订见 §0/§0.1，四轮全量行号核验修订见 §0.2。**业主定论：meta_query 路由肯定要废，两步走只是实施排序，第二步不可省略**）。**定位：本文档 = 意图识别改造的整体设计（废 meta_query 路由两步走）**；与 Blackboard 新对话模式（`req-blackboard-conversation-mode.md`，原「会话语义图/路线 B」）是两条独立轨道——那边管「历史与证据怎么进 prompt」（上下文层），这边管「进哪个编排档、工具箱里有什么」（路由层），分工与融合见 §4
来源：FinanceBench 评测 E 类「路由性空召回」根因——meta_query 误路由稳定复现（run-77b37dd521d2 / run-87f822a3948a 各 3 道），且分类器 reason 与输出自相矛盾（reason 推出「应归 semantic_retrieval」输出仍是 meta_query）

## 0. 评审结论与修订点（2026-10-02）

初版方案经两轮独立评审（结论互证）：**方向对，但初版有 1 个 P0 事实错误 + 根因归因错位 + 验收口径设反**。本版已按评审修订，核心变化：

| 评审发现 | 证据 | 本版处置 |
|---|---|---|
| **P0**：knowledge_stats 返回 `{documents,pages,storage,uploads}` 无 `items`，进 L1 后 `enforce_evidence` 闸（agent_configs.py:162-177，证据只认 tool JSON 的 `items[].text`）会把正确统计答案强制换成拒答 | L1 默认 `enforce_evidence=True`（agent_policy.py:210）；`build_meta_config` docstring（agent_configs.py:253-254）本就写明「QA guard 会把正确统计回答误判为无证据」——meta 档不装 guard 正是为此 | §2.4 新增前置条件 P-1（guard 证据口径兼容 stats 结果），未解决前不得下沉 |
| `force_first_search` 与「模型自选」自相矛盾：L1 段首轮强制注入 knowledge_search（agent_policy.py:116 → agent_loop.py:1078-1142，默认开），首轮数据源仍由路由绑定；真 meta 题白跑一次检索且注入的无关正文可能诱导编数字 | 代码实读 | §2.4 新增前置条件 P-2（stats 场景豁免/不注入） |
| 根因归因错位：三道 financebench 题全是英文，`META_QUERY_VERBS` 全中文（classifier.py:118-121），规则不可能命中——误路由来自 **LLM 分类器输出**（与「reason 与输出自相矛盾」吻合，是 prompt 对抗漂移），不是 `_is_meta_query` 规则短路。规则实际只拦 7 道真 meta 题（与 intent-router-v1「meta 族 10 题中 3 题落模型」互证），删它对目标题零作用、对真 meta 题是净亏（确定性零 LLM 调用 → 全押 LLM+工具自选，正好撞 P0） | 规则词表实读 + 题库扫描 | §2 改为两步走（**仅为实施排序**：第一步止血先行上线，第二步废路由是既定目标，不以前一步疗效为转移）；`_is_meta_query` 随第二步一并删除 |
| 验收第 1 条在 01319 上设反：01319 gold=**"0"**（题面原文 "If restructuring costs are not explicitly outlined then state 0"，答 0 是对的，病灶是「无召回蒙对」）；01328 gold="$411 million"（真错答）；00822 gold="Yes, his name is Richard A. Johnson"（与「答 0」无关） | 数据集 `data/evals/datasets/financebench-open-150-v1.json` 实测 | §3 验收口径重写 |
| 漏项：QA prompt 升版、测试断点、evals-core meta 桶、StatsAdapter docstring、`_has_substantive_content` 依赖 | 见 §2.4 改动清单 | 已补入 |

### 0.1 三评追加修订（2026-10-02，四条已逐项核码证实）

| # | 评审发现 | 证据 | 本版处置 |
|---|---|---|---|
| 1 | **P-2 与 P-3 对撞**：注入豁免需要统计意图信号，而第一步（删 classifier meta_query 输出值）+ P-3（删 `_is_meta_query`）把信号删尽——第二步世界里豁免无判据可用 | classifier.py:118-129（调用点 :589/:667/:915）；intent-router-v1 meta 族 10 题 = 规则直给 7 + 落模型 3（`_is_meta_query` 逐题复现核对） | P-2 定版 **c 案：降级纯 prompt 约束**（QA v14 措辞兜）+ 第一步回放探针量污染；实测超标再议 b 案窄启发式（盲区 = meta-rephrase 族按构造躲规则，豁免不了事故人群）；a 案「一律注入」与 c 的 prompt 措辞本是同一动作组合 |
| 2 | **第一步上线即红 intent-router-v1 的 3 道金标**：classifier 删 meta_query 输出值后，3 道落模型题无法再输出 meta，route 恒致命当场翻红 | ir-meta-dir-02 / ir-meta-ref-01 / ir-meta-ref-03 金标 route:"meta"，intent_eval.py:8-9 route 致命；基线 run-824537f13609（97/100）三道当前 pred=meta 全绿、当次 3 失败在 L0×1+L2×2 与 meta 族无关 | 3 道金标**回放后按实际路由桶改 L1**（预期 L1）+ `build_intent_set.py` 机械校验同步——**进第一步改动清单**（§2.2）；7 道规则命中题金标仍随第二步 |
| 3 | `_meta_answer_usable` 收紧两难：认 knowledge_stats 为证据工具→漏「调了 stats 仍编过滤零」的真事故形态；不认→误杀合法统计零（空库/0 篇）；数字出现性判据在「答案内容 × 是否调工具」粒度上结构性看不见数字来源 | agent_policy.py:59-67 现状=黑名单话术（注释明写窄口径防误伤）；stats JSON 满是 0（`deleted:0` 等）、meta 规则 2 允许四则运算（算出的数不在 JSON 里） | **第一步不做收紧**（§2.2 该行改「本步不动」），维持现状黑名单，第二步随档删除 |
| 4 | META prompt 身份冲突比初判重；「扩 build_meta_config 签名」过强 | prompts/agent_configs.py:240 身份句 + 规则 1「必须先调 knowledge_stats/禁止编数字」+ 规则 4「正文内容类问题不属于本通道职责」三处冲突；knowledge_search 工厂全参数有默认（agent_tools.py:581-596），`library_id` 已在 build_meta_config 签名里 | §2.2 META 行改「重写三处 + 升版 v3」；build_meta_config 行注明最简接法**无需扩签名**，真决策 = 自救检索是否与 L1 同源（doc_ids/filters 作用域） |

### 0.2 四评修订（2026-10-02，全量行号核验 + 外围面 grep）

四评对 §0/正文全部行号引用逐条对码，与三评结论互证（meta 族 7/3 拆分三评已逐题复现）；外围面 grep 证实 aichat-api / evals-ui / docs-ui / admin-web / user-web / nightly 链路源码对 meta_query 零命中，引用面全部落在 §2.4 清单内。四评新增修订：

| # | 评审发现 | 证据 | 本版处置 |
|---|---|---|---|
| 1 | 勘误：prompt 涉 meta 的是规则 6/7（:28-29），规则 7 是规则 6 的边界收紧、互补非「打架」；规则 2（:24）是考试/计算意图，与 meta 无关 | prompts/classifier.py 实读 | §1.1/§1.2/§2.2/§2.3/§2.4 全部改为规则 6/7 |
| 2 | **第一步非确定性**：`ServiceMode` Literal（base_contracts.py:71）仍接受 meta_query——单删 prompt 是赌 LLM 服从，漂移输出照过 pydantic 进 meta 分支（agent_policy.py:170-171 优先于一切 level）；本方案立论本就是「LLM 会漂移」 | base_contracts.py:64-72 + agent_policy.py:170-171 实读 | §2.2 新增 LLM 解析点（classifier.py:1013）归一化，与 prompt 删值构成双保险；第二步 §2.4 删临时归一化 |
| 3 | P-1 欠一道闸：guard 除 no_evidence 外还有 unsupported_reference——空证据下答案含「大写缩写+数字」token（如 ISO 19880）即拒答 | agent_configs.py:178-183 → retrieval_pipeline.py:342+ | P-1 扩为两道闸；§2.4 定版「stats 摘要纳入 evidence_parts」，否决「纯 stats 组合豁免 enforce_evidence」（重开 01319 型无证据出数字洞） |
| 4 | 漏项×4：base_contracts.py:71 Literal 成员（保留注 legacy，照 `sql_first` 先例——删成员会使历史轨迹/回放过不了校验）；classifier.py:667（`_rule_based_classify` 第二处规则命中，与 :915 重复）；build_intent_set.py 其余触点（:23/:36/:70/:117-129/:243/:348-349/:392）；docs_routes.py:322 / docs-core agent_port.py:308 注释 | 全仓 grep 交叉验证 | §2.3 P-3、§2.4 已补 |
| 5 | evals-core meta 桶留白定版：**保留注 legacy**——历史 run 记录存有 service_mode="meta_query"，删映射会追溯改写历史分布；新流量不再产生该值，桶自然归零 | intent_eval.py:32/:52-53 | §2.4 已定版，test_intent_eval.py:25 断言保留补注 |

## 1. 需求

废掉 meta_query 这条「路由即数据源绑定」的特权岔道：路由只定编排深度（level），数据源选择下沉工具层由模型自选。

### 1.1 三个实测病灶

| 病灶 | 证据 |
|---|---|
| 定义边界学不会 | 「问知识库本身 vs 问文档正文」的边界条款齐全且互补（规则 6 :28 + 规则 7 收紧 :29 + few-shot 反例 :39-43），并非条款打架（四评勘误：旧版写「规则 2 与规则 7」，规则 2 :24 实为考试/计算意图与 meta 无关）；financebench_id_01319/01328 三次 run 稳定误路由，分类器 reason 里自己推出「应归 semantic_retrieval」但输出仍是 meta_query——**这是 LLM 对边界的对抗性漂移，不是规则短路**（三道题均为英文，`META_QUERY_VERBS` 全中文，`_is_meta_query` 规则不可能命中），条款再齐也治不好 |
| 路由即数据源绑定 | 判错后工具箱里没有 knowledge_search（meta 档只有 knowledge_stats），连自救都不能，唯一指望是兜底回退 |
| 兜底条件可被绕过 | meta 通道答 "0" 能通过 `_meta_answer_usable` 检查 → 不回退 → 错答直接出库（01319/01328 实踩，答 "0" 无检索；01319 的 gold 恰好是 "0"，属「无召回蒙对」） |

### 1.2 根因分层（评审修订）

```
误路由来源拆解（对三道 financebench 靶题）：

  LLM 分类器 prompt（规则 6/7 边界下仍漂移） ← 真根因，三道题全在这里
        │  输出 meta_query（reason 自相矛盾）
        ▼
  build_attempts meta 独木桥        ← 放大器：判错即死胡同
        │
        ▼
  _meta_answer_usable("0"也过)      ← 兜底失效：错答出库

  _is_meta_query 规则短路           ← 与三道题无关（全英文不命中中文词表），
                                      删它不治病；它只服务 7 道真 meta 题
```

结论：**承重修改是「分类器 prompt 删 meta_query 输出值 + LLM 解析点代码级归一化」双保险**——`ServiceMode` Literal（base_contracts.py:71）仍接受 meta_query，单删 prompt 是赌 LLM 服从、漂移输出照样过 pydantic 进 meta 分支（agent_policy.py:170-171 优先于一切 level），归一化才使第一步构造性生效（见 §2.2）；废路由档是既定架构目标（业主定论 2026-10-02），不因第一步疗效而取消，但必须排在 P-1/P-2 前置条件之后实施。

## 2. 设计（两步走）

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
                                  max_turns=3, requires_tools, evidence闸,
                                  force_first_search=True（首轮注入 knowledge_search）]
```

### 2.2 第一步：止血 + 前置验证（先治三道靶题，爆炸半径最小）

定位：先把生产在出的错治掉（三道靶题真根因在 prompt），同时为第二步验证关键假设；**本步不免除第二步——废路由是既定目标，此处只是实施排序**。

只动分类器（prompt 删值 + LLM 解析点归一化双保险）+ meta 档自救，不碰路由结构：

| 处 | 动作 |
|---|---|
| `prompts/classifier.py` | 删 meta_query 输出值与规则 6/7 的 meta 条款（四评勘误：涉 meta 的是规则 6 :28 + 规则 7 收紧 :29，规则 2 :24 是考试/计算意图与 meta 无关）——三道靶题的真根因；层级表 :16、few-shot 正例 :37、「五种」输出清单 :56 同步清理。**单靠删值不保证生效**（Literal 白名单 base_contracts.py:71 仍收 meta_query），须与下一行归一化配套 |
| `classifier.py` LLM 解析点（:1013） | **代码级归一化（四评 #2，双保险的第二道）**：LLM 路径输出 service_mode=="meta_query" 一律改写 semantic_retrieval（pydantic 校验前）——漂移输出不再能进 meta 分支（agent_policy.py:170-171），第一步从「赌 prompt 服从」变构造性生效；两处规则路径（主路径步骤 1.6 :915、兜底 `_rule_based_classify` :667）的显式赋值不动，7 道真 meta 题行为不变 |
| `agent_configs.py` `build_meta_config` | 工具箱 `[knowledge_stats]` → `[knowledge_stats, knowledge_search]`，`max_turns` 2→3——判错也能自救，「独木桥」病根改一行就治好。接法：`knowledge_search(library_id=…)` 最简装配（工厂全参数有默认，agent_tools.py:581-596），**无需扩签名**（三评 #4）；待决一项 = 自救检索是否与 L1 同源（doc_ids/filters）——不扩签名即库级检索，与 meta 档现状一致 |
| `prompts/agent_configs.py` `META_AGENT_SYSTEM_PROMPT` | **重写三处而非加一条**（三评 #4）：身份句「你是知识库统计助手…回答知识库本身的统计/元数据问题」、规则 1「必须先调用 knowledge_stats…禁止凭印象编造任何数字」、规则 4「正文内容类问题不属于本通道职责」均与新增 knowledge_search 冲突（prompts/agent_configs.py:240-252）；升版 v2→v3 register（同步 run 快照 `prompt_versions`） |
| `agent_policy.py` `_meta_answer_usable` | **本步不动（三评 #3 定版：收紧撤销）**——收紧判据两难（认 stats 为证据工具则漏真事故形态、不认则误杀合法统计零，数字出现性判据结构性看不见来源，见 §0.1 #3）；维持现状黑名单，第二步随档删除 |
| `_is_meta_query` 规则 | 本步不动，**第二步随档删除**（见 P-3） |
| intent-router-v1 题集 | **3 道落模型金标必须随第一步改**：`ir-meta-dir-02` / `ir-meta-ref-01` / `ir-meta-ref-03`——classifier 删 meta_query 输出值后模型无法再输出 meta，route 恒致命（intent_eval.py:8-9）当场翻红（基线 run-824537f13609 三道当前 pred=meta 全绿）；回放后按实际路由桶改 L1（预期 L1），`build_intent_set.py` 机械校验同步。其余 7 道规则命中题金标仍随第二步（规则未删前路由不变） |

第一步完成后回放验证（§3），确认三道靶题治愈后即可排期第二步；若 E 类空召回仍有残留，说明根因未除尽，先补查再进第二步。

### 2.3 第二步：废 meta_query 路由（前置条件满足后才动）

```
classifier 输出 {level}（service_mode 退出路由；_is_meta_query 规则随档删除，见 P-3）
        │
        ├─ L0 ────────────────► [L0 闲聊直答档]（无工具）          ← 不变
        │
        ├─ L1（含原 meta 题）──► [L1档: 统一工具箱, max_turns=3,
        │                          requires_tools, evidence闸(需P-1改造)]
        │      工具箱 = knowledge_search   ← 问文档内容
        │               table_search      ← 问表格/数值
        │               entity_search     ← 问实体
        │               knowledge_stats ★ ← 问知识库本身（本次下沉）
        │      模型按工具描述自选；选错=一次无效调用，可换
        │      ※ 首轮注入污染以 prompt 约束兜（P-2 三评定版：纯 prompt 约束+探针，见前置表）
        │
        ├─ L2 ────────────────► [L2档(table首位+首轮注入) → L1档回退] ← 不变
        │
        └─ L3/L4 ─────────────► [complex档, max_turns=8, requires_tools] ← 不变

删除物：meta 档(build_meta_config)、meta→L1 双段回退、
        _meta_answer_usable/_META_NON_ANSWER_PATTERNS 特判、
        classifier 的 meta_query 输出值与规则6/7（第一步已删）
```

**前置条件（不满足不动工）**：

| # | 前置 | 原因 |
|---|---|---|
| P-1 | `make_final_answer_guard` 证据口径兼容非检索类工具，**两道闸都要过**（四评 #3）：①no_evidence——证据只认工具 JSON 的 `items[].text`（agent_configs.py:162-177），knowledge_stats 返回无 `items[]`，正确统计答案必判无证据；②unsupported_reference——空证据下答案含「大写缩写+数字」token（如 ISO 19880）即拒答（agent_configs.py:178-183 → retrieval_pipeline.py:342+） | 不解决则「真 meta 题答案正确」验收必挂——meta 档当年不装 guard 正是这个原因（agent_configs.py:253-254 注释）；只修①不修②，带标准编号引用的统计答案仍被拒 |
| P-2 | **定版（三评 #1）：降级为纯 prompt 约束，不做代码级豁免**——QA prompt v14 写明「注入的检索结果若与问题无关（如问知识库本身），忽略并改用 knowledge_stats」；第一步回放探针量污染（ir-meta-ref-* 与 01319/01328 形态题在一律注入下的编数字率），实测超标再议窄启发式豁免 | 原豁免方案与 P-3 对撞：豁免判据需统计意图信号，而第一步（删 classifier meta_query 输出值）+ P-3（删 `_is_meta_query`）把信号删尽；窄启发式盲区 = meta-rephrase 族按构造躲规则，豁免不了事故人群 |
| P-3 | `_is_meta_query` 规则**随档删除**（业主定论：废就废干净，不留第二条 meta 岔道）：它确定性拦截 7 道真 meta 题（零 LLM 成本）的价值，不敌「同义两条路」的维护与漂移成本；删除后真 meta 题由 LLM 判 L1 + 工具自选承接，依赖 P-1/P-2 先行落地。注意 `_is_meta_query` 引用共**三处**（定义 :127-129）：`_has_substantive_content`（:589，L0 兜底，删除需同步改判据）、`_rule_based_classify`（:667，LLM 失败时的规则兜底，与主路径步骤 1.6 :915 重复，两处同删）；intent-router-v1 题集 10 道 meta 金标与 `build_intent_set.py` 机械校验同步改（触点 :23/:36/:70/:117-129/:243/:259-265/:348-349/:392） | 评审实测：删规则对三道靶题零作用；保留它只是重复通道，与「废特权岔道」目标矛盾 |

### 2.4 改动清单（第二步全量）

| 处 | 动作 |
|---|---|
| `classifier.py` | 删 `_is_meta_query`（定义 :127-129；引用三处 :589/:667/:915 同步处置）与 `META_QUERY_VERBS`/`META_QUERY_TARGETS`；`_has_substantive_content`（:589）对 `_is_meta_query` 的 L0 兜底引用同步改判据；**删第一步的临时归一化**（meta 分支已不存在，LLM 残值经 Literal 校验后自然落 L1 默认档 agent_policy.py:210，归一化完成历史使命） |
| `prompts/classifier.py` | （第一步已删规则 6/7 与 meta_query 输出值） |
| `agent_configs.py` | 删 meta 档 build_meta_config（:243-275）；knowledge_stats 进 L1 工具箱（build_qa_config），工具描述写清用途边界；**P-1 定版**：stats 摘要纳入 guard 的 evidence_parts（①no_evidence 与 ②unsupported_reference 两道闸一并兼容——有 stats 证据后②自然解除）；**否决**「无 items 的纯 stats 组合豁免 enforce_evidence」——会把 01319 型「无证据出数字」的洞原样重开 |
| `agent_policy.py` | 删 `_META_NON_ANSWER_PATTERNS`/`_meta_answer_usable`（:43-62）与 meta→L1 双段回退分支（:170-176）；format_route_note 的 meta 文案同步清理（P-2 已定版纯 prompt 约束，**此处无注入豁免代码改动**） |
| `base_contracts.py` | `ServiceMode` Literal 的 `"meta_query"` 成员（:71）**保留改注 legacy**（四评 #4，照 `sql_first` 先例）——历史轨迹/回放记录含该值，删成员会使旧数据过不了 pydantic 校验；路由分支已删，残值自然落 L1 默认档，无行为影响 |
| QA prompt | 升 v14 并 register：现役生效版本是 V13（`_load_qa_system_prompt` 走 "latest"），其规则 5/6 仍按名点名 knowledge_search/table_search/entity_search 做路由引导，加第四个工具需同步措辞（注：「只有 knowledge_search 与 table_search 均无证据才拒答」的写死条款在 V7/V9，现役 V13 已改为对象对齐判断，不再是阻碍）；**措辞并入 P-2 约束**（「注入的检索结果若与问题无关，忽略并改用 knowledge_stats」） |
| `agent_tools.py` | `StatsAdapter` docstring「meta_query 通道专用」（:861）改写 |
| 预算闸 | 无需改动：qa 档 transformer 已 `protect_current_run=True`（agent_configs.py:418），与 meta 档同语义，当轮统计结果不被裁剪（初版 §2.4 注意点撤销） |
| `tests/angineer-core/test_budget_gates.py` | 3 处 import build_meta_config（:337/:354/:382）随档删除改写 |
| `services/angineer-core/tests/test_meta_query.py` | **改写而非「全过」**：现有用例断言 `_is_meta_query`/`_meta_answer_usable`/`service_mode=="meta_query"`/build_attempts meta 分支，全在被删之列；另 `tests/angineer-core/test_meta_query_routing.py` 同需处置 |
| evals-core | `derive_route()`（intent_eval.py:32/:52-53）meta 桶**保留注 legacy**（四评 #5 定版）：历史 run 记录存有 service_mode="meta_query"，删映射会追溯改写历史分布；新流量不再产生该值，桶自然归零。`test_intent_eval.py:25` 断言保留（legacy 映射仍命中历史形态），补注释 |
| intent-router-v1 题集 | 剩余 **7 道** meta 金标改为 L1 预期 + `scripts/build_intent_set.py` 的 `_is_meta_query` 机械校验同步删除/改判（触点 :23/:36/:70/:117-129/:243/:259-265/:348-349/:392）（3 道落模型金标已在第一步改，见 §2.2） |
| `docs_routes.py:322` / docs-core `agent_port.py:308` | titles 端点注释仍写「供 agent meta_query 通道」——顺手改中性描述（纯注释，无行为） |

### 2.5 暴露面评估

knowledge_stats 从服务 7 道规则命中题 → 暴露给 100% L1 流量。题库含统计词 31/2014（1.5%），工具描述的「数量/分布/趋势」与工程题（「波浪力分布」「吞吐量统计」）天然撞词——工具描述必须把「只在问知识库本身」的边界写死，并靠 P-1 改造后的 guard 兜底误调用。

### 2.6 范围边界

- 只拔 meta_query 这一颗钉子，不动 mode 轴整体（calculation/dynamic_orchestration 保留）——拆轴触发点仍是「第二通道（GIS/CAD/报告）立项」，本次控制爆炸半径
- 不碰 level 判定逻辑本身

## 3. 验收

- [ ] **第一步闸门（新增，三评 #2）**：intent-router-v1 回放——3 道落模型题按实际路由改 L1 后全绿，7 道规则题不红（金标随第一步移动的验收）
- [ ] **P-2 探针（新增，三评 #1）**：一律注入下 ir-meta-ref-* 与 01319/01328 形态题的编数字率——实测超标才升级代码级豁免，否则 P-2 维持 prompt 约束
- [ ] 三道靶题回放（financebench-open-150）：**retrieved_items 非空** + 01319 答 "0" **且带证据**（gold 就是 "0"，「不再答 0」目标设反已修正——病灶是无召回蒙对，不是答错）/ 01328 答 "$411 million" / 00822 答 "Yes, Richard A. Johnson"
- [ ] 真 meta 题回归：`services/angineer-core/tests/test_meta_query.py` 改写后全过 + 手写 3-5 道真 meta 题回放（应走 L1 档自选 knowledge_stats，答案正确；**第一步最小手术实施后需单独回放 intent-router-v1 的 7 道规则命中题**，防止统计题被 meta 档新增的 knowledge_search/注入证据带偏）
- [ ] **P-1 双闸验证（四评 #3）**：真 meta 题走 L1 后 final_outcome 非 no_evidence / unsupported_reference——两道闸各造一例（纯统计答案、带标准编号引用的统计答案如 ISO 19880 形态）
- [ ] 全量回归：pos-regress-60 + financebench-open-150 各跑一次，miss 数不升、ttft 不升（误路由题省掉失败回退应更快；真 meta 题可能多一轮工具选择，可接受）
- [ ] angineer-core 全量单测过（含 test_budget_gates.py、test_meta_query_routing.py 改写）
- [ ] （建议，独立于本改造）补「检索为空却非拒答」观测指标：01319 的「无召回蒙对」本质该由观测兜底（`final_outcome`/`path_trace` 已具备落盘基础），不该只靠改路由治

## 4. 与 Blackboard 新对话模式的分工与融合（2026-10-02 正名时补）

**为什么分开**：Blackboard 新对话模式（`req-blackboard-conversation-mode.md`）曾被上游 `req-chat-history-bloat.md` 的「路线 A/B」框架与本改造混在同一个话题里。实际两者改的是**同一条 aichat 管线的不同层**：

- 本方案（意图识别改造）＝**路由层**：决定请求进哪个编排档（L0/L1/L2/L3-L4）、工具箱里有什么、success_check 用哪套——改造后路由只剩 level 一根轴，数据源选择下沉工具层；
- 新对话模式＝**上下文层**：决定历史与证据怎么进 prompt（语义层逐字全带、证据层蒸馏进会话图按指针回引）——它挂在编排档之内，不改变路由行为。

**四个交点逐条对清（全部无阻塞）**：

| 交点 | 分工 / 约束 | 结论 |
|---|---|---|
| 路由形态 | 本方案第二步后路由只剩 level 轴（meta 档删除、stats 进 L1 工具箱）；新对话模式对路由的唯一依赖是「当轮证据全量进 prompt（protect_current_run）」——与 L1 档现状同语义 | 无耦合 |
| QA prompt 版本 | 本方案 P-2 约束措辞要进 QA v14；新对话模式不改 QA prompt（只新增子图渲染段，随会话图开关走） | v14 一次升级两边受益；排期合并对账、实现不分先后 |
| 评测基建 | 本方案验收走 intent-router-v1 回放（分类层探针）+ 靶题回放；新对话模式需新建多轮评测能力（现有评测每题独立 session 且不走 SSE） | 各建各的、互不阻塞；若后续做「同会话连发」基建可共享 |
| 蒸馏输入 | 新对话模式的会话图蒸馏吃本轮 tool 消息原文（knowledge_search/knowledge_stats JSON）；meta 档删除后 stats 调用发生在 L1 档，蒸馏器按 tool 名过滤即可（其 §3.1 红线已定口径） | 无耦合 |

**排期关系**：互不依赖、可并行。本方案两步走先行（止血 urgency 高：三道靶题在生产稳定错答）；新对话模式 M0 是离线重放，不依赖本方案任何一步。开关各自独立（prompt 版本 / `ANGINEER_CONV_GRAPH`），不存在合并发版约束；两边都不动 `protect_current_run` 与投影式纪律「本体永不动」，A-min 保险丝在两边语义下都保留。
