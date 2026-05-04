# docs-core 解耦与意图识别迁移计划

> 本文档记录 docs-core 向 angineer-core 让渡"意图识别、执行调度、回答生成"职责的分析结论与实施步骤。
> 撰写日期：2026-04-30

***

## 1. 为什么要改

### 1.1 当前架构的问题

docs-core 目前是一个**端到端查询系统**，从意图识别到回答生成全部自己完成：

```
前端 ──→ /api/knowledge/query (api-server)
              │
              ▼
    KnowledgeQueryService.query()
    ├─ parse_intent()         ← 意图识别
    ├─ build_execution_plan() ← 执行规划
    ├─ Executor.execute()     ← 检索+融合+重排
    ├─ build_citations()      ← 引用构建
    └─ assemble_answer()      ← 回答拼装(LLM)
```

这导致三个问题：

1. **angineer-core 被架空**：前端查询链路完全绕过 `IntentClassifier` 和 `Dispatcher`，angineer-core 的意图分类、SOP 编排、工具调用能力无法接入 docs 查询流程。
2. **L3/L4 无法支持**：
   - L3（公式计算）需要"检索公式 → 提取参数 → 调用计算 SOP → 生成回答"的多步编排，当前单链路无法支持。
   - L4（复合题目）需要 AI 自主分解子问题、循环调用多种能力，当前架构完全不支持。
3. **三大子模块无法协同**：docs-core、sop-core、engtools 是同一层级的子模块，但当前 docs-core 自己包办了全部，sop-core 和 engtools 无法介入 docs 查询链路。

### 1.2 目标架构

让 angineer-core 成为**查询调度的中枢**，docs-core 退化为**纯知识检索引擎**；前端只保留统一 AIChat 入口，通过 `scene + id` 路由到不同后端会话池：

```
前端 AIChat ──→ sessionKey = scene + ":" + id
                    │
                    ▼
             /api/query/v2 (api-server)
                    │
                    ▼
          ┌─────────────────────┐
          │  angineer-core      │
          │  IntentClassifier   │ ← 识别 L1/L2/L3/L4
          │  Dispatcher         │ ← 根据层级调度不同链路
          └─────────────────────┘
                    │
      ┌─────────────┼──────────────┬──────────────┐
      ▼             ▼              ▼              ▼
      L1            L2             L3             L4
      │             │              │              │
      ▼             ▼              ▼              ▼
  docs-core     docs-core      docs-core      Dispatcher
  语义检索      SQL 优先检索     标准检索/定位    动态规划
  + LLM         + 语义托底       + sop-core      + docs-core
                                  + LLM          + sop-core
                                                  + engtools
                                                  + LLM
```

### 1.3 改动范围

| 模块                | 当前职责                | 目标职责                              | 动作                                  |
| ----------------- | ------------------- | --------------------------------- | ----------------------------------- |
| **docs-core**     | 端到端查询（意图→检索→回答）     | 纯知识检索、文档管理、SQL/向量检索能力提供          | 剥离意图、调度、回答生成                        |
| **angineer-core** | LLM 客户端、SOP 匹配、步骤编排 | 查询调度中枢（意图识别 + 执行编排 + 对话模式切换）     | 扩展 IntentClassifier 支持 L1\~L4       |
| **sop-core**      | SOP 加载与解析           | 标准计算流程提供                          | 被 Dispatcher 调用                     |
| **engtools**      | 细粒度工具（计算器、网页查询等）    | 细粒度工具                             | 被 Dispatcher 调用                     |
| **前端 AIChat**    | 页面各自维护对话            | 统一聊天入口 + 基于 `scene + id` 的会话池切换  | 用 session map 管理上下文，禁止跨页面串台        |
| **api-server**    | docs 旧查询入口为主        | 统一 query 网关，按 scene/intent 路由后端模式 | 提供 `/api/query/v2`，承接前端统一 AIChat |

***

## 2. 要改什么

### 2.1 意图识别：从 docs-core 迁移到 angineer-core

**当前位置**：`services/docs-core/src/docs_core/query/intent_parser.py`

**当前问题**：

- 基于关键词规则匹配，无 LLM 语义理解
- `TaskType` 枚举与 Executor 强绑定，是"命令式"设计
- 无参数提取能力（L3 需要提取变量值如 `c=20, φ=30`）

**目标设计**：

在 angineer-core 中扩展 `IntentClassifier`，支持两层分类：

1. **元意图识别**（L1\~L4）：判断问题属于哪个层级
2. **执行模式决策**：判断应走 docs 检索、docs SQL、标准 SOP、还是动态编排
3. **具体 SOP 匹配**（主要发生在 L3）：在对应层级内匹配具体工程 SOP

```python
# 建议的新输出结构（angineer-core 层）
class IntentResult:
    intent_level: Literal["L1", "L2", "L3", "L4"]
    intent_type: str           # 更细粒度的意图标签
    parameters: dict           # 提取的参数（L3 的 c=20, φ=30）
    required_capabilities: List[str]  # ["retrieval", "calculation", "sop"]
    matched_sop: Optional[str] # L3/L4 匹配到的具体 SOP ID
```

**L1\~L4 分类定义**：

| 层级          | 用户问题示例                  | 所需能力                    | 当前 docs-core 支持度                 |
| ----------- | ----------------------- | ----------------------- | -------------------------------- |
| **L1 概念解析** | "什么是地基承载力？"             | 语义检索 + LLM 总结           | ✅ `content_qa` / `definition_qa` |
| **L2 条款应用** | "边坡 n 取值范围是多少？"         | SQL 优先 + 语义检索托底 + 条款定位 | ⚠️ 具备基础能力，但 schema 还不够业务化        |
| **L3 标准计算** | "已知 c=20, φ=30, 求地基承载力" | SOP 识别 + 参数提取 + 标准 SOP 计算 | ⚠️ `formula_qa` 只检索不计算           |
| **L4 复杂计算** | "某建筑场地...请进行地基评价"       | 问题分解 + 动态编排 + 工具链调用     | ❌ 未支持                            |

**补充说明**：

- **L2** 的核心不是“让 docs-core 做意图识别”，而是当 angineer-core 判定为条款应用后，优先调用 docs-core 的 Text2SQL / SQL 检索能力；SQL 失败或召回不足时再回退到语义检索。
- **L3** 是“有预定义工程 SOP”的标准计算，标准公式、标准流程、标准参数模板均应沉淀在 `sop-core`。
- **L4** 建议表述为“**无预定义工程 SOP 的复杂计算/复合任务**”，不是完全无 SOP，而是没有现成单一工程 SOP，需要 angineer-core 的 Dispatcher 动态组合 docs-core、sop-core、engtools 与 LLM。

### 2.2 执行规划：从 docs-core 迁移到 angineer-core

**当前位置**：`services/docs-core/src/docs_core/query/execution_planner.py`

**当前问题**：

- `ExecutionPlan` 只决定用哪个 Executor，是简单的 switch-case
- 不支持多步编排（L3 需要"检索 → 计算 → 回答"三步）

**目标设计**：

利用 angineer-core 已有的 `Dispatcher` 和 SOP 机制，把 L1\~L4 的处理流程定义为**元 SOP**（系统处理流程 SOP，非工程 SOP）：

- `meta_l1_semantic_retrieval`：调用 docs-core 语义检索 → 调用 LLM 生成回答
- `meta_l2_clause_lookup`：调用 docs-core SQL 检索 → 不足时回退语义检索 → 调用 LLM 生成回答
- `meta_l3_standard_calc`：调用 docs-core 做标准/公式定位 → 匹配 `sop-core` 标准 SOP → 执行计算 → 调用 LLM 生成回答
- `meta_l4_dynamic_orchestration`：进入 Dispatcher 多轮编排循环，必要时临时选择 SOP、工具和检索策略

### 2.3 查询服务：拆解 KnowledgeQueryService

**当前位置**：`services/docs-core/src/docs_core/query/service.py`

**当前问题**：`KnowledgeQueryService.query()` 是一个上帝方法，包了全部逻辑。

**拆解方案**：

| 方法                          | 当前位置                            | 目标位置                               | 说明                    |
| --------------------------- | ------------------------------- | ---------------------------------- | --------------------- |
| `parse_intent()`            | `query/intent_parser.py`        | `angineer-core/core/classifier.py` | 扩展 IntentClassifier   |
| `build_execution_plan()`    | `query/execution_planner.py`    | `angineer-core` 元 SOP              | 变成 SOP steps          |
| `_resolve_document_nodes()` | `query/service.py`              | `docs-core` 保留                     | 文档节点解析                |
| `Executor.execute()`        | `executors/*.py`                | 拆分                                 | 检索逻辑保留，调度逻辑迁移         |
| `build_citations()`         | `answering/citation_builder.py` | `docs-core` 保留                     | 作为检索后处理工具             |
| `assemble_answer()`         | `answering/answer_assembler.py` | `angineer-core`                    | Dispatcher 最后一步调用 LLM |

### 2.4 执行器：保留检索能力，剥离调度逻辑

**当前位置**：`services/docs-core/src/docs_core/executors/*.py`

**当前问题**：`ContentExecutor` 不仅做检索，还自己做融合、重排、证据判断。

**拆解方案**：

- **docs-core 保留**：
  - `dense_retriever.retrieve()` — 向量检索
  - `sparse_retriever.retrieve()` — 稀疏检索
  - `hybrid_retriever.fuse_candidates()` — 候选融合
  - `reranker.rerank_candidates()` — 重排
  - `formula_retriever.retrieve()` — 公式检索
  - `table_retriever.retrieve()` — 表格检索
- **迁移到 angineer-core**：
  - Executor 的 orchestration 逻辑（选择哪个检索器、是否 fallback、调用顺序）
  - `finalize_candidates()` 中的证据充分性判断（可作为 Dispatcher 的 step 条件）

### 2.5 回答层：answer\_assembler 迁移到 angineer-core

**当前位置**：`services/docs-core/src/docs_core/answering/answer_assembler.py`

**当前问题**：

- 深度依赖检索结果的 metadata 结构（`source_kind`, `entity_type`, `chunk_type`）
- 包含大量业务逻辑（公式片段抽取、表格切分、条款匹配）

**拆解方案**：

- **简单问答（L1/L2）**：angineer-core 的 Dispatcher 直接调用 LLM，传入检索结果作为 context，不需要专门的 `answer_assembler`
- **复杂问答（L3/L4）**：由 SOP 步骤中的某个 step 负责拼装 prompt
- **docs-core 保留**：`citation_builder.py` 作为独立工具，供 Dispatcher 调用构建引用

### 2.6 前端统一 AIChat 与会话池

**目标设计**：

- 前端只保留一个统一的 AIChat 入口，不在页面层面硬编码“这是 docs chat / 这是 sop chat”的交互差异。
- 页面切换时不是物理删除对话，而是切换到对应的**会话池 key**。
- 建议使用 `sessionKey = scene + ":" + id`：
  - `scene` 表示功能场景，例如 `docs`、`sops`、`workspace`、`admin`
  - `id` 表示该场景下的业务实体，例如 `docId`、`sopId`、`workspaceId`
- 前端通过 `sessionMap` 保存每个 `sessionKey` 对应的消息历史、上下文标签、模型选择与草稿输入。

**收益**：

1. 彻底避免跨页面、跨文档上下文串台。
2. 用户切换页面时可以保留各自思考痕迹。
3. 后端只需要根据 `scene` 和分类结果切换 service mode，而不需要前端维护多套 chat 组件状态机。

### 2.7 Canonical Schema 业务字段增强

**目标设计**：

为 `canonical_blocks` 与 `canonical_chunks` 增加统一的业务语义字段，作为 L2 SQL 检索和后续结构化问答的真相源。这里不采用过渡兼容方案，而是对现有 canonical schema 进行**直接硬切升级**，在 `canonical_sql_store.py`、`builder.py`、类型定义、查询映射中一次性落地以下 5 个字段，并要求重建 canonical 数据：

- `inherited_chapter` (`TEXT`, 可为空)
- `entity_tags` (`TEXT`, 存 JSON 数组)
- `conditions` (`TEXT`, 存 JSON 数组，如设计高水位、持久状况)
- `exam_tags` (`TEXT`, 存 JSON 数组，如抗倾覆、承载力)
- `clause_id` (`TEXT`, 如 `5.2.3`，专为规范准备)

**设计原则**：

- 这些字段属于**业务检索增强字段**，优先服务 L2 条款应用与规范问答。
- 字段应同时出现在 block/chunk 两层，便于 SQL 既能走细粒度定位，也能走 chunk 级摘要。
- `TEXT + JSON 数组` 仍作为当前 SQLite 直改后的正式存储格式，不保留旧列兼容逻辑。

**硬切要求**：

1. 不保留“旧 schema 可继续运行”的兼容逻辑。
2. 不做“字段缺失时回退旧查询路径”的双轨实现。
3. 直接修改现有 canonical schema，并要求相关文档重建 canonical 数据。
4. 所有读取 `CanonicalBlock` / `CanonicalChunk` 的路径都必须同步升级字段映射，避免出现“表里有字段、服务层拿不到”的半完成状态。

**需要同步修改的代码面**：

- `services/docs-core/src/docs_core/ingest/organize/types.py`
- `services/docs-core/src/docs_core/ingest/organize/builder.py`
- `services/docs-core/src/docs_core/ingest/store/canonical_sql_store.py`
- `services/docs-core/src/docs_core/knowledge_service.py`
- `services/docs-core/src/docs_core/text2sql/schema_linker.py`
- `services/docs-core/src/docs_core/text2sql/sql_validator.py`

**字段语义约束**：

- `clause_id`：规范条号，如 `5.2.3`，可由标题文本或继承链推导。
- `inherited_chapter`：当前块/片段继承到的最近章节归属，服务 SQL 过滤，不等同于完整 `section_path`。
- `entity_tags`：工程对象标签，如 `边坡`、`地基`、`挡土墙`。
- `conditions`：工况/条件标签，如 `设计高水位`、`持久状况`、`地震工况`。
- `exam_tags`：验算目标标签，如 `承载力`、`抗倾覆`、`沉降`。

### 2.8 模块边界再确认

- `docs-core` 只负责**信息检索与文档结构化数据供给**，不承担额外意图识别职责。
- `sop-core` 只负责**SOP 加载、解析、执行定义**，SOP 检索/匹配由 angineer-core 统一决策后再调用。
- `angineer-core` 负责**意图识别、服务模式选择、SOP 匹配、动态编排、回答生成**。
- 这意味着 docs 里的 chat 模式也应从“自带意图识别”转向“由 angineer-core 代理决策，docs 只暴露 retrieval/sql 能力”。

***

## 3. 怎么改（实施步骤）

### 3.0 优先级总览

为了避免“上层已切 SQL-first，但底层 schema 还没准备好”的空转，后续实施按以下优先级推进：

| 优先级 | 事项 | 是否必须先做 | 原因 |
| --- | --- | --- | --- |
| **P0** | canonical schema 直改（5 字段 + 类型 + builder + store + service + text2sql） | 是 | L2 SQL-first 的数据底座，不完成则后续路由无意义 |
| **P0** | 重建 canonical 数据并验证 SQL 检索可用 | 是 | schema 变更后必须重新生成真实数据 |
| **P1** | angineer-core 的 L1/L2/L3/L4 意图识别与 service mode 决策 | 是 | 这是新链路的总入口，决定问题走 semantic/sql/sop/orchestration |
| **P1** | api-server `/api/query/v2` 与元 SOP 链路 | 是 | 承接新调度模式，替代旧 `/api/knowledge/query` |
| **P2** | 前端统一 AIChat 与 `scene + id` 会话池 | 否，但强烈建议尽快做 | 影响体验与上下文隔离，但不阻塞后端新链路验证 |
| **P2** | 清理 docs-core 旧 query / executor / answer assembler | 否 | 应在新链路稳定后再删除，降低回滚风险 |

**建议执行顺序**：

1. 先做 canonical schema 直改与数据重建。
2. 再做 L2 SQL-first 的最小闭环验证。
3. 再做 angineer-core 的 L1-L4 路由与 `/api/query/v2`。
4. 最后再统一前端 AIChat 与下线旧链路。

### Phase 1：定义新契约（不改动现有代码）

1. **在 angineer-core 中定义** **`IntentResult`** **模型**
   - 位置：`angineer_core/standard/context_models.py` 或新文件
   - 包含字段：`intent_level`, `intent_type`, `parameters`, `required_capabilities`, `matched_sop`
2. **定义 docs-core 的检索接口契约**
   - docs-core 暴露的检索方法签名（输入 `query`, `doc_ids`, `top_k`, `filters`，输出 `List[RetrievedItem]`）
   - 明确 `RetrievedItem.metadata` 中各字段的语义，作为跨模块契约
   - 明确 SQL 检索接口契约（输入 query / doc_ids / sql_filters，输出 block/chunk/citation targets）
3. **定义元 SOP 模板**
   - 在 `data/sops/raw/` 下创建 `meta_l1_semantic_retrieval.md`, `meta_l2_clause_lookup.md`, `meta_l3_standard_calc.md`, `meta_l4_dynamic_orchestration.md`
   - 元 SOP 的 tool 字段使用 `docs_retrieval`, `docs_sql`, `sop_run`, `llm_generate` 等
4. **定义前端会话池契约**
   - 确定 `sessionKey = scene + ":" + id`
   - 明确 session map 中最少要保存的字段：消息、上下文、模型、草稿、关联资源
5. **定义 canonical 业务字段契约**
   - 明确 5 个新增字段的语义、取值来源、空值策略、下游使用方
   - 明确本次为 **直接硬切**，不做兼容旧 schema 的双轨设计

### Phase 2：在 angineer-core 中实现 L1\~L4 意图识别

1. **扩展** **`IntentClassifier`**
   - 修改 `angineer_core/core/classifier.py`
   - `route()` 方法先进行元意图分类（L1\~L4），再决定服务模式（semantic / sql / standard_sop / dynamic_orchestration）
   - 保留规则 fast-path（性能考虑），规则不匹配时调用 LLM
2. **实现参数提取**
   - 利用 `_extract_args_with_blackboard()` 已有能力
   - 为 L3 定义参数提取模板（识别公式变量和数值）
3. **补齐 L2/L3/L4 的模式判别规则**
   - L2：优先识别条款、章节、条件、验算目标
   - L3：优先识别已有标准 SOP 可承接的计算问题
   - L4：识别为无预定义 SOP 的复杂/复合任务

### Phase 3：在 api-server 中搭建新查询链路

1. **创建新的 API 入口**
   - 在 `api-server/main.py` 或新路由中创建 `/api/query`（或复用现有入口）
   - 新链路：`IntentClassifier` → `Dispatcher` → 调用 docs-core/sop-core/engtools/LLM
2. **封装 docs-core 检索为可调用函数**
   - 不注册为 ToolRegistry 中的 tool（docs-core 是子模块，不是细粒度工具）
   - 直接在 Dispatcher 的 step 实现中 import 并调用 docs-core 的语义检索器和 SQL 检索器
3. **实现元 SOP 的 step 执行逻辑**
   - `docs_retrieval` step：调用 docs-core 检索，结果写入 blackboard
   - `docs_sql` step：调用 docs-core 的 canonical SQL / Text2SQL 检索，结果写入 blackboard
   - `sop_run` step：调用 sop-core 执行工程 SOP
   - `llm_generate` step：调用 LLM 生成回答，传入 blackboard 中的检索结果
4. **统一前端 AIChat 的后端 service mode**
   - 前端统一上送 `scene`, `id`, `sessionKey`
   - api-server 按 scene + intent_level 切换到对应后端处理模式

### Phase 4：逐步替换旧链路

1. **并行运行新旧链路**
   - 保留 `/api/knowledge/query`（旧链路）
   - 新增 `/api/query/v2`（新链路）
   - 用 Benchmark（注册考试题集）对比两条链路的效果
2. **验证 L1\~L4 各层级**
   - L1：概念解析准确率
   - L2：SQL 命中率 + 条款定位准确率 + 语义托底成功率
   - L3：参数提取准确率 + SOP 匹配准确率 + 计算结果正确性
   - L4：任务分解质量 + 端到端通过率
3. **下线旧链路**
   - 新链路验证通过后，将 `/api/knowledge/query` 切换到新实现
   - 删除 `docs-core/query/intent_parser.py`, `execution_planner.py`, `service.py`
   - 删除 `docs-core/executors/*.py` 中的 orchestration 逻辑
   - 删除 `docs-core/answering/answer_assembler.py`

### Phase 5：docs-core 瘦身

1. **清理 docs-core 代码**
   - 保留：`retrieval/*`, `indexing/*`, `ingest/*`, `knowledge_service.py`
   - 删除或迁移：`query/*`, `executors/*`, `answering/answer_assembler.py`
   - 保留 `answering/citation_builder.py` 作为独立工具
2. **补齐 canonical schema**
   - 在 `canonical_sql_store.py` 中落地新增 5 个业务字段
   - 同步更新 `types.py`、`builder.py`、`knowledge_service.py`、`schema_linker.py`、`sql_validator.py`
   - 直接修改现有 canonical schema，不保留旧 schema 兼容路径
   - 对已有文档执行 canonical 数据重建

### Phase 5.5：按优先级拆解的落地任务

#### P0：必须先完成

1. 修改 `CanonicalBlock` / `CanonicalChunk` 类型定义，加入 5 个业务字段。
2. 修改 `canonical_sql_store.py` 表结构、插入语句、读取映射、索引定义。
3. 修改 `builder.py`，补齐 `clause_id`、`inherited_chapter`、`entity_tags`、`conditions`、`exam_tags` 的提取与继承逻辑。
4. 修改 `knowledge_service.py`，保证外部读取 canonical block/chunk 时能拿到新增字段。
5. 修改 `schema_linker.py` / `sql_validator.py`，让 SQL 链路真正能使用这些字段。
6. 重建 canonical 数据，并验证至少一条 L2 SQL 查询能命中这些字段。

#### P1：主链路能力建设

1. 扩展 `IntentClassifier` 输出 `intent_level + service_mode + matched_sop`。
2. 在 `api-server` 中实现 `/api/query/v2`。
3. 落地 `meta_l1_semantic_retrieval`、`meta_l2_clause_lookup`、`meta_l3_standard_calc`、`meta_l4_dynamic_orchestration`。
4. 验证 L1-L4 至少各有一条样例跑通。

#### P2：体验与收尾

1. 前端统一 AIChat，并落地 `sessionKey = scene + ":" + id` 的 session map。
2. 切页面只切会话池，不物理删除对话。
3. 新链路稳定后，删除 docs-core 旧 query / executor orchestration / answer assembler。

### Phase 5.6：评测体系与验证入口调整

**现状判断**：

- 当前 `eval_1.json` 更接近 **L1/L2 基线题库**，覆盖定义问答、定位问答、表格问答、拒答与最小 SQL 闭环。
- 当前 `eval_2(2020港航）.json` 更接近 **L3/L4 倾向题库**，包含大量综合案例、标准计算和复合求解问题。
- 但这两个题库**不能直接按文件名机械等同**为“测试集 1 = L1/L2、测试集 2 = L3/L4”，因为：
  - `eval_1` 里仍可能混入部分复杂定位或 SQL 题；
  - `eval_2` 里也可能存在可被 L2/L3 单链路解决的题目。

**建议改法**：

1. 题库的真相源不要再按“题库 1 / 题库 2”命名理解，而要在题目元数据里显式增加 `intent_level`、`service_mode`、`expected_route`。
2. 回归测试应按 `L1 / L2 / L3 / L4` 维度聚合统计，而不是只按题库文件聚合统计。
3. 现有 AIChat 抽屉评测入口可以保留，但角色要调整为**可视化评测控制台**，而不是唯一测试方式。

**抽屉是否需要修改**：

- 需要修改，但不是删除。
- 原因是完成本计划后，抽屉里至少应展示：
  - `intent_level`
  - `service_mode`
  - `matched_sop`
  - `route` / `meta_sop`
  - SQL 命中情况 / 语义托底情况
  - 会话来源 `scene + id`
- 也就是说，抽屉从“当前问答结果浏览器”升级为“新链路调试与回归验证面板”。

**推荐验证方式分层**：

1. **后端离线评测**：作为真相源，负责批量跑题、产出 JSON/Markdown 报告。
2. **抽屉可视化评测**：作为人工巡检入口，便于快速看错题、证据、链路。
3. **按层级统计**：最终报告必须能分开统计 L1/L2/L3/L4，而不是只给一个总分。

***

## 4. 风险与注意事项

| 风险           | 说明                                                           | 缓解措施                                              |
| ------------ | ------------------------------------------------------------ | ------------------------------------------------- |
| **性能退化**     | 规则路由 → LLM 路由增加延迟                                            | 保留规则 fast-path，LLM 仅用于复杂/模糊查询                     |
| **回答质量下降**   | `answer_assembler` 中的业务逻辑（公式片段抽取等）移到 LLM prompt 后，可能降低精度     | 在 prompt 中保留详细的检索结果结构，必要时保留专门的 post-processing 函数 |
| **SOP 维护成本** | 元 SOP 和工程 SOP 两套模板需要维护                                       | 元 SOP 数量固定（4 个），变化频率低                             |
| **跨模块契约稳定性** | `RetrievedItem.metadata` 字段语义变化会影响 angineer-core 的 prompt 拼装 | 定义明确的契约文档，变更时同步更新                                 |
| **回滚困难**     | 旧链路删除后，若新链路有问题难以快速回退                                         | Phase 4 保留新旧链路并行足够长时间，Benchmark 充分验证后再下线          |
| **SQL 召回失效** | L2 依赖 canonical schema 与业务字段质量，字段缺失会导致 SQL 优先策略失效            | 先补 schema，再做 L2 路由切换；保留语义检索托底                     |
| **会话池膨胀**    | 前端保留多页面历史对话后，session map 可能持续增长                               | 设计 LRU/手动归档策略，并限制每个 scene 的活跃会话数量                  |
| **硬切改动面大**  | canonical schema 直接硬切，类型、builder、store、service、text2sql 需同时改动         | 严格按 P0 顺序推进，并在重建 canonical 数据后再打开 L2 SQL-first       |

***

## 5. 与现有文档的关系

- 本文档聚焦于 **docs-core 解耦与意图识别迁移** 这一具体任务。
- 总体架构设计参考：`docs/services-techniques.md` 中的后端架构图。
- RAG 整体路线图参考：`docs/rag-implementation-roadmap.md`。
- 前端技术细节参考：`docs/apps-techniques.md`。
- 架构边界与端口契约以 `docs/architecture-map.yaml` 为准。

***

## 6. 验收标准

- [ ] `IntentClassifier` 能正确区分 L1/L2/L3/L4，准确率 > 90%（基于注册考试题集 Benchmark）
- [ ] 前端统一 AIChat 能基于 `scene + id` 稳定切换会话池，且不会发生跨页面串台
- [ ] `canonical_blocks` / `canonical_chunks` 完成 5 个业务字段扩展，并被 SQL 检索链路使用
- [ ] 评测题库中的题目已显式标注 `intent_level` / `service_mode` / `expected_route`
- [ ] 评测结果能够按 L1/L2/L3/L4 分层统计，而不只按题库文件汇总
- [ ] L3 问题能正确提取参数并匹配到对应工程 SOP
- [ ] L4 问题能进入多轮编排，至少完成"分解子问题 → 分别求解 → 汇总回答"的闭环
- [ ] docs-core 不再包含意图识别、执行调度、回答生成逻辑
- [ ] 新旧链路并行期间，新链路效果不低于旧链路
- [ ] `pnpm lint` 通过
- [ ] `pnpm docs:arch-check` 通过（涉及架构边界调整时）
