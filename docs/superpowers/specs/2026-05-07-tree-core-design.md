# tree-core 通用树操作服务 设计文档

## 目标

抽取 `services/tree-core` 作为通用树操作基础设施，消除各服务（evals-core、docs-core 等）重复的树 CRUD 代码。

## 数据模型

单表 `tree_node`，用 `tree_type` 区分领域，`extra_json` 存领域特有字段：

```sql
CREATE TABLE tree_node (
  node_id TEXT PRIMARY KEY,
  tree_type TEXT NOT NULL,
  title TEXT NOT NULL DEFAULT '',
  parent_id TEXT,
  scope_id TEXT NOT NULL DEFAULT '',
  sort_order INTEGER NOT NULL DEFAULT 0,
  is_folder INTEGER NOT NULL DEFAULT 0,
  extra_json TEXT,
  created_at TEXT NOT NULL DEFAULT '',
  updated_at TEXT NOT NULL DEFAULT ''
);
CREATE INDEX idx_tree_node_scope ON tree_node(tree_type, scope_id, parent_id, sort_order);
```

- `tree_type`：领域标识（`eval_folder`、`eval_dataset`、`knowledge_node` 等）
- `scope_id`：分组标识（evals 的 category，knowledge 的 library_id）
- `parent_id`：NULL 表示根节点
- `extra_json`：领域特有字段 JSON 序列化

## 核心 API

### tree_store.py

| 函数 | 职责 |
|---|---|
| `init_table(conn)` | 建表建索引 |
| `insert_node(conn, data)` | 插入节点，自动算 sort_order |
| `get_node(conn, node_id)` | 获取节点 |
| `update_node(conn, node_id, updates)` | 更新节点，parent 变更时自动归一化排序 |
| `delete_node(conn, node_id)` | 删除节点及子树，自动归一化兄弟排序 |
| `move_node(conn, node_id, new_parent_id, sort_order)` | 移动节点 |
| `list_children(conn, parent_id, scope_id)` | 列出直接子节点 |
| `list_nodes_by_scope(conn, tree_type, scope_id)` | 按范围列出所有节点 |
| `normalize_siblings(conn, parent_id, scope_id)` | 排序归一化 |

所有函数接收 `conn` 参数，由调用方控制连接和事务。

### tree_contracts.py

```python
class TreeNodeData(BaseModel):
    node_id: str
    tree_type: str
    title: str = ""
    parent_id: Optional[str] = None
    scope_id: str = ""
    sort_order: int = 0
    is_folder: bool = False
    extra: Dict[str, Any] = {}

class MoveNodeRequest(BaseModel):
    parent_id: Optional[str] = None
    sort_order: int = 0
```

## 迁移范围

### Phase 1: evals-core ✅ 已完成

### Phase 2: docs-core（当前）

#### 迁移映射

| 旧模型 | 新模型 |
|---|---|
| `nodes(id, title, type='folder', parent_id, sort_order, visible, library_id, ...)` | `tree_node(node_id, tree_type='knowledge_folder', scope_id=library_id, parent_id, is_folder=1)` |
| `nodes(id, title, type='document', parent_id, sort_order, visible, library_id, file_path, status, ...)` | `tree_node(node_id, tree_type='knowledge_doc', scope_id=library_id, parent_id, is_folder=0, extra_json={visible, file_path, status, ...})` |

#### 核心原则

1. **Folder 只存 tree_node**：folder 节点不再存入 `nodes` 表，完全由 `tree_node` 管理
2. **Document 业务属性留在 nodes 表**：`nodes` 表移除 `parent_id`、`sort_order` 列，只保留业务字段
3. **tree_node 与 nodes 同库**：`tree_node` 表建在 `knowledge_meta.sqlite` 中
4. **前端/API 不变**：通过 `_enrich_node_with_tree_info` 从 `tree_node` 附加树属性

#### nodes 表简化

移除列：`parent_id`, `sort_order`
保留列：`id`, `title`, `type`, `visible`, `library_id`, `file_path`, `status`, `parse_progress`, `parse_stage`, `parse_error`, `parse_task_id`, `strategy`, `schema_version`, `created_at`, `updated_at`

#### docs-core 改动

- `blocks_sql_store.py`：`KnowledgeMetaStore` 的 `init_schema` 增加 `tree_store.init_table`；`upsert_node`/`list_nodes`/`delete_nodes` 同步操作 `tree_node`
- `knowledge_service.py`：树操作（排序归一化、子树收集、移动）委托给 `tree_core.tree_store`
- `pyproject.toml`：增加 `angineer-tree-core` 依赖

#### 依赖方向

```
tree-core（零外部依赖）
    ↑
docs-core（dependencies 增加 "angineer-tree-core"）
    ↑
api-server
```

### evals-core 迁移映射

| 旧模型 | 新模型 |
|---|---|
| `eval_folder(folder_id, title, category, parent_folder_id, sort_order)` | `tree_node(node_id, tree_type='eval_folder', scope_id=category, parent_id=parent_folder_id, is_folder=1)` |
| `eval_dataset(dataset_id, title, category, folder_id, sort_order, question_count, ...)` | `tree_node(node_id, tree_type='eval_dataset', scope_id=category, parent_id=folder_id, is_folder=0, extra_json={question_count, ...})` |

### evals-core 改动

- `result_store.py`：移除 `eval_folder` 表和文件夹 CRUD 函数，改用 `tree_core.tree_store`
- `manager.py`：文件夹管理函数改为调用 `tree_core.tree_store`
- `contracts.py`：`CreateFolderRequest`/`UpdateFolderRequest`/`MoveDatasetRequest` 改用 `tree_core.tree_contracts`
- `evals_routes.py`：路由不变，仅适配新函数签名

## 依赖方向

```
tree-core（零外部依赖，只需 pydantic + sqlite3 标准库）
    ↑
evals-core（dependencies = ["angineer-tree-core"]）
    ↑
api-server
```

## 文件结构

```
services/tree-core/
  pyproject.toml
  src/tree_core/
    __init__.py
    tree_store.py
    tree_contracts.py
```
