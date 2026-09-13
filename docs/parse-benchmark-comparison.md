# 三方解析质量对比（同批 200 页）+ 表格文字差距归因

2026-09-13。样本：`data/evals/omnidocbench/predictions_eval200` 的 200 页（OmniDocBench v1.6 的
`--limit 200 --seed 42` 抽样）。口径：**官方 markdown 口径**（预测交 `content.md`/等价 markdown，
官方镜像 `ghcr.io/zeng-weijun/omnidocbench-eval:repro-ubuntu2204` 评分），三方同尺。

## 一、三方数字

| 指标 | 参考模型<br>`chutao__mu936_grpo_800_260328` | **MinerU 3.4.5 单独**<br>(hybrid) | 我们全链<br>(MinerU 3.4.5 + PoPo + Solo) |
|---|---|---|---|
| 文本 Edit_dist | **0.0344** | 0.0476 | 0.0813 |
| 表格 TEDS | 0.9097 | **0.9155** | 0.8821 |
| **表格内文字 Edit_dist** | 0.0682 | **0.0488** | **0.5632** |
| 公式 CDM | **0.982** | 0.9585 | 0.9509 |
| 公式 Edit_dist | **0.0687** | 0.0976 | 0.1116 |
| 阅读顺序 Edit_dist | **0.1168** | 0.1371 | 0.1503 |

（方向：Edit_dist 越低越好，TEDS/CDM 越高越好。参考模型覆盖 199/200 页，其余两方 200/200，
该页差异可忽略。）

### 版本标注

| 方 | 版本 | 来源 |
|---|---|---|
| MinerU 3.4.5 单独 | **3.4.5 / backend=hybrid** | 每篇 `mineru_raw/middle.json` 的 `_version_name`，200/200 一致；官方 Releases 里 `mineru-3.4.5-released` 即最新正式版（4.0.0a6 为预发布，未测） |
| 我们全链 | 同上 MinerU 3.4.5 + PoPo + Solo（`use_llm=False`） | 同一次解析的产物，链内两个阶段另计 |
| 参考模型 | 未知 | 官方镜像自带预测目录 `data_md/v1.6/chutao__mu936_grpo_800_260328`；不在 OmniDocBench 官方榜单（README 已核对），**命名疑似 MinerU 家族 + GRPO 微调，未证实** |

## 二、两个重要结论

### 结论 1：markdown 交付面上，我们全链落后于自己的上游 MinerU

MinerU 单独（我们自己的上游）在 markdown 口径四项里都比"我们全链"好：文本 0.0476 vs 0.0813、
表格 TEDS 0.9155 vs 0.8821、表格文字 0.0488 vs 0.5632、CDM 0.9585 vs 0.9509、阅读顺序 0.1371 vs 0.1503。

即：**在 markdown 交付面上，PoPo + Solo 目前是负贡献**。但请注意这套口径量的是"markdown 长什么样"，
**不是 RAG 检索吃的那层**——RAG 那层的结论见下面第五节，方向相反。

### 结论 2：表格文字差 8 倍，根因是 **markdown 投影把 HTML 表降级成管道表**

| 证据 | 数据 |
|---|---|
| 官方口径表格文字 Edit_dist | 我们 0.5632 / MinerU 单独 0.0488（差 11.5 倍） |
| 我们在 jsonl 层复算（`table_html` vs GT html 扁平比较） | **0.0946**——表格数据本身没问题 |
| 表格写法普查（66 页有表内容） | 我们 `content.md`：**0 页 HTML 表 / 54 页管道表**；MinerU 自己的 md：**54 页全是 HTML 表** |
| 逐格归因（73 张配对表） | 完全一致 61 / 网格维度不同 9 / 维度同但内容异 3 |

管道表（`| a | b |`）**表达不了 `rowspan`/`colspan`**，合并单元格在投影时被展平/重复；官方评测器
再把 markdown 转回 HTML 与 GT 比，结构对不齐 → 表格 TEDS 与表格文字 Edit_dist 双双受损。

因此表格的短板**不是识别问题，是我们自己交付格式的选择问题**。参考模型与 MinerU 都输出 HTML 表，
所以它们的表格文字指标天然好一个数量级。

代价权衡（尚未决策）：管道表在编辑器/预览里更可读，HTML 表在评测与"表格结构保真"上更好。
若把投影改成 HTML 表，预期表格指标接近 MinerU 单独的水平，但会影响前端 markdown 编辑体验。

## 三、归因工具

| 脚本 | 用途 |
|---|---|
| `scripts/collect_mineru_markdown.py` | 从各篇 `mineru_raw/origin.zip` 提取 MinerU 自带 markdown（step03 解压后会它被 Solo 投影覆盖，必须回 zip 取），顺带留痕版本 |
| `scripts/analyze_table_text_gap.py` | 逐表网格对比（复用 step04 的 `parse_table_grid`），分类 dims_diff / style_only / content_diff，并复算扁平编辑距离与官方口径对表 |
| `scripts/eval_parse_struct.py` | 结构层口径（jsonl 直比），`--pred-source mineru` 可切到 MinerU 原生 content_list，见 `docs/parse-struct-eval.md` |
| `evals_core/parse_struct/mineru_raw.py` | MinerU 原生 content_list → 结构层块 的映射（类型表 + 坐标 /1000） |

## 四、结构层口径（RAG 真正消费的那层）：MinerU 原始块 vs 我们全链

同一批 200 页、同一套 harness（`--pred-source mineru` vs 默认 `chain`）：

| 指标 | MinerU 原生块 | 我们全链 | Δ |
|---|---|---|---|
| 块召回率 | 77.8% | **88.2%** | **+10.5 个点** |
| 预测块被解释率 | 82.0% | **90.6%** | +8.6 |
| 块文本相似度（全部） | 0.6308 | **0.7469** | +11.6 |
| 块文本相似度（命中项） | 0.8384 | **0.8545** | +1.6 |
| 表格 TEDS | 0.9172 | 0.9172 | 0 |
| 公式相似度 | 0.6726 | 0.6726 | 0 |
| 阅读顺序（相邻对 / tau） | 97.3% / 0.9272 | 97.3% / **0.9294** | ≈0 |

**分项增益主要来自标题分类**：GT 有 510 个 `title` 块，MinerU 原生 content_list 里**没有 title 类型**
（标题一律 `text`），所以它 title 召回 0%；我们 78.0%（文本 0.940）。表格标题文字我们也更好
（0.848 vs 0.729）。其余类目两边持平。

**结论（与 markdown 口径相反）**：**在 RAG 检索依赖的结构层，PoPo + Solo 是净增益——块找得更全
（+10.5 个点）、标题可识别，文本/表格/公式/顺序没有退步。** markdown 面的"退步"是投影格式造成的
（管道表），不是结构能力问题。

### 量法修正记录（这三处曾产出过错误结论，留痕以免后人踩）

| 症状 | 真相 | 处置 |
|---|---|---|
| 图注召回 10.7%（MinerU 54.7%） | 我们的图注文本落在 `plain_text`，而匹配只读 `caption` 字段；逐条核查 75 条 GT 图注有 52 条文本确实存在 | `plain_text` 也作为 caption 候选 → 54.7%，与 MinerU 持平 |
| 图脚注召回 11.8%（MinerU 52.9%） | 同上；17 条 GT 图脚注里 16 条文本存在于我们产物 | `plain_text` 同时作 caption/footnote 候选 → 52.9% |
| 公式相似度 0.87 vs 0.50 | 一是公式跨 GT 块分组把多行拼成一条比，二是两侧取字段不同（MinerU 取 LaTeX、我们取 plain_text） | 公式不跨块分组 + 统一取 math 字段 → 两边均 0.6726 |

## 五、概念澄清（回答"OmniDocBench 是什么 / 那两个是不是现成功能"）

- **OmniDocBench 是文档解析质量基准**：1651 张标注页，评"文档图 → 结构化文本"的质量，端到端指标
  为文本 / 表格 / 公式 / 阅读顺序，另有专项子集（版面检测、公式识别、表格识别、OCR）。**它只评解析
  产物，不评检索、不评问答。**
- **VLM 图描述评测：不是它的现成功能。** GT 只存图注原文，没有描述的参考答案；要评只能自定义
  （覆盖率 + 抽样评估）。本仓库 pipeline 有 4.5 阶段 `figure_describe`（生产库覆盖率 92–100%），
  但**不在评测链的 5 个 stage 里**，故本对照中我们全链没有图描述（生产有）。
- **检索定向验证：也不是它的功能。** 现成可用的是 nightly 的 RAG 检索评测（hit@5 / MRR，跑在
  `lib-b07ed174`）；要验证"某批文档修好后能否被搜到"需要自写探针。

## 六、对外说法（给社区使用者）

我们公布两组数字，**口径、参赛者、可比范围都不同，引用时请连着口径一起引**：

评测体系共三层：

| 层 | 名字 | 口径 | 参赛者 | 能不能对外比 |
|---|---|---|---|---|
| 1 | **OmniDocBench**（官方） | 官方 markdown | 参考模型 / MinerU 3.4.5 / AnGIneer | ✅ 可与任何能输出 markdown 的系统比。注意本镜像**只接了 end2end**，版面检测/表格识别/公式识别等专项配置存在但未接线 |
| 2 | **ParseStruct**（我们自建） | 块级几何对齐 | MinerU 原生 content_list / AnGIneer jsonl | ⚠️ **不可**与官方榜单数字混用；只用于回答"RAG 依赖的那层还原得如何" |
| 3 | **Nightly-OpenRAG**（我们自建） | 问答 + 检索命中 | 任何跑在评测语料上的系统 | 内部使用（语料/题集自持） |

三条引用规范：

1. **数字必须带齐三样**：口径名 + 版本 + 样本。例：`OmniDocBench end2end，MinerU 3.4.5/hybrid，200 页 seed 42 抽样`；
2. **不跨口径推断**：markdown 分数不得用来推断检索质量；结构层分数不得声称为官方成绩；
3. **甲的表只有 MinerU 与我们可以同台**（参考模型没有位置信息，上不了乙；反向同理）。甲三方同台、乙两方同台，是固定的，不要混着讲。

为什么除了官方口径还要自建乙：OmniDocBench 端到端吃 markdown，而**RAG 检索吃的是块/索引层**
（canonical chunk + FTS/向量）——层级、块角色、位置在 markdown 里表达不了或会丢。官方镜像的专项任务
未接线，所以我们自建了等价口径，脚本、口径定义、已知量与踩过的坑全部公开（本文第五节 +
`docs/parse-struct-eval.md`），欢迎复现与质疑。

## 七、盲区与后续

1. 200/1651 页抽样，表格 73 张、公式样本更少，分类型数字只作线索；
2. MinerU 4.0.0a 预发布版未测（需单独 GPU 部署）；
3. 结构层口径目前只有我们全链的基线，MinerU 单独/参考模型无法在同一套结构指标下对比；
4. 本文件未验证检索侧效果（改产物后需重建索引方能看到）；
5. **下一步候选**：把 markdown 投影改成保留 HTML 表并复测（预期表格指标补齐）；定位文本指标
   0.0476→0.0813 的落差来源（Solo 的块重排/过滤/`plain_text_corrected` 改写）。

## 八、已修：markdown 投影保留 HTML 表（2026-09-13）

按上面的归因把 `markdown_projection._render_table` 改成默认直接落 `table_html`（保留 rowspan/colspan），
`build_faithful_markdown(..., html_tables=)` 保留开关可回滚。**A/B 实测**（同批 54 页含表格页，官方评测器）：

| 指标 | 管道表（原） | HTML 表（现） | Δ |
|---|---|---|---|
| 表格 TEDS | 0.8821 | **0.9155** | +0.0334 |
| 表格 TEDS_structure_only | 0.8985 | **0.9324** | +0.0339 |
| 表格文字 Edit_dist | 0.5632 | **0.0488** | −0.5144（11.5 倍） |
| 文本 Edit_dist | 0.0596 | 0.0596 | 0 |

HTML 表后的表格成绩**与上游 MinerU 单独持平**（0.9155 / 0.0488），即 markdown 面此前唯一的短板补平。

风险已核：前端本就支持后端 HTML 表（`docs-ui` 的 `renderTableHtmlToInlineHtml` 按结构原样渲染，
markdown 行内渲染器对 HTML 表格标签有保护分支），`table_lookup` 亦以 HTML 表为主路径、管道表为次路径。

注意：**存量 content.md 不会自动变**——投影在解析阶段执行，旧文档需重新投影（可只重跑投影、不必重跑解析），
本次评测语料的数字用的是重新投影后的预测。
