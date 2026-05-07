# 评测集树拖拽与文件夹持久化 实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 实现评测集树的完整拖拽功能，数据集可在同分组内的文件夹间拖拽移动，文件夹持久化到后端数据库。

**Architecture:** 后端新增 `eval_folder` 表和文件夹 CRUD API，扩展 `eval_dataset` 表增加 `folder_id`/`sort_order` 字段。前端 `useEvalDatasetTree` 从后端获取文件夹数据替换本地 `LocalFolder`，`EvalManage.vue` 启用拖拽并对接后端 API。

**Tech Stack:** Python/FastAPI/SQLite（后端），Vue 3/TypeScript/Ant Design Vue（前端）

---

## 文件结构

| 操作 | 文件 | 职责 |
|------|------|------|
| 修改 | `services/evals-core/src/evals_core/storage/result_store.py` | 新增 eval_folder 表、folder_id/sort_order 字段、文件夹 CRUD |
| 修改 | `services/evals-core/src/evals_core/dataset/manager.py` | 新增文件夹管理函数 |
| 修改 | `services/evals-core/src/evals_core/contracts.py` | 新增文件夹请求/响应模型 |
| 修改 | `services/api-server/evals_routes.py` | 新增文件夹 API 路由 |
| 修改 | `packages/evals-ui/src/types/eval.ts` | 新增 EvalFolder 类型，扩展 EvalDataset |
| 修改 | `packages/evals-ui/src/composables/useEvalDatasetTree.ts` | 从后端获取文件夹，替换 LocalFolder |
| 修改 | `packages/evals-ui/src/composables/useEvalDataset.ts` | 新增 moveDataset 方法 |
| 修改 | `packages/evals-ui/src/composables/index.ts` | 导出更新 |
| 修改 | `apps/admin-console/src/api/evals.ts` | 新增文件夹和移动 API |
| 修改 | `apps/admin-console/src/views/EvalManage.vue` | 启用拖拽、对接后端文件夹 API |
| 修改 | `packages/evals-ui/src/components/EvalDatasetTree.vue` | 透传拖拽相关 props/events |

---

### Task 1: 后端 — 数据库 Schema 扩展

**Files:**
- Modify: `services/evals-core/src/evals_core/storage/result_store.py`

- [ ] **Step 1: 在 `init_db` 中新增 `eval_folder` 表和 `eval_dataset` 的新字段**

在 `init_db()` 的 `conn.executescript(...)` 之后、`try: conn.execute("ALTER TABLE eval_run_detail...")` 之前，添加：

```python
    # 新增 eval_folder 表
    try:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS eval_folder (
                folder_id TEXT PRIMARY KEY,
                title TEXT NOT NULL DEFAULT '',
                category TEXT NOT NULL DEFAULT 'knowledge',
                parent_folder_id TEXT NOT NULL DEFAULT '',
                sort_order INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL DEFAULT '',
                updated_at TEXT NOT NULL DEFAULT ''
            )
        """)
        conn.commit()
    except Exception:
        pass

    # eval_dataset 新增 folder_id 和 sort_order 字段
    try:
        conn.execute("ALTER TABLE eval_dataset ADD COLUMN folder_id TEXT NOT NULL DEFAULT ''")
    except Exception:
        pass
    try:
        conn.execute("ALTER TABLE eval_dataset ADD COLUMN sort_order INTEGER NOT NULL DEFAULT 0")
    except Exception:
        pass
    conn.commit()
```

- [ ] **Step 2: 新增文件夹 CRUD 函数**

在 `result_store.py` 文件末尾添加：

```python
# --- 文件夹管理 ---

def insert_folder(data: Dict[str, Any]) -> Dict[str, Any]:
    """插入一条文件夹记录。"""
    now = datetime.now().isoformat()
    conn = _get_conn()
    conn.execute(
        """INSERT OR REPLACE INTO eval_folder
           (folder_id, title, category, parent_folder_id, sort_order, created_at, updated_at)
           VALUES (?, ?, ?, ?, ?, ?, ?)""",
        (
            data["folder_id"],
            data.get("title", ""),
            data.get("category", "knowledge"),
            data.get("parent_folder_id", ""),
            data.get("sort_order", 0),
            now,
            now,
        ),
    )
    conn.commit()
    return {**data, "created_at": now, "updated_at": now}


def list_folders() -> List[Dict[str, Any]]:
    """列出所有文件夹。"""
    conn = _get_conn()
    rows = conn.execute("SELECT * FROM eval_folder ORDER BY sort_order, created_at").fetchall()
    return [dict(row) for row in rows]


def get_folder(folder_id: str) -> Optional[Dict[str, Any]]:
    """获取单个文件夹。"""
    conn = _get_conn()
    row = conn.execute("SELECT * FROM eval_folder WHERE folder_id = ?", (folder_id,)).fetchone()
    return dict(row) if row else None


def update_folder(folder_id: str, updates: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """更新文件夹信息。"""
    allowed = {"title", "category", "parent_folder_id", "sort_order"}
    fields = [k for k in updates if k in allowed and updates[k] is not None]
    if not fields:
        return get_folder(folder_id)
    now = datetime.now().isoformat()
    conn = _get_conn()
    set_clause = ", ".join(f"{k} = ?" for k in fields)
    values = [updates[k] for k in fields] + [now, folder_id]
    conn.execute(f"UPDATE eval_folder SET {set_clause}, updated_at = ? WHERE folder_id = ?", values)
    conn.commit()
    return get_folder(folder_id)


def delete_folder(folder_id: str) -> bool:
    """删除文件夹，其下数据集移至分组根目录。"""
    conn = _get_conn()
    folder = get_folder(folder_id)
    if not folder:
        return False
    category = folder.get("category", "knowledge")
    conn.execute(
        "UPDATE eval_dataset SET folder_id = '', sort_order = 0 WHERE folder_id = ?",
        (folder_id,),
    )
    children = conn.execute(
        "SELECT folder_id FROM eval_folder WHERE parent_folder_id = ?", (folder_id,)
    ).fetchall()
    for child in children:
        conn.execute(
            "UPDATE eval_folder SET parent_folder_id = ? WHERE folder_id = ?",
            (f"group-{category}", child["folder_id"]),
        )
    cursor = conn.execute("DELETE FROM eval_folder WHERE folder_id = ?", (folder_id,))
    conn.commit()
    return cursor.rowcount > 0
```

- [ ] **Step 3: 扩展 `update_dataset` 的 allowed 字段**

修改 `update_dataset` 函数中的 `allowed` 集合：

```python
def update_dataset(dataset_id: str, updates: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """更新测试集元信息。"""
    allowed = {"title", "description", "category", "folder_id", "sort_order"}
    fields = [k for k in updates if k in allowed and updates[k] is not None]
    if not fields:
        return get_dataset(dataset_id)
    now = datetime.now().isoformat()
    conn = _get_conn()
    set_clause = ", ".join(f"{k} = ?" for k in fields)
    values = [updates[k] for k in fields] + [now, dataset_id]
    conn.execute(f"UPDATE eval_dataset SET {set_clause}, updated_at = ? WHERE dataset_id = ?", values)
    conn.commit()
    return get_dataset(dataset_id)
```

- [ ] **Step 4: 修改 `insert_dataset` 支持 folder_id 和 sort_order**

修改 `insert_dataset` 函数的 SQL 和参数：

```python
def insert_dataset(data: Dict[str, Any]) -> Dict[str, Any]:
    """插入一条测试集记录。"""
    now = datetime.now().isoformat()
    conn = _get_conn()
    conn.execute(
        """INSERT OR REPLACE INTO eval_dataset
           (dataset_id, title, category, description, schema_version, version,
            library_id, question_count, source_file, folder_id, sort_order, created_at, updated_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            data["dataset_id"],
            data.get("title", ""),
            data.get("category", "knowledge"),
            data.get("description", ""),
            data.get("schema_version", "eval.bundle.v2"),
            data.get("version", "1.0"),
            data.get("library_id", "default"),
            data.get("question_count", 0),
            data.get("source_file", ""),
            data.get("folder_id", ""),
            data.get("sort_order", 0),
            now,
            now,
        ),
    )
    conn.commit()
    return {**data, "created_at": now, "updated_at": now}
```

- [ ] **Step 5: Commit**

```bash
git add services/evals-core/src/evals_core/storage/result_store.py
git commit -m "feat(evals): add eval_folder table and folder_id/sort_order to eval_dataset"
```

---

### Task 2: 后端 — 文件夹管理函数与契约

**Files:**
- Modify: `services/evals-core/src/evals_core/contracts.py`
- Modify: `services/evals-core/src/evals_core/dataset/manager.py`

- [ ] **Step 1: 在 contracts.py 新增文件夹请求模型**

在 `CompareResult` 类之后添加：

```python
class CreateFolderRequest(BaseModel):
    """创建文件夹请求。"""
    folder_id: str
    title: str
    category: str = "knowledge"
    parent_folder_id: str = ""


class UpdateFolderRequest(BaseModel):
    """更新文件夹请求。"""
    title: Optional[str] = None
    category: Optional[str] = None
    parent_folder_id: Optional[str] = None
    sort_order: Optional[int] = None


class MoveDatasetRequest(BaseModel):
    """移动数据集请求。"""
    folder_id: str = ""
    sort_order: int = 0
```

- [ ] **Step 2: 在 manager.py 新增文件夹管理函数**

在文件末尾添加：

```python
# --- 文件夹管理 ---

def list_folders() -> List[Dict[str, Any]]:
    """列出所有文件夹。"""
    return result_store.list_folders()


def create_folder(data: Dict[str, Any]) -> Dict[str, Any]:
    """创建文件夹。"""
    return result_store.insert_folder(data)


def update_folder(folder_id: str, updates: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """更新文件夹信息。"""
    return result_store.update_folder(folder_id, updates)


def delete_folder(folder_id: str) -> bool:
    """删除文件夹。"""
    return result_store.delete_folder(folder_id)


def move_dataset(dataset_id: str, folder_id: str, sort_order: int = 0) -> Optional[Dict[str, Any]]:
    """移动数据集到指定文件夹。"""
    return result_store.update_dataset(dataset_id, {"folder_id": folder_id, "sort_order": sort_order})
```

- [ ] **Step 3: Commit**

```bash
git add services/evals-core/src/evals_core/contracts.py services/evals-core/src/evals_core/dataset/manager.py
git commit -m "feat(evals): add folder management functions and contracts"
```

---

### Task 3: 后端 — API 路由

**Files:**
- Modify: `services/api-server/evals_routes.py`

- [ ] **Step 1: 新增文件夹 API 路由**

在 `evals_routes.py` 中添加新的 import 和路由。先更新 import：

```python
from evals_core.contracts import (
    AddQuestionRequest,
    CompareResult,
    CreateDatasetRequest,
    CreateFolderRequest,
    EvalRunProgress,
    MoveDatasetRequest,
    StartEvalRunRequest,
    UpdateFolderRequest,
    UpdateQuestionRequest,
)
```

在 `# --- 评测运行 ---` 注释之前添加：

```python
# --- 文件夹管理 ---


@evals_router.get("/folders")
async def get_folders():
    """列出所有文件夹。"""
    folders = manager.list_folders()
    return {"folders": folders}


@evals_router.post("/folders")
async def create_folder(req: CreateFolderRequest):
    """创建文件夹。"""
    folder = manager.create_folder(req.model_dump())
    return folder


@evals_router.patch("/folders/{folder_id}")
async def update_folder(folder_id: str, req: UpdateFolderRequest):
    """更新文件夹信息。"""
    updates = req.model_dump(exclude_none=True)
    if not updates:
        raise HTTPException(status_code=400, detail="无更新内容")
    folder = manager.update_folder(folder_id, updates)
    if not folder:
        raise HTTPException(status_code=404, detail="文件夹不存在")
    return folder


@evals_router.delete("/folders/{folder_id}")
async def delete_folder(folder_id: str):
    """删除文件夹。"""
    success = manager.delete_folder(folder_id)
    if not success:
        raise HTTPException(status_code=404, detail="文件夹不存在")
    return {"status": "deleted"}


@evals_router.patch("/datasets/{dataset_id}/move")
async def move_dataset(dataset_id: str, req: MoveDatasetRequest):
    """移动数据集到指定文件夹。"""
    dataset = manager.move_dataset(dataset_id, req.folder_id, req.sort_order)
    if not dataset:
        raise HTTPException(status_code=404, detail="测试集不存在")
    return dataset
```

- [ ] **Step 2: Commit**

```bash
git add services/api-server/evals_routes.py
git commit -m "feat(evals): add folder CRUD and dataset move API routes"
```

---

### Task 4: 前端 — 类型与 API 扩展

**Files:**
- Modify: `packages/evals-ui/src/types/eval.ts`
- Modify: `apps/admin-console/src/api/evals.ts`

- [ ] **Step 1: 在 eval.ts 新增 EvalFolder 类型，扩展 EvalDataset**

在 `EvalDatasetCategory` 类型定义之后添加：

```typescript
/** 评测文件夹 */
export interface EvalFolder {
  folder_id: string
  title: string
  category: EvalDatasetCategory
  parent_folder_id: string
  sort_order: number
  created_at: string
  updated_at: string
}
```

在 `EvalDataset` 接口中添加 `folder_id` 和 `sort_order` 字段：

```typescript
export interface EvalDataset {
  dataset_id: string
  title: string
  category: EvalDatasetCategory
  description: string
  schema_version: string
  version: string
  library_id: string
  question_count: number
  source_file: string
  folder_id: string
  sort_order: number
  created_at: string
  updated_at: string
}
```

- [ ] **Step 2: 在 evals.ts API 客户端新增文件夹和移动 API**

在 `evalsApi` 对象中添加：

```typescript
  getFolders: () => api.get('/folders').then(r => r.data),

  createFolder: (payload: { folder_id: string; title: string; category: string; parent_folder_id?: string }) =>
    api.post('/folders', payload).then(r => r.data),

  updateFolder: (folderId: string, payload: { title?: string; parent_folder_id?: string; sort_order?: number }) =>
    api.patch(`/folders/${folderId}`, payload).then(r => r.data),

  deleteFolder: (folderId: string) =>
    api.delete(`/folders/${folderId}`).then(r => r.data),

  moveDataset: (datasetId: string, payload: { folder_id: string; sort_order: number }) =>
    api.patch(`/datasets/${datasetId}/move`, payload).then(r => r.data),
```

- [ ] **Step 3: Commit**

```bash
git add packages/evals-ui/src/types/eval.ts apps/admin-console/src/api/evals.ts
git commit -m "feat(evals): add EvalFolder type and folder/move API client"
```

---

### Task 5: 前端 — useEvalDatasetTree 改为后端文件夹

**Files:**
- Modify: `packages/evals-ui/src/composables/useEvalDatasetTree.ts`

- [ ] **Step 1: 重写 useEvalDatasetTree，从后端获取文件夹**

将整个文件替换为：

```typescript
/**
 * 评测数据集树数据转换 composable。
 * 将 EvalDataset[] + EvalFolder[] 转换为 SmartTreeNode[]，提供分组、展开等计算属性。
 */
import { computed, type Ref } from 'vue'
import type { SmartTreeNode } from '@angineer/ui-kit'
import type { EvalDataset, EvalDatasetCategory, EvalFolder } from '../types/eval'

export interface EvalTreeNode extends SmartTreeNode {
  questionCount?: number
  category?: EvalDatasetCategory
}

const ALL_CATEGORIES: { key: EvalDatasetCategory; label: string }[] = [
  { key: 'knowledge', label: '知识库评测' },
  { key: 'sop', label: 'SOP 评测' },
  { key: 'full_chain', label: '全链路评测' },
]

/** 判断是否为虚拟分组节点（按类别自动聚合的文件夹） */
export const isGroupNode = (node: SmartTreeNode): boolean => {
  return !!(node.key && String(node.key).startsWith('group-'))
}

/** 判断是否为后端持久化文件夹节点 */
export const isPersistedFolder = (node: SmartTreeNode): boolean => {
  return !!(node.key && String(node.key).startsWith('folder-'))
}

/** 从 group 节点 key 中提取 category */
export const getCategoryFromGroupKey = (key: string): EvalDatasetCategory => {
  return key.replace('group-', '') as EvalDatasetCategory
}

/** 从节点 key 或属性中提取 category */
export const getCategoryFromNode = (node: SmartTreeNode): EvalDatasetCategory => {
  if (isGroupNode(node)) return getCategoryFromGroupKey(String(node.key))
  if ((node as EvalTreeNode).category) return (node as EvalTreeNode).category!
  return 'knowledge'
}

/** 获取文件夹在分组中的父 key */
const getFolderParentKey = (folder: EvalFolder): string => {
  if (folder.parent_folder_id && folder.parent_folder_id.startsWith('folder-')) {
    return folder.parent_folder_id
  }
  return `group-${folder.category}`
}

export function useEvalDatasetTree(
  datasets: Ref<EvalDataset[]>,
  folders?: Ref<EvalFolder[]>,
) {
  /** 递归构建指定父节点下的文件夹子树 */
  const buildFolderTree = (parentKey: string, category: EvalDatasetCategory): SmartTreeNode[] => {
    const childFolders = (folders?.value || [])
      .filter(f => getFolderParentKey(f) === parentKey && f.category === category)
    return childFolders
      .sort((a, b) => a.sort_order - b.sort_order)
      .map(f => ({
        key: f.folder_id,
        title: f.title,
        isFolder: true as const,
        selectable: true,
        category: f.category,
        children: buildFolderTree(f.folder_id, category),
      }))
  }

  /** 将 datasets 按类别和文件夹分组并转换为树结构 */
  const treeData = computed<SmartTreeNode[]>(() => {
    const groups: Record<string, EvalDataset[]> = {}
    for (const ds of datasets.value) {
      const cat = ds.category || 'knowledge'
      if (!groups[cat]) groups[cat] = []
      groups[cat].push(ds)
    }

    return ALL_CATEGORIES.map(({ key, label }) => ({
      key: `group-${key}`,
      title: label,
      isFolder: true,
      selectable: false,
      category: key,
      children: [
        ...buildFolderTree(`group-${key}`, key),
        ...(groups[key] || [])
          .filter(ds => !ds.folder_id || ds.folder_id === '')
          .sort((a, b) => a.sort_order - b.sort_order)
          .map(item => ({
            key: item.dataset_id,
            title: item.title,
            isLeaf: true,
            isFolder: false,
            questionCount: item.question_count,
            category: item.category,
          })),
      ],
    }))
  })

  /** 默认展开所有分组节点 */
  const defaultExpandedKeys = computed(() =>
    treeData.value.map(n => n.key)
  )

  return {
    treeData,
    defaultExpandedKeys,
    isGroupNode,
    isPersistedFolder,
    getCategoryFromGroupKey,
    getCategoryFromNode,
  }
}
```

- [ ] **Step 2: 更新 composables/index.ts 导出**

确认 `isLocalFolder` 已被替换为 `isPersistedFolder`：

```typescript
export { useEvalDatasetTree, isGroupNode, isPersistedFolder, getCategoryFromGroupKey, getCategoryFromNode } from './useEvalDatasetTree'
export type { EvalTreeNode, LocalFolder } from './useEvalDatasetTree'
```

注意：保留 `LocalFolder` 类型导出以避免破坏其他引用，但实际不再使用。如果 `LocalFolder` 在 `useEvalDatasetTree.ts` 中已删除，则从导出中也删除。

- [ ] **Step 3: Commit**

```bash
git add packages/evals-ui/src/composables/useEvalDatasetTree.ts packages/evals-ui/src/composables/index.ts
git commit -m "feat(evals): useEvalDatasetTree reads folders from backend"
```

---

### Task 6: 前端 — useEvalDataset 新增文件夹和移动方法

**Files:**
- Modify: `packages/evals-ui/src/composables/useEvalDataset.ts`

- [ ] **Step 1: 新增文件夹和移动方法**

在 `useEvalDataset` 函数中添加：

```typescript
import type { EvalDataset, EvalFolder, EvalQuestion } from '../types/eval'
```

新增状态和方法：

```typescript
  const folders = ref<EvalFolder[]>([])

  const fetchFolders = async () => {
    try {
      const resp = await fetch('/api/evals/folders')
      if (resp.ok) {
        const data = await resp.json()
        folders.value = data.folders || []
      }
    } catch {
      folders.value = []
    }
  }

  const createFolder = async (payload: { title: string; category: string; parent_folder_id?: string }) => {
    const folderId = `folder-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 8)}`
    const body = { folder_id: folderId, ...payload }
    const resp = await fetch('/api/evals/folders', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    })
    if (resp.ok) {
      await fetchFolders()
      return await resp.json()
    }
    const errText = await resp.text().catch(() => '')
    throw new Error(errText || `创建文件夹失败 (${resp.status})`)
  }

  const renameFolder = async (folderId: string, newTitle: string) => {
    const resp = await fetch(`/api/evals/folders/${folderId}`, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ title: newTitle }),
    })
    if (resp.ok) {
      await fetchFolders()
      return true
    }
    const errText = await resp.text().catch(() => '')
    throw new Error(errText || `重命名文件夹失败 (${resp.status})`)
  }

  const deleteFolder = async (folderId: string) => {
    const resp = await fetch(`/api/evals/folders/${folderId}`, { method: 'DELETE' })
    if (resp.ok) {
      await fetchFolders()
      await fetchDatasets()
      return true
    }
    const errText = await resp.text().catch(() => '')
    throw new Error(errText || `删除文件夹失败 (${resp.status})`)
  }

  const moveDataset = async (datasetId: string, folderId: string, sortOrder: number = 0) => {
    const resp = await fetch(`/api/evals/datasets/${datasetId}/move`, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ folder_id: folderId, sort_order: sortOrder }),
    })
    if (resp.ok) {
      await fetchDatasets()
      return true
    }
    const errText = await resp.text().catch(() => '')
    throw new Error(errText || `移动失败 (${resp.status})`)
  }
```

在 return 中添加：

```typescript
    folders,
    fetchFolders,
    createFolder,
    renameFolder,
    deleteFolder,
    moveDataset,
```

- [ ] **Step 2: Commit**

```bash
git add packages/evals-ui/src/composables/useEvalDataset.ts
git commit -m "feat(evals): add folder CRUD and moveDataset to useEvalDataset"
```

---

### Task 7: 前端 — EvalDatasetTree 透传拖拽

**Files:**
- Modify: `packages/evals-ui/src/components/EvalDatasetTree.vue`

- [ ] **Step 1: 确认 EvalDatasetTree 已透传所有拖拽相关 props 和 events**

当前 `EvalDatasetTree` 已透传 `draggable` prop 和 `@drop`/`@drop-root`/`@drop-invalid` 事件，无需修改。确认以下内容存在：

- Props 中有 `draggable?: boolean`
- `SmartTree` 上有 `:draggable="draggable"`
- emit 中有 `drop`/`drop-root`/`drop-invalid`

如果缺少，补充即可。

- [ ] **Step 2: Commit（如有修改）**

---

### Task 8: 前端 — EvalManage.vue 启用拖拽与对接后端

**Files:**
- Modify: `apps/admin-console/src/views/EvalManage.vue`

- [ ] **Step 1: 替换 LocalFolder 为后端文件夹**

1. 移除 `localFolders` ref
2. 从 `useEvalDataset` 解构 `folders`、`fetchFolders`、`createFolder`、`renameFolder`、`deleteFolder`、`moveDataset`
3. 将 `useEvalDatasetTree(datasets, localFolders)` 改为 `useEvalDatasetTree(datasets, folders)`
4. 将 `isLocalFolderFn` 引用改为 `isPersistedFolder`

- [ ] **Step 2: 启用拖拽**

将 `EvalDatasetTree` 的 `:draggable="false"` 改为 `:draggable="true"`，并添加事件处理：

```html
<EvalDatasetTree
  ...
  :draggable="true"
  @drop="onTreeDrop"
  @drop-root="onTreeDropRoot"
  @drop-invalid="onInvalidDrop"
>
```

- [ ] **Step 3: 添加拖拽事件处理函数**

```typescript
/** 处理树节点拖放 */
const onTreeDrop = async (info: any) => {
  const dragKey = String(info.dragNode?.key || '')
  const dropKey = String(info.node?.key || '')

  if (isGroupNodeFn({ key: dragKey } as EvalTreeNode)) return
  if (isGroupNodeFn({ key: dropKey } as EvalTreeNode) && !info.dropToGap) return

  const dropToGap = info.dropToGap
  const dropNode = info.node
  const isDropFolder = dropNode?.isFolder === true

  let targetFolderId = ''
  if (!dropToGap && isDropFolder) {
    targetFolderId = dropKey.startsWith('folder-') ? dropKey : ''
  } else if (dropToGap) {
    const dropCategory = getCategoryFromNode(dropNode)
    targetFolderId = dropKey.startsWith('folder-') ? dropKey : ''
  }

  try {
    await moveDataset(dragKey, targetFolderId)
    message.success('移动成功')
  } catch (e: any) {
    message.error(e.message || '移动失败')
    await fetchDatasets()
  }
}

/** 处理拖到根目录 */
const onTreeDropRoot = async (dragNodeKey: string) => {
  if (isGroupNodeFn({ key: dragNodeKey } as EvalTreeNode)) return
  try {
    await moveDataset(dragNodeKey, '')
    message.success('已移动到根目录')
  } catch (e: any) {
    message.error(e.message || '移动失败')
    await fetchDatasets()
  }
}

/** 处理无效拖放 */
const onInvalidDrop = (reason: string) => {
  const messages: Record<string, string> = {
    'same-node': '不能拖到自身',
    'drop-to-descendant': '不能拖到子节点中',
    'drop-into-file': '不能拖入文件节点',
  }
  message.warning(messages[reason] || '无效的拖放操作')
}
```

- [ ] **Step 4: 修改文件夹操作对接后端**

将 `handleFolderModalOk` 改为调用后端 API：

```typescript
const handleFolderModalOk = async () => {
  if (!folderForm.value.name.trim()) {
    message.error('请输入文件夹名称')
    return
  }

  folderModalLoading.value = true
  try {
    if (folderForm.value.isNew) {
      const category = folderForm.value.parentId
        ? (getCategoryFromNode({ key: folderForm.value.parentId } as EvalTreeNode) || 'knowledge')
        : 'knowledge'
      const parentFolderId = (folderForm.value.parentId?.startsWith('folder-') ? folderForm.value.parentId : '')
      await createFolder({
        title: folderForm.value.name.trim(),
        category,
        parent_folder_id: parentFolderId || undefined,
      })
      message.success('创建成功')
    } else {
      await renameFolder(folderForm.value.nodeId, folderForm.value.name.trim())
      message.success('重命名成功')
    }
    folderModalVisible.value = false
  } catch (e: any) {
    message.error(e.message || '操作失败')
  } finally {
    folderModalLoading.value = false
  }
}
```

- [ ] **Step 5: 修改 onDatasetDelete 对接后端文件夹删除**

在 `onDatasetDelete` 中，如果删除的是文件夹节点，调用 `deleteFolder`：

找到 `onDatasetDelete` 函数，在处理 `isLocalFolderFn` 的分支改为：

```typescript
if (isPersistedFolder(node)) {
  modal.confirm({
    title: '删除文件夹',
    content: '删除后，文件夹内的数据集将移至分组根目录。确定删除？',
    okText: '确认',
    cancelText: '取消',
    async onOk() {
      try {
        await deleteFolder(key)
        message.success('删除成功')
      } catch (e: any) {
        message.error(e.message || '删除失败')
      }
    },
  })
  return
}
```

- [ ] **Step 6: 修改 onDatasetRename 对接后端文件夹重命名**

在 `onDatasetRename` 中，将 `isLocalFolderFn` 分支改为调用 `renameFolder`：

```typescript
if (isPersistedFolder(node)) {
  folderForm.value = {
    name: node.title,
    parentId: undefined,
    isNew: false,
    nodeId: key,
  }
  folderModalVisible.value = true
  return
}
```

- [ ] **Step 7: 在 onMounted 中加载文件夹数据**

```typescript
onMounted(() => {
  fetchDatasets()
  fetchFolders()
})
```

- [ ] **Step 8: 移除不再需要的 LocalFolder 相关代码**

- 移除 `localFolders` ref
- 移除 `generateFolderId` 函数
- 移除 `collectFolderKeys` 函数
- 移除 `isLocalFolderFn` 引用，替换为 `isPersistedFolder`
- 更新 import：从 `@angineer/evals-ui` 中导入 `isPersistedFolder` 替代 `isLocalFolder`

- [ ] **Step 9: Commit**

```bash
git add apps/admin-console/src/views/EvalManage.vue
git commit -m "feat(evals): enable drag-and-drop with backend folder persistence"
```

---

### Task 9: 验证与清理

**Files:**
- All modified files

- [ ] **Step 1: 运行 lint**

```bash
pnpm -w run lint
```

- [ ] **Step 2: 运行 harness（如可用）**

```bash
pnpm harness
```

- [ ] **Step 3: 手动验证**

1. 启动 `pnpm run serve`
2. 进入评测管理页面
3. 验证文件夹创建/重命名/删除持久化
4. 验证数据集拖拽移动到文件夹
5. 验证"拖到此处移动到根目录"功能
6. 验证知识库树的"拖到此处移动到根目录"功能已修复
