# KnowledgeChat RAG SOTA 改造实施清单

## 1. 目标定义

- 目标不是单一模型榜单第一，而是工程文档场景下的系统级 SOTA。
- 最终系统形态定义为：
  - `KnowledgeChat = Query Router + Hybrid Retrieval + Evidence Grounding + Table Intelligence + Optional Text-to-SQL + Eval Loop`
- 核心交付标准：
  - 文档解析稳定
  - 表格理解正确
  - 检索召回高
  - 回答有证据
  - 结构化查询可执行
  - 评测闭环可持续优化

## 2. 总体架构

### 2.1 八层架构

1. `L1 解析层`
   - MinerU 把 PDF 转成 Markdown、block、layout、table、outline。
2. `L2 规范化层`
   - 把 MinerU 原始产物统一转成仓库自己的 canonical schema。
3. `L3 表格理解层`
   - 对每张表做分类：数值型、文本型、混合型、映射型。
4. `L4 索引构建层`
   - 构建 chunk、outline、table schema、schema catalog、vector collections。
5. `L5 查询路由层`
   - 判断问题走 content、table、schema、sql、mixed 哪条链。
6. `L6 检索执行层`
   - dense retrieval + sparse retrieval + rerank + metadata filter。
7. `L7 回答生成层`
   - answer with citations，必要时生成和执行 SQL。
8. `L8 评测观测层`
   - 离线 benchmark、自建评测、线上日志回放、策略对比。

### 2.2 核心原则

- SQLite 是结构化真相源，不是临时过渡层。
- Chroma 是语义召回层，不是真相源。
- MinerU 产物不能直接喂 RAG，必须经过 canonical normalize。
- 表格优先分类，不默认 chunk。
- 回答必须带证据。
- 无法证实时优先拒答，不强答。
- 数值问题优先结构化查询，不靠 LLM 心算。
- 每次能力增强都必须可评测。

## 3. Canonical Schema

### 3.1 目标

- 把 MinerU 原始产物收口成稳定中间层。
- 后续 chunk、表格索引、向量化、引用都只依赖 canonical schema。

### 3.2 对象模型

- `Document`
- `Page`
- `Block`
- `Chunk`
- `OutlineNode`
- `Table`
- `CitationTarget`

### 3.3 字段建议

#### `Document`

- `doc_id`
- `library_id`
- `title`
- `source_file_name`
- `source_file_type`
- `schema_version`
- `parse_version`
- `language`
- `page_count`
- `status`
- `created_at`
- `updated_at`

#### `Page`

- `doc_id`
- `page_idx`
- `width`
- `height`
- `rotation`
- `image_path`

#### `Block`

- `block_id`
- `doc_id`
- `page_idx`
- `block_type`
- `text`
- `text_clean`
- `bbox`
- `reading_order`
- `section_path`
- `source`
- `source_ref`
- `parent_block_id`

#### `Chunk`

- `chunk_id`
- `doc_id`
- `chunk_type`
- `text`
- `text_clean`
- `token_count`
- `section_path`
- `page_start`
- `page_end`
- `source_block_ids`
- `citation_targets`
- `version`

#### `Table`

- `table_id`
- `doc_id`
- `page_start`
- `page_end`
- `title`
- `caption`
- `bbox`
- `table_type`
- `header_rows`
- `body_rows`
- `units`
- `row_count`
- `col_count`
- `source_block_ids`
- `version`

#### `CitationTarget`

- `target_id`
- `target_type`
- `doc_id`
- `page_idx`
- `bbox`
- `section_path`
- `display_title`
- `snippet`

## 4. 表格专项设计

### 4.1 分类

- `numeric_dense`
- `text_dense`
- `hybrid`
- `mapping_enum`

### 4.2 分类原则

- 数值型表：
  - 数字占比高
  - 平均单元格长度短
  - 语义集中在表头和第一列
- 文本型表：
  - 长文本单元格比例高
  - 行内包含说明、规则、约束
- 混合型表：
  - 同时有大量数值列和说明列
- 映射型表：
  - 左侧是代码、等级、名称
  - 右侧是解释、定义、状态说明

### 4.3 特征

- `numeric_ratio`
- `avg_cell_length`
- `long_text_cell_ratio`
- `first_col_uniqueness`
- `unit_density`
- `text_entropy`

### 4.4 多表示策略

- `table_meta`
- `table_schema`
- `table_row_keys`
- `table_summary`
- `table_text_chunks`

### 4.5 各类型索引策略

#### `numeric_dense`

- 保留：`table_meta`、`table_schema`、`table_row_keys`、`table_summary`
- 不建议直接整表 embedding
- 优先用于 schema/table lookup

#### `text_dense`

- 保留：`table_meta`、`table_schema`、`row_chunks`
- 行级 chunk 规则：`表标题 + 列标题 + 当前行文本单元格`
- 优先进入 RAG 检索

#### `hybrid`

- 数值列做 schema/index
- 说明列做 text chunk
- 追加整表摘要

#### `mapping_enum`

- 每行一条知识单元
- 适合定义问答、字段解释、等级映射

## 5. 索引体系

### 5.1 向量集合

- `content_vector`
- `outline_vector`
- `table_vector`
- `schema_vector`

### 5.2 稀疏检索

- `sparse_index`
- 用于术语、编号、条款号、字段名、表头名精确匹配

### 5.3 向量元数据

- `doc_id`
- `library_id`
- `entity_type`
- `page_idx`
- `section_path`
- `table_id`
- `version`
- `embedding_model`
- `language`

## 6. 查询路由

### 6.1 路由类型

- `content_qa`
- `definition_qa`
- `locate_qa`
- `table_qa`
- `schema_qa`
- `analytic_sql`
- `mixed`

### 6.2 路由策略

- 问概念、解释、条款：`content_qa`
- 问在哪一章、哪一页：`locate_qa`
- 问表格含义、表格说明：`table_qa`
- 问字段、指标、口径：`schema_qa`
- 问统计、汇总、比较：`analytic_sql`
- 默认策略：规则路由，后续可升级轻量分类器或 LLM router

## 7. 检索执行链

```text
Question
-> Normalize
-> Route
-> Dense Recall
-> Sparse Recall
-> Metadata Filter
-> Merge
-> Rerank
-> Evidence Pack
-> Answer / SQL
```

### 7.1 强制要求

- 不走“纯 Chroma top-k + LLM 生成”的简化路径。
- Dense 负责语义匹配。
- Sparse 负责精确术语与字段名匹配。
- Metadata Filter 负责范围控制。
- Rerank 负责 top-k 质量提升。

## 8. API 契约

### 8.1 主入口

- `POST /api/knowledge/query`

### 8.2 请求字段

- `query`
- `library_id`
- `doc_ids optional`
- `session_id optional`
- `history optional`
- `mode optional`
- `top_k optional`
- `include_debug optional`
- `include_retrieved optional`
- `filters optional`

### 8.3 返回字段

- `query_id`
- `task_type`
- `strategy`
- `answer`
- `citations`
- `retrieved_items optional`
- `sql optional`
- `confidence`
- `latency_ms`
- `debug optional`

### 8.4 辅助接口

- `POST /api/knowledge/retrieve`
- `POST /api/knowledge/schema-link`
- `POST /api/knowledge/text2sql`
- `POST /api/knowledge/eval/run`
- `GET /api/knowledge/eval/report/{run_id}`

## 9. Text-to-SQL 路线

### 9.1 执行链

1. `query classify`
2. `schema linking`
3. `candidate narrowing`
4. `sql generation`
5. `sql validation`
6. `sql execution + explanation`

### 9.2 必备护栏

- 字段别名字典
- 单位与口径定义
- 白名单表
- 只读 SQL 安全校验
- 结果行数限制

## 10. 评测体系

### 10.1 四类评测

- 解析评测
- 检索评测
- 生成评测
- Text-to-SQL 评测

### 10.2 P0 样本字段

#### `questions.jsonl`

- `question_id`
- `question`
- `task_type`
- `library_id`
- `doc_ids`
- `expected_route`
- `difficulty`
- `tags`

#### `gold_retrieval.jsonl`

- `question_id`
- `gold_doc_ids`
- `gold_chunk_ids`
- `gold_table_ids optional`
- `gold_section_paths optional`

#### `gold_answers.jsonl`

- `question_id`
- `gold_answer`
- `must_cite_target_ids`
- `allow_abstractive`
- `refusal_expected`

#### `gold_sql.jsonl`

- `question_id`
- `gold_schema_links`
- `gold_sql`
- `gold_result_preview`

### 10.3 指标建议

#### P0

- `Recall@3`
- `Recall@5`
- `MRR`
- `citation_accuracy`
- `answer_correctness`
- `refusal_correctness`
- `latency_p50/p95`

#### P1

- `table_hit@k`
- `mapping_row_hit@k`
- `schema_link_accuracy`
- `sql_execution_accuracy`
- `aggregation_accuracy`

### 10.4 公共 Benchmark

- 文档理解：`DocVQA`、`ChartQA`、`PubTables-1M`
- 检索：`BEIR`、`LoTTE`、`LongBench`
- SQL：`Spider`、`BIRD`、`WikiSQL`、`CSpider`、`DuSQL`

## 11. 分阶段实施

### P0 基础真相源

- 建立 canonical schema
- 建立结构感知 chunk
- 建立表格分类与多表示产物

### P1 检索主链

- 建立 content/outline/table/sparse 检索
- 建立 hybrid retriever
- 建立 rerank 接口

### P2 回答与引用

- 建立 citation builder
- 建立 answer assembler
- 建立 refusal policy

### P3 Schema 与 SQL

- 建立 schema vector
- 建立 alias dictionary
- 建立 schema linker
- 建立 sql validator / executor

### P4 质量逼近 SOTA

- 升级 reranker
- 升级 router
- 补足 table-aware retrieval
- 建立线上回放与 AB 对比

## 12. 目录与文件规划

### `services/docs-core/src/docs_core/canonical/`

- `__init__.py`
- `types.py`
- `builder.py`

### `services/docs-core/src/docs_core/tables/`

- `__init__.py`
- `table_classifier.py`
- `table_representation_builder.py`

### `services/docs-core/src/docs_core/retrieval/`

- `__init__.py`
- `contracts.py`
- `query_normalizer.py`
- `query_router.py`
- `dense_retriever.py`
- `sparse_retriever.py`
- `hybrid_retriever.py`
- `reranker.py`
- `citation_builder.py`
- `answer_assembler.py`
- `service.py`

### `services/docs-core/src/docs_core/text2sql/`

- `schema_linker.py`
- `sql_planner.py`
- `sql_generator.py`
- `sql_validator.py`
- `sql_executor.py`
- `sql_explainer.py`

### `services/docs-core/src/docs_core/evals/`

- `eval_retrieval.py`
- `eval_answer.py`
- `eval_text2sql.py`
- `eval_reporter.py`

### `tests/evals/knowledge_rag/`

- `questions.jsonl`
- `gold_retrieval.jsonl`
- `gold_answers.jsonl`
- `gold_sql.jsonl`

## 13. 实施顺序

1. 冻结 canonical object 与字段。
2. 冻结 table type 分类枚举。
3. 冻结 `/api/knowledge/query` 返回结构。
4. 冻结 P0 样本字段格式。
5. 开发 table classifier 与 canonical builder。
6. 开发 query router 与最小 retrieval service。
7. 接前端 citation 展示。
8. 建立 P0 评测基线。

## 14. 当前建议的第一批编码范围

- 新增 `docs/rag-implementation-roadmap.md`
- 新增 `docs_core.canonical` 骨架
- 新增 `docs_core.tables.table_classifier` 骨架
- 新增 `docs_core.retrieval` 最小 query contract / router / service
- 新增 `POST /api/knowledge/query`
- 先基于现有 `A_structured` 的 `document_segments` 与 `doc_blocks` 跑通最小可用闭环

## 15. Definition Of Done

- 文档已固化在仓库，便于后续新对话继续推进。
- 后端存在统一知识查询入口。
- 路由、引用、检索结果结构已标准化。
- P0 骨架已具备继续扩展到 hybrid retrieval 和 table-aware retrieval 的稳定边界。
