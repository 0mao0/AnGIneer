# 需求：长会话历史膨胀治理（闲聊 73k prompt 之痛）

> 状态：**根因已逐条代码核实、§5 前置核查已闭环（2026-09-26），待认领实施**。
> 发现于 2026-09-26 意图分类提速本地验收期间（同日已立
> `docs/req-table-retrieval-latency.md`，彼为本需求的前置观测来源之一）。
> 观测数据入口已就绪（data/ops/ttft-*.jsonl），认领即可量化。
> 2026-09-27 与业主讨论收敛方案形态：一期=分层压缩（§5 做 1~5），
> 二期=blackboard 滚动语义板（§5 远期方向），两期独立实施。

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
实测数字与闸状态完全咬合）：

1. **历史无闸进 prompt，主路径是内存累积而非 DB 回灌**：池 TTL 2h（`chat_agent.py:20`），
   同会话连发根本不触发回灌；真正的雪球是 `agent_session.py:57-63` 把**累积的
   `session.history` 本体**（含此前每轮的全量检索证据 tool 消息）整个传进 `run_agent_loop`，
   池命中照样膨胀。冷路径（池淘汰/重启后）`sqlite_store.load`（`sqlite_store.py:185`）
   同样全量 SELECT 无预算。
   **推论：只在 store.load 装闸不满足验收——修刀位置必须在 LLM prompt 组装层
   （transform_context），热/冷路径统一覆盖。**
2. **证据全文驻留 history**：run_end 落库切片含 role=tool 全量检索 JSON（`main.py:457` persist）；
   `agent_messages.py:230-244` 每次调用把 tool content 原文序列化进 prompt，逐轮累乘。
3. **闸覆盖残缺**：A1 闸（plan-ttft §3，`make_budget_transformer`，投影式）只装了 QA 档
   （`agent_configs.py:351-355`，默认 30k est）；**L0 `build_chat_config`（:199-216）与
   meta `build_meta_config`（:219-240）根本没装 transform_context**；complex 档
   100k est / stopper 120k（:472-473,589）对 QA 场景形同虚设。

伤害：延迟（大 prompt prefill 直线放大 ttft，Q5 的 15s 几乎全是 prefill）+ 成本（每轮
input tokens × 每请求）+ 检索证据在闲聊轮纯属浪费。

## 2. 目标

- **主目标**：同会话第 5+ 轮的 run prompt tokens ≤ 25k。
- **分解目标**：闲聊轮（L0）不携带历史检索证据；任意单轮 prompt 不随历史轮数无界增长。

## 3. 前置核查：enforce_evidence 不吃历史（2026-09-26 闭环，原「动刀前必须核实」项）

```
全部引擎判定 → 只扫当前 run/attempt 切片
├─ _tool_evidence_present / _tool_evidence_parts → messages[attempt_start_idx:]（agent_loop.py:781,787）
├─ final_answer_guard → messages[start_idx:]（agent_loop.py:844-851）
├─ success_check → added = messages[start_idx:]
└─ [Kx] 引用标记 → marker_allocator 每 run 独立分配

真正依赖历史的只有两处（裁剪红线）：
├─ _latest_user_query 全表倒扫 → 代检索/§8.6 改写取「上一问」→ 最近一条 user 必须保留
└─ run_end persist 返回 history[start_idx:] 切片 → 不能原地裁 history 本体（A1 投影式教训）
```

**推论：历史证据可放心降维成一行摘要，引擎判定零影响。**

## 4. 验收标准

1. 本地同会话连发 ≥6 题（混合 L1/L2/L0），ops jsonl 逐轮 prompt_tokens ≤ 25k。
2. **连贯性不劣化**：跟进式追问（§8.6 上下文化改写依赖上一问）与证据追问（「刚才第二条规范说什么」）
   人工比对不回退；nightly 整体不低于基线。
3. 新增行为有开关，默认值经实测后再定。

## 5. 实施方向（2026-09-26 核实后重排：本质是「A1 扩装+收紧」，不是新造轮子）

**做（按性价比排）：**

1. **L0(chat)/meta 档补装投影式 transformer** ← 性价比最高，Q5 从 73k 掉到 ~5k
   （L0 无工具无证据，prompt 只剩 system + 历史文本 + 历史摘要）。
2. **QA 档阈值收紧**：30k est 起步改 ~12k est（按 plan-ttft「中文 1 字≈1 token」换算
   ≈ 真实 24k）。注意 est（chars//2）与真实 token 的换算系数随文本形态浮动，
   **定值以 ops jsonl 实测标定**（验收只认真实 prompt_tokens ≤ 25k，est 只是实现侧旋钮）。
   Q1 地板 20.1k（当轮证据硬需求），历史压一行摘要后第 6 轮 ≈ 21-23k，可达成但紧；
   若个别题仍超，把旧 assistant 长答案也纳入压缩对象（现闸只压 tool 消息）。
3. **complex 档 100k est 重估**（L3 是 Q4 61k 的成因），对齐或独立于 QA 档新阈值。
4. **顺手修 A1 现存边界坑**：`protect_current_run` 以「最后一条 user 消息」为当轮边界
   （`agent_configs.py:419-431`），但 run 内 retry / 代检索会**注入内部 user 提示**
   （`agent_loop.py:746,769`）使边界后移，当轮已产出的证据反而落入可压区——
   超阈值会话里重试轮拿不到证据作答。应改用 run 起点划界，或跳过
   `_INJECTED_USER_PROMPTS` 前缀的内部提示。
5. **携带分层细化（投影侧策略升级，仍是 transformer 内实现）**：「历史证据全压成
   一行摘要」太粗——20 段证据里被答案引用的通常只有 1~5 段。按指涉价值分层：
   - **未被引用的 items 整块不进回灌**（73k 的大头就此归零，用户没看过、模型没用它
     推理，后续轮用不到）；
   - **上一轮答案实际引用过的证据**保留自描述摘要（「[上轮引用] JTG D60 第5.3.1条：
     首 200 字…」），防「刚才第二条规范说什么」类证据追问失忆。引用集判定复用
     答案文本的 [Kx] 标记解析（marker_allocator 映射现成，不新造）；[Kx] 编号每 run
     独立分配会跨轮撞号，故摘要必须自描述或重编号加轮次前缀；
   - **循环内部注入的 user 提示**（`agent_loop.py:746,769`）与历轮 tool_calls 入参
     是引擎脚手架，一律不进回灌（§8.6 已被内部提示坑过、取「上一问」须绕它）。
   做完 1~5 后预算闸退化为兜底保险丝，而不是主力手段。

**不做（原 §5.2「落库降维」裁撤，2026-09-26 核实后定论）：**

- ~~检索证据落 history 时截断/降维存储~~：A1 投影式压缩已达成同一 prompt 效果，
  且 chat.sqlite 保全量原文（审计/回放无损）、开关一行回退——DB 动刀纯属多余风险
  （v0.2.74「单测证明不了模型肯打」类风险一律不碰落库路径）。

**远期方向（二期）：blackboard——「越远的越薄」仍随轮数线性涨，终态是收敛为常数。**

agent 经典黑板模式（Hearsay-II 一脉；LLM 时代对应 MemGPT/Letta core memory、
LangGraph summary node、Claude Code auto-compact）：对话核心要义蒸馏成一块滚动语义板，
每轮只给「板 + 近端逐字尾 + 本次提问」，prompt 大小与轮数解耦、有上界。
但**纯「板+本次提问、历史记录全弃」不能照单实施**，两个硬伤都落在已付过学费的地方：

| 硬伤 | 场景 | 化解 |
| --- | --- | --- |
| 有损且损失不可预知 | 写板在第 N 轮末，当时不知道第 N+5 轮会指涉什么，被略过的细节永久出板 | 板必须含**指针清单**（历轮被引用的文档名/条款号，不存原文）——细节出板不出索引，指涉时模型重检索自捞（L1 段工具能力在手） |
| 逐字尾缺失 | §8.6 上下文化改写、代检索取「上一问」要求上一问逐字在场 | 保留最近 1~2 轮 user+assistant **逐字尾巴** |

终态每轮 prompt（大小 ≈ 常数）：

```
system（档位提示词 + 工具 schema）
+ blackboard（用户意图轨迹 / 被引规范指针清单 / 未决事项，run_end 后蒸馏合并）
+ 近端 1~2 轮逐字尾
+ 本次提问 + 本次全量证据（当轮不压，与 A1 protect_current_run 语义一致）
```

工程约定：

1. 板更新**异步**：run_end 后小模型蒸馏一次，不进 ttft 关键路径；每轮多一次小模型
   调用，对比每轮省下的 40~60k prefill 是零头。
2. 板是**派生缓存**：chat.sqlite 全量原文不动，板坏了可从库重建（延续 A1 投影式
   纪律——本体永不动）。
3. 指针清单几乎白送：复用答案 [Kx] 引用映射，蒸馏时把文档名/条款号并入板上，
   不依赖蒸馏模型「记得」原文。
4. 质量闸同 §4（nightly + 39 题拒答专项）；板写错的污染是静默累积的（漂移），
   故上线初期板版本随 run_id 落盘，可事后逐轮归因。
5. **与 SOP 黑板的关系（2026-09-28 核实现状）**：同属经典黑板架构，但非同一实例——
   `memory.py Memory.blackboard`（:41）是**结构化变量槽**，生命周期 = 单次 sop_execute
   （agent_policy 不传 memory → `sop_runner.py:58` 每次新建），与跨 run 会话历史零交集，
   不参与本需求的 token 膨胀、也不能直接拿来当会话板（形态不同：Dict[str,Any] 任务态 vs
   自然语言摘要+指针）。另注意 `Memory.chat_context`（:42,89）已挂一份聊天态半成品——
   **二期动工前先裁决以谁为载体**（扩 Memory 或独立板），禁止出现两个并行的会话记忆板；
   方向上二者可汇流成一份 Memory（任务态+对话态分区），届时 L3 计算题「上轮算出的系数」
   类指涉可直接走结构化槽而非重检索。

**正交项**：与 chat-history 保留期 GC（`ANGINEER_CHAT_RETENTION_DAYS`，跨会话删除）
互不替代。

## 6. 约束与风险

- 裁剪红线（§3）：最近一条真实 user 消息必保（§8.6 改写与代检索都靠它）；
  不原地改 history 本体（投影式 copy-on-write，A1 已立此规矩）。
- guard / 拒答重试已核实不吃历史证据，但重试轮的**当轮**证据绝不可被压
  （§5.4 边界坑修复的动机；v0.2.74 教训：单测证明不了模型肯打，39 题拒答专项必跑）。
- 开关可回退：`ANGINEER_QA_BUDGET_TOKENS_EST` 已存在；L0/meta 复用同机制
  （新开关键，登记 `.env.example` 注释行）；口径只认 ops jsonl 的 prompt_tokens 与 nightly。

## 7. 复现与数据入口

- 本地：起 dev 后端，同 `session_id` 连发 L1 题 + 闲聊题，看 `data/ops/ttft-*.jsonl` 的
  `final_turn_prompt_tokens`（观测已在，无需新打点）。
- 会话与消息明细：`data/chat.sqlite`（表 chat_sessions / chat_messages / chat_runs）。
- 对照参照（勘误原表述）：plan-ttft §8.1 的「多轮稳定 18-21k」是**生产同会话 3 轮、
  QA 档 A1 闸触发压平后的观察值**（跨 run 口径，非 run 内 attempts）；本地 5 题 L2 的
  31-34k 属同一闸 est < 30k 未触发区间。两者共同指向缺口 = L0/meta 无闸 +
  complex 100k + QA 阈值偏高，而非「跨 run 完全无闸」。

## 8. 交付物与工作量

- 代码改动 + 开关 + ops jsonl 前后对照。
- 实测报告：长会话逐轮 prompt_tokens 曲线、连贯性人工比对记录、nightly 对照
  （39 题拒答专项不得低于基线）。
- 若结论是「收益不足/风险过大」也接受——量化证据留档即可。
- **一期**（本轮交付，§5 做 1~5）：代码改动 + 开关 + ops jsonl 前后对照 +
  实测报告（长会话逐轮 prompt_tokens 曲线、连贯性人工比对、nightly/39 题对照）。
  工作量小：主战场 `agent_configs.py`（补装+阈值+划界修正+投影侧分层策略）+ 单测，
  不动 agent_loop、不动存储。
- **二期**（blackboard，另行立项）：蒸馏通道 + 板存储 + 逐轮板版本落盘，
  不纳入本轮验收；启动前需先确认一期收益边界（几十轮长会话真实存在与否）。
