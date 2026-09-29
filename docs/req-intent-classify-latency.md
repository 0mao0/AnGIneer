# 需求：意图分类提速（TTFT 最后一块硬骨头）

> 术语（2026-09-27 定版）：本文实现的「并行预热/检索预热」此后统一称**赌博式预检**（代码用 speculative：`fire_speculative_first_search` / `ANGINEER_SPECULATIVE_SKIP_TABLE`）；「预热」一词专留给进程启动灌缓存（FTS/向量/表格产物）。以下历史表述按原样保留。

> 状态：**主线已结题**（§8 六方向核对 + 101 题实测；v0.2.79 已上产，§9 生产验收 ttft 中位数 3204ms ≤6000ms 达标、分类 p50 1087ms 达标、并行开关定为开；§9.1 nightly 首跑排除回归 = §3.3 闭环）。
> 2026-09-29 追加 §10：专用意图识别测试集（100 题，L0-L4 分层）+ Intern-Decision「书生·明决」实测——
> 精度与现役 35B 不可区分、GPU 上 0.18s，判定不替换（理由与复评触发见 §10.6）。
> §10.8 该题集已产品化为 **intent-router-v1**（入库 + `intent` 评测器 + UI 可跑 + CLI，
> 3 次重跑 100% 逐题一致）。**服务器生效需部署 + 重导题集**。
> 关联计划 `docs/plan-ttft-improvement.md`（§8 尾巴；该计划文档 2026-09-29 已清理，git 历史可查），搁置原因「等 Jev 进展」——已在 §8 收口。
> 提出时间：2026-09-26。验收口径与约束见文末，**动 prompt 前必读「约束」一节**。

## 1. 背景与现状证据

生产问答 TTFT（首字时间）专项前四步完成后，多轮不增长已达标，但**单轮首字 ≤6s 的目标未达成，最好成绩 7.0s**。~~归因明确：意图分类的 LLM 调用占 ~4.5s，是剩余开销的大头。~~
**（2026-09-26 第三轮勘误：此归因不成立，见下方勘误块与 §8 收益修正。）**

证据（均为实测量级，非估算）：

| 项 | 数值 | 出处 |
| --- | --- | --- |
| L1 注入轮 TTFT（最好） | 7000ms（turns=1） | 生产 `logs/backend.log`：`agent run TTFT: run_id=... turns=1 ttft_ms=7000` |
| 分类 LLM 单次耗时 | 2.40s ~ 4.89s | `logs/backend.log`：`ai_inference.llm_client | [意图分类] (耗时: X.XX秒)` |
| ~~分类占单轮比例~~ | ~~~ 4.5 / 7.0 ≈ 六成~~ | **勘误：算术前提错误，见下** |

> **口径勘误（2026-09-26，实测钉死）**：`ttft_ms` 的计时起点在 agent 循环开始（`agent_loop.py:856`
> `run_started`），即**分类等待根本不在 ttft_ms 里面**——铁证：同题重测 ttft=1250ms < 分类耗时 2446ms。
> 因此「分类占 7.0s 六成」的算术前提错误；7.0s 的大头应重估为**检索链（含表格段 table= 10~28s，
> 已另立 `docs/req-table-retrieval-latency.md`）+ 20k 级 prompt prefill（+ 空答重试轮）**。
> 分类慢伤害的是 SSE 首帧前的白屏体感（用户侧首字 = 分类等待 + ttft_ms），不是 ttft_ms 指标本身。
> 本需求 P0 价值随之修正：条款号快路径 / SOP 缓存缩短 ttft 与体感；并行预热把检索段藏进分类等待
> （ttft 与体感双降）；分类本身的耗时优化（缓存/更快分类器）对 ttft_ms 无感、只改善体感。

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

### P0 开关清单（2026-09-26 落地，集中索引）

开关不写入 .env（全部有代码默认值，不设即按默认行为跑）；每条的完整语义在**定义处 docstring/注释**，
此处只作索引。生产改 .env 后必须 `cd docker && docker compose up -d <服务>` 重建容器（restart 不读新 env，09-25 实踩）。

| 开关 | 默认 | 作用 | 回退语义 | 定义位置 |
| --- | --- | --- | --- | --- |
| `ANGINEER_ROUTE_PARALLEL` | **true**（开；2026-09-26 生产 A/B 实测后定，发版时默认关） | 分类与首轮检索并行：请求进来即乐观预热 knowledge_search，分类返回后 L1 命中经检索 memo 单发复用，检索段移出关键路径 | =false 回纯串行（行为同改造前） | `route_pre.py::route_parallel_enabled` docstring + `agent_tools.py` memo 注释块 |
| `ANGINEER_CLAUSE_FASTPATH` | **true**（开） | 条款号问句（应符合/满足哪条规范、在哪条规范里）规则直达 L2 | =false 回 LLM 分类 | `classifier.py::_CLAUSE_NUMBER_PATTERN` 上方注释 |
| `ANGINEER_SOP_CACHE_TTL` | **300**（秒） | SOP 加载进程内缓存（mtime 信号失效），消灭每请求 ~47ms 全量重读 + index.json 重写 | =0 停用，回每请求全量重读旧路径 | `sop_loader.py::load_all` docstring |
| `ANGINEER_OPS_DISABLE` | 未设 = 开 | TTFT/分类耗时观测落盘总开关 | 设 1 停用落盘 | `ops_metrics.py` 模块 docstring |
| `ANGINEER_OPS_DIR` | `data/ops` | 观测 jsonl 目录覆盖 | — | 同上 |
| `ANGINEER_INJECT_FOLLOWUP_CHARS`（既有） | 15 | 短问跟进检索词改写阈值；并行预热在「短问**且**有上文」时跳过（首问短句不改写，照常预热） | — | agent_loop §8.6 既有定义 |

`.env.example` 已登记上述开关的注释行（2026-09-26）。ec2c17b（09-06）当时以「该文件为 GBK 乱码历史态」
为由不随开关更新，但 b44c03c（09-11）已将其重建为正常 UTF-8——该先例随修复失效，引用旧 commit 理由前先核实现状。

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

## 9. 生产验收结果（2026-09-26 晚，v0.2.79）

生产 A/B（同 5 题 L1、同会话模式、间隔 10 分钟、同为晚间网关负载；开关经 .env 切换）：

| 轮 | 基线 ttft（并行关） | 实测 ttft（并行开） | Δ | tool 段（检索） |
| --- | --- | --- | --- | --- |
| 1 乘潮水位 | 6055ms | 2568ms | -58% | 3286ms → 0ms（预热命中） |
| 2 设计低水位 | 5269ms | 3339ms | -37% | 1916ms → 0ms |
| 3 疏浚土分类 | 6258ms | 3204ms | -49% | 3060ms → 0ms |
| 4 抛石基床作用 | 7585ms | 4990ms | -34% | 2525ms → 0ms |
| 5 航道等级划分 | 4718ms | 2873ms | -39% | 1810ms → 0ms |
| **中位数** | **6055ms** | **3204ms** | **-47%** | **5/5 预热全命中** |

**验收判定**：

- §3.1 ✅ ttft 中位数 **3204ms ≤ 6000ms**（裕量 47%）；tool dur=0ms 即 memo 命中直接证据，证据量与基线逐字一致（prompt 16314 vs 16311）。
- §3.2 ✅ 分类耗时 p50 **1087ms ≤ 1500ms**（5 轮 1068~1506ms）。
- §3.3 ⏳ nightly 明晚 01:00 在 v0.2.79 上首跑，对照基线 84.9% 后闭环。
- §3.4 ✅ 开关默认值经生产 A/B 实测**定为「开」**（代码默认已翻转，生产 .env 已显式 =1）。

**遗留移交**：ttft 内部的 prefill 段（2.5~5s，晚间）与 Q3/Q4 的 33k/29k prompt（历史累积）属
`req-chat-history-bloat.md` 与 `req-table-retrieval-latency.md` 的管辖，不在本需求口径内。

### §9.1 nightly 首跑读数（2026-09-27，v0.2.79）

84.42%（878/1040，state=green；对钉版基线 84.90% 配对 delta -0.48pp，CI95 [-2.5, +1.5] 跨零不显著）；
对昨晚（v0.2.78）-2.50pp。**归因排查结论：非 v0.2.79 回归**——

- 检索层两晚逐字一致（text 行 hit@1 0.8615/MRR 0.9148 等全同）→ P0 动的分类/检索调度层排除；
- 逐题配对：对→错 48 / 错→对 22，翻转率 6.7%（低于 12% 噪声地板）；拒答分项 +1 题（48.7%→51.3% 变好）；
- 净 -26 题主体 = 生成抖动 × 严格 judge 的正常翻转（抽查翻转题：答案文本逐晚微变、judge 同模型 Qwen3.8-Flash-Next 两晚判分不同；1.00→0.00 极性翻转 8+ 例但答案确有实质差异）；
- 叠加判分口径自今晚起更严：nightly 判定四连修（删检索分兜底 + LaTeX 容错）随 v0.2.79 首发——方向是「测量更诚实」，非系统退化；
- 孤立缺陷 1 题：c8c8f25f 答案被 `</think>` 流式碎片污染（291KB）判 0 分（昨晚 0 题）——与 P0 无关，值 0.1pp，记录备查不立项。

## 10. 专用意图识别测试集（100 题）+ Intern-Decision「书生·明决」实测（2026-09-29）

上一节（§8）的 101 题集是临时拼的（40 真金 + 61 构造，L1 占 61%），只够回答「Jev/laya 能不能替」；
本节按业主 2026-09-29 要求把它升级为**专用意图识别测试集：100 题、L0-L4 分层覆盖、每题带陷阱族标签**，
并用它实测上海 AI 实验室新发布的决策模型 **Intern-Decision（书生·明决）**——
微信文章声称其 4B 在 JevBench 七项均分 90.02 超 Jev 88.74、单卡 4090 时延 33~44ms（比 Jev 快 2 倍以上）。

**Intern-Decision 是什么（实测确认，非转述）**：它不是聊天模型，而是**结构化决策器**——
输入 `state`（题干）+ `questions`（选项 schema：`choice`/`score`/`noul`），
**一次前向**输出每个字段在给定选项上的概率分布（取 placeholder 前一位的 logits 做 softmax，不走 `generate()`）。
权重 Apache-2.0 自托管（基座 Qwen3.5，`internlm/Intern-Decision-{0.8B,2B,4B}`），
接口与 laya-multilingual 同构，因此 §8 的评测脚本可直接复用。

### §10.1 题集设计

| 分层 | 题数 | route 桶 | 构成（陷阱族） |
| --- | --- | --- | --- |
| L0 闲聊 | 12 | L0 | 6 纯闲聊 + 6 歧义短语（「帮我」「你是谁呀」） |
| L1 正文语义 | 28 | L1 | 10 定义 + 6 统计词陷阱 + 3 礼貌前缀 + 3 概念对比 + 2 英文 + 4 真实生产题 |
| L1 meta_query | 10 | meta | 6 直白 + 4 换措辞（避开 few-shot 原句） |
| L2 条款/查表 | 22 | L2 | 10 查表取值 + 6 条款号问句 + 3 规范号 + 3 含数值但不计算 |
| L3 标准计算 | 16 | complex | 10 数值计算 + 3 考试选择题 + 3 单位/多参数 |
| L4 复杂任务 | 12 | complex | 6 方案设计/综合 + 4 多方案比选 + 2 多步复合 |

金标依据 = `prompts/classifier.py` v3 的层级表与关键规则 1–7 + `agent_policy.build_attempts` 的实际路由优先级
（route 桶派生：`casual_chat`→L0、`semantic_retrieval`→L1、`meta_query`→meta、`structured_lookup`→L2、
`standard_sop`/`dynamic_orchestration`→complex）。每题带 `family` 陷阱族标签，跑完可直接定位「哪类题在掉」。

**口径灰区（提前声明，勿当铁证）**：`L1_concept_compare` 3 题（「两者的区别/异同」）在分类法内部本就有张力——
`L1_KEYWORDS` 含「区别/异同/对比/比较」，而规则 5 写「多方案比较 = L4」。本集取
「只问区别 = L1、要求选型建议/方案论证 = L4」。**这 3 题的读法足以反转头名**（见 §10.6 敏感度），
后续用这套题集判定任何改动效应时，必须连带报这一项。

### §10.2 同题对照结果

| 系统 | level 准确 | mode 准确 | route 全口径 | route 生产可比¹ | 延迟 p50/p90/max |
| --- | --- | --- | --- | --- | --- |
| 规则层单独（无 LLM） | 78/100 | 75/100 | **77/100 (77%)** | 66/88 (75%) | — |
| 现役 Qwen3.6-35B 全链路 | 97/100 | 97/100 | **97/100 (97%)** | 86/88 (98%) | 2.86 / 9.12 / 24.16 s |
| laya-multilingual（同集复跑） | 52/100 | 39/100 | **43/100 (43%)** | 37/88 (42%) | 0.83 / 1.15 / 1.55 s |
| Intern-Decision 0.8B（简 criteria） | 94/100 | 91/100 | **91/100 (91%)** | 79/88 (90%) | 0.13 / 0.17 / 0.20 s |
| Intern-Decision 2B（简 criteria） | 95/100 | 87/100 | **93/100 (93%)** | 81/88 (92%) | 0.14 / 0.17 / 0.21 s |
| Intern-Decision 4B（简 criteria，CPU） | 95/100 | 92/100 | **93/100 (93%)** | 81/88 (92%) | 12.36 / 15.14 / 19.75 s |
| Intern-Decision 0.8B（完整 criteria） | 62/100 | 73/100 | **62/100 (62%)** | 50/88 (57%) | 0.15 / 0.21 / 0.29 s |
| Intern-Decision **2B（完整 criteria）** | 95/100 | 96/100 | **94/100 (94%)** | 82/88 (93%) | **0.18 / 0.20 / 0.26 s** |

¹ 生产可比 = 剔除 12 题 L0（生产链上 L0 由 `_check_l0_intent` 规则前置拦截，不进 LLM 分类器）。
² Intern-Decision 的 GPU 行 = 开发机 RTX 4070 Laptop 8G / bf16；CPU 行 = float32（4B 的 bf16 权重 9.1GB 装不进 8GB 显存，只能 CPU 跑）。
「简/完整 criteria」= 给模型的选项描述文本，见 §10.5——这是本次实测最容易被忽略、却决定成败的变量。
³ **「4B（完整 criteria）」这一格空着，不是漏填**：该跑在 CPU float32 下需 ~18GB 常驻，实测把开发机空闲内存
压到 1.9GB 并进入换页，45 分钟未跑完即中止（避免拖垮机器上的 dev 服务与其它任务）。
4B 的结论已由简 criteria 行 + 完整 criteria 下的 2B 充分支撑（4B 不比 2B 强），不再补跑。

**规则层单独 77/100 是重要基线**：现役 35B 的 97 里有 **24 题根本没进模型**（L0 规则 11 + meta 规则 7 +
条款号快路径 6，全对 24/24）；真正交给 LLM 的只有 76 题。隔离「换模型」效果只看这 76 题：

| 系统 | LLM 段 route 正确 | 该段延迟 p50 |
| --- | --- | --- |
| 现役 Qwen3.6-35B 全链路 | 73/76 (96%) | 3.55s |
| laya-multilingual | 31/76 (41%) | 0.86s |
| Intern-Decision 2B（简 criteria） | 69/76 (91%) | 0.14s |
| **Intern-Decision 2B（完整 criteria）** | **70/76 (92%)** | **0.18s** |
| Intern-Decision 4B（简 criteria，CPU） | 69/76 (91%) | 12.34s |

### §10.3 差距落在哪（分陷阱族）

| family | 规则层 | 35B | laya | 2B 简 | 2B 完整 | 0.8B 完整 |
| --- | --- | --- | --- | --- | --- | --- |
| L0_ambiguous (6) | 6/6 | 6/6 | 2/6 | 6/6 | 6/6 | 6/6 |
| L0_pure (6) | 5/6 | 5/6 | 4/6 | 6/6 | 6/6 | 6/6 |
| L1_def (10) | 10/10 | 10/10 | 1/10 | 10/10 | 10/10 | **0/10** |
| **L1_trap_stat (6)** | 3/6 | **6/6** | 0/6 | **0/6** | **5/6** | 0/6 |
| L1_concept_compare (3) | 3/3 | 3/3 | 0/3 | 3/3 | **0/3** | **0/3** |
| L1_politeness (3) | 3/3 | 3/3 | 0/3 | 3/3 | 3/3 | 0/3 |
| L1_english (2) | 2/2 | 2/2 | 0/2 | 2/2 | 2/2 | 0/2 |
| L1_real (4) | 4/4 | 4/4 | 0/4 | 4/4 | 3/4 | 0/4 |
| L2_lookup (10) | 6/10 | 8/10 | 2/10 | 10/10 | 10/10 | 10/10 |
| **L2_trap_noncalc (3)** | **0/3** | 3/3 | 1/3 | 3/3 | 3/3 | 3/3 |
| L2_clause_number (6) | 6/6 | 6/6 | 1/6 | 6/6 | 6/6 | 6/6 |
| L2_stdcode (3) | 3/3 | 3/3 | 0/3 | 3/3 | 3/3 | 3/3 |
| L3_calc / L3_mcq / L3_units (16) | 16/16 | 16/16 | 13/16 | 16/16 | 16/16 | 16/16 |
| L4_design / L4_multi (8) | 2/8 | 8/8 | 8/8 | 8/8 | 8/8 | 8/8 |
| **L4_compare (4)** | **1/4** | 4/4 | 3/4 | 3/4 | 4/4 | 4/4 |
| meta_direct / meta_rephrase (10) | 7/10 | 10/10 | 8/10 | 10/10 | 9/10 | **0/10** |

三处最有信息量的读法：

1. **`L1_trap_stat` 是提示词问题，不是模型问题**：简 criteria 下 2B/4B 对该族 **0/6**（把「某星表的中位红移」
   判成 meta/L2），把生产 prompt 的规则 7 原文抄进 criteria 后 2B 回到 **5/6**。同一模型、同一权重，只换选项描述。
   → 结论：拿 Intern-Decision 替换前，**必须先把生产分类法的边界规则完整搬进 criteria**，否则等于用半截 prompt 比。
2. **0.8B 反向塌陷**：完整 criteria 下它整体掉到 62/100，输出里**一条 L1 都没有**（46/100 判成 L0，L1_def 0/10、
   meta 0/10）——长选项定义超出 0.8B 的指令服从能力。它只在极简 schema 下可用，而极简 schema 下它又丢掉陷阱族。
3. **4B 不比 2B 强**：简 criteria 下 2B 与 4B 都是 93；完整 criteria 下 2B 94。加上 4B 的 bf16 权重 9.1GB
   装不进 8GB 显存（只能 CPU 12s/次），**性价比拐点在 2B**。

### §10.4 延迟与部署形态

| 口径 | p50 | p90 | max |
| --- | --- | --- | --- |
| 现役 Qwen3.6-35B（经 angineer.cn 网关） | 2.86 s | 9.12 s | **24.16 s** |
| Intern-Decision 2B，CPU float32（无 GPU） | 4.90 s | 5.18 s | 5.44 s |
| **Intern-Decision 2B，RTX 4070 8G / bf16** | **0.18 s** | **0.20 s** | **0.26 s** |
| Intern-Decision 0.8B，RTX 4070 8G / bf16 | 0.15 s | 0.21 s | 0.29 s |

- GPU 路径比现役快 **约 16 倍**，且**无长尾**（max 0.26s vs 35B 的 24.16s）——现役那条 p90 9.1s / max 24.2s
  的长尾与 §8 记的 Jev 25.6s 同源（跨境/网关抖动），是白屏体感的主要来源。
- **CPU-only 部署没有价值**：2B 在 CPU float32 上是 4.9s，比现役还慢——这条路必须带 GPU。
- **dtype 不是本轮差异来源**（逐题核对）：2B 同一 criteria 下 CPU float32 与 GPU bf16 的 level 判定
  **逐题全同（0/100 不同）**，仅 mode 有 2/100 不同；0.8B 的 level 也只有 1/100 不同。
  因此上表的 CPU/GPU 差异可归因于硬件与 dtypes 之外的因素，**精度结论不因换精度而变**。

### §10.5 口径警告：criteria 信息量决定成败

Intern-Decision 的接口要求把候选选项连描述一起给模型（`choice` + `criteria`），
所以「给多少定义」直接决定成绩。首轮（简 criteria）只给了一句话定义，**缺**生产 prompt 的两条边界规则——
规则 7（统计词陷阱）与规则 3/规则 5（查表取值 ≠ 计算、问区别 ≠ 方案比选）；
而 35B 基线拿的是完整生产 prompt。这属于口径不对称，已补第二轮完整 criteria 重跑。
**今后任何用这套题集做的对照，必须声明 criteria 版本**，否则两轮数字不可比。

### §10.6 结论

| 维度 | 判定 |
| --- | --- |
| 精度 | **不可区分**：主金标 35B 97 vs 2B 94；把 §10.1 的 3 题灰区改判 L4 后 35B **94** vs 2B **97**（2B 反超）。差距 ≤3 题 < 金标读法摆动（±3 题） |
| 延迟 | 2B 自托管在 8G 显卡上 0.18s p50、无长尾，比现役快一个数量级 |
| 对 ttft 的价值 | **不适用**——按 §8 口径勘误与 §9 实测，分类等待不在 `ttft_ms` 里（并行赌博式预检已把检索段藏进分类等待）。2B 的收益是 **SSE 首帧白屏时间**（用户侧首字 = 分类等待 + ttft），不是 ttft 指标 |
| 建议 | **不替换，登记为可选项**：精度不可区分 ⇒ 替换零收益却新增自托管依赖；且需服务器有可支配 GPU（腾讯云部署机是否有闲置显卡未核实） |
| 复评触发 | ① 部署机有闲置 GPU 且分类延迟重新进入关键路径；② Intern-Decision 出中文工程域继续预训练版本；③ 需要「分类器冗余/降级」时（网关挂掉时用本地 2B 顶上） |

**对题集本身的价值**：这套 100 题第一次把「替换方案评测」从临时拼盘变成可复跑的分层工具——
它独立抓出了三件现役链路的既有事实：规则层单独只有 77%（`L2_trap_noncalc` 0/3、`L4_compare` 1/4 是规则短板）、
现役 97% 里 24 题是规则拿的、以及 35B 在 `L2_lookup` 漏 2 题（§5.3 靶子的邻域）。

### §10.7 复现入口

| 项 | 路径 / 命令 |
| --- | --- |
| 题集（开发机原始版） | `D:\AI\intern-decision\cases100.json`（含 gold_level / gold_mode / gold_route / family / source） |
| 权重 | `D:\AI\intern-decision\{0.8B,2B,4B}`（hf-mirror 下载，Apache-2.0）；GPU venv `gpuvenv`（torch 2.14.0+cu126） |
| Intern-Decision | `gpuvenv\Scripts\python.exe eval_id_v2.py 2B bfloat16 cuda v2`（100 题 ≈20 秒；CPU 兜底把 `cuda` 换 `cpu`、`bfloat16` 换 `float32`） |
| 现役基线 | `python eval_35b.py`（**直接 import 主仓库 `IntentClassifier`**，走真实规则层 + 生产 prompt，非重写近似） |
| 聚合 | `python aggregate100.py` / `python report.py`（报告表格全部由落盘 JSON 生成，不手抄） |
| 全套结果 | `cmp_*.json` + `report_tables.md` |

环境注意：需 `torchvision`（模型带视频预处理配置，缺则 `AutoProcessor` 直接 ImportError）；
`causal_conv1d` / `flash-linear-attention` 未装，走参考实现——**结果正确但更慢**，装上是纯提速。

### §10.8 题集产品化：intent-router-v1（2026-09-29）

§10.1-§10.7 那套题集只活在开发机脚本里，团队没法复用。本节按 `clause-probe-v1` 的既有范式
把它做成**仓库内可跑**的一等公民（同一套结构：题集 bundle + 断言块入库 + evals-core 评测器 +
宿主注入依赖 + `scripts/` CLI 外壳）：

| 层 | 产物 | 说明 |
| --- | --- | --- |
| 题集真相源 | `scripts/build_intent_set.py` | 100 题题面与金标全在脚本里，**自带机械校验**（结构不变量 + 与上游规则层对账），不通过拒绝出 bundle；`.gitignore` 白名单已放行 |
| bundle | `data/evals/datasets/intent-router-v1.json` | `eval.bundle.v2`，item 带 `intent` 金标块。**题集 bundle 进版本控制**（`.gitignore` 白名单 `!data/evals/datasets/*.json`，"题集跟随代码版本"），随 deploy 落到服务器；构建器 + bundle 双真相源互为校验 |
| 入库 | `eval_question.intent_gold` | schema / storage / manager 三处已扩；回读校验 100/100 带金标（**首版 clause-probe 就是在这丢过字段**） |
| 评测器 | `evals_core/runner/intent_eval.py` | 新评测器 `intent`：`run_prediction` 只跑分类器、`evaluate` 跑路由断言；宿主未注入分类器时**报错而非静默跳过** |
| 宿主注入 | `services/aichat-api/evals_routes.py` 启动钩子 | 注入生产同一条链（`IntentClassifier` + `SopLoader`），不另写近似实现 |
| 评测器选择 | `suite_runner._determine_evaluator_names` | `intent_gold` 命中即 exclusive 接管，不进检索/问答/判官 |
| CLI 外壳 | `scripts/intent_route_probe.py` | 进程内直调生产分类器 + 复用 `intent_eval` 断言（与 UI 同一真相源）；`--model-only` 只看会进模型的那批；结果默认落 `data/evals/probes/`（data/ 不入 git，写仓库根会变 git 噪音） |
| CI 自检 | `services/evals-core/tests/test_intent_set_bundle.py` | 题集质量约束进 CI：结构不变量、每题带 trap/rationale、route 派生与评测器同源、灰区题不得含选型措辞、缺陷阱族必须在位 |

**断言分级（与 clause-probe 的差异点，必须记住）**：`route` 恒为致命项，`level` / `mode` 默认只记录。
理由：`agent_policy.build_attempts` 真正消费的是 `(level, mode)` 派生出的路由桶，同桶的 L3↔L4 混淆
不改注入工具、不影响链路。金标可置 `strict_level` / `strict_mode` 把对应项升为致命。
**所以本集的主指标是 route 命中率**，level/mode 命中率作诊断一并报出（UI 的 `checks` 里都可见）。

**质量改进（相对开发机首版）**：

1. **消除灰区题**——3 条 L1_concept_compare 改写为只问结构/定义差异。首版措辞「两者的区别是什么」
   同时命中 `L1_KEYWORDS` 的「区别」与规则 5 的「多方案比较=L4」，读法不同会反转头名（§10.6）。
   改后该族在两轮生产实测中稳定 3/3。CI 里有一条测试专门禁掉这类措辞回潮。
2. **补 3 个陷阱族**：`L1_stdcode_trap`（标准号出现≠L2：「JTS 181 是什么规范？」）、
   `L1_numbered`（有数值≠L3：「什么是5万吨级散货船？」）、`L3_mixed_signal`（依据规范+计算→L3）。
3. **每题带 `trap` + `rationale`**：复核者不必回读分类 prompt 就能审金标；CI 强制非空。
4. **机械校验 + `rule_hit` 元数据**：构建时用主仓库规则层对账，逐题记录「生产链上会被规则前置拦下，
   还是真的进分类模型」。实测 **76 题进模型 / 24 题被规则拦下**（L0 规则 11 + 条款号快路径 6 + meta 规则 7）。
5. **顺带抓到一条产品事实**：meta 族 10 题里 **3 题生产 meta 规则认不出**
   （「系统里有哪些知识库？」「目前一共支持哪些文件格式？」「知识库最近一次更新是什么时候？」），
   会落到分类模型。这些是好题面、保留，作为 `_is_meta_query` 覆盖缺口的常备回归靶子。

**题集可靠性实测（3 次同集重跑）**：route 命中 **97/100 三次全同**，逐题翻转 **0 题**
（3 组两两比对，route / level / PASS-FAIL 状态三项全为 0 翻转，100/100 逐题一致）；
稳定缺口固定为 3 题（`ir-l0-pure-04` 讲笑话未被 L0 规则+模型认出、`ir-l2-look-09/10` 问规范规定被答成 L1）。
**这是与 nightly 生成层的关键差异**：生成层 1040 题约 12% 翻转、必须配对分析；本集在分类层 3 次实测 100% 一致，
**所以 ≥1 题的差异就是真差异**，不必再上配对统计（前提是同一题集版本 + 同一分类器）。
（口径提醒：3 次一致是经验证据、不是确定性证明；换分类器或改分类 prompt 后应重跑一次翻转率再下结论。）

**验收依据（本机实跑）**：`scripts/intent_route_probe.py` 输出 route 97/100；
`suite_runner._run_single_question` 集成三例——答对→`quality=correct(score=1.0)`、
错桶→`quality=wrong(score=0.0)`、未注入→`status=error`（不静默）；
evals-core 全量 `165 passed`（从仓库根跑，含新增 `test_intent_eval.py` 24 例 +
`test_intent_set_bundle.py` 7 例）。
**注意**：库内题集已就绪（本机 `import_bundle` 已入 `evals.sqlite` 并回读校验 100/100 带金标），但**服务器要能跑需两步**——
① 部署（schema/评测器/注入三处改动 + bundle 文件随 `git reset --hard` 落服务器）；
② 服务器侧**重导题集一次**：admin UI「导入题集」或
`curl -X POST https://angineer.cn/api/evals/datasets/import -F file=@data/evals/datasets/intent-router-v1.json`
（无启动自动扫描，导入是显式幂等操作；`eval-nightly.yml` 里的 Import datasets 步就是这一步的自动化版，仅手工调试备用）。

