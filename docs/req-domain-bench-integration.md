# 需求：跨领域 RAG bench 接入 evals（P1 金融 FinanceBench → P2 法律 JEC-QA，医疗缓行）

> 状态：**需求（待实施）**。发现于 2026-09-26 臂 2 朴素基线工作（`docs/plan-rag-baseline-arms.md`）期间——
> C 层 nightly v4（Open RAG Bench 1040 题）目前只有全链一个数字，缺跨领域旁证；Open RAG Bench 的
> 「官方题 + 官方答案 + 官方指定语料」接入模式已验证可复制，本需求把它推广到法律/金融领域。
> 执行者需已读仓库 AGENTS.md（push/发版/数据边界纪律）。**本文自包含，不需要额外会话上下文。**
> 2026-09-26 定盘：**只做两域——P1 金融 FinanceBench、P2 法律 JEC-QA**；LegalBench-RAG 出局（基线是纯检索
> 口径、端到端无可对比锚点，语料又是 txt 非 PDF）。三域公开基线均已核实入档（§2.1），门槛随定盘收紧为：
> **端到端无可对比公开基线的域不接入**。

## 1. 背景与目的

- 评测体系 A/B/C 见 `docs/parse-struct-eval.md`：A=解析质量（已固化）、B=素材传递性（nightly 自带）、
  C=端到端问答（nightly_openRAG，v4=1040 题/188 篇语料，2026-09-24 基线正确率 84.9%）。
- C 层考法：官方题 + 官方参考答案，我们把官方指定 PDF 用自家解析管线灌库，闭卷作答，DeepEval 判分。
- 扩域目的：①「跨领域通用性」旁证（挡掉「只在 arXiv 英文论文语料上调出来的」质疑）；②销售素材
  （金融/法律是目标客户密集领域）；③每域约 2~3 天，判分引擎与报告管线零改动。

## 2. 目标与范围

| 优先级 | 基准 | 理由 | 工作量 |
|---|---|---|---|
| **P1** | **FinanceBench**（SEC 文件问答，数值题多） | **与 v4 端到端考法同构**（官方题+官方答案+指定语料，判分链零改动）——首域先跑它，把「域接入清单」沉淀成文档；销售价值最高；表格密集顺带验证 table_lookup；论文基线已核实（§2.1：oracle 85%、现实 RAG 最优档 50% 正确/39% 拒答、全配置汇总 47%）可作引用锚点 | 2~3 天 |
| **P2** | **JEC-QA**（中文法考 QA，[jecqa.thunlp.org](https://jecqa.thunlp.org)，AAAI 2020） | **中文**（贴近目标市场）+ **CodaLab 榜单** + 论文基线已核实（§2.1：SOTA≈28%、人 81%/64%、官网基线 21~44%）；26,365 道单选/多选题，选项判分零歧义；语料=公开法条文本可入管线。注意：官方口径=给定题干的选项判分（检索法条属任务内），我们是开放作答+固定库 RAG，须标注口径差异 | 2~3 天 |
| 缓行 | MIRAGE/MedRAG（医疗） | 两个坑：①其检索语料是切好的教科书/StatPearls chunks 而**非 PDF**，教科书有版权，「拿 PDF 走管线」不成立；②题式是选择题（MedQA 选 A/B/C/D），与开放问答判分不同构。等 P1/P2 跑通后再评估 | — |
| 不接入 | COLIEE | 年度**参赛制**竞赛（官方成绩页 coliee.org/results），任务为法律 entailment/检索，与我们 RAG 形态不同构，无法「接入」只能参赛 | — |

### 2.1 公开基线锚点（2026-09-26 逐一核实）

**基线门槛（2026-09-26 收紧）**：每域接入前必须核实到「论文或活榜单」的**端到端可对比**基线
（数字+口径+来源 URL 记入预注册）；只有检索指标级基线的域不满足门槛（判例=LegalBench-RAG，出局）。
**核实不到的域不做**。口径不一致的基线可引用，但必须标注差异（下表「口径与可比性」列即预注册需复写的口径声明）。

| 基准 | 已核实基线数字 | 口径与可比性 | 来源（核实方式） |
|---|---|---|---|
| ~~LegalBench-RAG~~（**出局 2026-09-26**，数字留档作出局依据） | 论文 4 个检索基线（Naive / RCTS 切分 / 各配 Cohere Reranker）：ALL 集 P@1≈2.4~6.4%、R@64≈61~76%（Naive 召回最高 R@64≈76%、P@1≈2.4%） | **纯检索指标、无端到端基线=不满足门槛**；且语料为 txt 分发（714 篇/6,858 题，走管线需回源找 PDF） | arXiv [2408.10343v1](https://arxiv.org/abs/2408.10343) Table 4~7（当日拉 HTML 全文核对）；官方仓库 `zeroentropy-ai/legalbenchrag` |
| FinanceBench | GPT-4-Turbo **Oracle（金证据页）85% 正确**；现实 RAG 最优档（GPT-4-Turbo 单库检索）**50% 正确 / 11% 错 / 39% 拒答**；Table 1 八配置汇总 **47% 正确 / 26% 错 / 27% 拒答**；闭卷仅 9% | 端到端问答、开放作答人工判分——与我们也最同构；**引用禁止把 85%（oracle）说成 RAG 成绩** | arXiv [2311.11944v1](https://arxiv.org/abs/2311.11944) Table 1（每配置 150 题人工复核）；官方仓库 `patronus-ai/financebench` |
| JEC-QA | 论文口径 **SOTA≈28% 正确**（熟练人 81% / 生手 64%）；官网 Baselines 节 **BiDAF/HAF ≈21~44%**（KD/AC 分卷、单选/多选分列，重跑口径）；**CodaLab 活榜单**（test 集） | 官方任务=给定题干的**单选/多选判分**（检索法条属任务内）；我们是开放作答+固定库 RAG，数字不可直接对表，须标口径 | 论文摘要（arXiv [1911.12011](https://arxiv.org/abs/1911.12011)）+ [jecqa.thunlp.org](https://jecqa.thunlp.org) Baselines 节（当日拉取核对） |

**明确不做**：不改 nightly 调度与门禁逻辑；新域不接 nightly 定时（先「立即运行」/手动跑批验证）；
不动臂 2/臂 3 基线工作（`scripts/naive_rag_baseline.py`，独立进行中）。

## 3. 可复用基建（全部已存在，不要新建）

| 件 | 位置/用法 |
|---|---|
| 题集注册 | `data/evals/datasets/<dataset_id>.json`（eval.bundle：`{"dataset": {...}, "items": [...]}`）+ `evals.sqlite` 的 `eval_dataset`/`eval_question` 行；**范例脚本 `scripts/build_subset_v3.py`**（含本地+生产双写） |
| 语料入库 | `docs_core` 解析管线。**注意：跨域 bench 走生产式入库（含 fts/vectors 索引，检索要吃索引）**，与 OmniDocBench 评测库（5 阶段 `PARSE_STAGES` 不建索引）不同；参照生产库 `lib-b07ed174` 的形态（`canonical_documents` + 索引） |
| 判分 | `EVAL_ENGINE=deepeval`，入口 `evals_core/runner/judge_deepeval.py::evaluate_via_deepeval`；判分链纪律（绝不落到被测模型之外的静默降级）在 `answer_eval.py::_judge_candidates` |
| 报告 | nightly 管道/看板按 dataset_id 直接消费；单跑可用「立即运行」或参照 `scripts/naive_rag_baseline.py` 的 run/judge/report 四段式 |
| 预注册格式 | **参照 `docs/plan-rag-baseline-arms.md`**：配方与判据跑前写死、结果无论好坏都回填 |

## 4. P1 FinanceBench 工作项

1. **数据获取与许可核查**：官方仓库 `patronus-ai/financebench`（论文 arXiv 2311.11944，2026-09-26 核实），
   150 题开源样本与判分口径同论文；语料=SEC 申报文件（10-K/10-Q，单篇可达数百页），源文件回 EDGAR
   下载（公开数据），来源 URL 记入预注册。
2. **小批试解析**：先 3~5 篇试跑解析管线估单篇耗时，按结果排分批跑批与入库窗口。
3. **题集转换**：question + gold answer + evidence → eval.bundle items；数值题（「FY2019 毛利率是多少」型，
   答案=数值+单位）优先用 `correctness_checks` 数值/关键词断言（改题不改判分器，`normalize_eval_text`
   已做全半角/空白归一）；若必须动 `_GEVAL_STEPS`/rubric，**按 `judge_deepeval.py` 头部纪律：
   改口径=重跑 30 题 A/B 重钉基线**，并在预注册记录；`task_type: "rag"`，`tags` 记公司/题型。
4. **语料入库**：SEC 文件 → 新建 library（建议 `lib-financebench`）→ 生产式入库（含索引）→
   与官方文档清单对账（篇数/字符量），缺口记录。
5. **抽样与预注册**：**主报告=官方 150 题开源样本**（与论文同题同判分口径，可与 §2.1 数字直接对表）；
   扩展档=全量 10,231 题分层抽样 500~1000。预注册按第 3 节格式，含：配方、**判据跑前写死**（建议：
   与臂 1/臂 2 的差值阈值、citation 命中阈值）、拒答/负样本设计（故意不入库的申报文件考拒答守卫——
   参照 Open RAG Bench 的 39 题做法，manifest 记 `is_hard_negative`）、§2.1 锚点三档。
6. **表格题子集**：summary 单列表格题子集正确率（table_lookup 卖点验证）。
7. **跑批 + 判分 + 结果回填**：summary 出数字；**结果无论好坏都回填预注册结果段**——选择性报告=全部作废。
   引用锚点三档（oracle 85% / 单库 RAG 50% / 全配置汇总 47%）写明档位不混用（85% 是 oracle 检索，
   不得表述为 RAG 成绩）。

## 5. P2 JEC-QA 工作项（P1 验收后启动）

1. **数据获取与许可核查**：官网 [jecqa.thunlp.org](https://jecqa.thunlp.org) 官方分发（26,365 题，
   KD/AC 分卷、单选/多选分列）；语料=中文法条文本（题目随附 relevant articles），来源与许可记入预注册。
2. **题式映射（本域特有的一步）**：单选/多选 → eval.bundle：题干+选项进 question，gold=gold 选项集合；
   判分优先走 `correctness_checks` 选项命中断言（gold 选项必须命中、其余必须不命中——零歧义、判分器零改动）；
   若必须新增 exact-set 判定，按判分器改动纪律 30 题 A/B 重钉。题面要求作答同时输出字母与选项内容，
   判分按选项内容命中断言（防只答字母的格式歧义）。
3. **语料入库**：法条文本 → 新建 library（建议 `lib-jecqa`）→ 生产式入库（含索引）→ 与官方法条清单对账。
   ⚠️ 法条是文本形态=LegalBench-RAG 同款坑：解析段锻炼不了，预注册标注「直灌文本，解析段未锻炼」。
4. **抽样与预注册**：26,365 题全量不现实——按 KD/AC 分卷、单选/多选分列分层抽样 500~1000；预注册含
   §2.1 锚点（SOTA≈28%、官网基线 21~44%）与口径声明：官方=给定题干的选项判分（检索法条属任务内）、
   我们=固定库 RAG 开放作答——数字并列引用，不做同表对比。
5. **跑批 + 判分 + 结果回填**：同 P1 第 7 步，结果好坏都报。

### 5.1 P2 数据可达性核查（2026-09-28；启动前实探，非转述——下次直接引用勿重探）

**官方原始分发已全面断链，官方指定法条语料拿不到**（逐条实证）：

| 渠道 | 结果 |
|---|---|
| `thunlp/jec-qa` 仓库 | 仅 28KB，只有加载脚本 `dataset/nlp/JsonFromFiles.py`，**无数据文件** |
| [jecqa.thunlp.org](https://jecqa.thunlp.org) 首页 | 静态页仅 arXiv PDF / CodaLab 22173 / GitHub 三链，**无直下数据** |
| CodaLab 22173 | 赛事已止、服务迁移（老站 `competitions.codalab.org` 提示去新站 codalab.lisn、新站搜不到）→ **数据不可匿名取** |
| ModelScope / OpenDataLab | 无 JEC-QA 镜像（API 空） |
| Kaggle | 有 `weipengfei/sfzy-small` 等镜像，但下载**需 Kaggle 凭据**（agent 不代持，见 P1 发布纪律类推） |
| GitHub code search | `question_body+relevant_articles+exam_year` 官方组合格式命中全是 BioASQ 同名字段，**无官方法条包** |

**可达的题集**：agieval 重打包的 MMLU 子集（hf-mirror `hails/agieval-jec-qa-kd` 1000 题单选 +
`hails/agieval-jec-qa-ca` 999 题含 466 多选，schema=`query/choices/gold`，已下载验证是真法考原题）。
**但 agieval 版不含官方随附的 10.7 万法条语料**——即「固定库 RAG」缺检索库。

**结论 = 阻塞在「语料源」，需业主拍板**（三选一，改动成绩性质故不自行默认）：
A 注册 CodaLab/联系作者取官方包（最忠实，需人工）；B 自抓 `flk.npc.gov.cn` 官方法条库当语料 + agieval 题
（全自动，但语料非官方原快照、版本可能与 gold 相关条不一致，口径声明加重）；C 先闭卷多选试点验证选项判分链、
RAG 全链待官方语料（诚实标注「未锻炼检索段」，§5.3 同款坑）。

**判分器改动预警（启动前先读）**：现有 `answer_eval.evaluate_correctness_check` 只支持
`contains_all`/`contains_any`（判「在场」），**无「干扰项不在场」断言**。§5.2 设想的「gold 命中 + 其余不命中」
之「其余不命中」半边需**新增 check type → 触发判分器改动纪律（30 题 A/B 重钉）**，非「判分器零改动」。

## 6. 纪律与坑（必读）

- **数据边界**：题集 bundle/manifest 留 `data/`（gitignored）；转换与跑批脚本进 `scripts/`（`scripts/*`
  默认忽略，按惯例在 `.gitignore` 白名单逐个放行）；预注册与结果文档进 `docs/`（进 git）。
- **判分口径**：不要为某域单独私改判分实现；领域判分要点优先走 `correctness_checks`；rubric 变更必须重钉。
- **口径对齐**：新域首跑前用 30~100 题试点看管道健康（判分兜底占比、失败率），试点不据此改配方。
- **服务器部署**：新域题集与语料库需在服务器重建（deploy 不搬 `data/`，AGENTS.md 有同步约定）；
  本地先行，验收后同步。
- **诚实呈现**：结果好坏都报；与臂 1 的差值不做事后解释性修改判据。

## 7. 验收清单（DoD）

- [ ] P1：题集 bundle + manifest 落 `data/evals/datasets/`，注册脚本入 `scripts/`（白名单放行）
- [ ] P1：金融语料库建成（含索引），与官方文档清单对账记录
- [ ] P1：预注册文档（`docs/plan-financebench-arms.md` 或并入本文结果段）判据跑前写死，含 §2.1 锚点三档与拒答设计
- [ ] P1：全量跑批 + 同引擎判分 + summary；结果回填，好坏都报
- [ ] P1 收尾后输出「域接入清单」小节（下一步域照此复制），再启动 P2
- [ ] P2：题集 bundle + 法条语料库（含索引，预注册标注直灌文本）+ 预注册（含口径差异声明）+ 跑批回填，验收标准同 P1
- [ ] 每域预注册含已核实公开基线（数字+口径+来源 URL，对齐 §2.1 格式）；端到端无可对比基线的域不接入
- [ ] 全程未 push（push 需用户明确指令）、未动 nightly 门禁与臂 2/臂 3

## 8. 关键路径速查

| 件 | 路径 |
|---|---|
| A/B/C 框架与口径 | `docs/parse-struct-eval.md` |
| 判分引擎与纪律 | `services/evals-core/src/evals_core/runner/judge_deepeval.py`、`answer_eval.py` |
| 题集注册范例 | `scripts/build_subset_v3.py` |
| 跑批四段式参照 | `scripts/naive_rag_baseline.py` |
| 预注册格式范例 | `docs/plan-rag-baseline-arms.md` |
| v4 题集样例 | `data/evals/datasets/open-ragbench-subset-v4.json` |
| 判分计划与实测 | `docs/plan-deepeval-judge.md` |

## 9. 域接入清单（P1 FinanceBench 沉淀，2026-09-28；P2 起照此复制）

**固定动线（顺序即依赖，每步产物是下一步的输入）**：

| # | 步骤 | 产物/验收 | P1 实例 |
|---|---|---|---|
| 1 | 基线核实：端到端可对比（数字+口径+来源 URL），核实不到不做 | §2.1 格式入档 | arXiv 2311.11944 Table 1 逐格核对 |
| 2 | 数据获取：官方题集**零自出**，语料按官方清单回源，blob_sha/页数对账 | `data/<域>/raw/` 清单 | 150 题 jsonl + 84 PDF（12,013 页） |
| 3 | 生产式入库：含 fts/vectors 索引；软阶段（PoPo/图描述/graph）失败**不判死整篇**，对账按核心链（raw_parse/structure/fts/vectors） | reconcile 全通过 | 84/84，succeeded 24 + partial 60 |
| 4 | 题集转换：eval.bundle.v2；转换脚本只改格式不改判分；**注册必须手验 `eval_question` 行数** | `manager.import_bundle` + 行数核对 | financebench-open-150-v1 |
| 5 | 预注册：配方+判据**跑前写死**，append-only；判分健康红线（judge_fail>10% 作废）写进文档 | `docs/plan-<域>-arms.md` | 三档 ≥55 / 50–55 / <50 |
| 6 | 试点（10~30 题）：只看管道健康（判分失败=0、空答、hit@doc），**不据此改配方** | 试点记录段 | pilot-10，jf=0 |
| 7 | 正跑：单实例判分（臂 2 纪律）、触发前查 `/health` 三连、run body 放仓库外（防热重载） | `POST /api/evals/runs` | run-53eabc428c89 |
| 8 | 判分健康核查：judge_failed 必须为 0 或补到 0；每失败题查 `semantic_reason` 签名（Errno 22=进程 stdout 断死，重定向重启后重跑） | 报告含「判分失败 N 题」行 | 0/150 |
| 9 | 结果回填：无论好坏；披露项齐全（端点混跑/软段失败数/结构性 0 产出/空答题单列） | 结果表+补充段 | 58.0%，≥55% 档 |
| 10 | 对外：柱状图**必须带对照柱**+判分口径脚注（自判≠人工=非同一把尺；oracle 档禁比） | README 段+图 | financebench-compare.png |
| 11 | 敏感性：只对**受影响题子集**配对复跑（nightly 噪声地板 ~12%，未受影响题复跑=引噪）；新增「v2 轮+动机」段，不改主报告 | 配对翻转清单 | PoPo 20 篇 → 31 题 |

**踩坑清单（P2 直接规避，勿重踩）**：

- `build_bundle` 类脚本只写 bundle JSON **不注册**进 evals.sqlite——注册（`import_bundle`）必须单独做并验 `eval_question` 行数；
- `/api/v1/documents/{id}/resume` 对预取子集是**假完成**（按原始 stages 算 remaining→空→不调度）；正确入口 = cancel 僵尸 task + `POST /api/knowledge/documents/{id}/stages/{stage}/retry`（N 起重跑复用前置产物）；
- 阶段级卡死（stage 永远 running）多因 docs-api 重启掐 worker——修法同上；对账脚本要能识别「state 说完成、canonical 无行」；
- 判分端点探针用 **`/api/llm2`**（Qwen3.8-Flash-Next 只挂 llm2，打到 /api/llm 得 404 不是配置错）；
- 判分失败签名「所有 LLM 配置均失败」+ 启动 shell 被杀 = 进程内 LLM 调用全抛 Errno 22、整场判分静默失败——**先重启带正确 stdout 重定向再触发评测**；
- 软段端点配置缺失不报错只空跑（figure_describe 整段全灭实为 .env 漏配 `*_CONFIGS`）——入库前逐项 grep .env 对照代码所需配置；
- 长跑批一律带 guard 保活（幂等可重入 + 进程数对账收口，别信 grep/tasklist）；并发对齐服务方承诺、失败带退避再重发；
- graph 段种子门控：非工程域语料结构性 0 实体（不调 LLM），属被测现状非缺陷，预注册披露即可，**勿为 bench 定制种子**。
