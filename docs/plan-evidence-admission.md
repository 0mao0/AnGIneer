# 施工单：证据上桌（LLM 定员）与上下文硬帽

状态：**v2（2026-10-04）**。v1 经外部评审修正：B1/B2 文档自相矛盾已修，G1 上桌定界、G4 部署面、次要三条已纳入；B3（跨模块落点）与 G2（memo 交互）经核实不成立，理由见 §4-A/§1 注。规则与术语已与用户三轮对齐。
关联：docs/plan-retrieval-speedup-v3.md（变更 A/F3 的 memo、二排 R2）；docs/req-chat-history-bloat.md（预算闸门原设计）。

## 0 背景与动机

- 10-04 nightly（run-c937b19fd04f）9 题上下文超限 400→自动拒答：输入 61,441 + 输出 4,096 = 65,537 > 65,536，确定性损失 ≈0.87pp/晚。
- 根因链：QA 档预算闸门只压历史轮次工具结果（当轮证据豁免，「宁可超限也不压当轮」）＋评测每题全新会话无历史可压＋单包证据体积无上界＋停止线 est 120k 事后才查。
- 方案定版：**LLM 上桌（0/1 定员出 listA）为主机制；体积硬帽挂公共末端做 fail-open 兜底；400 钳制为最后防线。**
- 术语定版：**LLM 二排=改序**（已有，ANGINEER_LLM_SECOND_RERANK，生产关）；**LLM 上桌=定员**（本次新做）。二排管队形、上桌管谁上桌，互不替代。

## 1 上桌规则（定版）

| 规则 | 内容 |
| :--- | :--- |
| 作用范围 | **仅 knowledge_search 的文本条目**（10-04 实测病态包全部来自它）；table_search / entity 条目不走上桌、只走硬帽（表格条目语义判相关性的摘录格式=表头＋首 N 行，列二期） |
| 输入 | rerank 截断后的 top15（ANGINEER_CONTEXT_TOP_N），每条摘录 ≤1k 字符 |
| 头部豁免 | rerank ≥0.6 免判，直接进 listA（防判官误杀头部） |
| 判官形态 | **批量一枪**：题干＋15 条摘录 → 输出 JSON `[{i, keep}]`；禁逐条 15 连调（延迟不可接受） |
| 判 1 门槛 | 放宽：「可能相关即 1」；0 只给「确定无关」（误判 1 代价小、误判 0 丢证据） |
| 吵架保留 | 判 0 且 rerank ≥0.3 → 保留，进 listA 尾部（相关性标签照贴，答案模型终裁） |
| 一致丢弃 | 判 0 且 rerank <0.3 → 丢（双信号一致） |
| 空桌拒答 | listA 空（判官全 0 且无 ≥0.3 条且无高分条）→ 走标准拒答话术，不回退；两个独立判者同时错才误拒 |
| fail-open | 判官异常/超时/输出不可解析 → 15 条全量放行，永不过滤层打死回答 |
| 决策留痕 | all_scores.retrieval.admission = {kept, dropped, quarreled, exempted, fallback, judge_config, judge_ms, **cap_dropped**}——「上桌丢」与「帽子丢」分开计数，nightly 归因可分 |

> **memo 交互（v2 评审 G2 的裁定）**：上桌决策**随装配结果一起进 memo**，是有意设计——memo 的单发复用正是检索提速变更 A「消灭同请求双跑」的延续，排除上桌会让每请求退化为双判官调用。上桌决策随 memo 值跨请求复用与检索成品同权（同键=同参数同结果）。判官「格式正确但判断错」不由缓存层解决（同请求重跑同样错），由吵架规则＋头部豁免＋留痕兜底。

## 2 硬帽与钳制（定版）

- **软帽** `ANGINEER_EVIDENCE_CAP_EST` 默认 80_000（est 口径 = chars//2）：**覆盖全部检索 kind**（knowledge/table/entity，落点在 _assemble_search_result 公共末端），按 rank 装填，超帽条目截尾（剩余预算 <200 字符则整条丢）。61k token 案例 ≈ est 120k，软帽可拦。
- **装配顺序与口径**：触发判定与判官读**帽前 est**（原始 15 条的体积）；顺序 = 上桌（可选）→ 硬帽装填 → 序列化。帽后 est ≤80k，任何「帽后 90k 触发」的写法都是死代码。
- 已知口径坑：est 对中文低估约 2x（1 字≈1 token，req-chat-history-bloat §3 自己标过）——中文语料软帽拦不全，由钳制层兜底；帽值因此不追求精确挡顶，只求把病态包砍到量级正常。
- **400 钳制**：client 识别 context-length 400 → 按 `limit − input − 512` 重算 max_tokens 重试一次；仍败才走原报错→拒答通道。中文规范语料（在线 chat）同样受益。
- P2 顺带：循环停止线 120k est env 化（`ANGINEER_BUDGET_STOPPER_EST`），换小上下文模型时不再裸奔。

## 3 判官配置

- 独立 config `ANGINEER_ADMISSION_LLM_CONFIG`，默认值对齐 llm2 条目（qwen3.8-flash-next，关思考）。**不复用 evals-core 的 `EVAL_JUDGE_MODEL` 的原因**：上桌判官住在 angineer-core（在线请求路径），EVAL_JUDGE_MODEL 是 evals-core 的变量——跨包读取违反模块解耦红线；值上对齐、机制上独立。
- 成本：prefill ≈5k token（题干＋15×1k 摘录）、输出 ~15 项 JSON；延迟预算 +1~3s。**all 档在 nightly 同窗与判分共享 llm2 端点，延迟红线必须在 nightly 窗口实测，不许只看在线低峰**（llm2 有洪流前科，见 req-table-retrieval-latency）。
- 触发模式 `ANGINEER_ADMISSION_MODE`：`oversize`（**默认**：仅帽前 est > 90k 的病态包走上桌，即昨晚 9 题族——这些题今天 100% 变错题，任何结果都不可能更差，属修 bug 性质）｜`all`（动正常题的证据面，有真实误杀/延迟风险，**A/B 过判据后才许设为默认**）｜`off`（逃生口）。

## 4 变更清单

| # | 内容 | 落点 |
| :--- | :--- | :--- |
| A | `admit_evidence()` 新函数（与 llm_second_rerank 并列）；由 agent_tools._assemble_search_result 在 rerank 截 15 后惰性 import 调用——与现有 rerank_candidates 同款跨模块方向（retrieval_pipeline 不反向依赖 agent_tools，无循环导入，已核实） | angineer-core/retrieval_pipeline.py |
| B | 装配公共末端软帽装填/截尾（全部 kind） | angineer-core/agent_tools.py |
| C | context-length 400 识别＋钳制重试一次 | services/ai-inference llm_client（通用受益） |
| D | 停止线 env 化（P2） | angineer-core/agent_configs.py |
| E | admission 块落 all_scores＋nightly 归因可见 | evals-core 评分链 |
| F | 6 个 env 键登记 .env.example（房子规矩）：`ANGINEER_ADMISSION_MODE`（off｜all｜oversize，**默认 oversize**）、`ANGINEER_ADMISSION_TRIGGER_EST`（默认 90_000，**帽前口径**）、`ANGINEER_ADMISSION_LLM_CONFIG`（默认 llm2 条目）、`ANGINEER_ADMISSION_EXCERPT_CHARS`（默认 1_000）、`ANGINEER_EVIDENCE_CAP_EST`（默认 80_000，0=关帽）、`ANGINEER_BUDGET_STOPPER_EST`（默认 120_000，P2） | .env.example |
| G | 单测 ≥10 例：判官坏输出 fail-open／吵架矩阵（0×高低分）／空桌拒答／头部豁免／帽装填截尾／钳制重试／留痕字段／帽前帽后口径 | 各包 tests |
| H | **部署面**：服务器 .env 同步 6 键＋`cd docker && docker compose up -d <服务>` 重建（`docker restart` 无效，env_file 创建时固化——AGENTS.md 已有实踩）；oversize 默认下漏配 env 无感，切 all 时忘重建即白跑 | 运维步骤 |

## 5 预注册判据（A/B 夜，跑前锁死）

- 设计：同模型（occamy-1.0 恒定）、同判官（qwen3.8-flash-next）、同题集 v4.1；**MODE=all 一晚 vs 同周最近的 oversize 夜，逐题配对**（噪声地板：~12% 翻转、净差 ±5 题，必须配对分析）。vs off 无信息量（off 档病态题必败）。A/B 只裁决 `all` 档能否转正，`oversize` 默认不依赖它。
- 红线（任一破即回退默认 oversize）：可答题正确率降幅 ≥1pp；**假拒答 ≥3 例，或连续两夜各 ≥2 例**（当前基线 1 例，样本太小，单夜 +2 在抽签范围内）；判官失败率 >0.5%。
- 收益判据：超限 400 = 0；答案段 prompt token p50 显著下降；单题延迟 p50 增幅 ≤2s（**nightly 窗口实测**）。
- 探索指标（如实记账、不定成败）：正确率净变化、不可答幻觉数（当前 15，理论上桌后应降）。

## 6 顺序与依赖

```
① B+C 硬帽＋400 钳制 ──> 独立收益先行（杀 9 题/晚，不依赖上桌）
② 回切对照夜（qwen3.6-35b 跑一晚，用户拍板）──> 归因 hit@1 悬崖＋模型贡献
③ A/E/F/G/H 实现＋本地验收（默认 oversize，只打病态包不扰正常题）──可与②并行（纯写码）
④ 上桌 A/B 夜：MODE=all vs 同周 oversize 夜，逐题配对
⑤ 按判据定 all 是否转正；off 留逃生口
```

## 7 风险表

| 风险 | 缓解 |
| :--- | :--- |
| 判官误杀关键证据 | 判 1 门槛放宽＋吵架保留＋头部豁免＋fail-open 四层 |
| 延迟超标 | 批量一枪＋小快模型＋nightly 窗口实测 p50（红线 2s） |
| 空桌拒答误触发 | 双信号一致才拒＋假拒答红线（≥3 或连两夜 ≥2） |
| 中文语料 est 低估 2x | 钳制层兜底（软帽只求量级正常） |
| 截尾丢尾部关键句 | 仅 est>80k 病态包触发＋丢的是 rank 尾部＋钳制兜底＋cap_dropped 留痕 |
| llm2 同窗洪流（nightly 判分＋上桌判官） | all 档延迟红线按 nightly 窗口口径实测；oversize 档触发率 ~1% 无感 |

## 8 未决项（用户拍板）

1. 回切对照夜是否排期（约 3h GPU，一次回答模型贡献＋hit@1 悬崖两案）。
2. 判官 config 默认挂 llm2 条目确认。
3. 软帽 80k est、触发阈值 90k est（帽前口径）数值确认。
4. A/B 夜排期（nightly 调度当前 off，需手动触发）。
