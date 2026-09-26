# 需求：长会话历史膨胀治理（闲聊 73k prompt 之痛）

> 状态：**根因已逐条代码核实、§5 前置核查已闭环（2026-09-26），待认领实施**。
> 发现于 2026-09-26 意图分类提速本地验收期间（同日已立
> `docs/req-table-retrieval-latency.md`，彼为本需求的前置观测来源之一）。
> 观测数据入口已就绪（data/ops/ttft-*.jsonl），认领即可量化。

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

**不做（原 §5.2「落库降维」裁撤，2026-09-26 核实后定论）：**

- ~~检索证据落 history 时截断/降维存储~~：A1 投影式压缩已达成同一 prompt 效果，
  且 chat.sqlite 保全量原文（审计/回放无损）、开关一行回退——DB 动刀纯属多余风险
  （v0.2.74「单测证明不了模型肯打」类风险一律不碰落库路径）。

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
- 工作量评估：小。主战场 `agent_configs.py`（补装+阈值+划界修正）+ 单测 +
  ops jsonl 前后对照，不动 agent_loop、不动存储。
