# Docs 模块后端优先优化设计

**日期**: 2026-06-18
**状态**: design
**范围**: `services/docs-core/`、`services/api-server/`、`services/angineer-core/`、`packages/docs-ui/`（仅最小配套）

---

## 1. 背景

当前 docs 模块已经具备从文件导入、MinerU 解析、结构化、canonical 重建到 hybrid 检索的完整闭环，但存在三个根问题：

1. 上游解析链路缺少统一、稳定、可解释的语义真相源。
2. 图、表、公式与正文、附注、目录层级的关系主要依赖启发式拼接，准确性与一致性不够稳定。
3. 检索层过早承担“补救结构问题”的职责，导致索引重建、hybrid 融合、citation 输出都建立在不够稳固的上游结果之上。

这会直接带来以下后果：

- 同一文档重复解析后，结构树、块类型、父子关系和 citation 目标可能波动。
- 图表、公式相关问答依赖“附近正文”而不是稳定的结构关系，难以精确命中。
- 检索结果看起来能工作，但本质上是在错误结构上做更复杂的排序与拼接。

因此，本次设计不以“先拆前端”或“先升级向量检索”为起点，而是以“后端算法主链稳定化”为第一优先级。

## 2. 目标

### 2.1 核心目标

1. 建立规则优先、AI 增强的解析主链，使结构化、层级化和关系抽取结果稳定、可解释、可回放。
2. 统一 docs 模块的文档语义真相源，消除 `rawfiles / doc_blocks_graph / canonical` 多套投影之间的漂移。
3. 让图、表、公式成为一等结构对象，并与正文、caption、footnote、正文引用建立显式关系。
4. 以稳定语义图为基础，重建 canonical 索引单元、citation 真相源和检索策略。
5. 将前端改造约束为“适配稳定协议、展示置信度与关系”的最小范围，而不是优先做组件拆分。

### 2.2 非目标

- 本次不优先做 `KnowledgeManage.vue` 的大规模拆分。
- 本次不先引入新的外部向量数据库作为首要改造动作。
- 本次不把所有解析判断都交给 LLM。
- 本次不重做整个 docs 产品交互，而是先稳定后端契约。

## 3. 设计原则

- 规则优先：结构化、层级化和关系抽取的主路径由规则完成，AI 仅处理规则难以稳定覆盖的歧义点。
- 真相源唯一：同一层语义事实只保留一份稳定来源，其他对象都视为可重建读模型。
- 显式关系：图、表、公式、标题、正文、附注之间的联系必须以结构边表达，而不是依赖检索时临时猜测。
- 原子构建：解析结果必须先写入 staging，再通过校验后一次性替换正式结果。
- 可观测可评测：每一阶段都必须记录来源、置信度、耗时与失败原因，便于回归和评测。

## 4. 方案比较

### 4.1 方案 A：继续以现有多投影链路为中心，局部补规则

- 保持 `rawfiles -> doc_blocks_graph -> canonical -> retrieval` 的现状。
- 针对目录、图表、公式逐项增加启发式规则。

优点：

- 改动小，短期能修一些显性问题。

缺点：

- 无法解决真相源漂移。
- 规则越补越分散，后续更难定位问题。
- 检索层仍然在承接上游结构不稳的问题。

### 4.2 方案 B：AI 主导解析，规则只做清洗

- 让 LLM 决定目录层级、图表归属、公式语义和正文关系。
- 规则层负责抽取原始块和基本清洗。

优点：

- 理论上覆盖复杂版式与歧义场景更快。

缺点：

- 不可解释，不利于回归验证。
- 解析结果稳定性依赖模型与 prompt，生产可控性不足。
- 与你的目标“后端算法非常清晰准确”相冲突。

### 4.3 方案 C：规则优先的语义图主链，AI 做增强

- 统一块类型与关系边，先用规则构建文档语义图。
- AI 只参与目录层级冲突、图表/公式弱关联判断、标题与公式语义补强。
- canonical、citation、检索都从同一套稳定语义图重建。

优点：

- 结构稳定、可解释、可验证。
- 最适合逐步引入评测和增量索引。
- 能把 AI 的收益放在真正困难且边界明确的问题上。

缺点：

- 前期需要重构部分数据模型与投影链路。

### 4.4 结论

采用方案 C。当前关键不是“更快接入更强模型”，而是“先把后端主链做成稳定的语义基础设施”。

## 5. 目标架构

### 5.1 总体数据流

```text
文件导入
  -> MinerU 原始结果落盘
  -> Raw Normalize
  -> Block Type Normalize
  -> Hierarchy Inference
  -> Relation Extraction
  -> AI Assist (仅冲突节点)
  -> Document Semantic Graph
  -> Canonical Read Models
  -> Sparse / Dense / Table / Formula Index
  -> Retrieval / Citation / Preview
```

### 5.2 模块职责

- `mineru_parser.py`: 只负责与 MinerU 交互、下载和保存原始产物，不负责推导业务语义。
- `structure_builder.py`: 负责从原始产物归一化为块、层级、关系和中间统计。
- `assets_file_store.py`: 负责 staging、原子提交、版本化产物落盘和重建触发。
- `builder.py`: 只负责从稳定语义图重建 canonical blocks/chunks/tables/citation_targets。
- `knowledge_routes.py`: 只负责任务编排、阶段状态和 API 契约，不下沉语义规则。
- `dispatcher.py` 与 retrieval 模块：只消费 canonical 与 citation 真相源，不反向修正上游结构。

## 6. 文档语义图设计

### 6.1 块类型统一

将现有散乱的块类型收敛为有限集合：

- `title`
- `paragraph`
- `list_item`
- `toc_entry`
- `figure`
- `figure_caption`
- `table`
- `table_caption`
- `formula`
- `formula_caption`
- `footnote`
- `page_header`
- `page_footer`
- `page_number`

兼容原则：

- 上游 MinerU 原始类型保留在 `source_type`。
- 下游 canonical、检索和前端只使用统一类型，不直接依赖 MinerU 原始命名。
- `equation_interline / equation / formula` 必须在归一化阶段合并为 `formula`。

### 6.2 关系边

语义图至少定义以下边类型：

- `parent_of`: 结构父子关系
- `next_of`: 阅读顺序关系
- `caption_of`: caption 指向图、表、公式
- `footnote_of`: 附注指向图、表、公式或正文块
- `references`: 正文显式引用目标对象
- `describes`: 正文对图、表、公式的描述关系
- `derived_from`: 派生块指向原始块

### 6.3 节点定位信息

每个语义块必须具备：

- `doc_id`
- `block_uid`
- `block_type`
- `source_type`
- `page_idx`
- `bbox`
- `reading_order`
- `text`
- `text_clean`
- `source_file`
- `source_span`
- `confidence`
- `provenance`

其中：

- `confidence` 表示当前块类型或关系判断的可信度。
- `provenance` 表示该结果来自 `rule`、`rule+ai`、`manual` 还是 `fallback`。

## 7. 解析主链设计

### 7.1 Stage 1: Raw Normalize

输入为 MinerU 原始文件集合，如 `content_list_v2.json`、`layout.json`、`model.json`。

要求：

- 不再把 `content_list_v2.json` 作为唯一硬依赖，必须支持 `v2 -> v1 -> layout/model fallback`。
- 所有原始文件先统一整理到 staging 目录。
- 对大文件分段解析结果进行页码与 source span 校正，避免后续页定位漂移。

### 7.2 Stage 2: Block Type Normalize

目标是把原始解析块稳定映射为统一块类型。

规则要求：

- 列表块必须拆成独立 `list_item`，保留原始顺序。
- 图、表、公式的主体与 caption、footnote 分开建块。
- `page_header/page_footer/page_number` 进入图谱但默认不参与检索主链。

### 7.3 Stage 3: Hierarchy Inference

目录和标题层级采用规则优先：

- 编号模式优先，如 `1`、`1.1`、`1.1.1`
- 版面特征辅助，如字体、bbox、缩进、上下文连续性
- 目录页与正文页分开判定

AI 只在以下场景介入：

- 多个候选层级得分接近
- 标题文本缺少稳定编号，但结构层次明显
- 目录页条目与正文标题存在冲突映射

AI 输出必须是“候选修正”，不能覆盖原始定位信息。

### 7.4 Stage 4: Relation Extraction

图、表、公式关系抽取改成两阶段：

1. 规则硬约束阶段：
   - 同页优先
   - 相邻区域优先
   - 上下相对位置优先
   - 跨栏冲突排斥
   - 显式编号匹配优先
2. AI 弱判定阶段：
   - 只对规则无法唯一确定的候选执行语义判断
   - 输出目标对象、理由、置信度

对于公式，除主体外还应抽取：

- `formula_number`
- `formula_variables`
- `formula_context_blocks`
- `formula_reference_blocks`

### 7.5 Stage 5: Semantic Graph Commit

阶段产物包括：

- `semantic_graph.json`
- `semantic_graph_version.json`
- `semantic_graph_stats.json`

提交规则：

- 先写 staging
- 通过图结构校验、节点数量校验、关键关系校验后再原子替换正式结果
- 若失败，保留上一版本正式结果并标记当前任务失败

## 8. Canonical 读模型重建

### 8.1 设计原则

- canonical 不是新的真相源，而是从语义图重建的检索读模型。
- 图谱变更后允许重建 canonical，但不允许直接绕过图谱修改 canonical。

### 8.2 读模型对象

- `canonical_blocks`: 面向定位与引用
- `canonical_chunks`: 面向正文语义检索
- `canonical_tables`: 面向表格检索
- `canonical_formula_units`: 面向公式问答与参数解释
- `citation_targets`: 面向引用输出和预览高亮

### 8.3 Chunking 原则

chunk 不再只按 token 数或相邻段拼接，而要围绕“可检索证据单元”构建：

- 标题锚点单元
- 正文内容单元
- 列表过程单元
- 表摘要单元
- 表行单元
- 公式主体单元
- 公式说明单元
- 图表说明单元

同一 chunk 必须满足：

- 单一主语义焦点
- 可稳定回溯到 source block ids
- citation 能落到具体目标

## 9. 索引与检索设计

### 9.1 优先顺序

索引检索优化的顺序固定为：

1. 先稳定索引单元
2. 再重做 sparse
3. 再做 citation 真相源接入
4. 再做增量索引
5. 最后替换向量检索实现

### 9.2 Sparse 检索

当前 `%LIKE%` 策略升级为 FTS/BM25，按对象分别建索引：

- `chunk_text_index`
- `title_index`
- `table_index`
- `formula_index`
- `caption_index`
- `footnote_index`

收益：

- 提高中文长问句与术语定位能力
- 降低 SQL 全表扫描成本
- 为后续 hybrid 融合提供更稳定的候选分布

### 9.3 Dense 检索

dense 检索延后优化，但需要先做两件事：

- 禁止生产主链长期回退到低质量 hash embedding
- 让 embedding 与 chunk 类型绑定，避免标题、表行、公式说明混用同一召回策略

在 canonical 稳定后，再替换当前 SQLite 全扫式向量检索。

### 9.4 Hybrid 融合

hybrid 融合改为配置化策略，而不是硬编码常数：

- 按问题类型区分 `definition_qa / locate_qa / table_qa / formula_qa`
- 按对象类型区分 `content / title / table / formula / caption`
- 输出融合分数组成，便于离线评测

### 9.5 Citation

citation 输出必须直接消费 `citation_targets`：

- 回答引用定位到具体 block、table、formula 或 figure
- 富媒体引用保留 `table_html / math_content / image_path`
- 前端预览和回答引用使用同一套目标对象

## 10. 任务编排与可观测性

### 10.1 解析任务状态机

解析任务统一为：

- `queued`
- `running`
- `cancel_requested`
- `cancelled`
- `completed`
- `failed`

要求：

- cancel 必须可被后台任务读取并生效
- 任何阶段失败都要记录 `failed_stage`
- 每个阶段记录耗时、输入条数、输出条数、异常摘要

### 10.2 观测指标

至少增加以下指标：

- `raw_blocks_count`
- `semantic_nodes_count`
- `semantic_edges_count`
- `title_conflict_count`
- `figure_relation_count`
- `table_relation_count`
- `formula_relation_count`
- `citation_target_count`
- `canonical_chunk_count`
- `index_build_ms`

## 11. 前端最小配套

前端本次只做协议适配，不作为主改造对象。

需要支持的最小能力：

- 展示块 `confidence` 与 `provenance`
- 展示图、表、公式与正文/附注/引用的显式关系
- 基于 `citation_targets` 做稳定高亮与跳转
- 在人工审核后回写 `manual` provenance

不在本次优先范围内：

- 大规模拆分 `KnowledgeManage.vue`
- 重做工作区整体交互
- 先做复杂前端性能优化

## 12. 影响范围

### 12.1 后端核心文件

- `services/docs-core/src/docs_core/ingest/extract/mineru_parser.py`
- `services/docs-core/src/docs_core/ingest/normalize/structure_builder.py`
- `services/docs-core/src/docs_core/ingest/normalize/formula_semantics.py`
- `services/docs-core/src/docs_core/ingest/store/assets_file_store.py`
- `services/docs-core/src/docs_core/ingest/store/blocks_sql_store.py`
- `services/docs-core/src/docs_core/ingest/store/canonical_sql_store.py`
- `services/docs-core/src/docs_core/ingest/organize/builder.py`
- `services/api-server/knowledge_routes.py`

### 12.2 检索相关文件

- `services/docs-core/src/docs_core/retrieval/sparse_retriever.py`
- `services/docs-core/src/docs_core/retrieval/dense_retriever.py`
- `services/docs-core/src/docs_core/retrieval/table_retriever.py`
- `services/docs-core/src/docs_core/retrieval/hybrid_retriever.py`
- `services/docs-core/src/docs_core/indexing/vector_indexer.py`
- `services/docs-core/src/docs_core/indexing/sqlite_vector_store.py`
- `services/angineer-core/src/angineer_core/dispatcher.py`

### 12.3 前端最小配套文件

- `packages/docs-ui/src/composables/useKnowledgeStructuredIndex.ts`
- `packages/docs-ui/src/composables/useWorkspaceLinkage.ts`
- `packages/docs-ui/src/components/common/workspace/PDFParsedWorkspace.vue`
- `apps/admin-console/src/views/KnowledgeManage.vue`

## 13. 实施顺序

### Phase 1：解析主链稳定化

1. 统一原始输入兼容策略，去掉对单一 `content_list_v2.json` 的硬依赖。
2. 统一块类型与关系边模型。
3. 引入 staging 和原子提交。
4. 建立解析任务状态机与阶段日志。

### Phase 2：语义图与 canonical 重建

5. 用语义图替代分散的多投影主链。
6. 让 canonical blocks/chunks/tables/formulas/citation_targets 全部从语义图重建。
7. 增加公式、图表、附注和正文引用的显式关系。

### Phase 3：索引检索优化

8. 将 sparse 升级为 FTS/BM25。
9. 接入 citation_targets 到回答主链。
10. 实现 canonical 与索引的增量重建。
11. 最后替换向量检索实现并校准 hybrid 权重。

### Phase 4：前端最小适配

12. 前端适配新的关系结构、citation 和 provenance。
13. 在协议稳定后，再评估页面拆分与组件下沉。

## 14. 验收标准

- 同一文档重复解析，多次结果的层级树与关键关系稳定一致。
- 图、表、公式都能稳定关联到 caption、footnote、正文引用和原始页定位。
- canonical 与 citation_targets 都从同一语义图重建，不再存在漂移。
- 检索层可直接命中图表、公式和正文证据，而不是只命中附近文本。
- 回答引用能落到具体对象，前端高亮与回答引用一致。
- 解析任务可取消、可追踪、可定位失败阶段。

## 15. 风险与约束

- 语义图收敛会影响现有前后端协议，需要分阶段兼容。
- 若规则覆盖不足，AI 兜底比例会过高，削弱可解释性，因此必须同步建设评测样本。
- 若 canonical 重建边界设计不清，容易把“真相源”和“读模型”重新混淆。
- 若前期没有稳定回归文档集，优化容易退化为基于个别样本的局部修补。

## 16. 评测与验证

### 16.1 回归样本

至少准备以下样本集：

- 标准目录清晰文档
- 目录页与正文标题不一致文档
- 图表密集文档
- 公式密集文档
- 跨页表格文档
- 多栏排版文档

### 16.2 指标

- 标题层级准确率
- 图表 caption 关联准确率
- 公式说明关联准确率
- citation 命中准确率
- sparse 首屏召回率
- hybrid 最终命中率
- 解析全链路耗时

### 16.3 自动化方向

- 为块类型归一化建立单元测试。
- 为目录层级推断建立规则测试。
- 为图表/公式关系抽取建立契约测试。
- 为 canonical 重建建立快照测试。
- 为 retrieval 和 citation 建立回归测试。

## 17. 下一步

本设计确认后，下一步不直接编码，而是输出详细实施计划，按以下优先级展开：

1. 后端算法主链
2. 索引检索主链
3. 前端最小配套

实施计划需要精确到文件、子任务、验证命令和阶段验收标准。
