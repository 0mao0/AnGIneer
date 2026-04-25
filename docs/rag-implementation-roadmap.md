# KnowledgeChat 开发路线图

## 1. 文档目的

本文件不是功能清单堆砌，而是用来统一以下三件事：

- 系统到底要做成什么样
- 新能力应该放在哪一层
- 接下来开发的优先顺序是什么

本文默认场景为：工程规范、制度文档、设计说明、PDF 技术资料等“长文档 + 强证据 + 强结构”的知识问答系统。

---

## 2. 最终目标

目标不是做一个“能聊天”的 RAG，而是做一个**可解释、可扩展、可评测**的工程文档问答系统。

最终系统形态定义为：

```text
KnowledgeChat
= Intent Parse
+ Executor Planning
+ Evidence Retrieval
+ Evidence Grounding
+ Specialized Reasoning
+ Optional SQL Execution
+ Evaluation Loop
```

核心要求：

- 文档解析稳定
- 检索结果可追溯
- 回答必须带证据
- 表格、公式、编号、章节这些结构信息必须被利用
- 数值与统计类问题不能只靠 LLM 猜
- 每次策略变更都能评测

---

## 3. 总体思路

### 3.1 先理解问题，再决定怎么做

系统不应该采用“所有问题统一走一条检索链”的方式。

更合理的主链是：

```text
用户问题
-> 问题理解
-> 意图分类
-> 执行器选择
-> 证据召回 / 结构化查询 / 计算 / 综合分析
-> 证据打包
-> 回答生成
-> 引用返回
```

这里最重要的设计变化是：

- 不是先检索再碰运气回答
- 而是先判断这是什么问题，再走对应执行路径

### 3.2 系统不是“只有检索”

在这个系统里，用户问题可能进入不同方向：

- 精确查找：编号、术语、条款、章节
- 语义问答：解释、概念、定义
- 表格问答：查值、映射、字段解释
- 公式问答：公式内容、变量说明、计算依据
- 计算型问答：检索后组合公式与说明，再回答
- 统计型问答：直接走结构化查询或聚合
- 多证据综合：检索后再做整理和分析
- 流程化说明：把检索结果组织成步骤或条件链

因此，系统核心不是“一个 retriever”，而是：

- `Intent Parser`
- `Executor Planner`
- 多种 `Executor`
- `Evidence Grounding`

---

## 4. 分层架构

### 4.1 分层定义

建议长期保持以下层级：

1. `Parsing`
   - 原始 PDF / Markdown / MinerU 结果解析
2. `Canonical`
   - 统一中间模型
3. `Understanding`
   - 表格理解、公式理解、结构增强
4. `Indexing`
   - 检索和查询所需索引构建
5. `Query`
   - 问题理解与执行计划
6. `Executors`
   - 按问题类型执行不同路径
7. `Retrieval`
   - 证据召回组件
8. `Answering`
   - 回答拼装、拒答、引用
9. `Evaluation`
   - 评测、回放、对比

### 4.2 模块职责边界

#### `ingest`

负责：

- 原始文件解析与中间产物落盘
- canonical schema 构建与持久化
- 表格、公式、章节等结构化增强
- 为后续 retrieval / indexing 提供稳定真相源

不负责：

- embedding provider 选择
- 向量库写入与向量检索
- dense / sparse 融合与召回排序

当前代码映射：

- `ingest/extract`：解析入口
- `ingest/normalize`：表格/公式/结构增强
- `ingest/organize`：canonical 类型与构建
- `ingest/store`：文件、SQLite、调试产物持久化

#### `indexing`

负责：

- embedding provider 配置与调用
- 向量记录构建
- 向量库存储与查询
- retrieval 可消费的索引层抽象

不负责：

- canonical schema 定义
- 原始文档存储
- 文档结构化理解
- 回答拼装

当前代码映射：

- `indexing/embedding_provider.py`
- `indexing/vector_indexer.py`
- `indexing/vector_store.py`
- `indexing/chroma_vector_store.py`
- `indexing/sqlite_vector_store.py`
- `indexing/config.py`

#### `query`

只负责：

- 问题规范化
- 意图识别
- 执行计划选择
- 最终调用哪个执行器

不负责：

- 直接做召回细节
- 直接做 SQL
- 直接做回答拼接

#### `retrieval`

只负责：

- 召回候选证据
- 精排 / 融合 / 元数据过滤

不负责：

- 决定系统总体走哪条业务链
- 拼完整回答

#### `executors`

负责：

- 承接 `query` 给出的执行计划
- 组织调用一个或多个 retrieval / SQL / analysis 组件

典型执行器：

- `content_executor`
- `table_executor`
- `formula_executor`
- `sql_executor`
- `synthesis_executor`

#### `answering`

负责：

- 证据打包
- 回答拼装
- 拒答策略
- 引用结构返回

---

## 5. 真相源与索引原则

### 5.1 真相源

- `SQLite canonical` 是结构化真相源
- `middle.json` 是调试与可视化中间产物，不是真相源
- 向量库如果引入，只是语义召回层，不是真相源

### 5.2 当前与目标

当前：

- 主链已经以 `knowledge_index.sqlite` 中 canonical 数据为基础
- `dense retrieval` 已升级为基于真实向量索引命中的最小实现
- 已支持外部 embedding provider，当前默认使用 `DashScope`，并保留本地 `hash` 作为 fallback
- 已接入 `Chroma` 作为默认 vector store，并保留 `SQLite` 作为 fallback
- 当前向量索引已覆盖 `chunk`、`table schema`、`table row key`、`formula` 等核心对象
- 当前 dense / sparse / hybrid 的融合与 rerank 仍偏启发式，不是完整生产级检索平面

目标：

- 稀疏召回：负责术语、编号、条款、字段名、表头名的精确匹配
- 稠密召回：负责真正的语义召回
- 融合层：统一做分数归一化、去重、rerank

### 5.3 索引对象

长期应支持以下索引对象：

- `content chunks`
- `outline anchors`
- `table schema`
- `table row keys`
- `table row text`
- `formula blocks`
- `formula explanations`
- `schema catalog`

---

## 6. 问题理解模型

### 6.1 先分“大方向”，再分“执行方式”

建议把问题理解拆成两层：

#### 第一层：意图家族

- `reference_lookup`
- `semantic_qa`
- `locate_navigation`
- `table_lookup`
- `formula_calc`
- `structured_aggregation`
- `multi_hop_synthesis`
- `workflow_explanation`
- `mixed`

#### 第二层：执行方式

- `exact_lookup`
- `sparse_retrieval`
- `semantic_retrieval`
- `table_aware_retrieval`
- `formula_aware_retrieval`
- `sql_execution`
- `retrieval_plus_analysis`
- `retrieval_plus_workflow`

### 6.2 系统至少要识别的问题类型

#### `reference_lookup`

问题特征：

- 问条款号、编号、公式编号
- 例：`6.2.1 的内容是什么`

执行重点：

- 精确编号匹配优先

#### `semantic_qa`

问题特征：

- 问定义、概念、解释
- 例：`乘潮水位是什么意思`

执行重点：

- 语义召回 + 稀疏兜底

#### `locate_navigation`

问题特征：

- 问在哪一章、哪一节、哪一页

执行重点：

- outline / citation target 优先

#### `table_lookup`

问题特征：

- 问表格中的值、映射、枚举、字段说明

执行重点：

- 按表格类型分流

#### `formula_calc`

问题特征：

- 问公式内容、按式计算、变量含义、取值方法

执行重点：

- 公式块 + 相邻解释 + 参数说明 + 条款上下文

#### `structured_aggregation`

问题特征：

- 问统计、汇总、比较、多少处、多少个

执行重点：

- 不应只靠检索后摘抄
- 应优先走 SQL 或结构化聚合

#### `multi_hop_synthesis`

问题特征：

- 需要多条证据综合
- 例：`单一潮位站乘潮水位的确定依据和适用条件分别是什么`

执行重点：

- 多证据召回后结构化综合

#### `workflow_explanation`

问题特征：

- 要求输出步骤、流程、条件链

执行重点：

- retrieval 后做流程化组织

---

## 7. 关键执行链

### 7.1 内容问答链

```text
Question
-> intent parse
-> content executor
-> sparse retrieval + dense retrieval
-> merge + rerank
-> answer with citations
```

### 7.2 表格问答链

```text
Question
-> intent parse
-> table executor
-> table type identify
-> schema / row key / row chunk retrieval
-> evidence pack
-> answer with citations
```

### 7.3 公式/计算问答链

```text
Question
-> intent parse
-> formula executor
-> formula block retrieval
-> formula context retrieval
-> parameter / explanation retrieval
-> evidence pack
-> answer with citations
```

### 7.4 统计/SQL 问答链

```text
Question
-> intent parse
-> sql executor
-> schema link
-> candidate narrowing
-> SQL generation
-> SQL validation
-> SQL execution
-> explanation + evidence
```

### 7.5 综合分析链

```text
Question
-> intent parse
-> synthesis executor
-> multi-source retrieval
-> structure extraction
-> synthesis
-> answer with citations
```

---

## 8. 表格与公式专项策略

### 8.1 表格

表格至少分为：

- `numeric_dense`
- `text_dense`
- `hybrid`
- `mapping_enum`

长期策略：

- `numeric_dense`
  - 优先 `schema lookup` / `row key lookup`
- `text_dense`
  - 优先 `row chunk retrieval`
- `mapping_enum`
  - 优先“每行一条知识单元”
- `hybrid`
  - 同时保留数值索引和文本索引

### 8.2 公式

公式问答不应只把公式当普通文本块。

公式专项应至少保留：

- `formula block`
- `formula number`
- `formula summary`
- `formula params`
- `formula explanation lines`
- `formula context`

公式问答至少支持：

- `公式 X 是什么`
- `公式 X 中 Y 表示什么`
- `某指标按什么公式计算`
- `某参数如何确定`

---

## 9. 当前实现状态

### 9.1 已经完成的部分

- Canonical SQLite 真相源
- `/api/knowledge/query` 主入口
- 基础检索模块拆分
- 基础回答模板与引用结构
- 表格检索已有第一版专用分流
- 公式/计算问答已有第一版专用链
- `analytic_sql` 已接入最小 Text-to-SQL 闭环
- `indexing/` 层已独立，embedding / vector store / vector indexer 已从原有分散目录收敛
- 已接入 `DashScope` external embedding provider，并支持本地 `hash` fallback
- 已接入 `ChromaVectorStore`，并支持 `SQLiteVectorStore` fallback
- canonical 文档保存后会自动构建向量索引
- dense retrieval 已切换为消费真实向量命中
- `docs_core/evals/*` 已形成 retrieval / answer / text2sql 评测模块骨架
- 已提供最小评测 API：题目列表与整套评测运行入口

### 9.2 已做但还不够深入的部分

- Query Router 目前仍偏规则型
- Dense 已接入真实向量召回，但 Dense / Sparse / Hybrid 的融合、归一化、rerank 仍偏启发式
- 表格策略已起步，但评测样本仍需继续扩充
- 公式链已接入，但还需继续提升参数说明、多步解释与复合问题协同能力
- Text-to-SQL 目前只支持 canonical SQLite 上的最小只读计数类问题
- 评测已模块化，且已有最小 run/report API，但还没有持久化回放、基线沉淀与 A/B 对比能力

### 9.3 还没有真正完成的部分

- 生产级 embedding / vector retrieval
- 复合问题的 Query Decomposition 与多执行器协同
- `synthesis_executor` 多证据综合链
- Text-to-SQL 的复杂聚合、多表、排序与白名单扩展
- 更强的 Schema linker
- SQL 安全验证增强
- 真正可切换的 A/B/C 多策略执行平面
- 策略回放与 A/B 对比

---

## 10. 开发优先级

### Priority A：收紧架构边界

目标：

- 先把 `query / retrieval / answering / executors` 的边界固定下来

必须完成：

- `query` 只做理解与规划
- `retrieval` 只做召回
- `answering` 只做回答与拒答
- 复合能力进入 `executors`

验收标准：

- 新增能力不会再出现“应该放哪一层”的混乱

### Priority B：补齐专用执行器

目标：

- 不再让所有问题统一挤进 content retrieval

必须完成：

- `table executor`
- `formula executor`
- `sql executor`
- `synthesis executor`

验收标准：

- 各类问题能稳定走对路径

### Priority C：补齐真 dense 与向量层

目标：

- 从最小向量闭环升级到更高质量语义召回

必须完成：

- embedding provider 治理与质量评测
- ANN / vector store 的稳定性、可观测性与索引增强
- chunk / table / formula / schema 向量索引继续增强
- dense + sparse 融合策略升级

验收标准：

- dense retrieval 不再依赖启发式 token overlap 兜底才能工作

### Priority D：最小 Text-to-SQL 闭环

目标：

- `analytic_sql` 从占位返回升级为可执行能力

必须完成：

- `schema_linker`
- `sql_planner`
- `sql_generator`
- `sql_validator`
- `sql_executor`
- `sql_explainer`

验收标准：

- 至少支持只读、白名单、单表聚合与排序

当前状态：

- `table executor`、`formula executor`、`sql executor` 已落最小可用版本
- 当前仍缺 `synthesis_executor`
- 复合问题仍会被压缩为单路执行器，尚未形成协同编排

### Priority E：评测服务化

目标：

- 任何策略变更都能对比效果，而不是只靠主观感觉

必须完成：

- retrieval eval
- answer eval
- sql eval
- run/report API
- 基线结果沉淀

验收标准：

- 每次变更都能输出统一报告

当前状态：

- 已完成 `docs_core/evals/*` 模块化下沉
- 已提供最小统一 API，但当前返回的是即时聚合结果
- `tests/evals/knowledge_rag/*` 目前仅保留样本数据与薄入口
- 后续仍需补评测回放、基线沉淀、持久化报告与 A/B 对比

---

## 11. 建议目录结构

```text
services/docs-core/src/docs_core/
  ingest/
    parser/
    canonical/
    structured/
    storage/

  indexing/
    config.py
    embedding_provider.py
    vector_indexer.py
    vector_store.py
    chroma_vector_store.py
    sqlite_vector_store.py

  query/
    contracts.py
    intent_parser.py
    execution_planner.py
    service.py

  executors/
    content_executor.py
    table_executor.py
    formula_executor.py
    sql_executor.py
    synthesis_executor.py

  retrieval/
    sparse_retriever.py
    dense_retriever.py
    hybrid_retriever.py
    table_retriever.py
    formula_retriever.py
    reranker.py

  answering/
    citation_builder.py
    answer_assembler.py

  text2sql/
    schema_linker.py
    sql_planner.py
    sql_generator.py
    sql_validator.py
    sql_executor.py
    sql_explainer.py

  evals/
    eval_retrieval.py
    eval_answer.py
    eval_text2sql.py
    eval_reporter.py
```

说明：

- `ingest` 负责解析、canonical、structured 和真相源落盘
- `indexing` 负责面向 retrieval 的索引构建，不等同于“所有存储”
- `query` 是上层
- `retrieval` 是下层
- `answering` 最好独立
- `executors` 用来承接复合业务链

---

## 12. 近期实施顺序

### Step 1

收紧模块边界：

- 明确 `query / retrieval / answering / executors`

### Step 2

补齐表格与公式执行器：

- 表格问答
- 公式问答
- 计算型问答

### Step 3

落地真 dense 与向量层：

- 语义召回不再伪装成 dense

### Step 4

落地 Text-to-SQL：

- 解决统计、计数、聚合、比较类问题

### Step 5

落地评测服务化：

- 建立持续优化闭环

注：

- 当前目录重构中的 Step 2 已先把 `text2sql/` 与 `evals/` 的模块边界落地
- 当前目录重构中的 Step 3 已把 `indexing/`、`DashScope embedding` 与 `Chroma fallback` 落地到最小可用版本
- roadmap 里的 Step 4 / Step 5 仍表示“把能力做深做强”，不是说目录层还没接入

---

## 13. Definition of Done

当以下条件成立时，认为路线图进入稳定执行态：

- 系统分层清楚
- 新能力有明确归属层
- 用户问题能先识别方向，再走对应执行器
- 检索不是唯一动作，计算、分析、SQL、流程化说明都有专门路径
- 回答始终带证据
- 关键链路都有评测

---

## 14. 一句话版本

KnowledgeChat 不是“统一检索然后回答”的系统，而是“先理解问题，再选择执行器，再基于证据完成回答”的系统。
