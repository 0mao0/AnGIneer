# 需求：长会话历史膨胀治理（闲聊 73k prompt 之痛）

> 状态：待认领。发现于 2026-09-26 意图分类提速本地验收期间（同日已立
> `docs/req-table-retrieval-latency.md`，彼为本需求的前置观测来源之一）。
> 观测数据入口已就绪（data/ops/ttft-*.jsonl），认领即可量化。

## 1. 背景与现状证据

**同一会话连发 5 题**（本地实测 2026-09-26，session `chat-mui9pfcm-qc6p86` 及复测会话），
逐题 `final_turn_prompt_tokens`（`data/ops/ttft-*.jsonl`）：

| 题序 | 问题 | prompt tokens | ttft_ms |
| --- | --- | --- | --- |
| 1 | 什么是乘潮水位？（L1） | 20,120 | 6625 |
| 2 | 重力式码头…应符合哪条规范要求？（L2） | 34,079 | 24327 |
| 3 | 依据《海港…》确定设计船型尺度（L2） | 31,506 | 19938 |
| 4 | 某5万吨级散货船…试计算码头前沿水深（L3） | 61,389 | 25390（turns=2） |
| 5 | **你好，在么（L0 闲聊）** | **60,364 / 复测 72,819** | **13719 / 15343** |

**闲聊一句「你好」背上 60~73k prompt、首字 15s**。根因画像（待认领人逐条核实）：

1. **会话跨 run 全量回灌**：chat_history `store.load` 把历史消息（含每轮注入的检索证据 tool 结果全文）
   无预算裁剪地拼进下一 run 的 messages——plan-ttft §8.1 的「多轮稳定 18-21k（A1 闸压平）」是
   **run 内 attempts 口径**，跨 run 的 session 载入没有对应闸。
2. **证据全文驻留 history**：role=tool 的检索结果（20 段证据 + 引用）整块留在消息流里，逐轮累乘。
3. **L0 闲聊档同样继承**：闲聊不需要旧证据，却照单全收。

伤害：延迟（大 prompt prefill 直线放大 ttft，Q5 的 15s 几乎全是 prefill）+ 成本（每轮 input tokens
× 每请求）+ 检索证据在闲聊轮纯属浪费。

## 2. 目标

- **主目标**：同会话第 5+ 轮的 run prompt tokens ≤ 25k（A1 闸口径从 run 内延伸到 session 载入）。
- **分解目标**：闲聊轮（L0）不携带历史检索证据；任意单轮 prompt 不随历史轮数无界增长。

## 3. 验收标准

1. 本地同会话连发 ≥6 题（混合 L1/L2/L0），ops jsonl 逐轮 prompt_tokens ≤ 25k。
2. **连贯性不劣化**：跟进式追问（§8.6 上下文化改写依赖上一问）与证据追问（「刚才第二条规范说什么」）
   人工比对不回退；nightly 整体不低于基线。
3. 新增行为有开关，默认值经实测后再定。

## 4. 复现与数据入口

- 本地：起 dev 后端，同 `session_id` 连发 L1 题 + 闲聊题，看 `data/ops/ttft-*.jsonl` 的
  `final_turn_prompt_tokens`（观测已在，无需新打点）。
- 会话与消息明细：`data/chat.sqlite`（表 chat_sessions / chat_messages / chat_runs）。
- 对照参照：plan-ttft §8.1「多轮 18-21k」为 run 内口径，勿混用。

## 5. 建议方向（按性价比排，需先核实可行性）

1. **session 载入预算闸**：`store.load` 后按 token 预算从新到旧保留窗口，更早轮次丢弃或仅保留
   user/assistant 正文（剥离 tool 结果块）。
2. **tool 结果降维入史**：检索证据落 history 时以截断/引用标记形态存储——**必须先查 enforce_evidence
   与引用校验是否依赖历史中的证据全文**（[Kx] 标记校验逻辑，动错会连环）。
3. **L0 闲聊档剥离历史**：闲聊档 config 不注入历史证据块（保留最近 1~2 轮对话即可）。
4. 与 chat-history 保留期 GC（`ANGINEER_CHAT_RETENTION_DAYS`，跨会话删除）正交，互不替代。

## 6. 约束与风险

- §8.6 跟进式改写依赖「上一问真实提问」——裁剪不得把最近一轮 user 消息裁掉。
- guard / 拒答重试逻辑若读取历史中的证据块，降维方案需先验证（v0.2.74 教训：单测证明不了模型肯打）。
- 开关可回退；口径只认 ops jsonl 的 prompt_tokens 与 nightly。

## 7. 交付物

- 代码改动 + 开关 + ops jsonl 前后对照。
- 实测报告：长会话逐轮 prompt_tokens 曲线、连贯性人工比对记录、nightly 对照。
- 若结论是「收益不足/风险过大」也接受——量化证据留档即可。
