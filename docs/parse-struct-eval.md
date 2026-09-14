# ParseStruct：结构层解析评测（jsonl 口径）

## 评测体系：A / B / C 三层

按"**验证对象**"划分（不是按工具划分）——pipeline 的产物本体是 jsonl，markdown 是它的投影：

| 层 | 验证对象 | 口径 / 工具 | 输出形态 | 台上选手 |
|---|---|---|---|---|
| **A. 解析结果质量** | pipeline 的产物（jsonl 本体 + 它的 markdown 投影） | ① 官方 OmniDocBench 口径（jsonl→markdown，别人的评测器）<br>② **ParseStruct / ParseStructComparison**（jsonl 块层，我们的脚本） | 分数 | ① 三方：参考模型 / MinerU 的 md / 我们的 md<br>② 两方：MinerU **原生 content_list** / 我们的 jsonl |
| **B. 素材传递性** | jsonl → canonical → chunk → 向量 | 覆盖率与一致性断言（**已固化进 nightly**，见下） | **缺失清单**（不是分数） | 只有我们 |
| **C. 端到端效果** | agentic chat | nightly_openRAG（检索命中 + 答对） | 分数 | 跑在评测语料上的任何系统 |

### 三条使用纪律

1. **A 的两个口径并列报，不能互相替代**。同一个 GT，两种刻度：ParseStruct 量 jsonl 本体；
   官方 markdown 口径量"jsonl + 投影"。差值本身是有效信息——**差值 = 投影损耗**
   （实测：表格 TEDS 0.9172 vs 0.8821，差的 3.6 个点就是 HTML 表被拍成管道表造成的，改投影后两者追平）。
   官方 markdown 口径同时兼任 **markdown 交付面**的验收（markdown 有自己的消费者：前端预览/编辑、
   导出、step07 图谱抽取、agent 的 table_lookup），不只是 jsonl 的影子。
2. **参考模型只在 A① 能上场**（它只吐 markdown、没有坐标）；MinerU 两个台都能上，但用的是它**不同的产物**
   （A① 用它的 markdown、A② 用它的原生 content_list）——所以"MinerU 的分数"必须带口径。
3. **B 是断言不是评测**：它答"内容有没有原样送到检索层"，答不了"chunk 边界切得对不对"、
   "section_path 语义对不对"（这两件三层都答不了，因为没有对应标注）。所以 B 的产物是缺失清单，
   适合做 CI 断言，不必做成常设分数体系。

### B 的固化位置（2026-09-13）

| 项 | 内容 |
|---|---|
| 实现 | `evals_core/material_parity.py`（数据源可注入，单测不碰真实 DB） |
| 运行 | `evals_core/nightly/pipeline.py` 的 `_material_health` 步骤：每晚评审**开跑前**先跑，best-effort——体检自身失败只记日志，不影响结论，也不侵入解析链 |
| 配置 | `data/evals/nightly_settings.json`：`parse_health_enabled`（默认 true）、`parse_health_libraries`（默认 [] = 全部库）、`parse_health_max_docs`（默认 200，按产物修改时间倒序） |
| 产物 | `data/evals/nightly/<date>/material_parity.json|md`（含每篇缺失清单） |
| 告警 | severity ∈ {warn, fail, error} 时额外推一条企微到 SYSTEM 群（不改动原有结论消息） |
| 手动复查 | `python scripts/run_material_health.py --libraries <lib> --max-docs N [--json out.json]`；退出码 0=ok / 1=warn,fail / 2=体检失败，可接 CI |

**检查项**（逐文档）：① 内容落地（`content_json` 有文本而 `plain_text` 为空）；② 块→chunk 覆盖
（块文本是否出现在该文档的 chunk 文本里，空白无关、取前 24 字符，容许 2% 缺口）；
③ chunk→向量（有 chunk 而向量点为 0）；④ 索引存在（canonical 有无记录）。
**按设计不入索引的块不参与 ②**：页眉/页脚/页码、`layout_category=furniture`、`is_active=0`
——不排除会造成 94% 的假阳性（实测：default 库未覆盖率 3.3% → 0.19%）。

**② 的探针取 `plain_text_corrected or plain_text`**（2026-09-14）：链路构建 canonical/chunk 时
优先消费 PoPo 校正后的字段，只比 `plain_text` 会把"被校正改写过的块"一律报成未覆盖。实踩：
一篇论文的 4 个公式块因 PoPo 把左端 `V_{s}=` 校正成 `V=` 而全部失配（前 24 字符探针必然打不中），
改用 corrected 后 **0 失配**——内容确实送达了检索层，只是以校正后的形式。

**符号改动单列报出（不计 fail）**：`symbol_mismatch`（链路自己打的标）表示 PoPo 校正改动了
公式符号，属**数据质量信号**——`V_{s}` → `V` 丢下标，语义变了。体检每晚报计数与样例
（`blocks_symbol_mismatch` + `symbol_mismatch_samples`，进摘要与结论卡片那一行），
但**不判 fail**：它答的是"校正对不对"，不是"内容有没有送到"。

**④ 只对"计划建索引"的文档断言**（2026-09-14，判定依据是 `doc_parse_stages` 的事实，不是排除名册）：

| 阶段事实（`fts` 行） | 处理 |
|---|---|
| 无记录（只跑部分阶段入库，如评测库） | **豁免并计数**（未计划建索引，不是缺陷） |
| 状态 `skipped` | 豁免并计数（明确不适用） |
| 状态 `completed` 但 canonical 无行 | **照报**（状态说建完、实际没写进去） |
| 状态 `running`/`pending`/`failed`/`partial` | **照报**（中断未完成） |

为什么这么定：服务器上的 `omnidocbench` 评测库只跑 5 阶段（`run_omnidocbench_eval.py` 的 `PARSE_STAGES`
不含 `fts`/`vectors`），却在每晚的素材检查里固定报 11 篇"未索引"；而 `default` 库那篇
《JTS 154-2018 防波堤与护岸设计规范》是真的被服务重启打断 fts、索引被清空（状态卡在 `running`）——
**同一套断言必须能同时区分这两者**，按库加白名单做不到（白名单会让该库的真问题也永远隐身）。
豁免**不可静默**：篇数同时进摘要文本与 nightly 结论卡片那一行，否则 stage 记录被弄丢时体检会静默转绿。

首次真实运行发现（2026-09-13，各取最近 10-12 篇）：

| 库 | 内容未落地 | 块→chunk 未覆盖 | severity |
|---|---|---|---|
| default | 27 块 | 31/15923（0.19%） | fail |
| lib-b07ed174（nightly 语料） | 181 块 | 25/3335（0.75%） | fail |
| omnidocbench（修复后重解析） | **0** | **0/108** | **ok** |

生产两个库的"内容未落地"是**修复前解析的存量产物**（那五类块当时被整类吃掉），重新解析后才会消失
——体检会在每晚提醒这个积压，这正是它该做的事；若**新**解析文档仍报此项，则是链路回归。

命名约定：**ParseStruct 是我们自建口径的名字，不可声称为 OmniDocBench 官方分数**。

## 为什么要另建一套口径

官方 OmniDocBench 端到端评测只吃 **markdown**：把我们的 `content.md` 交给官方评测器，由对方的
正则把 markdown 再切回块，位置是**字符偏移**，再与 GT 的块（真 bbox）匹配。它量的是
「交付的 markdown 有多好」，而 **RAG 检索吃的是 canonical jsonl / SQLite / 向量那一层**——
块层级、section_path、chunk 边界、表格检索表示在 markdown 里根本不存在，官方口径一个都不量
（详见 `docs/omnidocbench-baseline.md` 的口径说明）。

本口径不绕 markdown：直接拿 `doc_blocks_graph.jsonl` 的块（真 bbox）与 GT 的 poly 做**几何对齐**，
量 RAG 真正依赖的那层。**不需要 18GB 镜像、不需要 GPU、不重跑解析**（读已落盘产物，200 页跑完约 2 分钟）。

## 怎么跑

```bash
python scripts/eval_parse_struct.py \
    --state data/evals/omnidocbench/predictions_eval200/state.json \
    --out data/evals/omnidocbench/result_jsonl200
# 可选：--gt <OmniDocBench.json> --library-dir <documents 目录> --iou-min 0.3
#       --filter-prefix <文件名前缀> --limit <页数>
```
产物：`structure_result.json`（逐页明细）+ `structure_report.md`（报告）。

## 口径定义

| 环节 | 规则 |
|---|---|
| 页 ↔ 文档 | `state.json` 的 page_id → doc_id；缺失时按 `source/` 文件名兜底 |
| 坐标 | GT `poly`（扁平列表）→ bbox，按 `page_info.width/height` 归一；我们的 `bbox` 本身就是 0–1 归一 |
| 类目映射 | GT 类目 → 我们的 `block_type`，见 `parse_struct/categories.py`；caption/footnote 按**父块指针**映射（我们是 paragraph 块 + `caption_block_uid`） |
| 匹配 | IoU ≥ 0.3，或预测块中心落在 GT 框内，或 GT 框被预测块覆盖 ≥ 60%（三条并集，应对两侧块粒度不一致） |
| caption 匹配 | 边距放宽到 6%（caption 贴在表/图外面，且我们多数情况下没有它的独立 bbox） |
| 文本比较 | 覆盖分组后两侧各自拼接，再算归一化编辑距离，分母取较长者（恒 0–1） |
| 表格 | 官方 TEDS，**HTML↔HTML 直比**（不过 markdown，vendor 见 `parse_struct/_vendor/omnidocbench/`） |
| 公式 | LaTeX 去风格化（去空白/花括号/`\left`/转义）后串比对，**非 CDM** |
| 阅读顺序 | 匹配块的 GT `order` vs 我们的 `block_seq`：相邻对顺序正确率 + Kendall tau |
| 分母 | GT 侧只进"我们有对应类目"的类目（`categories.py` 的 `UNMAPPED_GT` 排除）；我们侧排除 `UNMAPPED_OURS` |

**关键设计：覆盖分组**。两侧块粒度经常不一致（实测：GT 把公式数组按行标 7 个
`equation_isolated`，我们合成 1 个块）。逐块硬比会把"整段 vs 单行"算成全错（公式一度只有 0.07），
故把互相覆盖的 GT 块归为一组、两侧各自拼接后再比一次。

## 基线（200 页，2026-09-12）

### 总览

| 指标 | 值 | 说明 |
|---|---|---|
| 块召回率 | **87.2%** | GT 待评块 3634 个命中 3170 |
| 预测块被解释率 | 90.4% | 我们 3852 个可评块中参与匹配 3484（低=多出块） |
| 块文本相似度（命中项） | **0.8479** | 只看匹配上的块＝识别质量，n=2666 |
| 块文本相似度（全部） | 0.7290 | 漏检块按 0 计入，n=3101 |
| 表格 TEDS | **0.9183** | HTML↔HTML 直比，n=74 |
| 公式相似度 | 0.4939 | LaTeX 去风格化串比（非 CDM），n=150 |
| 阅读顺序（相邻对 / tau） | **97.5% / 0.9321** | 193 页 |

### 按类目

| GT 类目 | GT 块数 | 召回率 | 文本相似度(命中项) | 表格 TEDS |
| --- | --- | --- | --- | --- |
| text_block | 2006 | 95.0% | 0.8392 | — |
| title | 517 | 77.4% | 0.9399 | — |
| header | 243 | 72.8% | 0.9250 | — |
| equation_isolated | 200 | 99.0% | 0.5006 | — |
| page_number | 145 | 89.7% | 0.9518 | — |
| figure | 139 | 92.1% | — | — |
| footer | 103 | 86.4% | 0.9489 | — |
| figure_caption | 75 | **10.7%** | 0.8636 | — |
| table | 74 | 100% | — | **0.9183** |
| table_caption | 53 | 58.5% | 0.8703 | — |
| table_footnote | 24 | 83.3% | 0.8653 | — |
| page_footnote | 17 | 35.3% | **0.0000** | — |
| figure_footnote | 17 | **11.8%** | 0.0805 | — |
| list_group | 13 | **0.0%** | — | — |
| code_txt | 8 | 25.0% | 0.0000 | — |

### 按文档类型

| data_source | 页数 | GT 块 | 召回率 | 文本相似度 | 表格 TEDS | 顺序相邻对 |
| --- | --- | --- | --- | --- | --- | --- |
| PPT2PDF | 37 | 211 | 0.777 | 0.6716 | 0.9429 | 0.983 |
| book | 36 | 517 | 0.863 | 0.7550 | 0.9974 | 0.966 |
| academic_literature | 23 | 384 | 0.935 | 0.7403 | 0.8808 | 0.994 |
| newspaper | 20 | 1150 | 0.888 | 0.7153 | 0.7879 | 0.976 |
| colorful_textbook | 19 | 274 | 0.821 | 0.6973 | 0.9475 | 0.965 |
| exam_paper | 19 | 378 | 0.913 | 0.7244 | 0.9780 | 0.990 |
| research_report | 19 | 215 | 0.884 | 0.8257 | 0.9258 | 0.953 |
| magazine | 18 | 273 | 0.813 | 0.7112 | — | 0.975 |
| note | 12 | 199 | 0.965 | 0.8701 | 0.9814 | 0.993 |
| historical_document | 1 | 33 | 0.182 | 0.1368 | — | 0.600 |

## 这套口径查出的问题（按优先级）

1. **caption 图注大面积没落地**：`figure_caption` 召回仅 10.7%（75 个只捕到 8 个）、
   `table_caption` 58.5%。我们的 caption 多数不是独立块，而是父节点的 `caption` 文本字段
   （实测 200 篇：250 个表图节点里 15 个有指针块、50 个只有文本字段）——RAG 侧图注是重要的上下文，
   值得补成正式块。根因（2026-09-12 代码核查）：caption 文本**只**来自 MinerU 的 `image_caption`
   字段（`solo_engine.py` 的 `extract_plain_text` image 分支），MinerU 不给就没有任何几何兜底
   （`collect_media_related_block_refs` 的 needles 为空即直接 return）。另注：VLM 图描述属独立
   stage `figure_describe`，**不在评测链的 5 个 stage 里**，故本轮评测完全没有图描述（生产有，
   落 `figure_description`，canonical 会与 caption 拼接进可检索文本）。**此项未修。**
2. **`page_footnote` 等 5 类块的文本被链路吃掉（已修，本次）**：`extract_plain_text` 缺
   `chart` / `page_footnote` / `page_aside_text` / `code` / `algorithm` 五个分支，落到末尾
   `return ""` → `plain_text` 为空 → `build_node_text` 无 content_json 兜底 → canonical chunk 为空
   → **FTS/向量索引里没有这段**；markdown 投影同样只读 plain_text，也不含。实测受影响：评测语料
   209 篇中 **54 块**重获文本（chart 22、旁注 20、参考脚注 6、代码 5、算法 1），合计约 7100 字符。
   修复后原有 `page_footnote` 的"召回 35.3% / 文本相似度 0.0000"这类假差会消失。
   **注意：存量解析产物与本文基线数字均为修复前口径，需重新解析才会变。**
2b. **上述修复的检索侧验证（2026-09-13，由本项目自测——OmniDocBench 不具备检索/FTS 能力）**：
   这 25 篇此前**从未建过索引**（评测用的 5 阶段链不含 `fts`/`vectors`）。用生产入口
   `build_sqlite_index_from_graph` + `rebuild_document_vectors` 重建后自测：
   - 目标文本进入 `canonical_chunks.text_clean`：抽样 8/8；
   - **全库不限定文档**的关键词检索（生产函数 `search_chunk_fts`，CJK bigram + BM25）：
     **12/12 进前 100，其中 10 篇第 1**；
   - **语义检索**（Qdrant 向量，生产 embedding 链）：**10/12 进前 10，其中 10 篇第 1**；
     两个非第 1 的案例是查询本身歧义（单字旁注"卷"）与通用片段（"(a) original data" 在别处重复），
     非检索失败——这两条内容在向量库中确认存在；
   - **因果反证**：把 chart/page_footnote/page_aside_text/code/algorithm 的 `plain_text` 置空后
     重建 canonical，探针字符串从 chunk 文本消失（4/4）——可检索性来自本次修复。
   - **本验证的边界**：① 自建探针，非基准；② 只证明"内容被两种检索召回"，**不衡量端到端检索质量**
     （hit@5、问答正确率需要带 gold 的问题集，OmniDocBench 提供不了，要用 nightly 那类体系）；
     ③ 探针查询串须用完整文本——实测截断到 30 字符会让一篇排第 1 的内容掉出前 10（假阴性）。
   复现脚本：`scripts/reindex_parse_docs.py`（重建 + 探针，`--reindex` 才写库）。

3. **`list_group` 完全未建模**（0/13）：GT 有列表容器概念，我们没有对应结构。
4. **公式串相似度 0.49**：主因不是识别错，而是**多行数组的表示约定不同**（GT 用 `{l}`，
   MinerU 用 `\begin{array}{l}`）——这条指标只适合作回归跟踪，不能当质量绝对值；要绝对值得用 CDM。
5. **表格 TEDS 0.9183 低于 book(0.9974) 的短板在 newspaper 0.7879 / academic_literature 0.8808**，
   与之前 markdown 口径的指向一致（复杂版式的表格）。

## 盲区与维护约定

- **不是官方分数**：这是自定义口径，只做内部回归跟踪（同规则前后可比）。对外可比数字只能来自
  官方 markdown 口径或官方镜像。
- **阈值是约定**：IoU 0.3 / 覆盖 0.6 / caption 边距 6% 都会影响数字——重跑对比时必须用同一套阈值
  （脚本参数默认值即基线口径）。
- **chunk 层未覆盖**：本口径量到"块"，chunk 边界（`canonical_builder` 的块拼接）与 section_path
  正确性还没量；RAG 检索直接吃这两样，是下一步该补的。
- **TEDS 不得本地改写**：`_vendor/omnidocbench/table_metric.py` 与官方逐位一致是可比性前提，
  要改行为请改我们自己的输入归一（见该目录 SOURCE.md）。
