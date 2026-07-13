# SOP 提取器：基于 cangjie-skill 框架丰富 SOP 生成内容

> 状态：编码中（Step 1-5.5 已完成）
> 依赖：知识图谱按文档隔离方案（`knowledge-graph-per-doc-plan.md`）已完成

---

## 0. 目标

当前 `SopPathGenerator` 生成的 SOP 是**裸骨架**——只有步骤名、步骤类型（inspection/decision/calculation）、空 tools/inputs/outputs。没有工程实际内容填充。

引入 cangjie-skill 的 5 个提取器，在知识图谱构建完成后对每个文档执行一次 LLM 提取，为图谱的**实体**和**关系**附加 5 类语义标注。SOP 生成时自动注入这些标注，产出包含原则、案例、反例、术语解释、框架流程的**丰富 SOP**。

## 0.1 用户操作流程

```
docs 模块                                     SOP 模块
─────────                                    ────────
打开文档 → 点击"提取图谱" (秒级)                  
        → 点击"AI 深度提取" (1-5分钟)            
              │                                
              └─→ B1实体抽取 → B6三重验证         
                  → B7 Zettelkasten            
                  → E1-E5 提取器 (顺带跑完)     
                                                打开 SOP 模块
                                                ├─ 看到"从文档生成"按钮
                                                ├─ 选择已提取的文档
                                                └─ 一键生成该文档的 SOP 列表 (秒级)
                                                      │
                                                      └─ SOP 自动带原则/案例/反例/术语
```

**时序关系**: docs 模块的"AI 深度提取"完成之后，SOP 模块的"从文档生成"才可用（依赖图谱数据+提取器标注）。两者不必在同一次操作中完成——可以先提取图谱，随后任何时候再去 SOP 模块生成 SOP。

---

## 1. 5 个提取器定义

每个提取器输入：文档全文本 + 知识图谱中的实体名列表。输出：标注列表，通过 API 写回图谱。

### E1 框架提取器 (framework-extractor)

**用途**: 从工程标准中发现结构化的设计流程、验算步骤、施工工序。

**对应 cangjie 原文** (`extractors/framework-extractor.md`): 提取书中的决策框架和思维模型。

**工程适配**:
```
输入: 文档文本 + 所有实体名
输出: 流程图片段
  - name: "重力式码头设计流程"
  - steps: ["确定设计水位", "计算波浪力", "抗倾覆验算", "抗滑移验算", "地基承载力验算"]
  - entry_condition: "已知码头结构形式为重力式"
  - source_section: "第5章 重力式码头设计"
  - entity_path: ["设计高水位", "波浪力计算", "抗倾覆验算", "抗滑移验算", "承载力验算"]
```

**存储**: 框架本身不直接存入图谱节点/关系。产出一个独立的 `framework` JSON 数组，存储在文档级元数据中。SOP 生成时，按 entity_path 匹配 —— 如果 SOP 的步骤序列命中某个 framework 的 steps，则填充 SOP 的描述和步骤间关系说明。

### E2 原则提取器 (principle-extractor)

**用途**: 从工程标准中发现规范性条文和设计准则。

**对应 cangjie 原文** (`extractors/principle-extractor.md`): 提取书中的原则、清单、规则。

**工程适配**:
```
输入: 文档文本 + 所有实体名
输出: 原则列表
  - principle: "抗倾覆安全系数不小于1.2"
  - category: "强制性要求" | "推荐做法" | "限制条件"
  - applies_to_entities: ["抗倾覆验算", "持久状况"]
  - source_clause: "5.3.2条"
  - evidence_quote: "原文引用"
```

**存储**: 写入 `graph_relations.conflict_note` 或新增 `principle_note` 字段？更合理的是：原则附着在**关系**上（因为原则通常是"在某种条件下某个验算必须满足什么"）。对于强制要求类原则，存为关系的 `evidence_text` 绑定。对于通用原则（不绑定特定实体对），存入新的 `graph_principles` 表。

**决策**: 新增 `graph_principles` 表，`(principle_id, principle_text, category, source_clause, library_id, doc_id)`。关联实体通过中间表 `principle_entities(principle_id, entity_id)`。

### E3 案例提取器 (case-extractor)

**用途**: 从工程标准中发现附带数值的完整计算示例。

**对应 cangjie 原文** (`extractors/case-extractor.md`): 提取书中作者亲自使用过的实例。

**工程适配**:
```
输入: 文档文本 + 所有实体名
输出: 案例列表
  - case_title: "某5万吨级码头抗倾覆验算实例"
  - inputs: { "设计高水位": "4.5m", "波浪力": "120kN/m", ... }
  - computation: "分项系数法: K_倾 = M_稳 / M_倾 = 4500 / 3200 = 1.41 ≥ 1.2, 满足要求"
  - involved_entities: ["设计高水位", "波浪力计算", "抗倾覆验算"]
  - source_section: "附录B 计算实例"
```

**存储**: 案例体量大，不适合挤进实体字段。新增 `graph_examples` 表，`(example_id, title, inputs_json, computation_text, source_section, library_id, doc_id)` + 关联表 `example_entities(example_id, entity_id)`。

SOP 生成时，按 entity 交集查找关联案例，写入 `evidence_text`。

### E4 反例提取器 (counter-example-extractor)

**用途**: 从工程标准中发现不当做法、失效模式、禁止项。

**对应 cangjie 原文** (`extractors/counter-example-extractor.md`): 提取书中警告的失败模式。

**工程适配**:
```
输入: 文档文本 + 所有实体名
输出: 反例/禁忌列表
  - warning: "施工水位取值不当可能导致设计水位偏高，增加不必要的工程费用"
  - category: "取值错误" | "漏项" | "组合错误"
  - relates_to_entities: ["施工水位", "设计高水位"]
  - severity: "经济风险" | "安全风险"
  - source_section: "附录B 计算实例"
```

**存储**: 存入实体级或关系级 warning。新增 `graph_warnings` 表，`(warning_id, warning_text, category, severity, source_clause, library_id, doc_id)` + `warning_entities(warning_id, entity_id)`。

SOP 生成时，命中实体的 warning 注入为步骤的 cautions 标注。如果是关系级 warning，写入关系 `conflict_note`。

### E5 术语提取器 (glossary-extractor)

**用途**: 从工程标准中提取专业术语定义。

**对应 cangjie 原文** (`extractors/glossary-extractor.md`): 提取关键概念词典。

**工程适配**:
```
输入: 文档文本 + 所有实体名
输出: 术语定义列表
  - term: "设计高水位"
  - definition: "建筑物在正常使用条件下，考虑设计波浪、设计流速等因素后确定的水位高程"
  - aliases: ["设计高潮位"]
  - synonyms: ["设计水位"]
  - source_section: "2.1 术语和定义"
```

**存储**: 直接写回 `graph_entities` 的 `description` 字段（幂等 upsert：有则追加来源，无则设置）。alias 写回 `aliases` 字段。

---

## 2. 数据模型新增

### 新表（SQLite，附加在 `knowledge_graph.sqlite` 或独立 SOP 库）

| 表 | 字段 | 用途 |
|---|---|---|
| `graph_principles` | `principle_id TEXT PK, principle_text TEXT, category TEXT, source_clause TEXT, library_id TEXT, doc_id TEXT` | E2 原则 |
| `principle_entities` | `principle_id TEXT, entity_id TEXT, UNIQUE(principle_id, entity_id)` | N-M 关联 |
| `graph_examples` | `example_id TEXT PK, title TEXT, inputs_json TEXT, computation_text TEXT, source_section TEXT, library_id TEXT, doc_id TEXT` | E3 案例 |
| `example_entities` | `example_id TEXT, entity_id TEXT, UNIQUE(example_id, entity_id)` | N-M 关联 |
| `graph_warnings` | `warning_id TEXT PK, warning_text TEXT, category TEXT, severity TEXT, source_clause TEXT, library_id TEXT, doc_id TEXT` | E4 反例 |
| `warning_entities` | `warning_id TEXT, entity_id TEXT, UNIQUE(warning_id, entity_id)` | N-M 关联 |
| `graph_frameworks` | `framework_id TEXT PK, name TEXT, steps_json TEXT, entry_condition TEXT, source_section TEXT, library_id TEXT, doc_id TEXT` | E1 框架 |

### 现有表更新

| 表 | 变更 | 用途 |
|---|---|---|
| `graph_entities` | 已有 `description`、`aliases` | E5 术语直接写入（幂等 upsert） |
| `graph_relations` | 已有 `evidence_text`、`conflict_note` | E2 原则关系级写入 evidence；E4 关系级 warning 写入 conflict_note |

---

## 3. 实现步骤

### Step 1 — 提取器 LLM prompt 模板（Python 常量）

**文件**: `services/knowledge-graph/src/knowledge_graph/extractor_prompts.py`（新文件）

包含 5 个 `SYSTEM_PROMPT` + `USER_PROMPT_TEMPLATE`，直接来自 cangjie-skill 的 `extractors/*.md` 翻译为工程标准语境。每个 prompt 定位为"输入文档文本和实体名列表，输出标注 JSON"。

核心原则保持 cangjie 原版：
- 三重验证（V1/V2/V3）同样适用于提取器的输出——每个原则/案例/术语都必须通过验证才入库。
- E1-E5 共用三重验证逻辑。

### Step 2 — 提取器执行逻辑

**文件**: `services/knowledge-graph/src/knowledge_graph/graph_orchestrator.py`

新增方法 `_run_extractors(doc_id, library_id, entity_names, document_text) -> Dict`:

1. 选按文档长度分块（每块 ≤ 12000 字符）
2. 对每块依次调 5 个提取器（串行，共 5*M 次 LLM 调用）
3. 每个提取器的输出经三重验证过滤
4. 通过的写入对应表 / 更新对应字段

在 `expand_all_packets` 末尾（Zettelkasten 之后）调用该方法。

### Step 3 — 存储层

**文件**: `services/knowledge-graph/src/knowledge_graph/graph_store.py`

新增方法：
- `add_principle(principle_text, category, entity_ids, ...)`
- `add_example(title, inputs_json, computation_text, entity_ids, ...)`
- `add_warning(warning_text, category, severity, entity_ids, ...)`
- `add_framework(name, steps_json, entry_condition, ...)`
- `get_principles_by_entity_ids(entity_ids) -> List`
- `get_examples_by_entity_ids(entity_ids) -> List`
- `get_warnings_by_entity_ids(entity_ids) -> List`
- `get_frameworks_by_doc(library_id, doc_id) -> List`

Schema 初始化在 `_init_schema` 中追加新表。

### Step 4 — SOP 生成增强

**文件**: `services/knowledge-graph/src/knowledge_graph/sop_path_generator.py`

`path_to_sop_template` 增强：

1. 对于 SOP 的每个 step（对应一个实体），查关联的 principles / examples / warnings
2. **原则**注入：step 的 principled 约束写入 `description` 补充段
3. **案例**注入：step 的 computation_text 写入 `execution.tools.note`
4. **反例**注入：step 的 warnings 写入 `description` 末尾（⚠ 标注）
5. **术语**注入：step 的起始概念自动从 entity.description 填充，写入 `description`
6. **框架**匹配：SOP 步骤序列若匹配某 framework.steps，则用 framework.description 填充 SOP 前言段

**新增 API 参数**: `POST /api/graph/sop/generate` 增加 `include_extractions: bool = True`

### Step 4.5 — 按文档批量生成 SOP 列表

当前 SOP 生成是手动的：用户在 SOP 模块选实体路径 → 调 `/api/graph/sop/generate` → 生成单个 SOP JSON。用户需要在**图谱提取完成后**，在 SOP 模块对某文档一键生成所有可派生的 SOP。

**触发方式**: SOP 模块新增"从文档生成"按钮，列出已有图谱的文档，选中后一键生成。

**自动路径发现逻辑** (`generate_sops_from_doc`):

1. 查询该文档的 `graph_frameworks`（E1 提取器产出），每个 framework 的 `steps_json` 就是一条 SOP 路径
2. 若无 framework，从图谱关系推导：找到 ACTION 层实体 → 追溯其入向关系链 → 构建线性实体路径
3. 每条路径调 `SopPathGenerator.generate_sop_skeleton()` 生成 SOP JSON
4. 写入 `data/sops/json/{sop_id}.json`，更新 `data/sops/index.json`

**API**:
- `POST /api/graph/sop/generate-from-doc` — 传入 `library_id`, `doc_id`，返回 `{ generated: [...sop_ids], total: N }`
- `GET /api/graph/sop/generate-from-doc/status?library_id=&doc_id=` — 返回进度（已在图谱完成时立即可用，为同步操作；若后续改为异步则复用此端点）

**前端**:
- `packages/sop-ui/src/components/SOPTree.vue` — 工具栏新增"从文档生成"按钮
- 弹出文档选择器（列出已有图谱的文档，即 `list_entities_by_doc` 结果非空的文档）
- 选中文档 → 调用 generate-from-doc → SOP 列表刷新

### Step 5 — 前端：SOP 可视化标注展示

**涉及文件**:
- `packages/sop-ui/src/components/SOPPropertyPanel.vue` — 增加 principles / examples / warnings 展示区
- `packages/sop-ui/src/components/SOPStepNode.vue` — 步骤节点增加 warning 图标
- `packages/sop-ui/src/types/sop.ts` — `SopStep` 类型扩展 `principles`, `examples`, `warnings` 字段

展示方式：
- 原则：绿色标签，hover 显示原文引用
- 案例：折叠面板，展开显示计算过程
- 反例：橙色 ⚠ 标签，hover 显示原因

### Step 5.5 — 前端：SOP 模块"从文档生成"按钮

**涉及文件**:
- `packages/sop-ui/src/components/SOPTree.vue` — 工具栏新增"从文档生成"按钮
- `packages/sop-ui/src/composables/useSopApi.ts` — 新增 `generateSopsFromDoc(libraryId, docId)` 方法
- 按钮点击 → 弹出文档选择器（列表来自 `GET /api/knowledge/nodes` 中状态为 completed 且有图谱数据的文档）→ 选中 → 调用 `POST /api/graph/sop/generate-from-doc` → 刷新 SOP 列表

### Step 6 — 前端：触发提取器（图谱页面）

**涉及文件**:
- `packages/docs-ui/src/components/common/index/Preview_KnowledgeGraph.vue` — 在"AI 深度提取"完成后，多一个"提取 SOP 标注"按钮

**流程**: 点击 → `POST /api/graph/extractors/run` → 后台跑 5 个提取器 → 更新图谱 → 返回完成状态

### Step 7 — API 路由

**文件**: `services/api-server/graph_routes.py`

新增端点：
- `POST /api/graph/extractors/run` — 触发 5 提取器，传入 `library_id`, `doc_id`
- `GET /api/graph/extractors/status` — 查询提取进度
- `GET /api/graph/entities/{entity_id}/enrichment` — 获取某实体的原则/案例/反例/术语
- `POST /api/graph/sop/generate-from-doc` — 从文档图谱自动发现路径并批量生成 SOP
- `POST /api/graph/sop/generate` — 现有端点，增加 `include_extractions` 参数

| 端点 | 方法 | LLM | 耗时 | 说明 |
|---|---|---|---|---|
| `/sop/generate-from-doc` | POST | 无 | 秒级 | 纯图谱读取 + JSON 写入，不调 LLM |
| `/sop/generate` | POST | 无 | 秒级 | 已有端点，仅加参数 |
| `/extractors/run` | POST | 有 | 分钟级 | 触发 E1-E5 LLM 提取 |

**文档选择列表**: 复用现有 `GET /api/knowledge/nodes` 列表，筛选 `status=completed` 且有图谱数据（可通过 `GET /api/graph/stats?library_id=&doc_id=` 返回 entity_count > 0 判断）的文档。

---

## 4. LLM 调用量估算

| 阶段 | 调用次数 | 说明 |
|---|---|---|
| B1 实体抽取 | N (N = packet数) | 已实现 |
| B6 三重验证 | N | 已实现 |
| B7 Zettelkasten | 1 | 已实现 |
| **新增 E1-E5 提取器** | **5 * M** (M = 文档分块数, ≤4) | 每块跑 5 个提取器 |
| **提取器输出验证** | **5 * M** | 每个提取器输出经三重验证 |
| **合计增加** | **≤ 40 次** | 按 4 块算，每块 10 次 |

总 LLM 调用（全流程）: 2N + 1 + 40 ≈ **50-70 次** / 文档（按 N=10-15 估计）。

**优化策略**:
- 步骤 2（"提取图谱"种子规则）**跳过提取器**——只有"AI 深度提取"触发
- E1-E5 可配置为部分启用（用户只勾选需要的提取器）
- 原则/案例结果缓存，文档未修改时不重新提取

---

## 5. 风险

| 风险 | 影响 | 缓解 |
|---|---|---|
| LLM 调用量激增 | 单文档 50+ 次调用，可能超 10 分钟 | 默认只在"深度提取"触发；可单独勾选提取器 |
| 案例提取准确率低 | 工程标准中案例格式多样（表格/公式/文字），LLM 可能误解析 | 案例不进入图谱核心路径，仅作 SOP 补充标注；错误可由人工修正 |
| 反例语义模糊 | "不当做法"在标准中常以"不宜/不应/严禁"表达，但有些负面语义在上下文中 | 只处理明确的禁止性表述；争议条目保留原始引用 |
| SOP 生成注入过多信息 | SOP 描述过长，影响可读性 | 折叠式展开，默认只显示摘要 |
| 新表增加 KG 复杂度 | 8 个新表（含中间表） | 全部可选——不启用提取器时表为空，不影响现有逻辑 |

---

## 6. 文件变更清单

| 文件 | 变更类型 | 内容 |
|---|---|---|
| `services/knowledge-graph/src/knowledge_graph/extractor_prompts.py` | **新增** | 5 个提取器的 SYSTEM_PROMPT + USER_PROMPT_TEMPLATE |
| `services/knowledge-graph/src/knowledge_graph/graph_store.py` | **修改** | 新表 schema + 8 个存储方法 + `get_docs_with_graph()` 查询 |
| `services/knowledge-graph/src/knowledge_graph/graph_orchestrator.py` | **修改** | `_run_extractors()` 方法 + `expand_all_packets` 调用 |
| `services/knowledge-graph/src/knowledge_graph/sop_path_generator.py` | **修改** | 增强 path_to_sop_template + 新增 `generate_sops_from_doc()` 方法 |
| `services/api-server/graph_routes.py` | **修改** | 新增 /extractors/run, /entities/{id}/enrichment, /sop/generate-from-doc; 更新 /sop/generate |
| `packages/sop-ui/src/types/sop.ts` | **修改** | SopStep 类型扩展 + DocForSopGen 类型 |
| `packages/sop-ui/src/components/SOPPropertyPanel.vue` | **修改** | 三大标注展示区 |
| `packages/sop-ui/src/components/SOPStepNode.vue` | **修改** | warning 图标 |
| `packages/sop-ui/src/components/SOPTree.vue` | **修改** | 工具栏新增"从文档生成"按钮 + 文档选择弹窗 |
| `packages/sop-ui/src/composables/useSopApi.ts` | **修改** | 新增 `generateSopsFromDoc(libraryId, docId)` |
| `packages/docs-ui/.../Preview_KnowledgeGraph.vue` | **修改** | 提取器触发按钮 |
| `docs/sop-extractor-plan.md` | **本文档** | 实施计划 |
