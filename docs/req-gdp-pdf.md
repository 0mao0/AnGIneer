# GDP.pdf 基准集成与判分口径（预注册）

状态：**已集成，本地全量跑通**；未进 nightly、未同步生产。
结论：GDP.pdf 定位为**专业文档多模态 grounding 的能力体检集**（暴露图/表像素短板 + L4 长题空答），**不作对外计分榜**——口径与官方不可成表对比。

## 1. 来源与可得性（已核实）

| 项 | 内容 |
|---|---|
| 出品 | Surge AI，GDP.pdf benchmark（`https://surgehq.ai/benchmarks/gdp-pdf`），OpenAI 在 GPT-5.6 发布、Anthropic 在 Fable 5 system card 官方引用 |
| 构成 | 100 题，每题 1 份自带专业 PDF，10 域（工程/建筑/制造供应链/医疗/法律/金融投资/保险/地产/HR/STEM 各 ~7–15 题） |
| rubric | 每题 3–30 条判据（中位 11），`type` ∈ Primary Intent / Dodged Bullet；`severity` ∈ Certain/Possible/Unlikely dealbreaker |
| 官方判分 | rubric 全条通过（all_pass，headline）+ mean criteria；官方 judge = `google/gemini-3.5-flash`，5 epochs |
| 数据可得 | 官方 HF `surgeai/GDP.pdf` 已转私有（匿名/token 均 404）；改用社区镜像 `tolo6474/GDP.pdf`——**与 sleepyheeler/Oitaaa 三方 `data.parquet` sha256 逐字节一致（`2ba18b4f…`）锁定**；100 PDF 全部下载校验 |
| 本地真相源 | `data/gdp_pdf/raw/parquet_a.parquet` + `data/gdp_pdf/pdfs/`（100）+ `data/gdp_pdf/raw/pdf_manifest.json` |

## 2. 集成构件

- 判分器：`services/evals-core/src/evals_core/runner/rubric_eval.py`（`RubricEvaluator(AnswerEvaluator)`，复用问答链生成 + 判官逐条判 rubric；注册名 `rubric`）
- 派发：`suite_runner._determine_evaluator_names` 带 `rubric_gold` → `["rubric"(,"retrieval")]`，rubric 恒为 primary（防检索分顶成假绿）
- 入库字段：`eval_question.rubric_gold`（新增列，`_ensure_eval_question_columns` 自动迁移）；`schema.py` 加 `rubric` 块；`manager` 透传
- 脚本：`scripts/gdp_pdf/{import_docs,build_bundle,pilot_run}.py`；入库库名 `GDP-PDF`（本机 `lib-0a1f1335`）
- 题集：`data/evals/datasets/gdp-pdf-v1.json`（100 题，已导入 evals 库，100/100 带 rubric_gold）
- 题集卡 meta：`build_bundle._card_meta`（发布方/测试类型/喂法=单篇RAG/简介/来源/按域 distribution/官方 leaderboard）
- 层级分布真相源：`scripts/gdp_pdf/classify_levels.py` → `raw/levels.json`，用**生产同款 `IntentClassifier`** 逐题判（非手工）；build_bundle 消费回填 `intent_level`。本集结果 **L1 36 / L2 5 / L3 8 / L4 51**（L4 偏多=GDP 长多步专业题，也是 §5 空答集中的路径）
- 结果件：`data/gdp_pdf/pilot_result_full.json`

## 3. 判分口径（预注册，勿改后追比）

- **headline = all_pass**（所有 rubric 条通过→quality=correct，否则 wrong）；**mean_criteria**（通过比例）作部分分观测。
- **判官 = 自家候选链（Qwen3.8-Flash-Next，temp 0.1）**，与全套评测同一噪声口径；**未对齐官方 gemini**。判官为旋钮：`pilot_run --judge <配置名>` / 题集 `judge_config_name`；要贴官方数需先在 LLM_CONFIGS 配官方端点，且仍不改系统侧口径。
- **分批判官**：rubric 按 `GDP_RUBRIC_BATCH`（默认 8）切批逐批判、全局序号合并；仅全批失败才 JUDGE_FALLBACK（→score=None→skipped，不假绿）。实测 29 条题从 207s 超时崩→63s 判全、0 崩。
- **系统口径 ≠ 官方**：官方=整本 PDF 直读多模态模型、全库检索；我们=解析入库→检索→生成、且每题 `doc_ids` 锁到其 1 份 PDF（**oracle-doc**，检索命中 100% 是必然、不代表检索力）。**成绩只能与官方榜并列引用，不得成表对比。**

## 4. 全量结果（100 题，本机进程内，判官 Qwen3.8-Flash-Next）

总：all_pass **3%**、mean_criteria **30.1%**、拒答 24、空答 9、检索命中 100%、判官崩 0。
（官方同 headline frontier all_pass 25–31%，且为多模态整本直读——见 §3 口径差。）

| 域 | n | all_pass | mean | 拒答 | 空答 |
|---|---|---|---|---|---|
| Insurance | 9 | 1 | 0.44 | 2 | 0 |
| Finance/Investing | 9 | 1 | 0.42 | 2 | 1 |
| STEM/Research | 15 | 0 | 0.36 | 5 | 1 |
| Construction | 10 | 1 | 0.31 | 1 | 3 |
| Real Estate | 10 | 0 | 0.31 | 2 | 0 |
| Engineering | 10 | 0 | 0.30 | 3 | 0 |
| Healthcare | 11 | 0 | 0.30 | 3 | 2 |
| Manufacturing/供应链 | 10 | 0 | 0.24 | 3 | 0 |
| HR | 9 | 0 | 0.14 | 3 | 1 |
| Legal | 7 | 0 | 0.13 | 0 | 1 |

**读法**：成败高度取决于**答案在正文/表格文字里还是在图/表示意图像素里**。文本/条款型（保险、金融报告、部分医疗）mean 0.30–0.44、含 3 道 all_pass 满分（建筑许可 18/18、迪士尼年报 17/17、保险费率计算 12/12）；图/表像素型（制造 0.24、法律 0.13、HR 0.14）系统性偏低。all_pass 因 LLM 判官逐条严（差 1 条 dealbreaker 即判 0），对内看 mean_criteria 更有意义。

## 5. 空答根因（9 题，`answer_len=0` 且非拒答）

链路诊断：`llm_error_count=0`、`retrieved_items≈29`（检索正常），`trace_notes` 关键两行——
`上下文预算超阈值，停止继续调用工具（should_stop）` + `生成结束：本轮未产出首字（按边界规则收尾）`。
即长而多步的专业题被意图分类判成 **L4 → dynamic_orchestration**，agent 工具/二排循环烧光上下文预算，最终生成无首字→空。**属 angineer-core L4 编排行为被 GDP 长提示触发，非 GDP 集 bug**；修它（预算护栏/降级到直答）是 angineer-core 的后续活，本集先如实记账。

## 6. 评测页 run 与漏项根因（2026-10-02）

- **评测页 run `run-d9d2f0460430`**（100 题，HTTP 链路，服务重启加载新码后）：all_pass **3%**（correct 3 / wrong 97 / skipped 0）、mean_criteria **31.1%**、judge_failed 0、final_outcome = model_answer 59 / model_refusal_kept 19——**与进程内试点（§4）对账一致**，证明评测页 rubric 判分路径正常。
- 逐域 all_pass：金融 2/9、建筑 1/10、其余 0；mean 最高金融/地产 0.37、最低法律 0.16。
- **近满分池**（mean≥0.5 未全过）25 题、100 条失败判据：**79/100 是"漏项"**（判据要求"列全所有 X"，模型只列部分）、25/100 答错或负向判据（Dodged Bullet）违反、**仅 7/100 属图/地图类**（结构性不可做）。
- **3 题回放定根因**（比对缺失项在【检索证据】vs【canonical 全文】的有无）：**2/3 = 检索漏**（全文有、检索没取到 → 模型拒答/少答），1/3 = 模型漏（半拒答，证据不足支撑枚举）。
- **实验：只调 `ANGINEER_CONTEXT_TOP_N`（15/30/50）→ 无效**：缺失关键词三档下均未进证据（覆盖恒 False）、n_pass 不动；env 确已生效（证据数 15→35）。⇒ 瓶颈**不在 15 条上下文截断，在候选未召回**。
- 更正记录：曾据回放输出误称"表格没喂"——实际表格以 `table_summary`（其 text=整表 `art.full_text`）进候选、本就参与检索（`table_retriever.py:427`、`sparse_retriever.py:233`）。
- 结论：改进点在**召回/候选生成**（长问题语义稀释 → 细节块排不进 top-k）；方向 = 长问题多子查询分解 / 枚举型意图自适应扩样（angineer-core 检索编排）。

## 7. 未做 / 待办

- 官方「整本 PDF 多模态直读」参照臂未做（那才逼近官方口径，但就不是我们产品链路了）——若要出对外可比数需另立臂。
- 召回改造未做：长问题多子查询分解 / 枚举型自适应扩样（§6 实验证明只调 `ANGINEER_CONTEXT_TOP_N` 无效）。
- 5 epochs 未跑（单次，含生成端噪声，参照 nightly 噪声地板纪律，趋势判断需配对/多采）。
- 未进 nightly、未同步生产（生产同步=push evals-core 新码 + 服务器建库导 bundle + doc_id 按 doc_name 对账，需授权）。
