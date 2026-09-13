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

### 结论 1：我们全链在**四项指标上全部落后于 MinerU 单独**

MinerU 单独（我们自己的上游）就已经比"我们全链"好：文本 0.0476 vs 0.0813、表格 TEDS 0.9155 vs
0.8821、表格文字 0.0488 vs 0.5632、CDM 0.9585 vs 0.9509、阅读顺序 0.1371 vs 0.1503。

即：**在 markdown 交付面上，PoPo + Solo 这两个阶段目前是负贡献**。这里的"负贡献"仅指
markdown 口径的四个指标——PoPo/Solo 带来的结构信息（层级、块角色、表格 cells、caption 绑定、
图描述钩子）不在这套指标里，需要结构层口径与检索侧才能评价（结构层口径目前只覆盖我们全链）。

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
| `scripts/eval_parse_structure.py` | 结构层口径（jsonl 直比），见 `docs/parse-structure-eval.md` |

## 四、概念澄清（回答"OmniDocBench 是什么 / 那两个是不是现成功能"）

- **OmniDocBench 是文档解析质量基准**：1651 张标注页，评"文档图 → 结构化文本"的质量，端到端指标
  为文本 / 表格 / 公式 / 阅读顺序，另有专项子集（版面检测、公式识别、表格识别、OCR）。**它只评解析
  产物，不评检索、不评问答。**
- **VLM 图描述评测：不是它的现成功能。** GT 只存图注原文，没有描述的参考答案；要评只能自定义
  （覆盖率 + 抽样评估）。本仓库 pipeline 有 4.5 阶段 `figure_describe`（生产库覆盖率 92–100%），
  但**不在评测链的 5 个 stage 里**，故本对照中我们全链没有图描述（生产有）。
- **检索定向验证：也不是它的功能。** 现成可用的是 nightly 的 RAG 检索评测（hit@5 / MRR，跑在
  `lib-b07ed174`）；要验证"某批文档修好后能否被搜到"需要自写探针。

## 五、盲区与后续

1. 200/1651 页抽样，表格 73 张、公式样本更少，分类型数字只作线索；
2. MinerU 4.0.0a 预发布版未测（需单独 GPU 部署）；
3. 结构层口径目前只有我们全链的基线，MinerU 单独/参考模型无法在同一套结构指标下对比；
4. 本文件未验证检索侧效果（改产物后需重建索引方能看到）；
5. **下一步候选**：把 markdown 投影改成保留 HTML 表并复测（预期表格指标补齐）；定位文本指标
   0.0476→0.0813 的落差来源（Solo 的块重排/过滤/`plain_text_corrected` 改写）。
