# AnGIneer 检索链路（Retrieval Chain）技术说明

> 本文档是知识库问答「从问题到证据」的完整链路说明，包含多路召回、融合、重排、引用装配与拒答守卫。
> 检索链路是踩坑最多的地方，本文同时记录关键踩坑与当前对策。

## 1. 总体链路

```text
用户问题
  │
  ▼
意图分类（L0~L4，规则 + LLM）
  │
  ▼
策略展开（agent_policy → attempts）
  │
  ▼
工具调用（knowledge_search / table_search / entity_search / sop_execute / calculator …）
  │
  ▼
多路召回（dense / sparse / clause / table / formula）
  │
  ▼
候选融合（RRF + 源权重 + 任务加成 + 去重）
  │
  ▼
重排（远端 reranker → 本地 phrase rerank 降级）
  │
  ▼
引用装配（MarkerAllocator → cite 标记 → evidence / citations）
  │
  ▼
最终回答守卫（final_answer_guard）
```

核心代码：`services/angineer-core/src/angineer_core/agent_tools.py`（工具层）、
`services/docs-core/src/docs_core/step09_query/retrieval/`（召回与融合）、
`services/docs-core/src/docs_core/step09_query/retrieve_service.py`（HTTP 内部检索端点）。

## 2. 多路召回

每一路返回 `RetrievedItem` 候选，随后统一进入融合。

| 来源 | 职责 | 实现文件 |
| :--- | :--- | :--- |
| `dense` | 语义向量召回（在线 bge-m3；502 时降级 hash embedding） | `dense_retriever.py` |
| `sparse` | 关键词/短语召回（CJK 2 字词、短语、条款号） | `sparse_retriever.py` |
| `clause` | 条款号直达（如 6.2.8.1），对规范条文类问题有强加成 | `clause_resolver.py` |
| `table` | 表格召回，返回含完整行数值的表格块 | `table_retriever.py` |
| `formula` | 公式与公式上下文（含"式中"解释段） | `formula_retriever.py` |

### 2.1 查询归一化

`query_normalizer.py` 提供：

- `tokenize_query`：分词与去停用；
- `build_cjk_ngrams`：CJK 2 字词，供 sparse LIKE 匹配；
- `build_query_phrases`：短语；
- `extract_clause_refs`：提取 `6.2.8.1`、`第 3.2 节` 等条款号；
- `normalize_match_text`：统一全角/半角、去掉空格。

### 2.2 表格检索的坑（重要）

- 正文索引里表格通常只有「标题 + 注 + 行数列数摘要」的容器块，**没有行数值**；
- 具体数值只有 `table_retriever` 返回的表格块里有；
- 因此**查表/数值/尺度/吨级类问题必须走 table_search**，且 query 尽量用用户原问法，
  改写后的 query（例如拼上"船型参数"）会导致表格召回失效、公式召回灌满；
- 兜底策略：`knowledge_search` 在识别为查表类问题时，会额外并入 TableRetriever 结果，
  并在融合后按 `table_id` 用完整表格文本补全候选（防止只给摘要、模型拿不到数值）。

### 2.3 公式检索的坑

- 公式正文与「式中」解释段在数据结构里有父子关系；
- 仅返回公式块时模型容易误判"t1/t2/t3 未定义"；
- 对策：`FormulaRetriever` 把公式 + 其解释段作为一整条上下文返回。

## 3. 候选融合（hybrid_retriever.py）

融合算法：**加权 RRF（Reciprocal Rank Fusion）**，同源先去重、再按名次贡献分数。

```text
fusion_score = RRF(rank) * source_weight + task_type_bonus
```

### 3.1 源权重

| 来源 | 权重 | 说明 |
| :--- | :--- | :--- |
| `dense` | 1.0（hash 降级时 0.05） | 在线 embedding 失败自动降级 |
| `sparse` | 1.0 | |
| `clause` / `clause_direct` | 1.6 | 条款直达再 +1.0 加成 |
| `table_row_key` | 1.8（table 任务）/ 0.6 | |
| `table_schema` / `table_summary` | 1.2~1.5（table 任务）/ 0.5 | |
| `toc` | locate 1.05 / 普通 0.12~0.18 | 目录类候选压制 |

### 3.2 去重 key

`build_candidate_key`：

- 有 `citation_target_id` → `target:{id}`；
- 表格块（`table_*`）→ `table:{table_id}`，**同一张表只保留最相关一条**，避免多行分数虚高挤掉条款/正文；
- 公式块 → `formula:{base_id}`；
- 图 → `figure:{item_id}`；
- 其余 → `item_id`。

### 3.3 任务类型加成

- `table_qa`：表格块 +0.25~0.35；
- `locate_table/figure/formula/clause`：对应目标 +0.35~0.5；
- 目录（toc）：普通任务 -0.35；
- `clause_direct`：+1.0（压过表格/公式，防止查条款被表淹没）。

## 4. 重排

`rerank_candidates`：

1. 配置了 `ANGINEER_RERANKER_URL` 且候选 > 阈值时，调远端 reranker；
2. 远端失败/未配置 → 回退本地 `reranker.py` 的 phrase 重排；
3. `locate_*` 类任务不重排（保序）。

> 踩坑：远端 reranker 502 时自动降级本地，排序质量下降但不会断链。

## 5. 引用装配（agent_tools.py）

检索结果 → `_assemble_search_result`：

- `MarkerAllocator` 按工具前缀分配标记：`knowledge_search` → `K1..Kn`，`table_search` → `T1..`，`entity_search` → `E1..`；
- 每条候选注入 `metadata.cite`，正文 `[K3]` 等标记与之一一对应；
- `evidence`：`Evidence`（source/library_id/kind/items…）供前端展示与守卫使用；
- `citations`：含 `doc_title` 前缀、`section_path`、`snippet`（截断 200 字）、`score`、`fusion_sources`；
- 前端按 cite 标记把 `[Kx]` 渲染成数字圆圈，hover 看原文，点击跳 PDF 高亮 bbox。

## 6. 拒答守卫（final_answer_guard）

`agent_configs.py::make_final_answer_guard`，两层兜底：

1. **enforce_evidence**：工具全部无有效证据（items 无 text）→ 强制替换为拒答话术；
2. **未检索引用校验**：答案里出现证据中没有的规范编号/题库背景 → 替换为拒答话术；
3. **标记清理**：答案中的 `[KTE]` 必须真实存在于工具返回，编造标记一律移除（不因此拒答）。

## 7. 关键踩坑记录

| 问题 | 现象 | 对策 |
| :--- | :--- | :--- |
| Embedding 服务 502 | dense 降级 hash，排序质量下降 | 降权 0.05；依赖 sparse/clause 兜底；恢复服务后复测 |
| query 被改写 | 表格召回失效、公式灌满 | 提示词强制"查表类用原问法"；table_search 描述强调 |
| 表格容器块无行值 | 搜到表标题却答不出数值 | knowledge_search 并入表格行 + 按 table_id 补全文本 |
| 同表多行分数虚高 | 表格挤掉条款/正文 | 融合按 table_id 去重，不累加 |
| 条款号被表淹没 | 查 6.2.8.1 却返回船闸表 | clause_direct +1.0 加成 |
| 公式解释缺失 | 模型误判参数未定义 | 公式 + 解释段整体返回 |
| 远端 reranker 502 | 排序退化 | 自动回退本地 phrase rerank |

## 8. 关键代码锚点

- 工具层：`agent_tools.py`（`_run_knowledge_search` / `RetrieverAdapter` / `_assemble_search_result`）
- 策略层：`agent_policy.py`（L1/L2 attempts 装配）
- 提示词：`prompts/agent_configs.py`（QA_AGENT_SYSTEM_PROMPT，改后必须升版本）
- 召回：`step09_query/retrieval/{dense,sparse,clause,table,formula}_retriever.py`
- 融合：`step09_query/retrieval/hybrid_retriever.py`
- 重排：`step09_query/retrieval/reranker.py`
- 检索服务：`step09_query/retrieve_service.py`、`angineer-core/docs_retrieval_client.py`
