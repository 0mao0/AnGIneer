# 需求：跨领域 RAG bench 接入 evals（P1 法律 LegalBenchRAG → P2 金融 FinanceBench，医疗缓行）

> 状态：**需求（待实施）**。发现于 2026-09-26 臂 2 朴素基线工作（`docs/plan-rag-baseline-arms.md`）期间——
> C 层 nightly v4（Open RAG Bench 1040 题）目前只有全链一个数字，缺跨领域旁证；Open RAG Bench 的
> 「官方题 + 官方答案 + 官方指定语料」接入模式已验证可复制，本需求把它推广到法律/金融领域。
> 执行者需已读仓库 AGENTS.md（push/发版/数据边界纪律）。**本文自包含，不需要额外会话上下文。**

## 1. 背景与目的

- 评测体系 A/B/C 见 `docs/parse-struct-eval.md`：A=解析质量（已固化）、B=素材传递性（nightly 自带）、
  C=端到端问答（nightly_openRAG，v4=1040 题/188 篇语料，2026-09-24 基线正确率 84.9%）。
- C 层考法：官方题 + 官方参考答案，我们把官方指定 PDF 用自家解析管线灌库，闭卷作答，DeepEval 判分。
- 扩域目的：①「跨领域通用性」旁证（挡掉「只在 arXiv 英文论文语料上调出来的」质疑）；②销售素材
  （金融/法律是目标客户密集领域）；③每域约 2~3 天，判分引擎与报告管线零改动。

## 2. 目标与范围

| 优先级 | 基准 | 理由 | 工作量 |
|---|---|---|---|
| **P1** | **LegalBenchRAG**（合同/判例 QA，答案为原文 span） | 语料小、span 判分最容易，适合先把「域接入清单」沉淀成文档 | 1~2 天 |
| **P2** | **FinanceBench**（SEC 文件问答，数值题多） | 销售价值最高；表格密集可顺带验证 table_lookup；论文公开基线（GPT-4-Turbo 金开卷 85%、现实 RAG 配置 ~47% 正确/27% 拒答）可作引用锚点 | 2~3 天 |
| **P2 备选** | **JEC-QA**（中文法考 QA，[jecqa.thunlp.org](https://jecqa.thunlp.org)，AAAI 2020） | **中文**（贴近目标市场）+ **CodaLab 榜单** + 论文基线；26,365 道单选/多选题，选项判分零歧义；语料=公开法条文本可入管线。注意：榜单是闭卷知识问答口径，我们做 RAG 版须标注口径差异 | 2~3 天 |
| 缓行 | MIRAGE/MedRAG（医疗） | 两个坑：①其检索语料是切好的教科书/StatPearls chunks 而**非 PDF**，教科书有版权，「拿 PDF 走管线」不成立；②题式是选择题（MedQA 选 A/B/C/D），与开放问答判分不同构。等 P1/P2 跑通后再评估 | — |
| 不接入 | COLIEE | 年度**参赛制**竞赛（官方成绩页 coliee.org/results），任务为法律 entailment/检索，与我们 RAG 形态不同构，无法「接入」只能参赛 | — |

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

## 4. P1 LegalBenchRAG 工作项

1. **数据获取与许可核查**：官方源（GitHub/HuggingFace 检索 "LegalBenchRAG"，接入前核实论文/仓库/HF id、
   版本与许可，把来源 URL 记入预注册文档——本文件不预填 id，防转述失真）。语料为合同文本，
   逐篇核对公开度与再分发条款。
2. **题集转换**：question + answer span → eval.bundle items。映射建议：
   `answer.gold_answer` = 官方 gold span（span 判分天然是包含性判断，GEval 现有 rubric 可直接用）；
   高价值的题可用 `answer.correctness_checks`（关键词断言，`normalize_eval_text` 已做全半角/空白归一）
   表达「必须命中的条款关键词」；`tags` 记录源文档 id 与题型；`task_type: "rag"`。
3. **语料入库**：合同文档 → 新建 library（建议 `lib-legalbench`）→ 生产式入库（含索引）→ 与官方文档清单对账（篇数/字符量），缺口记录。
4. **抽样与预注册**：全量或分层抽样（题多可抽 500~1000）；预注册文档按第 3 节格式，含：配方、
   **判据跑前写死**（建议：与臂 1/臂 2 的差值阈值、citation 命中阈值）、拒答/负样本设计
   （哪些文档故意不入库，考拒答守卫——参照 Open RAG Bench 的 39 题做法，manifest 里记 `is_hard_negative`）。
5. **跑批 + 判分 + 结果回填**：summary 出数字；**结果无论好坏都回填预注册结果段**——选择性报告=全部作废。

## 5. P2 FinanceBench 工作项（P1 验收后启动）

1. 语料为 SEC 申报文件（10-K/10-Q，单篇可达数百页）：先小批试解析估单篇耗时，排分批跑批；
2. **数值题判分口径**：FinanceBench 大量「FY2019 毛利率是多少」型题目，答案=数值+单位。两条路：
   优先用 `correctness_checks` 数值/关键词断言（改题不改判分器）；若必须动 `_GEVAL_STEPS`/rubric，
   **按 `judge_deepeval.py` 头部纪律：改口径=重跑 30 题 A/B 重钉基线**，并在预注册记录；
3. 表格密集：顺带在 summary 里单列表格题子集的正确率（table_lookup 卖点验证）；
4. 其余同 P1 第 4、5 步。

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
- [ ] P1：法域语料库建成（含索引），与官方文档清单对账记录
- [ ] P1：预注册文档（`docs/plan-legalbench-arms.md` 或并入本文结果段）判据跑前写死
- [ ] P1：全量跑批 + 同引擎判分 + summary；结果回填，好坏都报
- [ ] P1 收尾后输出「域接入清单」小节（下一步域照此复制），再启动 P2
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
