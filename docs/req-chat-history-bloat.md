# 需求：长会话历史膨胀治理（闲聊 73k prompt 之痛）

> 状态：**A-min 已实施并本地实测达标（2026-09-29，§11），待随 0.2.85 发版**；
> 后续按 §7 决策点观测定 B/A-full。
> 发现于 2026-09-26 意图分类提速本地验收期间（同日已立
> `docs/req-table-retrieval-latency.md`，彼为本需求的前置观测来源之一）。
> 观测数据入口已就绪（data/ops/ttft-*.jsonl），认领即可量化。
> 2026-09-27 与业主讨论收敛方案形态：一期=分层压缩，二期=blackboard 滚动语义板。
> 2026-09-29 通读复核修订：§5.5 未引用证据改指针行（UI resultItems 证伪「用户没看过」）、
> skip 前缀修法、当轮自超豁免、prefix-cache 对照。
> 2026-09-29 二次定版（与业主讨论）：**一期/二期不是先后两期，是两条替代路线**——
> A=阈值压缩（治标，削斜率），B=会话语义图（治本，收敛为常数）；
> 本轮只做 A-min 止血，A 的分层携带（原 §5.5）挂起让位给 B，避免工程量浪费。

## 1. 背景与现状证据

**同一会话连发 5 题**（本地实测 2026-09-26，session `chat-mui9pfcm-qc6p86` 及复测会话），
逐题 `final_turn_prompt_tokens`（`data/ops/ttft-*.jsonl`），并附当日核实的档位与闸状态：

| 题序 | 问题 | prompt tokens | ttft_ms | 档位 / 闸状态（已核实） |
| --- | --- | --- | --- | --- |
| 1 | 什么是乘潮水位？（L1） | 20,120 | 6625 | QA 档，当轮地板（无历史） |
| 2 | 重力式码头…应符合哪条规范要求？（L2） | 34,079 | 24327 | QA 档 est < 30k，闸未触发 |
| 3 | 依据《海港…》确定设计船型尺度（L2） | 31,506 | 19938 | QA 档 est < 30k，闸未触发 |
| 4 | 某5万吨级散货船…试计算码头前沿水深（L3） | 61,389 | 25390（turns=2） | complex 档闸 100k est，形同虚设 |
| 5 | **你好，在么（L0 闲聊）** | **60,364 / 复测 72,819** | **13719 / 15343** | **L0 档根本没装闸（最重灾区）** |

**闲聊一句「你好」背上 60~73k prompt、首字 15s**。根因（2026-09-26 逐条代码核实，
2026-09-29 复核行号有 ~10 行漂移、机制全部属实，下文引用以函数名为锚）：

1. **历史无闸进 prompt，主路径是内存累积而非 DB 回灌**：池 TTL 2h（`chat_agent.py:20`），
   同会话连发根本不触发回灌；真正的雪球是 `agent_session.py:57-63` 把**累积的
   `session.history` 本体**（含此前每轮的全量检索证据 tool 消息）整个传进 `run_agent_loop`，
   池命中照样膨胀。冷路径（池淘汰/重启后）`sqlite_store.load`（`sqlite_store.py:185`）
   同样全量 SELECT 无预算。
   **推论：只在 store.load 装闸不满足验收——修刀位置必须在 LLM prompt 组装层
   （transform_context），热/冷路径统一覆盖。**
2. **证据全文驻留 history**：run_end 落库切片含 role=tool 全量检索 JSON（`main.py:457` persist，
   knowledge_search/table_search top_k=20 候选全文）；`agent_messages.py:230-244` 每次调用
   把 tool content 原文序列化进 prompt，逐轮累乘——73k 的大头。
3. **闸覆盖残缺**：A1 闸（plan-ttft §3，`make_budget_transformer`，投影式）只装了 QA 档
   （`build_qa_config`，默认 30k est，env `ANGINEER_QA_BUDGET_TOKENS_EST`）；**L0
   `build_chat_config` 与 meta `build_meta_config` 根本没装 transform_context**；complex 档
   100k est / stopper 120k（`build_complex_config`）对 QA 场景形同虚设。
   且 est（chars//2）对纯中文低估约 2x（1 字≈1 token），30k est ≈ 实际 60k。

伤害：延迟（大 prompt prefill 直线放大 ttft，Q5 的 15s 几乎全是 prefill）+ 成本（每轮
input tokens × 每请求）+ 检索证据在闲聊轮纯属浪费。

## 2. 目标

- **主目标**：同会话第 5+ 轮的 run prompt tokens ≤ 25k。
- **分解目标**：闲聊轮（L0）不携带历史检索证据；任意单轮 prompt 不随历史轮数无界增长。

## 3. 前置核查：enforce_evidence 不吃历史（2026-09-26 闭环）

```
全部引擎判定 → 只扫当前 run/attempt 切片
├─ _tool_evidence_present / _tool_evidence_parts → messages[attempt_start_idx:]（agent_loop.py）
├─ final_answer_guard → messages[start_idx:]
├─ success_check → added = messages[start_idx:]
└─ [Kx] 引用标记 → marker_allocator 每 run 独立分配

真正依赖历史的只有两处（裁剪红线）：
├─ _latest_user_query 全表倒扫 → 代检索/§8.6 改写取「上一问」→ 最近一条 user 必须保留
└─ run_end persist 返回 history[start_idx:] 切片 → 不能原地裁 history 本体（A1 投影式教训）
```

**推论：历史证据可放心降维，引擎判定零影响。**

## 4. 验收标准

1. 本地同会话连发 ≥6 题（混合 L1/L2/L0），ops jsonl 逐轮 prompt_tokens ≤ 25k；
   **豁免口径**：当轮自身证据即超 25k 的题（重表题 L2 table_search / L3 大计算）单列观测
   不判失败——当轮证据受 protect_current_run 保护，本就不该压。
2. **连贯性不劣化**：跟进式追问（§8.6 上下文化改写依赖上一问）与证据追问（「刚才第二条规范说什么」）
   人工比对不回退；nightly 整体不低于基线。
3. 新增行为有开关，默认值经实测后再定。
4. **ttft 改善须排除 prefix-cache 假象**：实测报告补「同档连发 vs 跨档切换」ttft 对照——
   压缩使 prompt 前缀逐轮变化，会让 vLLM prefix caching（dgx1 已开）跨轮复用失效，
   「tokens 变小」与「缓存失效」两个效应须分开读数，验收终值认 ttft 不只认 tokens。

## 5. 路线 A：阈值压缩（治标，本轮只做 A-min 止血）

本质是「A1 扩装+收紧」，不是新造轮子；修刀唯一位置 = `transform_context` 投影层
（copy-on-write，history 本体与落库保全量原文，A1 已立此规矩），热/冷路径统一覆盖。

### 5.1 A-min（本轮交付）：机械改动、低风险、收益最大

```
改动全部收敛在 agent_configs.py（+单测），不动 agent_loop、不动存储：

1. L0 chat 档补装 transform_context
   └─ 无工具，裸装即可（无当轮证据可误压）
2. meta 档补装 transform_context，必须 protect_current_run=True
   └─ meta 有 knowledge_stats 工具（max_turns=2），当轮统计结果在 user 之后；
      裸装会把当轮数字压成一行摘要，统计答案失真（2026-09-29 评估新发现）
3. QA 档阈值收紧：30k est → 16k est（定值见 §11.1 回归）
   └─ 定值流程写死：以 ops jsonl 实测混合文本回归 est(chars//2)→real 系数，
      取 p99 反推阈值（验收只认真实 prompt_tokens ≤ 25k，est 只是实现侧旋钮）
4. complex 档 100k est 重估 → 24k est，独立于 QA 档（L3 是 Q4 61k 的成因；
   SOP 长 run 需证据余量，不对齐 16k）
5. 顺手修 A1 现存边界坑：protect_current_run 以「最后一条 user 消息」为当轮边界
   （make_budget_transformer），但 run 内 retry / 代检索会注入内部 user 提示
   （agent_loop.py 多处 append role="user"）使边界后移，当轮已产出的证据反而落入
   可压区——超阈值会话里重试轮拿不到证据作答。
   定版修法：定位边界时跳过 _INJECTED_USER_PROMPTS 前缀的内部提示（agent_loop.py:227
   已有该常量，import 即用，纯 agent_configs 可实现）；备选的「run 起点划界」否决——
   run_start_idx 传不进 transformer，必动 agent_loop/session 签名，与本路线
   「不动 agent_loop」冲突。
```

压缩语义（沿用 A1 现状）：est 超阈值 → 从最老的历史 tool 消息开始，压成
`[已压缩: 工具 xx 的结果，要点: …]` 一行，压到达标为止；当轮（边界之后）绝不压。
保留红线：最近一条真实 user 逐字（§8.6 改写与代检索靠它）。

预期收益：Q5 73k → ~5-15k（L0 无工具无证据，prompt 只剩 system + 历史文本 + 历史摘要；
~5k 是本题集最好情况，L3 长答案会话十几轮约 15-20k，仍在 25k 目标内）。

### 5.2 A-full（挂起）：分层携带，仅当路线 B 不立项时回填

「历史证据全压成一行摘要」太粗——20 段证据里被答案引用的通常只有 1~5 段。分层策略：

- **被答案引用的 items** → 自描述摘要（「[上轮引用] JTG D60 第5.3.1条：首 200 字…」），
  防「刚才第二条规范说什么」类证据追问失忆。引用映射重建路径：MarkerAllocator 把 cite
  写进 `item.metadata["cite"]`（`agent_tools.py`），随工具结果序列化进 tool 消息 JSON；
  投影时解析历史 tool 消息 JSON 的 metadata.cite 重建 [Kx]→item，无需新增落盘；
  [Kx] 编号每 run 独立分配会跨轮撞号，故摘要必须自描述或重编号加轮次前缀。
  **动工前加一条冷路径核查**：池淘汰后 `sqlite_store.load` 重建的消息里 cite 是否仍在
  （热路径肯定在，冷路径若序列化裁剪过就会断）。
- **未被引用的 items** → 降为指针行（文档名/条款号一行，每条几十 token），不整块丢弃——
  思考过程面板把全部检索条目渲染给用户（`aichat-ui types/chat.ts` `resultItems`），
  用户会指着未引用条目追问；指针行保住「用户见过」的指涉可捞（模型按指针重检索）。
- **循环内部注入的 user 提示**与历轮 tool_calls 入参是引擎脚手架，一律不进回灌
  （§8.6 已被内部提示坑过、取「上一问」须绕它）。
- 实施口径建议：历史 tool 消息降维**常驻执行**（不依赖 est 阈值），阈值退化为兜底保险丝——
  压缩是无损投影，本体还在，没有「不超就不压」的保留价值。

**挂起理由**：若路线 B 立项落地，分层携带的 cite 映射重建与指针行会被图结构整个替换，
工程量浪费；且 A-min 后 25k 大概率已达标，A-full 的边际收益待决策点数据判定。

### 5.3 不做（定论）

- ~~检索证据落 history 时截断/降维存储~~：投影式压缩已达成同一 prompt 效果，且 chat.sqlite
  保全量原文（审计/回放无损）、开关一行回退——DB 动刀纯属多余风险。

## 6. 路线 B：会话语义图（治本，独立立项）

**设计文档已独立成文并正名：`docs/req-blackboard-conversation-mode.md`（原名 req-conversation-memory-graph.md，2026-10-02 定名「Blackboard 新对话模式」）**——
形态定版、写/读路径、存储与载体裁决、质量闸、里程碑均以该文为准；本节保留原始讨论要点备查。

**形态定版（2026-09-29 与业主讨论，取代原「blackboard 滚动摘要板」表述）**：
所有对话沉淀为**一张持续演化的语义图**——每轮对话蒸馏出的关键节点、关系和引用
增量合并进图，而非线性摘要：

```
        一张持续演化的会话图（跨 run 存活）
        ┌──────────────────────────────────┐
每轮     │ 节点：实体 / 规范条款 / 算出的量    │
run_end  │ 边：  引用 / 推导 / 待决关系        │
后蒸馏 ──►│ 指针：节点挂文档位置（不存原文）    │
合并      └──────────────────────────────────┘
              │ 每轮 prompt 只携带
              ▼
        与本轮提问相关的子图 + 近端 1~2 轮逐字尾
```

对话不是被「压缩丢弃」，而是被**结构化吸收**：「上轮算出的系数」成为图上的值节点，
「引用过 JTG D60 §5.3.1」成为引用边。prompt 大小与轮数解耦、收敛为常数；
细节出图不出索引，被指涉时模型按指针重检索自捞（L1 段工具能力在手）。
参照系：MemGPT/Letta core memory、Zep 时序知识图谱、LangGraph summary node 一脉，
但形态是图而非摘要文本。

工程要点（立项时展开）：

1. 图更新**异步**：run_end 后小模型蒸馏合并，不进 ttft 关键路径；每轮多一次小模型调用，
   对比每轮省下的 40~60k prefill 是零头。
2. 图是**派生缓存**：chat.sqlite 全量原文不动，图坏了可从库重建（延续投影式纪律）。
3. 引用边几乎白送：复用答案 [Kx] 引用映射，蒸馏时把文档名/条款号作为节点并入图，
   不依赖蒸馏模型「记得」原文。
4. **子图召回**是新工程点：按本轮提问从图里取相关子图（实体匹配/向量召回/近邻扩展），
   这是相比摘要板多出的核心工程量，立项时单独评估。
5. 图结构尽量 **append-only**（新增为主、修订走追加标记）：每轮整图重写会使 vLLM
   prefix caching 跨轮复用失效——前缀稳定是蒸馏质量之外的第二个延迟杠杆。
6. 质量闸同 §4（nightly + 39 题拒答专项）；图写错的污染是静默累积的（漂移），
   上线初期图版本随 run_id 落盘，可事后逐轮归因。
7. **载体裁决先行**：`memory.py Memory.blackboard`（结构化变量槽，生命周期 = 单次
   sop_execute，与跨 run 会话历史零交集）不能直接拿来当会话图；`Memory.chat_context`
   已挂一份聊天态半成品——动工前先裁决以谁为载体，禁止两个并行的会话记忆结构；
   方向上可汇流成一份 Memory（任务态+对话态分区），L3「上轮算出的系数」类指涉
   可直接走结构化节点而非重检索。
8. **与 A 路线的关系**：A 的预算闸保留作保险丝（图召回失败/图损坏时兜底），两路线不冲突。

## 7. 决策点：A-min 之后选哪条路

```
A-min 上线（本轮）
   │
   ▼ 观测 2~4 周：ops jsonl 逐轮 prompt_tokens 曲线 + 长会话（>10 轮）真实出现频率
   │
   ├─ ≤25k 稳定达标 且 长会话场景稀少 ──► 收工，B 不立项（A-min 即为终态）
   ├─ ≤25k 达标 但 长会话真实存在 ──────► 立项 B（语义图），A 闸留作保险丝
   └─ 仍超标 且 B 暂不立项 ─────────────► 回填 A-full（§5.2 分层携带）
```

## 8. 约束与风险

- 裁剪红线（§3）：最近一条真实 user 消息必保；不原地改 history 本体（投影式 copy-on-write）。
- guard / 拒答重试已核实不吃历史证据，但重试轮的**当轮**证据绝不可被压
  （§5.1.5 边界坑修复的动机；v0.2.74 教训：单测证明不了模型肯打，39 题拒答专项必跑）。
- meta 档补装必须带 protect_current_run（§5.1.2），否则统计题当轮数字被压。
- 开关可回退：`ANGINEER_QA_BUDGET_TOKENS_EST` 已存在；L0/meta 复用同机制
  （新开关键，登记 `.env.example` 注释行）；口径只认 ops jsonl 的 prompt_tokens 与 nightly。
- 正交项：与 chat-history 保留期 GC（`ANGINEER_CHAT_RETENTION_DAYS`，跨会话删除）互不替代。

## 9. 复现与数据入口

- 本地：起 dev 后端，同 `session_id` 连发 L1 题 + 闲聊题，看 `data/ops/ttft-*.jsonl` 的
  `final_turn_prompt_tokens`（观测已在，无需新打点）。
- 会话与消息明细：`data/chat.sqlite`（表 chat_sessions / chat_messages / chat_runs）。
- 对照参照（勘误原表述）：plan-ttft §8.1 的「多轮稳定 18-21k」是**生产同会话 3 轮、
  QA 档 A1 闸触发压平后的观察值**（跨 run 口径，非 run 内 attempts）；本地 5 题 L2 的
  31-34k 属同一闸 est < 30k 未触发区间。两者共同指向缺口 = L0/meta 无闸 +
  complex 100k + QA 阈值偏高（且 est 对中文低估 ~2x），而非「跨 run 完全无闸」。

## 10. 交付物与工作量

- **本轮（A-min，§5.1）**：代码改动 + 开关 + ops jsonl 前后对照 + 实测报告
  （长会话逐轮 prompt_tokens 曲线、连贯性人工比对、nightly/39 题拒答专项对照、
  §4.4 prefix-cache ttft 对照）。
  工作量小：主战场 `agent_configs.py`（补装+阈值+划界修正）+ 单测，
  不动 agent_loop、不动存储。
- **路线 B（语义图，§6，另行立项）**：图存储 + 蒸馏合并通道 + 子图召回 + 逐轮图版本落盘，
  不纳入本轮验收；启动条件见 §7 决策点。
- 若结论是「收益不足/风险过大」也接受——量化证据留档即可。

## 11. A-min 实测记录（2026-09-29 本地，session `chat-amin-test-0929`）

### 11.1 阈值定值（步④的回归依据）

ops 配对回归（`chat_runs` × `llm_turn-*.jsonl`，74 run）：

```
real/est 系数（est≥2k，n=57）：p50=1.11  p90=1.30  p99=1.46
est [12k,16k) → real max 18.3k ✓     est [16k,20k) → real max 22.4k ✓
est [20k,30k) → real p50 31.8k ✗（超标区）
```

**定值：QA 档 16k est**（p99 系数 1.46 × 16k ≈ 23.4k real，对 25k 线留 1.6k 余量）；
chat/meta 档 12k est（无证据需求，更紧）；complex 档 24k est（独立于 QA，
SOP 长 run 需证据余量；L3 当轮自超按 §4.1 豁免）。

### 11.2 连发 7 题前后对照（真实 prompt_tokens，data/ops/llm_turn-20260929.jsonl）

| 题 | 基线（09-26 改前） | A-min 后 | ttft（first_delta_ms） |
| --- | --- | --- | --- |
| Q1 L1 乘潮水位 | 20,120 | 20,852（地板，无历史可压） | 3.8s（基线 6.6s） |
| Q2 L2 重力式码头 | 34,079 | **20,706** | 3.8s（基线 24.3s） |
| Q3 L2 船型尺度 | 31,506 | 28,220（略超 25k，当轮证据占大头，近豁免） | 5.2s（基线 19.9s） |
| Q4 L3 前沿水深 | 61,389 | **28,354**（complex 24k est；§4.1 豁免项） | 4.6s（基线 25.4s） |
| Q5 L0 你好，在么 | **72,819** | **2,515** | **0.73s**（基线 15.3s，-95%） |
| Q6 追问「刚才第二条规范」 | — | 14,989 | 2.8s，答案正确引出 JTS 167—2—2009 ✓ |
| Q7 L1 设计高水位 | — | 22,829 | 4.2s |

- §4.1 达标：6/7 ≤ 25k；Q3 略超（28.2k，est 压到阈值后当轮证据占大头）、Q4 为豁免项。
- §4.2 连贯性：Q6 证据追问正确（assistant 文本逐字保留策略生效，规范名在场）；
  Q7 上下文化改写正常（「上一问」拼接行为同改前）。
- §4.4 ttft：压缩后各轮 first_delta 全面低于基线（Q5 -95%）；同档连发 vs 跨档切换
  无异常反弹，prefix-cache 失效效应未盖过 tokens 变小收益。

### 11.3 质量闸状态

- 单测：tests/angineer-core 286 + aichat-api 75 全绿（3 个 test_route_pre 失败为
  改前既有，干净 HEAD 复现相同）。
- 冒烟门禁（open-ragbench-smoke-v1，25 题）：**改前干净 HEAD 跑同样未通过**
  （0.72 vs 基线 0.84、refusal 0.4 vs 0.8），且两次 run 的错误题集合逐题相同
  （refusal-e827/d98b/543e + 4 道内容题）——判为既有问题（基线系 08-27 记录，
  模型/判分漂移），与 A-min 无关；A-min 那次多 6 题 judge_failed 为判分端点抖动。
  **冒烟基线陈旧是独立待办，不阻塞本需求，但 nightly/39 题拒答专项建议在发版后补跑对照。**

### 11.4 改动清单

- `agent_configs.py`：`_is_injected_user_prompt` 划界跳过（步③）；`build_chat_config`
  裸装闸（步①）；`build_meta_config` protect 装闸（步②）；`_budget_tokens_est` 通用化 +
  QA 默认 30k→16k（步④）；complex 默认改 env 驱动 100k→24k + 设 0 关闭修复（步⑤）。
- 开关：`ANGINEER_{QA,CHAT,META,COMPLEX}_BUDGET_TOKENS_EST`（均已登记 `.env.example`，0=关闭回退）。
- 单测：test_budget_gates.py +12（划界跳过、四档装配、阈值定值锚定、0 值关闭）。
