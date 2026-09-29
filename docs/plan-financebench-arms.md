# FinanceBench 域接入：预注册配方与判据（2026-09-27）

> **本文件在跑批之前写死**，跑批后不得回改配方参数与判据——跨域成绩的公信力来源同
> `plan-rag-baseline-arms.md`。需要改参数 = 追加新段落（注明日期与动机），不覆盖旧配方。
> 需求出处：`docs/req-domain-bench-integration.md` §4；基线锚点均已于 2026-09-26 从论文原文核实。

## 目的与锚点

FinanceBench（patronus-ai，arXiv 2311.11944）= 开源金融 SEC 文件问答 150 题（开源子集），
论文 Table 1 给出 8 种配置的公开基线。我们的锚点（口径与可比性逐条声明）：

| 锚点 | 数字 | 口径与可比性 |
|---|---|---|
| GPT-4-Turbo **Oracle** | **85%** correct | 人工直接喂 evidence 页（金标检索），**检索上限参照**，不得表述为 RAG 成绩 |
| GPT-4-Turbo **Single Vector Store**（论文内最优现实 RAG） | **50%** correct / 11% incorrect / 39% not_answered | 单库朴素向量检索 + GPT-4-Turbo，与端到端 RAG 同构，**主对比锚点** |
| 8 配置 **Total 行** | 47% / 26% / 27% | 8 种配置汇总（含 oracle 与闭卷），**不是任何单个 RAG 配置**，引用时必须注明 |
| 闭卷 GPT-4-Turbo | 9% correct | 无检索下限参照 |

**判分口径差异声明（跑前写死，结果并列呈现、不进同一张表）**：论文判分 = 人工双人标注
（correct / incorrect / not_answered 三类）；我们 = DeepEval GEval（rubric、阈值 0.65，
judge 与 nightly 同款链），拒答行为单独统计（不并入正确率分母口径见判据）。
**发布时不写「与论文同口径」，只写「对照论文公开基线数字，判分方式不同」**。

## 语料与入库配方（预注册，跑前定死）

| 项 | 值 | 说明 |
|---|---|---|
| 语料 | **84 篇 SEC PDF**（150 题涉及的全部唯一文档） | 下载自官方 registry `doc_link`（EDGAR 原始文件）；与仓库内置 PDF 以 **git blob sha 对账**（`data/financebench/raw/pdf_manifest.json`），字节级一致才算过 |
| 入库 | **我们的全管线**（`stages=all`：MinerU→popo/structure→figure_describe→fts→vectors→graph） | 这正是被测对象——解析质量与检索工程都是域接入要锻炼的 |
| 知识库 | `FinanceBench-Open`（独立新库，不混入工程域库） | 绑定 scope=doc API Key，脚本 `scripts/financebench/import_docs.py`（断点续跑） |
| 题集 | 官方开源子集 **150 题全量**，不抽样、不删题 | 论文主报告即此 150 题，全量保可比性；扩展档（500~1000）后置另注册 |
| 题集格式 | `financebench-open-150-v1`（eval.bundle.v2）：gold_answer=官方 answer 原文；纯数值答案→`contains_any` 裸数字断言（归一化去逗号/货币符，判分失败兜底用）；`refusal_expected=false` 全量（开源子集全部可答）；retrieval gold_doc_ids=官方 doc_name 对应入库 doc_id | 脚本 `scripts/financebench/build_bundle.py` |
| 生成/判分 | 与 nightly 完全同款链；`EVAL_DEEPVAL_EXTRA=0` | 单实例判分（臂 2 事故纪律：28 并发打挂网关致 84% 判分失败） |

## 指标与预注册判据

**主指标 = 150 题语义正确率**（judge semantic_passed；判分失败题按 nightly 同规则兜底重判，不人工改判）：

- **≥ 55%** → 超论文现实 RAG 最优档（50%）≥5pp，可对外表述「超过论文公开的现实 RAG 配置最优档」；
- **50–55%** → 并列线：表述「与论文现实 RAG 最优档持平（判分方式不同）」；
- **< 50%** → 照实发布，**禁止**任何「超过/持平」表述，转向分析原因（解析/检索/生成哪层）；
- 85% oracle 档只作上限参照引用，任何情况下不得把我们的成绩与 oracle 档直接比。

**辅助指标**（不设通过线，如实记录）：

- 检索 hit@doc：gold 文档是否进入系统召回集（gold_doc_ids 来自官方 doc_name→doc_id 映射，1:1 无歧义）；
- 拒答行为：semantic 未过且 `is_refusal` 的题数（对应论文 not_answered 列，仅并列呈现）；
- 分题型正确率：metrics-generated / domain-relevant / novel-generated 各 50 题（论文 Table 1 同维拆分）。

**判分健康红线**：判分失败（judge_fail）> 15 题（10%）→ 本轮成绩无效，修复后整轮重跑；
凡判分失败题一律走 `--auto-retry` 至耗尽或清零，报告必须含「判分失败 N 题」可见行。

## 公平性纪律

1. 配方不做逐题调优；试解析 3~5 篇与 10 题试点**只看管道健康**（解析成功率、hit@doc 水位、答案目检），不据此改配方；
2. 判分失败题按 nightly 同规则兜底，不人工改判；
3. 结果无论好坏都回填本文件结果段——**选择性报告 = 全部作废**；
4. 同一配方只跑一轮定稿；发现管道缺陷修复后重跑须在新段落注明「v2 轮 + 动机」。

## 试点记录（2026-09-27 追加；公平性纪律 1：只看管道健康，不据此改配方）

- 抽样：`financebench-pilot-10-v1`（scripts/financebench/build_pilot.py，question_type 分层随机 seed=42、4/3/3，
  仅取当时已入库文档）；run-757f6d0cecf1。
- 前两次尝试整体作废：aichat-api 被 watchfiles 热重载打断作答（`cannot schedule new futures after
  interpreter shutdown`，6/10 空答 + 判分失败）——环境性事故非被测系统缺陷；以 `ANGINEER_NO_RELOAD=1`
  重启服务后第三次跑通。
- 健康读数：**判分失败 0 题、空答 0 题、hit@5_doc 9/10**（quality 5/10 仅参考，见下）。判分健康红线通过。
- 口径观察（不改判分器，主指标按预注册 = judge semantic_passed 口径出数）：`suite_runner._decide_quality`
  的 PASSED_THRESHOLD=0.8 严于 bundle 的 semantic_threshold=0.65，存在「semantic_passed=True 但 quality=wrong」
  边界带（试点 1 题：MGM EBITDAR 区域题）。工程域 nightly 同此语义，跨域口径一致。
- 入库侧记录（主报告披露用）：①figure_describe 软阶段在已入库文档中多篇失败（外部端点，解析主链与
  检索不受影响）；②graph 实体抽取在金融域 0 产出——种子实体与抽取提示词按工程规范域构建
  （`step07_graph` 56 枚中文种子，无命中即短路不调 LLM），属被测产品现状，非本域接入缺陷。

## 入库运维记录（2026-09-27 追加；只涉基础设施，未动配方）

- 解析端点：DGX MinerU（:8007）当日间歇 502/挂死（请求可 hang 至 600s read timeout），`.env` MINERU_CONFIGS
  临时 company 置前（同一 hybrid-engine，产物含 hybrid_auto 结构，与 DGX 解析同源）；DGX 恢复后可调回。
  **主报告披露义务**：语料 84 篇中部分走 company 端点解析（端点分布以 import 日志为准），属基础设施调度非配方变更。
- PoPo：唯一端点 DGX vLLM（:8008）。DGX 侧 2026-09-27 确认可承 6 并发（POPO_MAX_CONCURRENCY=2→6）；
  实测吞吐随 DGX 共享负载波动大（p50 22s ↔ 尾部 400s+），非本侧可控。
- 重试策略修正（2026-09-27，DGX 侧指出故障放大后核实采纳）：请求级超时 300s（`POPO_API_TIMEOUT` 隐性默认）
  小于实测解码 400-580s，叠加 `POPO_INFERENCE_RETRIES=1` 的超时即重提 = 同一请求双份解码烧卡。
  修正为：超时 900s 对齐真实解码 + 请求级重试 0 + 文档级退避重试（120s×n，经 cancel→stages/popo/retry 官方入口）。
  DGX 修复后（17:40）其服务端断连会真取消任务，并约定：失败重试一律带退避、并发对齐 4
  （`POPO_MAX_CONCURRENCY=6→4`）；审计确认全链已无零退避重发路径（LLM 客户端指数退避、MinerU 3/6s、文档级 120s×n）。
- 环境根因两处（与成绩无关，但记录以免未来排查踩坑）：①`pnpm run --parallel /dev:.*-api$/` 看门狗反复复活
  带 uvicorn-reload 的实例打断在跑任务，已连根 + `.env` 写死 `ANGINEER_NO_RELOAD=1`（main.py 新增该开关读取，
  默认行为不变，未提交）；②`/api/v1/documents/{id}/resume` 对预取子集存在假完成语义（按原始 stages 算范围），
  入库脚本改用 `parse/{task}/cancel + stages/popo/retry` 官方入口。
- 单篇耗时基线（136 页 10-K，DGX 健康时）：raw_parse 227s + popo 575s + vectors 72s + 其余 <10s。

## 结果（2026-09-28 回填；run-53eabc428c89，2026-09-28 01:22–04:0x，150 题一轮定稿，配方未动）

| 指标 | 我们 | 对照锚点 | 预注册判据 | 判定 |
|---|---|---|---|---|
| 150 题语义正确率 | **87/150 = 58.0%** | 50%（现实 RAG 最优档）/ 85%（oracle）/ 47%（8 配置汇总） | ≥55% / 50–55% / <50% 三档 | **≥55% 档**：可对外表述「超过论文公开的现实 RAG 配置最优档」（判分方式不同，须并列标注 DeepEval 非人工） |
| 检索 hit@doc | hit@1_doc **144/150（96%）**，hit@5_doc 144/150 | — | 辅助 | 检索层健康；未中的 6 题即错误主体候选（生成层为主） |
| 拒答题数 | **20/150 自发拒答**（model_refusal_kept）+2 题空答（answer 空串记 wrong） | 39/150（Single Vector Store not_answered） | 辅助 | 低于对照拒答率，与工程域「守卫倾向作答」同向；不设通过线仅呈现 |
| 分题型正确率 | metrics-generated **72.0%**（36/50）/ domain-relevant **46.0%**（23/50）/ novel-generated **56.0%**（28/50） | — | 辅助 | domain-relevant 最弱（需跨表推理/口径换算型） |
| 判分失败题数 | **0 题** | — | ≤15 | 通过（无需 auto-retry） |

**结果段补充（口径与披露，均为跑前已记录的运维事实，非事后修饰）**：

- 口径：主指标 = judge `semantic_passed`（DeepEval GEval，非人工复核）。quality correct=84（`_decide_quality`
  PASSED_THRESHOLD=0.8 严于 bundle 0.65 的既有边界带，3 题 sem 过 quality wrong，试点已记录）；对外引用只引 58.0%。
- 被测模型 = Qwen3.6-35B-A3B（dgx1 vLLM，config_snapshot 钉），judge = Qwen3.8-Flash-Next（llm2），判分链与
  nightly 同款；`final_outcome` 分布：model_answer 123 / model_refusal_kept 20 / model_answer_stripped 5 / 空答 2。
- 解析披露：①PoPo 失败 20 篇（TimeoutExpired 为主，DGX 冻结窗口）未补跑，structure/fts/vectors 均 completed
  （检索链完整，PoPo 为增强段）；②figure_describe 失败 56 篇（.env 当时未配端点→整段空跑，
  2026-09-28 已配 FIGURE_DESCRIBE_CONFIGS=dgx-llm1 qwen3.6-35b 并验证视觉可用；正跑后补跑，不影响本轮口径——
  数值题主吃表格+正文；补全敏感性分析见 v3 轮）；③84 篇中部分走 company hybrid-engine 端点（与 DGX 同源），MinerU 全 84 篇 raw_parse completed；
  ④graph 金融域结构性 0 实体（中文种子门控，被测现状）；⑤JPMORGAN_2023Q2_10Q 曾 structure 卡 running，
  正跑前经 cancel→structure/fts/vectors 重排补齐全（completed，4803 chunks），未污染 run。
- 两空答题（financebench_id_00540 AES / 04080 NIKE）：模型返回空串带引用，判 wrong 不判 judge_fail；
  若做敏感性分析优先复核这两题。
- 表格/数值题子集（需求文档 P1-6，bundle 带 contains_any 数值断言的 52 题）：semantic_passed **37/52 = 71.2%**，
  显著高于非数值子集 50/98 = 51.0%——表格检索链路（table_lookup）在金融表格密集域为正贡献；
  citation_ok 150/150。
- 按预注册判据落 ≥55% 档，且判分失败 0——本轮成绩有效。禁止引用 85%（oracle）作任何对比。

## v2 轮：PoPo 补全敏感性分析（2026-09-28 追加；公平性纪律 4「修复后重跑须注明 v2 轮 + 动机」）

- **动机**：主 run 语料态下有 20 篇 PoPo 段失败（记 partial，核心链齐）。补全 PoPo 是否改变成绩？
  主报告 58.0% 口径**不变**，本轮为新增披露。
- **方法**（配对，非总分对比）：①20 篇经 cancel→`stages/popo/retry` 全部补成 20/20
  （初期 3 篇反复失败，根因 DGX vLLM `max_model_len=16384` 上下文拒绝 400——DGX 提升至 32768 后一次过，
  见 `docs/req-dgx-popo-stability.md` §6；该需求书 2026-09-29 已清理，git 历史可查）；②只对受影响 31 题（20 篇所涉，`financebench-sens-31-v1`）复跑，
  其余 119 题不跑（语料未变，复跑=纯引噪）；③按 question_id 逐题对齐翻转；④异动题第三采样定性
  （`financebench-sens4-v1`）。判分链、模型、配方全部不动，单变量=那 20 篇 chunks。
- **结果**（run-955f99dd41e9，31 题，judge_failed=0）：主 run 18/31 过 → 配对复跑 15/31；
  **wrong→correct 翻转 = 0**；correct→wrong 表面 3 题（00517/00494/01091，全部集中在 BOEING_2022_10K）。
- **定性（第三采样 run-25e32b64a762）**：3 道「回退」在同为 PoPo 补全态的语料上**全部翻回 True**
  （00517 曾输出垃圾「2. 1200.001」、01091 曾拒答——均为生成抽签，非 PoPo 证据劣化；与 nightly
  单跑翻转率 ~12% 互证）；00678 三采样稳定错（判分 reason 显示数值事实接近过关线但 sem=False，留档）。
- **结论**：**PoPo 补全对本域无可测正收益**——0 题翻绿；回退亦非其害。工程含义：金融 SEC 表格域，
  PoPo 后处理段（DGX fp8）对端到端成绩贡献 ≈0，其价值若存在应在解析质量侧（A 层）而非 C 层成绩。
- 状态披露：当前库内 20 篇语料态=PoPo 补全后（与主 run 读数产生态不同），配对分析显示该差异无系统效应。

## v3 轮：图描述补全敏感性分析（2026-09-29 追加；公平性纪律 4「修复后重跑须注明 v3 轮 + 动机」）

- **动机**：主 run 语料态下有 57 篇 figure_describe 段失败（当时 `.env` 未配端点→整段空跑，结果段补充 ②已披露）。
  补全图描述是否改变成绩？主报告 58.0% 口径**不变**，本轮为新增披露。
- **方法**（配对，非总分对比）：①57 篇两段补跑全部补成 **57/57**（首段 36 篇 + 补跑脚本 21 篇，`fig_repair.out.log`
  + `fig_retry21_result.json`）；②对 57 篇所涉 102 题（`financebench-figpair-102-v1`）复跑，其余 48 题不跑；
  ③按 question_id 逐题对齐翻转；④12 道异动题第三采样定性（`financebench-figflip-12-v1`）。
- **落盘验证（补跑真实性的独立核对）**：57/57 阶段 completed；修复篇 canonical 层 283 个 figure 块**100% 带
  >200 字 VLM 描述**（抽样为实质图表解读文本）；chunk 层 51 块含图句式（"This line chart…"），描述已进可检索单元。
- **双变量披露（必读）**：本轮复跑与主 run 之间语料与判分器**同时**变化——复查轮 caliber_fp 含 `judge_scale_fix:v1`
  （P0 判分刻度修复，2026-09-28 16:59 部署），主 run（09-28 01:22 起）无此项；两轮 steps_fp `d0af48300740`、
  模型 Qwen3.6-35B-A3B、judge Qwen3.8-Flash-Next 均一致。**翻转=语料补全与判分刻度修复的混合效应，单轮无法分离**。
- **结果**（run-64c7df29e285，102 题，≈06:18–08:06，judge_failed=0）：主 run 基线 58/102 过 → 配对复跑 **54/102**；
  wrong→correct **4 题**（00080/00720/01028/04080）；correct→wrong **8 题**
  （00494/00684/00723/01077/01964/02981/07661/10499）。翻转 12/102≈11.8%，与 nightly 单跑翻转地板 ~12% 同量级，
  净差 −4 在噪声内。
- **定性（第三采样 run-c625925210c5，12 异动题同语料态复跑）**：
  ①**8/12 翻回**（6 道 C2W 回通过；00080 0.06→0.7→0.2、04080 空答→0.8→0.0 亦不稳定）⇒ 生成抽签为主，非语料所致；
  ②**2 题稳定增益**：00720 基线整题拒答 → 两轮都答对 1.0；01028 基线 0.6（贴 0.65 线）→ 0.7/1.0；
  ③**2 题连续两轮失败**：01964（两轮均报「证据不足以确定最大负债」，基线答对 Customer Deposits）、
  02981（两轮算错 3 年平均营业利润率：14.1% / 15.8%，基线 10.3% 正确）。
- **异动溯源（追加探查，同日）——四道「稳定」异动均定因于推理侧，图描述无因果证据**：
  · **00720=意图路由抽签**：基线判 L1（概念解析，单轮语义检索，池中无毛利率相关证据）→ 拒答；两轮复跑均判
    L4（复杂任务，动态编排 turns=3）→ 补检索到「Discount revenue 为本司最大收入来源」等证据 → 答对。分类 prompt
    版本三轮一致、分类器输入为题干（不含语料）⇒ 语料侧无法解释；102 题整体意图/结局分布两轮一致
    （L1 62/63、L3 31/31、L4 8/8，outcome 83/82 answer、14/15 refusal），无系统漂移。
  · **01028=同一证据下作答/判分摆动**：三轮前排证据完全一致（前 8 条同 id 同分；rechk↔third Jaccard=1.0），
    同一证据三采样 0.6/0.7/1.0 跨 0.65 线。
  · **01964/02981 亦非检索侧重排**：前排证据与基线一致（01964 前 6 条同 id 同分、Jaccard 0.88；02981 前 4 条同 id）；
    差异在推理侧——01964 是「积极作答→保守声明证据不足」的行为翻转；02981 是 SOP 循环轮数 3→9/10、池 15→27/43 条
    （多轮引入干扰表），两轮各算出**不同**错值（14.1% / 15.8%），同语料两采样不一致。
  · 图描述项在这四题的证据池中仅以相关性 0.00–0.16 垫底陪跑，未参与作答论证。**结论：语料侧（图描述）对这些
    异动无因果证据；四题定因均为路由/作答/循环的推理侧抽签，留档**。
- **结论**：**图描述补全对本域 C 层无可测系统正收益**——净差 −4 在噪声内，12 处异动中 8 处为抽签；4 处「稳定」异动
  经溯源全部定因于推理侧（1 路由抽签 + 1 同证据摆动 + 2 推理侧个体漂移），**图描述无因果证据**。工程含义与 v2 一致：
  金融 SEC 表格域，解析增强段（PoPo / 图描述）对端到端 C 层成绩贡献 ≈0；其价值若存在应在 A 层解析质量侧。
- 状态披露：当前库内 57 篇语料态=图描述补全后（与主 run 读数产生态不同），配对分析显示整体效应在噪声内、
  无异动可归因于语料；4 题个体异动均为推理侧（路由/作答/循环）留档。
