# AnGIneer 知识库数据模型（Knowledge Data Model）

> 知识库的持久化布局：元数据库、树模型、索引库、文件目录、多租户/API Key 与图谱。

## 1. 数据目录

```text
data/
├─ knowledge_base/
│  ├─ knowledge_meta.sqlite            # 全局元数据（库、节点、解析任务）
│  ├─ knowledge_index.sqlite           # 全局索引（canonical + FTS + 向量 + 块）
│  └─ libraries/
│     ├─ default/
│     │  ├─ knowledge_meta.sqlite      # 早期按库拆分的历史元数据（可能为空/遗留）
│     │  └─ documents/{doc_id}/…       # 一文档一目录
│     └─ lib-bidcompare/…
├─ api_keys.sqlite                     # API Key（含 library_id 绑定）
├─ parse_records.sqlite                # 解析记录（统计/列表）
└─ evals/…                             # 评测数据
```

## 2. 元数据库（knowledge_meta.sqlite）

| 表 | 说明 |
| :--- | :--- |
| `libraries` | 知识库（id/name/description） |
| `nodes` | 文档节点（title/type/library_id/status/parse_*/strategy） |
| `tree_node` | 树结构（node_id/tree_type/title/parent_id/scope_id/sort_order/extra_json/deleted） |
| `parse_tasks` | 解析任务（status/progress/stage/stage_message） |
| `parse_task_steps` / `doc_parse_stages` / `parse_stage_steps` | 阶段与步骤明细 |

### 2.1 树模型

- `tree_type`：`knowledge_folder` / `knowledge_doc`；
- `scope_id` = `library_id`，`parent_id` 表达层级，`sort_order` 兄弟排序；
- **文件夹只写 tree_node**，文档写 nodes + tree_node 两份；
- 软删除：`tree_node.deleted` + `nodes.deleted` 双标记，文件保留可恢复；
- 树操作统一走 `tree_core`（`services/tree-core`，零外部依赖）。

> 注意：早期版本把部分元数据拆分到 `libraries/{lib}/knowledge_meta.sqlite`，
> 属于遗留迁移产物，读取以全局 `knowledge_meta.sqlite` 为准。

## 3. 索引库（knowledge_index.sqlite）

| 表 | 说明 |
| :--- | :--- |
| `canonical_documents/pages/blocks/outlines/chunks/tables/citation_targets` | 规范化文档模型 |
| `canonical_chunk_fts`（+辅助表） | FTS5 全文索引 |
| `canonical_vectors` | 向量索引（SQLite 后端） |
| `doc_blocks` / `document_segments` / `doc_block_corrections` | 结构化索引与人工修正 |

向量后端可用 Chroma（`DOCS_VECTORSTORE_PROVIDER=chroma`）或 SQLite，启动失败自动回退 SQLite。

## 4. 多租户 / API Key

- `api_keys.sqlite`：key_hash / user_name / scope / **library_id**；
- P2 起新 key 自动生成 `lib-xxxx` 租户库；
- 中间件（`middleware/api_key_auth.py`）强制 scope：绑定后 query 缺失自动注入 library_id，
  不一致拒绝（防串库）；
- v1 外部 API（`/api/v1/documents/*`）按 API key 的 user_name 在其绑定库根部建同名文件夹收纳文档；
- `parse_records.sqlite`：解析记录（uploaded_by / api_key_id / library_id / status / stages），
  供"知识库-列表"页统计与删除恢复。

## 5. 图谱与 Dream Cycle

- 图谱：`step07_graph`，实体/关系按 `library_id + doc_id` 隔离；LLM 抽取受开关控制；
- 图谱存储：`graph_store`（SQLite/Chroma 混合），快照接口 `GET /api/graph/snapshot`；
- Dream Cycle：`step08_maintain` 定期巡检（去重、矛盾、孤立、过期、SOP 健康），
  报告落库并提供确认/合并/清理 API。

## 6. 版本与迁移

- `SCHEMA_VERSION` 用于检测旧解析产物与新逻辑不兼容，触发强制重解析；
- `nodes` 表从旧版（含 parent_id/sort_order 列）自动迁移到新版（树拆到 tree_node）；
- 新增列/表用幂等迁移（`ALTER TABLE ... ADD COLUMN` 捕获 OperationalError 忽略）。

## 7. 关键代码锚点

- 服务层：`docs_service.py`（list_nodes / create_node / register_document / update_node）
- 存储：`step05_sqlite_fts/store/blocks_sql_store.py`、`canonical_sql_store.py`
- 树：`services/tree-core/src/tree_core/tree_store.py`
- 路径：`docs_core/paths.py`（library_root / get_doc_root / get_parsed_dir …）
- API Key：`docs-api/models/api_key.py`、`middleware/api_key_auth.py`
- 解析记录：`docs-api/models/parse_record.py`
