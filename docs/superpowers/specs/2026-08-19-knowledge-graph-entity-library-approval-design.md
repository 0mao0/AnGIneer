# 知识图谱：通用实体库 + LLM 抽取 + 管理员审批 设计

> 日期：2026-08-19
> 状态：设计定稿，待实施计划
> 关联现状：`services/docs-core/src/docs_core/step07_graph/`、`services/docs-api/graph_routes.py`

## 1. 背景与目标

当前知识图谱默认只跑“种子共现”基线；LLM 实体抽取默认关闭，即使开启，新实体也会直接写入实体表，没有“待审核/拒绝”语义。用户希望：

1. 每个 library 拥有自己的通用实体库；
2. 每篇新 PDF 解析完成后自动跑 LLM 抽取；
3. LLM 抽到的新实体先进入待审状态，管理员可批准或拒绝；
4. 被拒绝的实体不进入通用实体库，并从相关文档图谱中移除后重新抽取该文档。

## 2. 非目标

- 不做关系审批流；关系仍由置信度、三重验证、人工纠错兜底。
- 不做跨 library 的全局实体库。
- 不做大规模图谱可视化重构。

## 3. 已确认决策

| 决策项 | 结论 |
| --- | --- |
| 实体库作用域 | 每个 `library_id` 一套 |
| 新实体审核前状态 | 实体先入库并标记 `pending`，来源文档图谱内可用，通用实体库中不正式展示 |
| 管理员拒绝行为 | 被拒实体不进入通用实体库；从相关文档图谱中移除/降权；触发这些文档重新抽取 |
| LLM 触发时机 | 新 PDF 解析完成后自动异步跑 LLM 抽取 |
| 去重策略 | 自动精确/近似去重与别名归并，确认不重复的才进入 pending |
| 关系审核 | 关系不单独进待审；文档内先用，实体审批通过后关系才作为通用关系正式可用 |

## 4. 总体流程

```text
新 PDF 解析完成
      │
      ▼
图谱快速基线（种子共现，保留，秒级）
      │
      ▼
入队 LLM 图谱抽取任务（异步，不阻塞解析）
      │
      ▼
实体去重/别名归并
      │
      ├─ 已存在 approved/pending 实体 → 复用
      └─ 新实体 → 写入 graph_entities，status=pending
      │
      ▼
关系落库（library_id + doc_id 隔离）
      │
      ▼
管理端审核 pending 实体
      │
      ├─ approve → approved，进入通用实体库
      └─ reject → rejected，清理相关文档关系，并触发文档重抽
```

## 5. 数据模型

### 5.1 `graph_entities` 新增字段

```text
status           TEXT NOT NULL DEFAULT 'approved'  -- pending | approved | rejected
proposed_doc_id  TEXT DEFAULT ''                   -- 提名该实体的文档
proposed_by      TEXT DEFAULT ''                   -- 可选：提名来源标识
reject_reason    TEXT DEFAULT ''
reviewed_at      TEXT DEFAULT ''
reviewed_by      TEXT DEFAULT ''
```

新增索引：

```text
idx_entities_status (library_id, status)
idx_entities_proposed_doc (library_id, proposed_doc_id)
```

### 5.2 状态语义

| 状态 | 含义 | 文档图谱可见 | 通用实体库/检索可见 | 去重候选 |
| --- | --- | --- | --- | --- |
| `approved` | 管理员或历史数据确认 | 是 | 是 | 是 |
| `pending` | LLM 新提名，待审核 | 是 | 否 | 是 |
| `rejected` | 管理员拒绝 | 否（重抽后移除） | 否 | 否 |

### 5.3 兼容与迁移

- 旧实体表增加 `status` 列时，默认值设为 `approved`。
- 现有 56 个种子实体初始化为 `approved`。
- 旧库已有实体迁移为 `approved`，避免历史图谱消失。
- 旧关系数据不受影响。

### 5.4 关系模型不变

`graph_relations` 不增加审批状态。通用视图只展示两端实体均为 `approved` 的关系；文档视图允许 `pending` 实体参与，但排除 `rejected`。

## 6. 新 PDF 自动抽取与入池

1. 解析完成后，将“LLM 图谱抽取”作为后台任务入队，不阻塞上传/解析主流程。
2. 抽取仍基于 `build_evidence_packets` 生成的 EvidencePacket。
3. 每个 packet 一次 LLM 调用，抽取实体与关系。
4. 实体归并顺序：
   - 精确匹配 `name` / `aliases`；
   - 归一化匹配（全半角、空格、大小写等）；
   - 近似匹配（embedding 相似度或 LLM 判断）；
   - 命中已有 `approved/pending` → 复用；
   - 未命中 → 新建，状态 `pending`。
5. 关系落库前确保实体存在（即使 pending）。
6. 保留现有三重验证、Zettelkasten、E1–E5 提取，它们继续只影响关系置信度和语义标注。

## 7. 管理员审批

### 7.1 接口

```text
GET  /api/graph/entities/pending?library_id=
     返回 pending 实体列表：名称、layer、来源文档、出现次数、证据片段、关联关系

POST /api/graph/entities/{entity_id}/approve
     body: {}

POST /api/graph/entities/{entity_id}/reject
     body: { "reason": "..." }
```

### 7.2 通过

- `status → approved`；
- 记录 `reviewed_at / reviewed_by`；
- 进入 library 通用实体库；
- 已有文档图谱无需重建，自动从“文档内可见”升级为“通用可见”。

### 7.3 拒绝

- `status → rejected`；
- 记录 `reject_reason / reviewed_at / reviewed_by`；
- 找出该 library 中所有引用该实体的文档；
- 删除或软隐藏这些文档中与该实体相关的关系；
- 从文档图谱实体集合中移除被拒实体；
- 对受影响文档触发一次“重新抽取”，并将该实体加入本次抽取忽略名单；
- 多个受影响文档可合并/批量重抽。

## 8. 查询与可见性改造

| 入口 | 过滤规则 |
| --- | --- |
| `GET /api/graph/snapshot?doc_id=...` | 显示 `approved + pending`，排除 `rejected` |
| `GET /api/graph/snapshot`（全局） | 仅 `approved` 实体；关系仅保留两端均 approved |
| `GET /api/graph/entities/search` | 默认仅 `approved`；管理端可传参数查看 pending |
| `entity_search` 工具 | 仅 `approved` |
| `GET /api/graph/stats` | 默认统计 approved；文档维度按文档规则 |
| 导出/交付 | 仅 approved 实体及对应关系 |

建议在 `GraphStore` 封装统一查询方法：

```text
list_entities_by_status(library_id, status)
list_entities_by_doc(...)      # 内部排除 rejected
list_all_entities(...)         # 默认 approved
search_entities(...)           # 默认 approved
```

## 9. 前端改造

1. **知识图谱页**
   - 文档视图显示 approved + pending，节点可显示“待审核”角标；
   - 全局视图只显示 approved；
   - 重抽期间显示“图谱刷新中”或暂时隐藏被拒节点。
2. **管理后台**
   - 在 admin-web 知识库列表页（`KnowledgeStats`）头部、`LibrarySelect` 下拉旁新增“实体审核”按钮；
   - 点击后打开右侧抽屉/弹框，展示当前选中 `library_id` 的 pending 实体列表；
   - 列表显示：实体名、layer、来源文档、出现次数、证据片段、关联关系；
   - 支持“通过”和“拒绝（必填原因）”。

## 10. 错误处理与幂等

### 10.1 错误处理

- LLM 抽取失败：任务标记 `failed`，保留种子基线图谱，可重试，不阻塞其它功能。
- 实体归并冲突：无法自动确定时默认不合并，新实体进入 pending，由管理员判断。
- 拒绝后重抽失败：保留 rejected 状态，文档图谱页提示“部分实体待重新抽取”，允许手动重试。
- 并发/重复任务：按 `doc_id + task_type` 加幂等锁，避免重复写入。

### 10.2 幂等

- 实体按 `(library_id, name)` upsert；
- 关系按 `(source_id, target_id, relation_type, library_id, doc_id)` upsert；
- 重抽前清理该文档中被拒实体相关的关系，再重新生成。

## 11. 测试策略

1. 单元测试
   - 状态迁移：pending → approved / rejected；
   - 查询过滤：文档视图含 pending、通用视图仅 approved；
   - 拒绝清理：被拒实体相关关系被移除，来源文档标记需重抽；
   - 去重归并：精确、别名、近似匹配；
   - 幂等：同一文档重复抽取不产生重复实体/关系。
2. 集成测试
   - 新 PDF 自动入队 → LLM 抽取 → 实体 pending → 文档图谱可见；
   - 审批通过 → 通用实体库可见；
   - 审批拒绝 → 文档重抽 → 被拒实体不再出现。
3. 前端测试
   - 审核列表渲染、通过/拒绝操作、pending 角标、全局视图不显示 pending。

## 12. 实施顺序

1. 数据层：`graph_entities` 加字段与索引，旧数据迁移。
2. 抽取层：新实体写入 pending；实体去重/别名归并；自动 LLM 抽取后台任务。
3. 审批层：pending 列表、approve、reject，拒绝后触发文档重抽。
4. 查询层：统一 status 过滤。
5. 前端：管理后台实体审核页 + 图谱页 pending 标记与全局过滤。
6. 测试：单元、集成、前端测试补齐。

## 13. 接口清单

```text
GET  /api/graph/entities/pending?library_id=
POST /api/graph/entities/{entity_id}/approve
POST /api/graph/entities/{entity_id}/reject
POST /api/graph/entities/{entity_id}/merge   # 可选：管理员手动合并疑似重复实体
```

## 14. 风险与缓解

| 风险 | 缓解 |
| --- | --- |
| pending 实体泄漏到通用视图 | 所有读取入口统一 status 过滤，并有测试覆盖 |
| 拒绝后重抽成本高 | 受影响文档合并批量重抽，任务异步 |
| 自动去重误合并 | 自动无法确认时进入 pending，由管理员人工判断 |
| LLM 抽取成本 | 默认异步、可配置开关/限流，失败保留种子基线 |
| 旧数据兼容 | 迁移默认 approved，不改变历史图谱可见性 |
