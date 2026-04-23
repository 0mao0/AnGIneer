# Docs 模块下一步开发计划

## 1. 文档目的

本文件用于在当前真实实现基础上，指导 `docs` 模块的后续开发。
目标不是重复描述理想架构，而是回答 4 个问题：
- 当前已经稳定落地了什么
- 当前最影响效果的短板是什么
- 下一步应该先做什么，后做什么
- 每一步做到什么程度才算完成

---

## 2. 当前真相源

截至当前代码状态，`docs` 模块应按以下事实理解：

- 解析主链已落地：`/api/knowledge/parse` + `ParseOrchestrator` + MinerU + 一文档一目录存储
- 结构化主链已落地：`doc_blocks_graph_v1` + canonical SQLite + `knowledge_meta.sqlite` / `knowledge_index.sqlite`
- 查询主链已落地：`query -> executors -> retrieval -> answering`
- 专用执行链已落地最小版本：`content` / `table` / `formula` / `sql`
- 评测主链已落地最小版本：题目读取、运行整套评测、返回聚合报告

当前不应误判为“已完成”的部分：

- 真正的 embedding / vector retrieval
- Query Decomposition 与多执行器协同
- `synthesis_executor`
- 复杂 Text-to-SQL
- 评测回放、A/B 对比、长期基线沉淀
- 可选的多策略 A/B/C 执行平面

---

## 3. 核心问题

### 3.1 检索层名实不符

- `dense_retriever` 与 `sparse_retriever` 当前仍是启发式匹配和规则计分
- ingest 主链没有向量化工序
- 仓库内没有独立 embedding 模型层与 vector store 适配层

影响：

- 语义召回质量上限较低
- “dense / sparse / hybrid” 的命名容易让团队高估真实能力

### 3.2 Query 层只能单路执行

- 当前意图路由为单标签分类
- 执行规划一次只会选中一个 executor
- 复合问题无法拆成子问题并行协同

影响：

- 表格 + 公式 + 条款类问题容易误路由
- 复合问答结果受单一主意图支配

### 3.3 Answering 层过轻

- 当前更接近“片段选择 + 模板拼装”
- 缺少多路证据编排与综合推理

影响：

- 可以做“带证据回答”
- 但还不能稳定处理复杂综合分析问题

### 3.4 文档与实现长期漂移

- 历史文档同时混杂“已落地”“进行中”“规划中”
- `docs-ui` 内还残留未接线的设计期 API/composable

影响：

- 容易在评估阶段误判完成度
- 新开发容易建立在错误前提上

---

## 4. 开发原则

后续开发默认遵守以下原则：

1. 先收紧真相源，再扩能力。
2. 先打通最小闭环，再追求完整架构。
3. 新能力必须明确落在 `query / executors / retrieval / answering / text2sql / evals` 某一层。
4. 未落地能力不得在 README 和技术文档中表述为“当前已实现”。
5. 每一阶段结束后，必须同步更新对应文档。

---

## 5. 分阶段计划

### P0：文档与接口收敛（已完成）

目标：

- 消除“文档已承诺但代码未落地”的误导
- 清理共享层中未接线或过期的接口描述
- 明确 `docs-ui` 中“正式能力”和“设计残留”的边界

范围：

- 更新 `README.md`
- 更新 `docs/apps-techniques.md`
- 更新 `docs/services-techniques.md`
- 更新 `docs/rag-implementation-roadmap.md`
- 盘点 `packages/docs-ui` 中未接线 API 和 composable
- 将 `docs-ui` 旧接口、死代码、设计期残留纳入后续清理范围

交付物：

- 文档状态统一为“已落地 / 最小实现 / 规划中”
- `docs-ui` 共享层能力清单
- `docs-ui` 清理目标清单（旧接口、未接线 composable、死代码）
- 下阶段开发计划文档

验收标准：

- 团队阅读文档后，不会再误认为多策略和真向量检索已经可用
- 文档中涉及当前状态的描述可被代码直接验证

当前状态：

- 文档真相源收敛已完成
- 计划文档已建立
- `docs-ui` 的清理目标已确认，但代码层清理尚未开始

### P1：补齐检索基础设施

目标：

- 从“伪 dense”升级到“真 dense”

范围：

- 引入独立 embedding 模型层
- 定义 vector store 抽象接口
- 在 ingest 主链补齐向量化工序
- 为 chunk / table / formula / schema 建立向量索引
- 重构 `dense_retriever`，改为真实向量召回

建议落点：

- `services/docs-core/src/docs_core/embedding/`
- `services/docs-core/src/docs_core/vectorstore/`
- `services/docs-core/src/docs_core/ingest/`
- `services/docs-core/src/docs_core/retrieval/dense_retriever.py`

验收标准：

- 代码中存在可替换的 embedding provider
- 向量索引可被 ingest 主链产出和读取
- `dense_retriever` 不再依赖 token overlap 作为主逻辑

### P2：补齐复合问题执行能力

目标：

- 让系统能处理“表 + 公式 + 条款 + 综合说明”类问题

范围：

- 为 `query` 层增加最小 Query Decomposition
- 增加多路子查询规划
- 新增 `synthesis_executor`
- 让 `answering` 支持多证据拼装而不只是单片段模板输出

建议落点：

- `services/docs-core/src/docs_core/query/`
- `services/docs-core/src/docs_core/executors/synthesis_executor.py`
- `services/docs-core/src/docs_core/answering/`

验收标准：

- 一个问题可被拆成多个子任务
- 至少支持“条款定位 + 公式说明”“表格取值 + 条件说明”两类复合问答
- 返回结果能明确展示多路证据来源

### P3：扩展 Text-to-SQL

目标：

- 从“只读计数”扩展到“可用统计分析”

范围：

- 增强 `schema_linker`
- 支持单表聚合、排序、过滤
- 增强 SQL 校验与白名单
- 继续保留 canonical SQLite 作为真相源

验收标准：

- 支持 `count / avg / min / max / group by / order by` 的最小闭环
- SQL 校验失败可解释
- 不破坏现有只读安全边界

### P4：评测与回放平台化

目标：

- 让策略变更可以持续比较，而不是靠主观感觉

范围：

- 评测结果持久化
- 基线报告沉淀
- 回放能力
- A/B 对比能力

建议落点：

- `services/docs-core/src/docs_core/evals/`
- `apps/api-server/main.py`
- `apps/admin-console/src/views/components/KnowledgeEvalDrawer.vue`

验收标准：

- 每次运行可生成带时间戳的报告
- 历史结果可回看
- 至少支持两次运行结果对比

### P5：多策略执行平面（可选项，最后评估）

目标：

- 仅在单策略主链已无法满足需求时，再评估是否引入真实多策略执行平面

范围：

- 重新确认 A/B/C 多策略是否仍有业务价值
- 如果确认需要，再补策略切换、统一响应结构和横向评测
- 如果确认不需要，则正式废弃历史文档中的多策略承诺，只保留单主链架构

验收标准：

- 团队对“是否保留多策略”形成明确结论
- 若保留，则有最小可用实现与评测入口
- 若不保留，则文档与代码彻底收敛到单策略主链

---

## 6. 建议优先级

建议按以下顺序推进：

1. `P0` 文档与接口收敛
2. `P1` 检索基础设施
3. `P2` 复合问题执行能力
4. `P3` Text-to-SQL 扩展
5. `P4` 评测平台化
6. `P5` 多策略执行平面（仅在确有必要时）

原因：

- 不先收敛真相源，后续所有讨论都会继续漂移
- 不先补向量层，`dense` 与 `hybrid` 无法真正提升
- 不补多路执行，复杂问题体验很难显著改观
- 多策略不是当前主线阻塞项，应在单主链做实后再决定是否保留

---

## 7. 本阶段完成定义

当前这轮文档收敛任务完成的标准是：

- 4 份现有文档与真实实现状态一致
- 新计划文档可直接用于后续排期和评审
- 不再把“规划能力”写成“当前已完成能力”

---

## 8. 后续维护规则

- 每当 `docs` 模块新增一个实际可用能力时，先更新对应文档中的“当前实现状态”，再补“后续计划”。
- 每当某项规划被证伪或延期时，优先修改文档，不保留含糊描述。
- 每轮涉及 `docs` 主链的改动，默认同步检查本文件是否需要更新。
