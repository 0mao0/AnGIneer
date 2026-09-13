# ParseStruct：结构层解析评测（jsonl 口径）

## ParseStruct 在评测体系里的位置

| 层 | 名字 | 口径 | 量什么 | 谁能同台 |
|---|---|---|---|---|
| 1 | **OmniDocBench**（官方） | 官方 markdown | 交付的 markdown 像不像标准答案 | 任何能出 markdown 的系统（参考模型 / MinerU / 我们） |
| 2 | **ParseStruct**（本文件，自建） | 块级几何对齐 | RAG 依赖的结构层还原度、与上游 MinerU 的差异 | 只有产出块+位置的一方（我们 / MinerU 原生 content_list） |
| 3 | **Nightly-OpenRAG**（自建） | 问答 + 检索命中 | 端到端能不能搜到、答对 | 任何跑在评测语料上的系统 |

命名约定：**ParseStruct 是我们自建口径的名字，不可声称为 OmniDocBench 官方分数**；官方镜像只接了
end2end（markdown），版面检测等专项配置存在但未接线，这也是自建本口径的原因。

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
