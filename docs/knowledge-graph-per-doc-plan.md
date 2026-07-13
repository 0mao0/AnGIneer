# 知识图谱：按文档隔离 + 启用 LLM 抽取 实施计划

> 状态：计划阶段（未开始编码）
> 目标：让知识图谱 (a) 支持按文档维度查看与强隔离，(b) 真正从文档文本中发现文档专属的实体与关系，而不再只是 70 个固定种子的共现骨架。

---

## 0. 已确认的决策

| 决策项 | 结论 |
| --- | --- |
| 前端默认视图 | 默认显示「本文档」；已确认两步提取流程（见 A5） |
| 隔离粒度 | 按 `library_id + doc_id` 强隔离 |
| LLM 抽取开关 | 默认手动开启（开关默认关，用户/接口显式开启） |
| 旧库处理 | 重建 `data/knowledge_graph.sqlite`，清空当前趋同骨架后重新摄入 |
| 种子实体 | `config.py` 中 70 个固定种子为初始基线；种子可由两处扩展：(1) 每次 LLM 抽取产出的非种子新实体自动加入图谱；(2) 后续可在 `config.py` 中以增量方式追加新种子（重新 ingestion 即可更新） |

---

## 1. 现状关键事实（影响设计）

- `push_to_graph` / `POST /api/graph/build/from-doc` 调用 `build_evidence_packets(library_id, doc_id, doc_title="", ...)`，**`doc_title` 硬编码为空** → 实体 `source_doc` 实际为空，无法按文档溯源。
- `EvidencePacket` 本身带 `library_id` / `doc_id`，但 `expand_from_packet` 只把 `packet.doc_title` 写入实体，未存 `doc_id`。
- `GraphEntity` / `GraphRelation` 仅有 `source_doc` / `source_clause`，**没有 `library_id` / `doc_id` 字段**，且 `get_graph_snapshot` 返回全库。
- `EntityExtractor.extract_from_packet`（LLM 实体+关系抽取）与 `RelationInferrer.infer_relations`（LLM 关系推理）**已实现但未被 orchestrator 调用**（死代码）。
- 前端 `packages/docs-ui/.../Preview_KnowledgeGraph.vue` 调 `GET /api/graph/snapshot` 时不带任何文档参数。

---

## 2. 方案 A：按文档强隔离与过滤（`library_id + doc_id`）

### A1. 数据模型 —— 仅关系表加字段，实体表不加（关键设计）

**设计决策：`library_id`/`doc_id` 仅加在 `graph_relations` 表，不加在 `graph_entities` 表。**

原因：`graph_entities` 有 `UNIQUE(name)`，同名实体跨文档全局唯一。如果给实体加上 `(library_id, doc_id)`，当多篇文档包含同名实体时，后摄入的文档会覆盖前者的 doc_id，导致按文档过滤时实体归属漂移（详见本节末尾示例）。

实际语义也正确：实体（如"设计高水位"）是所有文档共享的概念，其归属是"整个知识体系"而非某个特定文档；是**关系**（如"承载力验算 requires 设计高水位"）属于特定文档的论证上下文。

`services/knowledge-graph/src/knowledge_graph/graph_store.py`：
- `GraphRelation` 增加 `library_id: str = ""`、`doc_id: str = ""`。
- `GraphEntity` **不加** `library_id`/`doc_id`——保留现有字段 `source_doc`/`source_clause` 作为展示元数据，仅修正 `source_doc` 不再为空。
- schema 仅关系表增加对应列 + 索引：
  - `idx_relations_doc (library_id, doc_id)`

**`graph_relations` UNIQUE 约束修正：**
当前 `UNIQUE(source_id, target_id, relation_type)` 全局去重。按文档强隔离后，不同文档的相同三元组必须各自独立存储：
```sql
UNIQUE(source_id, target_id, relation_type, library_id, doc_id)
```
SQLite `ALTER TABLE` 不支持修改约束，但因为确认了**重建旧库**（见第 4 节），所以只需修改 `_init_schema()` 中的 `CREATE TABLE` 语句即可，不需要迁移逻辑。

### A2. 写入时带文档标识
- `GraphOrchestrator.expand_from_packet` 中：
  - `GraphEntity(...)` 的 `source_doc` 改为取 `packet.doc_title or packet.doc_id`（修正空值），**不加** `library_id`/`doc_id`（实体跨文档共享）。
  - `GraphStore.add_relation(...)` 增加 `library_id=packet.library_id, doc_id=packet.doc_id` 入参并落库（关系归属文档）。
- 后续 B7 Zettelkasten 产出的关系同样传入 `library_id`/`doc_id`。

### A3. 存储层新增按文档查询
`GraphStore` 新增：

- `get_relations_by_doc(library_id, doc_id)` — `SELECT * FROM graph_relations WHERE library_id=? AND doc_id=?`，一次 SQL 返回全量（避免现有 snapshot 中遍历实体逐个查关系的 N+1 问题）。

- `list_entities_by_doc(library_id, doc_id)` — 实体本身不带 `doc_id`（A1 决策），因此通过**关系反向收集**：
  ```sql
  SELECT DISTINCT e.* FROM graph_entities e
  JOIN graph_relations r ON (e.entity_id = r.source_id OR e.entity_id = r.target_id)
  WHERE r.library_id = ? AND r.doc_id = ?
  ```
  即：该文档所有关系中涉及的全部实体（source + target 去重）。

- `get_graph_snapshot(library_id=None, doc_id=None)`：当两者均为 `None` 时返回全库（保持兼容），否则按 `(library_id, doc_id)` 过滤；
  - `stats` 反映**该文档的作用域统计**（从过滤后的关系集合中统计涉及的实体/关系数量和 layer/type 分布），而非全库总数；
  - `entities` 用 `list_entities_by_doc`，`relations` 用 `get_relations_by_doc`。

### A4. 接口层
`services/api-server/graph_routes.py`：
- `GET /api/graph/snapshot?library_id=&doc_id=` 透传过滤。
- `POST /api/graph/build/from-doc` 构建完成后**直接返回该文档作用域 snapshot**（`get_graph_snapshot(library_id, doc_id)`），方便前端构建完即获本篇图谱。
- 新增 `enable_llm_extraction: bool` 请求字段（默认 `False`），透传给 orchestrator。

### A5. 前端——两步提取流程
涉及文件：
- `packages/docs-ui/src/components/common/index/Preview_KnowledgeGraph.vue`
- `apps/admin-console/src/views/KnowledgeManage.vue`（传导 `library_id`/`doc_id` props）

**Props 传导路径：**
`KnowledgeManage.vue` 持有 `selectedNode` 及其 `library_id`/`doc_id` → 通过 `PDFParsedWorkspace` → `PDFParsedViewerCombo` → `Preview_KnowledgeGraph` 逐层 props 透传。若链条太长，也可让 `Preview_KnowledgeGraph` 通过 inject/provide 直接从父级上下文获取。

**视图与加载：**
- `fetchGraph()` **默认带**当前文档的 `library_id` / `doc_id`。
- 增加视图切换：**「本文档」/「全局」** radio，默认「本文档」。
  - 「本文档」带 `?library_id=&doc_id=`；
  - 「全局」不带参数。

**两步提取流程（从方案 A 的一步双项改为两步走）：**

**第 1 步——种子规则提取（始终可用，秒级）：**
```
文档尚未提取图谱
                                  ↓
┌─────────────────────────────────────────┐
│  📊 本文档尚未提取图谱                   │
│                                         │
│  点击「提取图谱」按钮，系统会快速扫描     │
│  文档中已知的工程术语，建立基础实体关系。   │
│  支持高亮 70+ 种标准术语及关联。          │
│                                         │
│  [ 提取图谱 ]   ← 点击后 loading           │
└─────────────────────────────────────────┘
```
- 点击后调 `POST /api/graph/build/from-doc`（`enable_llm_extraction=false`）。
- 请求仅走种子共现逻辑（B1 第 1 步），**纯文本处理 + SQLite 写入，预计 1-10 秒完成**。
- 完成后直接返回 doc 作用域 snapshot，前端刷新渲染图谱。
- 按钮变为 `disabled`（已提取），下方出现第二步入口。

**第 2 步——AI 深度提取（可选，LLM 增强，1-5 分钟）：**
```
图谱已提取（种子规则）                   
┌─────────────────────────────────────────┐
│  ✅ 基础提取已完成                       │
│                                         │
│  AI 深度提取（含 LLM 三重验证 + 语义连接） │
│  预计耗时 1-5 分钟，会从文档中发现更多      │
│  专业实体和跨章节隐含关系。                │
│                                         │
│  [ AI 深度提取 ]  ← loading → disabled    │
└─────────────────────────────────────────┘
```
- 点击后调 `POST /api/graph/build/from-doc`（ `enable_llm_extraction=true`）。
- 走 LLM 全流程：B1 LLM 抽取（每 packet 1 次）+ B6 三重验证（每 packet 1 次）+ B7 Zettelkasten（全文档 1 次）。**预计 N 个 packet × 2 次 LLM + 1 次 ≈ 1-5 分钟**。
- 完成后用返回值更新 entities/relations，按钮变为 `disabled`（已深度提取）。

**种子规则的来源说明：**
种子实体来自 `config.py` 中的 70 个工程标准术语（如"航道""防波堤""承载力验算"等，分 concept/condition/action 三层）。这是一种开放的设计——任何 LLM 抽取产出的非种子新实体都会自动加入图谱；后续也可以直接在 `config.py` 中以增量方式追加新种子，重新 ingestion 即可更新范围。

---

## 3. 方案 B：启用 LLM 抽取，发现文档专属实体/关系

### B1. orchestrator 接入 LLM（受开关控制）
`GraphOrchestrator.expand_from_packet(packet, enable_llm: bool = False)`：
1. **种子基线（始终执行，低置信兜底）**：保留现有种子共现逻辑，`confidence = AI_EXTRACTED (0.3)`。
2. **LLM 扩展（仅当 `enable_llm=True`）**：对每个 `EvidencePacket` 调 `EntityExtractor.extract_from_packet(...)`，得到 `entities`（含 layer、evidence）与 `relationships`（含 type、confidence、evidence）。

**统一模型：** 所有 LLM 调用（B1 实体抽取、B6 三重验证、B7 Zettelkasten）统一使用 `Qwen3.6-A3B`，通过 `LLMClient.chat(config_name="Qwen3.6-A3B")` 注入。`EntityExtractor`、`RelationInferrer`、`QuestionMapper` 的默认 `config_name` 均统一为该模型。

**LLM 调用粒度——每个 packet 一次，不按 seed 循环（关键设计决策）：**
现有 `extract_from_packet(text, section_path, seed_entity_name, progress_callback)` 要求传入单个 `seed_entity_name`，若按当前种子循环（N 个命中种子 × M 个 packet），开销不可接受。
改为：**每 packet 一次 LLM 调用**，将 `seed_entity_name` 改为该 packet 中命中的所有种子列表（作为 prompt 中的上下文），一次返回该 packet 的全局提取结果。需要微调 `extract_from_packet` 签名或在其外包装一层，将 `seed_entity_name: str` 扩展为 `seed_entity_names: List[str]`。
这会控制 LLM 调用次数 = packet 数量（通常 ≤20），而非 seed 数量 × packet 数量。

### B2. 处理「非种子新实体」
LLM 可能产出不在种子表里的实体名。需要：
- `GraphStore.upsert_entity_by_name(name, layer, source_doc="", source_clause="", ...)`：按 name 幂等创建/更新（实体跨文档共享，不带 doc_id）。
- `GraphStore.add_relation_by_names(source_name, target_name, relation_type, confidence, evidence, library_id, doc_id, ...)`：内部按 name 解析/创建实体再建关系，**关系带上 library_id / doc_id**（关系归属文档）。

### B3. 置信度与类型映射
- LLM 返回的 relation type 已在枚举内（`defines/requires/constrains/conditions_on/computes_from/verifies`），直接落库。
- LLM 关系自带 confidence（0–1）→ 直接写入；种子启发式关系保持 `0.3`。
- 实体 layer 由 LLM 给的 `concept|condition|action` 决定；缺省走现有 `classify_entity` 关键词兜底。

### B4. 性能与可控性
- LLM 抽取按 packet 调用，文档大时 N 个 packet = N 次 LLM：
  - 增加 `enable_llm_extraction` 开关（**默认关**，确认决策）；
  - packet 文本截断（`MAX_TEXT_CHARS=8000` 已有）；
  - 可选：合并相邻小 packet、限制每文档最大调用次数。

### B5. `RelationInferrer`（可选增强）
`infer_relations` 与 `extract_from_packet` 二选一或互补：建议先用 `extract_from_packet`（一次调用同时拿实体+关系，更省），`infer_relations` 作为备用路径按需启用。

### B6. 三重验证增强关系置信度（融合 cangjie-skill 方向 1）

当前所有 AI 提取的关系统一标记 `confidence = AI_EXTRACTED (0.3)`，缺少质量区分。引入 cangjie-skill RIA-TV++ 的**三重验证**（Triple Verification）作为关系的置信度后处理。

**验证标准（对每条 AI 提取的关系跑 LLM 评估）：**
1. **跨域佐证（Cross-validation）**：该关系在原文是否有 ≥2 处独立文本支持（跨段落/跨章节），而非单次偶然共现？
2. **预测力（Predictive power）**：用该关系能否回答原文未明说但属于相关领域的新问题？
3. **独特性（Uniqueness）**：该关系是否为工程领域常识（如"混凝土需要水泥"）？常识关系不赋予高置信度。

**置信度调整规则：**
```
通过 3/3 → 升级为 QUESTION_VALIDATED (0.5)
通过 2/3 → 维持 AI_EXTRACTED (0.3)
通过 1/3 或 0/3 → 维持 AI_EXTRACTED (0.3)，写入 conflict_note: "未通过三重验证（X/3）"
```

**实现方式：**
- 在 `expand_from_packet` 的 LLM 抽取（B1）结束后，新增一个 `_verify_relations(relations, packet_text, entity_names)` 方法，对当前 packet 产出的所有关系做一次批量三重验证 LLM 调用（而非逐条调用，节省开销）。
- 仅对 `enable_llm=True` 且 `confidence < 0.5` 的关系启用验证（已 HUMAN_REVIEWED 的关系跳过）。
- 验证失败的 relation **不删除**——回退到原置信度，并在 `conflict_note` 记录原因，便于前端展示审核入口。

### B7. Zettelkasten 语义连接增强（融合 cangjie-skill 方向 3）

当前 relation 主要靠**文本内共现**（种子 cooccurrence）或**单 packet LLM 抽取**，无法发现跨章节/跨 packet 的隐含逻辑关系。引入 cangjie-skill 的 **Zettelkasten 连接分析**，在 packet 级别的抽取完成后，对整篇文档做一次全局语义连接。

**Zettelkasten 连接类型 → AnGIneer relation 映射：**

| Zettelkasten 连接 | AnGIneer 关系类型 | 示例 |
|---|---|---|
| 依赖（depends_on） | `requires` | "稳定性验算 requires 设计高水位" |
| 约束（constrains） | `constrains` | "沉降计算 constrains 地基处理方案" |
| 前提（prerequisite_of） | `conditions_on` | "地震工况 conditions_on 稳定性验算" |
| 验证（verifies） | `verifies` | "裂缝验算 verifies 混凝土配筋" |
| 组合/替代（composes/alternative_to） | `defines` 或新增 note | "系船柱 + 靠船墩 → 码头系泊系统" |

**实现方式：**
- 在 `expand_all_packets` 全部 packet 处理完毕后，对整篇文档调用 Zettelkasten 分析——输入：`doc_id` 下所有已入库实体名 + 文档摘要；输出：跨 packet 语义连接列表。
- 由 `GraphOrchestrator` 新增 `_link_zettelkasten(doc_id, entities, doc_summary)` 方法。
- 产出的关系置信度标记为 `AI_EXTRACTED (0.3)`，然后走 B6 三重验证升级。
- 仅在 `enable_llm=True` 时执行（作为 LLM 深度模式的补充），不会显著增加调用次数（整个文档一次）。
- 实现位置：`expand_all_packets` 末尾（packet 级抽取完成后）调用。

---

## 4. 旧库重建（确认决策）

- **时机：步骤 0，在所有代码改动之前执行。** 原因：A1 修改了 `graph_relations` 的 `UNIQUE` 约束（增加 `library_id + doc_id`），SQLite 无法通过 `ALTER TABLE` 变更约束，只能改 `CREATE TABLE` 语句。若旧库存在，新代码的 `_init_schema` 中 `CREATE TABLE IF NOT EXISTS` 会认为表已存在而跳过，但旧表约束与代码预期不一致 → 写入行为错误。因此在代码改动前**直接删除旧库文件**，后续首次 `_init_schema` 会建新表。
- `data/knowledge_graph.sqlite` 直接删除重建（无迁移脚本，不保留旧数据）。
- 代码部署后对所有需纳入的文档重新走 `build/from-doc`（或 `push_to_graph`）。

---

## 5. 实施步骤（建议顺序）

0. **[旧库]** 删除 `data/knowledge_graph.sqlite`（必须在代码改动前，避免 `CREATE TABLE IF NOT EXISTS` 跳过表重建而 UNIQUE 约束未更新）。
1. **[A1+A2]** 修改 `_init_schema` 的 `CREATE TABLE` 语句（关系表加 `library_id`/`doc_id` 列、改 UNIQUE 约束）；`GraphRelation` 加字段，`GraphEntity` 不加；`expand_from_packet` 中 entity 修正 `source_doc` 空值，relation 填入 `packet.library_id`/`packet.doc_id`。
2. **[A3]** 存储层：`list_entities_by_doc`、`get_relations_by_doc`、`get_graph_snapshot` 加过滤参数及过滤后的 scope stats。
3. **[B2]** 新增 `upsert_entity_by_name` / `add_relation_by_names`（为 LLM 抽取的 name 型结果提供入库方法）。
4. **[B1+B3]** 改造 `expand_from_packet`：接入 LLM 抽取（每 packet 一次、受 `enable_llm` 开关控制）、非种子实体按 name 创建、置信度映射；保留种子基线兜底。
5. **[B6]** 实现 `_verify_relations()` 三重验证方法（批量 LLM 调用，对当前 packet 产出的关系做跨域佐证/预测力/独特

性评估，通过全部三项则置信度升至 0.5），集成到 `expand_from_packet`。
6. **[B7]** 实现 `_link_zettelkasten()` 方法（整篇文档一次 LLM 调用，输入全部已提取实体+文档摘要，发现跨 packet 语义依赖/约束/前提关系），集成到 `expand_all_packets` 末尾。
7. **[A4]** 接口 `snapshot` 过滤 + `build/from-doc` 返回文档作用域 snapshot + `enable_llm_extraction` 字段 + `PushDocRequest` 增加 `enable_llm_extraction: bool`。
8. **[A5]** 前端：props 传导 `library_id`/`doc_id`、「本文档/全局」切换（默认本文档）、两步提取流程（「提取图谱」种子规则按钮 + 「AI 深度提取」按钮）、构建后增量刷新。
9. **[B4]** 补 LLM 开关全局配置 + 合并小 packet / 限制每文档最大 LLM 调用次数等性能保护。
10. **[验证]** 重建库后，用 2 篇不同文档分别摄入 → 验证「本文档」视图隔离、「全局」视图累加、「提取图谱」按钮流程、三重验证置信度升级、Zettelkasten 跨段连接。

---

## 6. 验证

- 单元测试：在 `services/knowledge-graph` 现有测试基础上增加：
  - 按 `doc_id` 过滤后实体/关系只占本篇；
  - 开启 `enable_llm` 后能 upsert 非种子新实体并成功建关系；
  - 三重验证：mock LLM 返回通过 3/3、2/3、0/3 三种结果，验证 `_verify_relations` 正确调整置信度；
  - Zettelkasten：mock LLM 返回跨 packet 连接，验证 `_link_zettelkasten` 正确创建跨段关系。
- 手动：用 2 篇不同文档分别测试：
  - 步骤 1：点击「提取图谱」（种子规则）→ 秒级完成，展示基础图谱；
  - 步骤 2：点击「AI 深度提取」→ 1-5 分钟完成，实体/关系显著增多；
  - 「本文档」视图实体/关系不同；
  - 「全局」视图为两者累加；
  - 同步启用 `enable_llm_extraction=true` 测试三重验证置信度升级、Zettelkasten 跨段连接。
- `pytest` 现有 `knowledge-graph` 测试保持通过；CI 可用 mock LLM 验证流程。

---

## 7. 风险

| 风险 | 说明 | 缓解 |
| --- | --- | --- |
| **旧库有数据时刷 schema 失败** | 新 `CREATE TABLE IF NOT EXISTS` 不会重定义已存在的表 → 关系表 UNIQUE 约束未更新 | 步骤 0 先删库，不依赖 ALTER TABLE 迁移 |
| **LLM 成本/时延** | B1（每 packet 一次）+ B6（每 packet 批量验证一次）+ B7（整文档一次 Zettelkasten），合计约 `2N+1` 次 LLM 调用/文档 | 默认关 LLM；B6 可配置跳过已 human-reviewed 的关系；B7 限制实体数上限（≤50）；总计限制每文档 ≤30 次调用 |
| **三重验证误判** | LLM 对工程领域"常识"的判断可能不一致 | 验证结果仅影响置信度标签，不删除关系；`conflict_note` 保留审核线索 |
| **Zettelkasten 幻觉连接** | LLM 可能对不关联的实体强加语义关系 | 产出的 Zettelkasten 关系初始置信度 `AI_EXTRACTED (0.3)`，必须通过 B6 三重验证才升级；前端低置信度关系用虚线展示 |
| **强隔离副作用** | 切换文档后「本文档」若未摄入则为空 | 搭配「提取图谱」按钮引导触发 |
| **实体覆盖丢失** | 多文档共享同名实体导致归属覆盖 | 实体不标 `doc_id`（A1 设计决策），仅关系表按 doc 隔离，通过关系反向收集实体 |
| **非种子实体 name 冲突** | LLM 产出的实体名可能与已有种子同名但 layer 不同 | `upsert_entity_by_name` 不覆盖已有 layer（同名种子优先），若冲突记录 warning 日志 |
| **无关系实体不可见** | 仅在文本出现但无关系的实体在「本文档」视图不展示 | 可接受——孤立实体对图谱无价值；如需展示，前端可用基于 `source_doc` 的辅助查询兜底 |
