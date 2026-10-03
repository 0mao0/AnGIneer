# OfficeQA Pro 133 题接入预注册（本地回归压力集）

> 状态：**预注册（判据跑前写死，append-only，结果无论好坏都回填）**。
> 2026-10-03 立项：入集判定达标（逐条对 `docs/req-domain-bench-integration.md` §2.1 门槛 + §5.02 两必查，
> 证据快照 `data/scratch/officeqa-eval/`）。业主同日定性：**本地回归集，不进生产**（服务器磁盘不够）——
> 服务器数据层/评测页/生产复核全不碰，与「新域不接 nightly 定时」既有纪律零冲突。

## 1. 定位（为什么不挂金融系列）

- 数据上确实是第二个金融集，但**库内定位=历史档案检索-解析压力集**：题集标题 `【档案压力】OfficeQA Pro 133题`，
  题集卡 `domain=历史档案检索（美国财政部公报）`，仿 gdp-pdf-v1 先例（其 domain 写「多专业高难度」，能力定性非域定性）。
- 与 `financebench-open-150-v1`（守「读懂财报并作答」段、对外成绩单）分段互补：OfficeQA 守
  「大海捞针检索 + 扫描件表格解析 + 多步计算」段（筛库后仍 2–3.5 万页）。
- 对外只出一句话主张（「历史档案扫描件海量检索也能答对」），**数字不并列成第二个金融分数**；
  判分尺不同（数值容差 ≠ semantic judge），并排必口径误读。

## 2. 公开锚点（2026-10-03 逐一核实，引用必须带档位与日期）

| 档位 | 数字 | 口径与可比性 | 来源 |
|---|---|---|---|
| **主榜档（最新 harness 榜）** | Opus 5 60.9 / Claude Fable 5 60.9（08-02）；GPT-5.6 Sol 60.2 / GPT-5.5 57.1（07-20）；Opus 4.6 51.1 / GPT-5.4 41.4（3 月模型按最新 Pro 重跑）；Opus 4.7 46.6（非单调，实录）；Opus 4.8 48.9；Opus 4.5 38.4；Antigravity Gemini 3.1 Pro 39.1*；GPT-5.1 15.0；Gemini 3 Pro 3.0 | 全库 697 册 PDF + 全能力 agent（文件搜索+**联网**+代码执行），Pro 133 题、0% 容差。我们是**筛库 + 闭卷无联网**——只可并列引用，不同表 | 官方 README `figures/officeqa_pro_agent_harness_performance.png`（2026-10-03 easyocr 逐柱读，conf≥0.81；本地副本 `data/scratch/officeqa-eval/`） |
| 主榜档（2026-03 技术报告旧口径） | Opus 4.6 48.1（最高）/ GPT-5.4 High 36.1 / Gemini 3.1 Pro Preview 18.1；换解析器 ai_parse 50.4 / Docling 38.4 / unstructured.io 31.1 | 同上；同一模型与最新榜数字不同（48.1→51.1），**引哪档写哪档日期** | arXiv 2603.08655 正文（2026-10-03 全文实读） |
| 闭卷下界 | <5%（参数知识）；闭卷+联网 <12%（GPT-5.4 11.3） | 证「背不出答案」=污染风险低的实证 | 同上 |
| oracle 档（**对外禁引**） | 给定答案页：PDF 36–57%；Databricks 解析 66.9（Opus 4.6） | 非检索配置 | 同上 |
| agentbeats.dev 榜 | **不可当锚** | Full 246 题口径（≠Pro）、自报无审核、one-jump 一家同日 15 行 26.8→100% 刷分 | 2026-10-03 实抓 |

## 3. 配方（跑前写死）

| 项 | 定版 |
|---|---|
| 题集 | `officeqa-pro-133-v1`，官方 `officeqa_pro.csv` 133 题零自出；金标块 `numeric={"answer": 官方原文, "tolerance": 0.0}` |
| 判分 | `evals_core.runner.numeric_eval`：官方判分器 vendored（`officeqa_reward.py` @ 7b9a3c154ef9，逐字未改，Apache 2.0 署名）；**零判官调用**；主指标 = 0% 容差通过率（官方榜同尺），1% 容差档仅第二观测 |
| 语料 | 新库 `lib-officeqa`（开发机本地）；按 `source_files` 筛库（官方明示法），册数/页数以转换脚本实数回填 §3.1；生产式入库（fts+vectors），对账按核心链，软阶段失败不判死整篇 |
| 问答端 | 现役生产配方（被测模型=LLM_CONFIGS 默认档，与 FinanceBench run 同端点）；**无联网工具**（披露项 D1） |
| 运行 | 开发机「立即运行」，单实例判分（臂 2 纪律），触发前 /health 三连，run body 放仓库外 |
| 环境 | 本地专属：不进服务器、不进 nightly、不进 evals.sqlite 生产侧；对外引用注明「本地口径、生产未重建」 |

### 3.1 筛库实数（转换脚本跑完回填，不许拍脑袋）
- 引用册数：**191 册**（2026-10-03 实测；首跑 123 是坑——官方 README 称 source_files 用 `;` 分隔，Pro 实际是 **CRLF 换行**，
  只按 `;` 切会把多册题合成假 stem；转换脚本已改双分隔符重出）；multi_doc 题 **66/133**（跨册检索占比过半，捞针压力真实）。
- 页数合计：**24,705 页 / 191 册**（2026-10-03 pypdf 实数，0 册打不开；`data/officeqa/page_stats.json`）。
  PoPo 开发机经网关 4.2s/页 ÷ 并发 4 ≈ **7.2 小时**（仅 PoPo 段）；raw_parse（MinerU 并发 2）无扫描页基线，
  以入库驱动（`data/officeqa/ingest_driver.py`，在途窗口 8）前几册实测速率回填实况。
- PDF 落盘 `data/officeqa/pdfs/treasury_bulletin_pdfs/`（gated 已 auto 批准，开发机 hf 缓存凭据直取，未过手凭据）。

## 4. 判据（跑前写死，事后不改）

- **主指标** = 133 题 0% 容差通过率。
  - **≥40% 好**：筛库收益抵掉无联网损失，逼近官方 3 月全库档（48.1）；
  - **30–40% 过线**：合理带——无联网结构性白丢约 13pp（D1）对上筛库检索空间缩小的反向收益；
  - **<30% 差**：先归因再定罪——拆 hit@5(doc)（检索没找到）vs 检索命中仍答错（解析/计算断），两类修法不同，不许笼统说"管线差"。
- **健康红线（先于成绩判）**：`numeric_status` 出现 `SCORER_ERROR>0` 或 `NO_GOLD>0` → 本场作废，修完重跑（判分链必须零异常，确定性判分没有任何兜底借口，同判分兜底红线 eb017e9 纪律）。
- **检索参照**（非门禁）：hit@5(doc)（gold 册在 `source_files` 内）随场报告，供 <30% 档归因用。
- **拒答观测**：`Unable to determine` 题单列（官方判 0，我们同样计 wrong，不单设拒答率判据——官方榜也没这维度）。

## 5. 披露项（回填时逐项核）

- D1 ~13% 题官方标注需 web search（它声称：官方 blog/README，10-01 记录）——我们无联网，预期白丢。
- D2 ~3% 图表像素题各家全挂（技术报告 §5.3 失败模式）。
- D3 筛库口径 ≠ 官方全库：成绩**只能并列引用**，不得与 §2 任何档同表对比（[[baseline-preregistration-discipline]]）。
- D4 判分尺 = 官方确定性数值容差，与 nightly/FinanceBench 的 semantic judge 不同尺，跨题集不得互比。
- D5 本地口径：仅开发机复跑，生产未重建（业主 10-03 定性，服务器磁盘约束）。
- D6 License：数据 CC-BY-SA 4.0（对外成绩单挂 Databricks 署名），代码 Apache 2.0。

## 6. 动线（§9 域接入清单实例化，顺序即依赖）

1. HF gated 申请（**业主账户动作**：hf.co 登录 → `databricks/officeqa` → Request access，gated=auto 秒批）；
2. 下载 `officeqa_pro.csv` + 筛库 PDF → `data/officeqa/raw/`（HF_TOKEN 由业主环境持有，agent 不代持凭据）;
3. `scripts/build_officeqa_set.py`：CSV→bundle + 筛库清单 `data/officeqa/corpus_manifest.json`（只改格式不改判分）；
4. 语料入库 `lib-officeqa`（含索引）→ 与 manifest 对账（册数/页数），回填 §3.1；
5. `manager.import_bundle` 注册 → **手验 `eval_question` 行数 = 133**（§9 坑：build 脚本不注册）；本地读穿修复（ce34be6）在位，新库无需重启 aichat-api；
6. 试点 10 题：只看管道健康（SCORER_ERROR=0、NO_GOLD=0、空答清单、hit@doc），**不据此改配方**；
7. 正跑 133 题 + §4 健康核查；
8. 结果回填 §7（好坏都报）+ 披露项 D1–D6 实况化；
9. 对外主张一句话 + 判分口径脚注（自判≠官方 agent harness，非同一能力面）。

## 7. 结果（跑完回填）

（空）
