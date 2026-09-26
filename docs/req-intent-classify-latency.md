# 需求：意图分类提速（TTFT 最后一块硬骨头）

> 状态：待认领。关联计划 `docs/plan-ttft-improvement.md`（§8 尾巴），此前搁置原因「等 Jev 进展」。
> 提出时间：2026-09-26。验收口径与约束见文末，**动 prompt 前必读「约束」一节**。

## 1. 背景与现状证据

生产问答 TTFT（首字时间）专项前四步完成后，多轮不增长已达标，但**单轮首字 ≤6s 的目标未达成，最好成绩 7.0s**。归因明确：**意图分类的 LLM 调用占 ~4.5s**，是剩余开销的大头。

证据（均为实测量级，非估算）：

| 项 | 数值 | 出处 |
| --- | --- | --- |
| L1 注入轮 TTFT（最好） | 7000ms（turns=1） | 生产 `logs/backend.log`：`agent run TTFT: run_id=... turns=1 ttft_ms=7000` |
| 分类 LLM 单次耗时 | 2.40s ~ 4.89s | `logs/backend.log`：`ai_inference.llm_client | [意图分类] (耗时: X.XX秒)` |
| 分类占单轮比例 | ~ 4.5 / 7.0 ≈ 六成 | 同上 |

调用链（生产实际路径，`route_pre_enabled()` 默认开）：

```
POST /api/chat/agent
  └─ main.py:382  route_pre_enabled() → route_request(..., classify=classify_intent_offloaded)
       └─ main.py:267  classify_intent_offloaded   # executor 线程，不阻塞 SSE 循环
            └─ main.py:262  _classify_intent_blocking
                 ├─ sop_loader.load_all()           # 每次请求都加载 SOP（60 条）
                 └─ IntentClassifier(sops).classify_intent(query, config_name, mode)
                      ├─ classifier.py:854  _check_l0_intent()  # 规则前置，仅覆盖 L0 闲聊
                      └─ LLM 调用（分类 prompt：services/angineer-core/src/angineer_core/prompts/classifier.py）
```

分类结果决定路由段（L0/L1/L2/L3/L4 → agent_policy.build_attempts），进而决定首轮直达注入用哪个工具（L1=knowledge_search、L2=table_search）。

## 2. 目标

- **主目标**：生产 L1 注入轮 `ttft_ms` 中位数 ≤ 6000ms（当前最好 7000ms）。
- **分解目标**：分类耗时 p50 ≤ 1500ms（日志口径），且不劣化路由正确性。
- **不追求**：SSE 首帧时间（等待文案已有分段进度，用户感知是另一回事）；本需求只优化「首个正文 token」。

## 3. 验收标准

1. 生产同会话实测：连续 ≥5 轮 L1 注入轮 `ttft_ms` 中位数 ≤6000ms（口径见「复现」）。
2. 分类耗时：`[意图分类] (耗时: X.XX秒)` 中位数 ≤1.5s。
3. **无路由劣化**：nightly 整体准确率不低于当前基线（v0.2.77 首跑 86.9%，基线 84.9%）；`eval_question.intent_level` 为 gold，可在评测口径里对比路由命中的 `intent_level`。
4. 新增行为有开关，默认值经生产实测后再定。

## 4. 复现与数据入口

- 生产 TTFT：`docker logs angineer-aichat-api 2>&1 | grep "agent run TTFT"`（或 `logs/backend.log`，注意该文件混合 UTF-8/UTF-16LE 编码）。
- 分类耗时：同日志 grep `意图分类`（`[DEBUG-SOP-ROUTE]` 与 `ai_inference.llm_client` 两处）。
- 路由标签：日志 `[DEBUG-SOP-ROUTE] LLM意图分类结果: {... "intent_level": "L1" ...}`。
- 评测基线：生产机 `/home/runner/AnGIneer/data/evals/evals.sqlite`（表 `eval_run` / `eval_run_detail`），基线指针 `data/evals/baseline/baseline_run.json`。

## 5. 建议方向（不限定，需自行论证取舍）

按「改动成本 × 收益」粗排，留作起点：

1. **分类结果缓存**：query 归一化后进程内 LRU（可选持久化）。评估：生产重复问占比要先量，别假设。
2. **分类与首轮检索并行**：注入当前依赖分类结果决定工具（L1/L2）。可探索「先按 scene/规则默认跑 knowledge_search，分类返回后再决定是否补 table_search」——但要注意别把两段检索的成本压回来。
3. **扩大规则快路径**：现仅有 L0 闲聊规则（`_check_l0_intent`）。明显的表格/条款题（含「表」「累积频率」「条款」等）可加规则直达 L2。
4. **给分类换更快模型 / 降 max_tokens**：分类输出极短，先量当前配置是否有浪费（`config_name` / `mode` 传递链）。
5. **缩短分类 prompt**：每次把 60 条 SOP 全量注入分类上下文是否必要？考虑按 query 向量召回 top-k SOP。
6. **SOP 加载缓存**：`sop_loader.load_all()` 每请求一次，先确认它是否有缓存与磁盘 IO 成本。

## 6. 约束与风险（重要）

- **不许为了快牺牲路由正确性**：分类错一位（L1↔L2/L4）会换错注入工具、换错段，nightly 整体会掉。
- **prompt 改动必须先过专项验证再上**：v0.2.74 的教训是「单测只能证明令牌机器认得出，证明不了模型肯打」。分类 prompt 任何改动要先跑路由专项（对照 `eval_question.intent_level`）与 nightly 整体，再发版。
- **回退开关**：新增缓存/规则/模型切换都要能一键回退（env 开关，默认值发版时明确）。
- **口径纪律**：TTFT 只认 `agent run TTFT ... ttft_ms`（不含前端渲染）；别拿端到端墙钟顶替。

## 7. 交付物

- 代码改动 + 开关 + 复现脚本（若能顺手把「TTFT/分类耗时统计」做成一行命令更好）。
- 一份实测报告：改动前后 L1 注入轮 ttft_ms 分布（≥5 轮）、分类耗时分布、nightly 整体与路由对照结果。
- 若结论是「收益不足/风险过大」也接受——把量化证据留下即可，避免下一个人重复踩。
