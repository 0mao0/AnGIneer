# angineer-tree-core

[![PyPI](https://img.shields.io/pypi/v/angineer-tree-core)](https://pypi.org/project/angineer-tree-core/)

AnGIneer 的通用树节点存储层（纯 Python 库）：树节点的 **增删改查 / 移动（跨父节点自动重排）/
同级排序归一化 / 作用域隔离**，全部落在调用方传入的一个 SQLite 连接上。

> 定位：只做存储与排序，不含 HTTP、不含业务语义（"文件夹/文档/知识库"这些含义由消费方定义）。
> 连接与事务归调用方——所有函数都接收 `sqlite3.Connection`，不自己开连接；`insert/update/delete/normalize`
> 会自行 `commit`，`mark_node_deleted` 特意不 commit（软删标记留给调用方决定何时提交）。
> `init_table` 会确保连接按列名取行（`row_factory = sqlite3.Row`），调用方无需自己设置。

## 安装

```bash
pip install angineer-tree-core

# 或从 GitHub 钉版本安装
pip install "angineer-tree-core @ git+https://github.com/0mao0/angineer-tree-core.git@v0.1.0"
```

Python 要求 `>=3.10`；唯一运行依赖 `pydantic>=2.0,<3.0`。

## 快速开始

```python
import sqlite3
from tree_core import tree_store

conn = sqlite3.connect(":memory:")
tree_store.init_table(conn)                      # 建表建索引，幂等

tree_store.insert_node(conn, {"node_id": "d1", "tree_type": "doc",
                              "title": "规范A", "is_folder": True})
tree_store.insert_node(conn, {"node_id": "n1", "tree_type": "doc",
                              "title": "第一章", "parent_id": "d1"})

tree_store.list_children(conn, "d1")             # 直接子节点，按 (sort_order, created_at)
tree_store.move_node(conn, "n1", None)           # 移到根层：自动补 sort_order 并归一化两边
tree_store.normalize_siblings(conn, None, "")    # 根层 sort_order 收敛成 0..n-1
tree_store.delete_node(conn, "d1")               # 删除节点与整棵子树，并归一化原父级
```

## API

| 函数 | 作用 | 备注 |
| :--- | :--- | :--- |
| `init_table(conn)` | 建表 `tree_node` + 索引，并确保 `row_factory = sqlite3.Row` | 幂等；顺带给老库补 `deleted` 列（ALTER 失败即忽略） |
| `insert_node(conn, data)` | 插节点；`sort_order < 0`（默认）自动排到同级末尾 | `INSERT OR REPLACE`；`node_id` / `tree_type` 必填 |
| `get_node(conn, node_id)` | 取单个节点（不存在返回 `None`） | 读回时 `extra_json` 自动解析成 `extra` 字典，`is_folder` 转 bool |
| `update_node(conn, node_id, updates)` | 改字段；**父或作用域变化时自动归一化新旧两组兄弟** | 只认白名单：`title` / `parent_id` / `scope_id` / `sort_order` / `is_folder` / `extra` |
| `delete_node(conn, node_id)` | 删节点及其整棵子树 | 物理删除；返回是否命中 |
| `mark_node_deleted(conn, node_id, deleted)` | 软删标记 / 取消标记 | **不 commit**，由调用方决定何时提交 |
| `is_node_deleted(conn, node_id)` | 查软删状态 | |
| `move_node(conn, node_id, new_parent_id, sort_order=-1)` | 移动节点（`sort_order >= 0` 时同时钉位） | 内部走 `update_node` |
| `list_children(conn, parent_id, scope_id="")` | 直接子节点（`parent_id=None` = 根层） | 按 `scope_id` 过滤 |
| `list_nodes_by_scope(conn, tree_type, scope_id)` | 该树该作用域的全部节点 | 建树/对齐用 |
| `list_nodes_by_type(conn, tree_type)` | 该树跨作用域的全部节点 | |
| `normalize_siblings(conn, parent_id, scope_id)` | 同级 `sort_order` 收敛成从 0 连续 | 移动后会自动调用 |

## 数据契约

`tree_core.TreeNodeData` / `tree_core.MoveNodeRequest`（pydantic 模型，供消费方做入参校验）：

| 字段 | 说明 |
| :--- | :--- |
| `node_id` / `tree_type` | 节点主键 + 树类型；**`tree_type` + `scope_id` 是隔离键**——同一张表可并存多棵树 × 多个作用域 |
| `parent_id` | `None` = 根层 |
| `sort_order` | 同级顺序；插入默认排末尾，移动后自动归一化 |
| `is_folder` | 消费方语义（本库只存不解释） |
| `extra` | 任意字典 → 存 `extra_json`，读回自动还原 |

## 不在本库范围

- HTTP / 接口层（消费方自己包）；
- 业务树语义（文件夹、文档、知识库的规则）；
- 连接的创建、事务边界与并发控制（调用方负责）；
- 迁移与数据修复脚本。

## 开发与测试

```bash
pip install -e ".[dev]"
python -m pytest tests -q
```

测试覆盖：建表幂等、插入排序、软/硬删除、跨父移动与同级归一化、作用域隔离、契约模型校验。

## 许可

MIT
