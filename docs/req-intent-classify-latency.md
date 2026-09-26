# 需求：意图分类提速（TTFT 最后一块硬骨头）

> 状态：待认领（2026-09-26 已完成六方向核对 + Jev/Laya 替换方案 101 题实测，见 §8；主线建议 = 方向②并行化）。
> 关联计划 `docs/plan-ttft-improvement.md`（§8 尾巴），此前搁置原因「等 Jev 进展」——已在 §8 收口。
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
2. 分类耗时：中位数 ≤1.5s。**口径修正（2026-09-26）**：`[意图分类] (耗时: X.XX秒)` 这一字面量在当前源码中不存在；可用锚点 = `ai_inference.llm_client` 的 `[输出响应] (耗时: ...)`（紧邻 `[DEBUG-SOP-ROUTE] LLM 意图分类成功` 之前），或由交付物在分类路径新增显式打点（后者为准）。
3. **无路由劣化**：nightly 整体准确率不低于当前基线（v0.2.77 首跑 86.9%，基线 84.9%）；`eval_question.intent_level` 为 gold，可在评测口径里对比路由命中的 `intent_level`。
4. 新增行为有开关，默认值经生产实测后再定。

## 4. 复现与数据入口

- 生产 TTFT：`docker logs angineer-aichat-api 2>&1 | grep "agent run TTFT"`。**修正（2026-09-26）**：生产 `logs/backend.log` 已不存在（`/home/runner/AnGIneer/logs/` 为空、容器内亦无；09-26 容器重建后旧日志随旧容器丢弃），`docker logs` 只覆盖当前实例——验收报告类观测应落盘到 `data/` 随卷留存，不能只依赖容器日志。
- 分类耗时：锚点见 §3.2；路由标签 `[DEBUG-SOP-ROUTE] LLM意图分类结果: {...}` 仍有效。
- 评测基线：生产机 `/home/runner/AnGIneer/data/evals/evals.sqlite`（表 `eval_run` / `eval_run_detail`），基线指针 `data/evals/baseline/baseline_run.json`。**注意**：`eval_question` 全部 2156 题 `intent_level=L1`（open-ragbench 英文学术 QA）——它只能验证「L1 题是否被正确路由」，L2/L3/L4 判别力需构造边界题集（§8 的 101 题集可复用）。

## 5. 建议方向（2026-09-26 逐条核对后的勘误版；实测证据见 §8）

1. **分类结果缓存**：query 归一化后进程内 LRU（可选持久化）。生产重复问占比仍未量，收益存疑，保留观察。
2. **分类与首轮检索并行** ⬅ **推荐主线（§8.1）**：L1/L2 都已是 `force_first_search=True` 首轮直达注入，只差按 scene/规则默认乐观发起 knowledge_search 的预热复用；分类结果仍一票决定走哪段，路由正确性零风险，猜错代价仅多一次检索（~0.5s 级）。检索预热有先例（a03984f）。
3. **扩大规则快路径**：新增实测靶子——现行 35B 把 4 条「应符合哪条规范 / 在哪条规范里 / 抗滑稳定性验算应符合哪条」类**条款号题**漏成 L1；此类 pattern 可规则直达 L2（须过路由专项）。
4. ~~给分类换更快模型 / 降 max_tokens~~ **勘误（实测反转）**：生产双 config 基准 Qwen3.6-35B-A3B p50 1.12s **快于** Qwen3.8-Flash-Next p50 2.82s，默认档已是更快的一档，无第三端点；分类耗时 1.1~4.9s 的波动来自负载（空闲态 p50 已达 1.5s 目标线），换模型/降 max_tokens 治不了。
5. ~~缩短分类 prompt（60 条 SOP 全量注入）~~ **勘误（前提错误）**：分类 LLM 调用用固定模板 `CLASSIFY_INTENT_SYSTEM_PROMPT`（~1600 字符），**从不注入 SOP**（SOP 只进 `route()` 精排，不在 TTFT 路径）；压缩模板剩余空间仅 ~0.1-0.3s prefill，还要过 prompt 专项，不划算。
6. **SOP 加载缓存**：实测坐实且比预期糟——每请求 ~47ms（开发机热缓存），且因部分 SOP blackboard=None 触发 `refresh_index()` **每次重写 index.json**（含 raw/ markdown 全量重解析）= 每请求一次磁盘写。值得修，量级 0.05~0.2s。

## 6. 约束与风险（重要）

- **不许为了快牺牲路由正确性**：分类错一位（L1↔L2/L4）会换错注入工具、换错段，nightly 整体会掉。
- **prompt 改动必须先过专项验证再上**：v0.2.74 的教训是「单测只能证明令牌机器认得出，证明不了模型肯打」。分类 prompt 任何改动要先跑路由专项（对照 `eval_question.intent_level`）与 nightly 整体，再发版。
- **回退开关**：新增缓存/规则/模型切换都要能一键回退（env 开关，默认值发版时明确）。
- **口径纪律**：TTFT 只认 `agent run TTFT ... ttft_ms`（不含前端渲染）；别拿端到端墙钟顶替。

## 7. 交付物

- 代码改动 + 开关 + 复现脚本（若能顺手把「TTFT/分类耗时统计」做成一行命令更好）。
- 一份实测报告：改动前后 L1 注入轮 ttft_ms 分布（≥5 轮）、分类耗时分布、nightly 整体与路由对照结果。
- 若结论是「收益不足/风险过大」也接受——把量化证据留下即可，避免下一个人重复踩。

## 8. 替换方案实测结论（2026-09-26，「等 Jev 进展」收口）

**同 101 题三方对照**（40 题真金 = eval_question L1 抽样 + 61 题构造全层级边界题，gold 按分类法 v3 定义标注；
路由准确率按 `build_attempts` 实际优先级派生；题集与原始结果存开发机 `D:\AI\laya-eval\`，可复跑可扩展）：

| 系统 | 路由准确率（全口径） | 生产可比口径¹ | 延迟 p50/p90/max | 部署形态 |
| --- | --- | --- | --- | --- |
| 现行 Qwen3.6-35B（生产分类器） | 90/101 = 89% | **94.7%** | 1.22s / 1.54s / 2.56s | 网关→DGX |
| Jev（jev-latest，托管 API） | 94/101 = 93% | 92.6% | 1.18s / 3.21s / **25.6s** + 1 次调用失败 | 海外 API，无自托管 |
| laya-multilingual（本机 643MB CPU） | 32/101 = 32% | 29.5% | 0.58s / 0.71s / 0.79s | Apache 2.0 可自托管 |

¹ L0 闲聊由前置规则拦截、不进分类模型，剔除 6 题 L0 后比较。

**分系统结论**：

- **Jev**：中文工程域能打（level 96%，含统计词陷阱/英文题全对），但生产口径反输现役 2pp（其全口径优势纯属 L0 红利）；
  延迟长尾 25.6s 且与请求大小无关（跨境 RTT + early access 服务抖动），设 2s 超时约四成调用落兜底。
  **复评触发条件：亚太接入点 / 开源权重 / 部署形态变化，任一满足再测。**
- **Laya**：路由准确率低于「全判 L1」的躺平基线（55%）——模型卡自认弱点（multilingual 版 typed-decisions
  zero-shot 0.342 近随机）实测应验，误判呈系统性偏向（L1→complex ×33、L1→meta ×18）。
  翻案条件 = 用其公开的 RLCD 配方在自建标注集上微调（标注工程，非替换）；生产机 3G 内存也放不下 fp32 权重（ONNX int8 或升配是前提）。
- **无 drop-in 替换者**。主线维持方向②并行化，叠加方向⑥顺手修与方向③规则靶子。
- **收益修正（同日复核，推翻早先「约 3~4s」的粗估）**：并行化的本质收益 = 把检索段移出关键路径，
  TTFT 变为 **max(分类, 检索) + 答案首字**——只稳赚 min(分类, 检索) ≈ 0.5s。空闲态（分类 1.2s）≈ 3.2s 达标；
  **负载态（分类 4.5s）≈ 6.5s 未必达标**，分类波动一毫秒没少。彻底治负载波动只有把分类本身变快：
  自训小分类器（蒸馏，50ms 级）或规则快路径扩覆盖——两者应与并行化同批推进，而非留作二期。
  进取变体「投机生成」（用乐观 L1 证据提前算答案 prefill，分类返回后放行或丢弃）可把负载态压到 ≈4.5~5s，
  代价是误路由（~5-10%）浪费一次 prefill + SSE 缓冲复杂度，作开关可选项。

**前提复核（顺带核实）**：生产两端点均经 angineer.cn 网关，ec2c17b（09-06）起隐式注入 `enable_thinking=False`——
09-25 实测的分类 2.40~4.89s 与思考 token 无关，是 35B 的负载波动；本表 p50 1.22s 与 §5.4 基准 1.12s 互证。
