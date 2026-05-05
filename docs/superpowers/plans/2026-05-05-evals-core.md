# evals-core 统一评测体系 实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 为 AnGIneer 建立完整的评测体系，包含后端评测引擎（evals-core）、前端评测组件（evals-ui）、API 路由和管理后台集成。

**Architecture:** evals-core 作为独立 Python 包，api-server 新增 /api/evals/* 路由组调用它。前端 evals-ui 作为独立 Vue 组件包，admin-console 新增"测试集"tab 页面组合使用。评测执行采用异步+轮询模式，结果持久化到 SQLite。

**Tech Stack:** Python 3.10+ / FastAPI / Pydantic / SQLite / Vue 3 / TypeScript / Ant Design Vue 4.x / Less / Pinia

**Spec:** `docs/superpowers/specs/2026-05-05-evals-core-design.md`

---

## File Structure

### 新建文件

| 文件 | 职责 |
|------|------|
| `services/evals-core/pyproject.toml` | 包定义与依赖 |
| `services/evals-core/src/evals_core/__init__.py` | 包入口 |
| `services/evals-core/src/evals_core/dataset/__init__.py` | dataset 子包 |
| `services/evals-core/src/evals_core/dataset/schema.py` | Pydantic 数据模型 |
| `services/evals-core/src/evals_core/dataset/loader.py` | JSON 题集加载与校验 |
| `services/evals-core/src/evals_core/dataset/manager.py` | 题集 CRUD |
| `services/evals-core/src/evals_core/runner/__init__.py` | runner 子包 |
| `services/evals-core/src/evals_core/runner/base.py` | 评测器基类 |
| `services/evals-core/src/evals_core/runner/retrieval_eval.py` | 检索评测 |
| `services/evals-core/src/evals_core/runner/answer_eval.py` | 回答评测 |
| `services/evals-core/src/evals_core/runner/text2sql_eval.py` | SQL 评测 |
| `services/evals-core/src/evals_core/runner/sop_eval.py` | SOP 评测骨架 |
| `services/evals-core/src/evals_core/runner/suite_runner.py` | 评测套件编排 |
| `services/evals-core/src/evals_core/storage/__init__.py` | storage 子包 |
| `services/evals-core/src/evals_core/storage/result_store.py` | SQLite 存储 |
| `services/evals-core/src/evals_core/contracts.py` | API 请求/响应模型 |
| `apps/api-server/evals_routes.py` | API 路由 |
| `packages/evals-ui/package.json` | 前端包定义 |
| `packages/evals-ui/tsconfig.json` | TS 配置 |
| `packages/evals-ui/src/index.ts` | 统一导出 |
| `packages/evals-ui/src/types/eval.ts` | 类型定义 |
| `packages/evals-ui/src/styles/index.less` | 样式入口 |
| `packages/evals-ui/src/styles/variables.less` | 样式变量 |
| `packages/evals-ui/src/components/EvalLevelBadge.vue` | L1-L4 标签 |
| `packages/evals-ui/src/components/EvalScoreBar.vue` | 得分进度条 |
| `packages/evals-ui/src/components/EvalDatasetTree.vue` | 测试集树 |
| `packages/evals-ui/src/components/EvalQuestionCard.vue` | 题目卡片 |
| `packages/evals-ui/src/components/EvalQuestionList.vue` | 题目列表 |
| `packages/evals-ui/src/components/EvalRunPanel.vue` | 运行面板 |
| `packages/evals-ui/src/components/EvalImportModal.vue` | 导入弹窗 |
| `packages/evals-ui/src/components/EvalCompareView.vue` | 对比视图 |
| `packages/evals-ui/src/composables/index.ts` | composable 导出 |
| `packages/evals-ui/src/composables/useEvalDataset.ts` | 测试集数据 |
| `packages/evals-ui/src/composables/useEvalRun.ts` | 评测运行 |
| `packages/evals-ui/src/composables/useEvalCompare.ts` | 历史对比 |
| `apps/admin-console/src/api/evals.ts` | API 客户端 |
| `apps/admin-console/src/views/EvalManage.vue` | 测试集页面 |

### 修改文件

| 文件 | 改动 |
|------|------|
| `apps/api-server/main.py` | 添加 evals-core 路径到 sys.path，挂载 evals_router |
| `apps/admin-console/src/App.vue` | navItems 增加 evals 项 |
| `apps/admin-console/src/router/index.ts` | 增加 /evals 路由 |
| `apps/admin-console/package.json` | 增加 @angineer/evals-ui 依赖 |
| `package.json` | 增加 evals 相关脚本 |

---

## Phase 1: 后端 — services/evals-core

### Task 1: evals-core 包骨架

**Files:**
- Create: `services/evals-core/pyproject.toml`
- Create: `services/evals-core/src/evals_core/__init__.py`
- Create: `services/evals-core/src/evals_core/dataset/__init__.py`
- Create: `services/evals-core/src/evals_core/runner/__init__.py`
- Create: `services/evals-core/src/evals_core/storage/__init__.py`

- [ ] **Step 1: 创建 pyproject.toml**

```toml
[build-system]
requires = ["setuptools>=68", "wheel"]
build-backend = "setuptools.build_meta"

[project]
name = "angineer-evals-core"
version = "0.1.0"
description = "AnGIneer evaluation engine"
requires-python = ">=3.10"
dependencies = [
    "pydantic>=2.0.0",
    "httpx>=0.25.0",
]

[tool.setuptools]
package-dir = {"" = "src"}

[tool.setuptools.packages.find]
where = ["src"]
```

- [ ] **Step 2: 创建包入口文件**

`services/evals-core/src/evals_core/__init__.py`:
```python
"""AnGIneer 统一评测引擎。"""
```

`services/evals-core/src/evals_core/dataset/__init__.py`:
```python
"""题集管理子包。"""
```

`services/evals-core/src/evals_core/runner/__init__.py`:
```python
"""评测执行子包。"""
```

`services/evals-core/src/evals_core/storage/__init__.py`:
```python
"""结果持久化子包。"""
```

- [ ] **Step 3: 安装 evals-core**

Run: `pip install -e services/evals-core`
Expected: Successfully installed angineer-evals-core-0.1.0

- [ ] **Step 4: 验证包可导入**

Run: `python -c "import evals_core; print(evals_core.__name__)"`
Expected: evals_core

- [ ] **Step 5: Commit**

```bash
git add services/evals-core/
git commit -m "feat: add evals-core package skeleton"
```

---

### Task 2: 数据模型（schema.py + contracts.py）

**Files:**
- Create: `services/evals-core/src/evals_core/dataset/schema.py`
- Create: `services/evals-core/src/evals_core/contracts.py`

- [ ] **Step 1: 创建 dataset/schema.py** — 包含 RetrievalGold, AnswerGold, SqlGold, SopGold, EvalQuestionItem, EvalDatasetMeta, EvalBundleV2, EvalDatasetRow, EvalQuestionRow 等 Pydantic 模型。完整代码见 spec 第 6.1 节的数据结构。

- [ ] **Step 2: 创建 contracts.py** — 包含 CreateDatasetRequest, AddQuestionRequest, UpdateQuestionRequest, StartEvalRunRequest, EvalRunProgress, CompareResult 等 API 契约模型。完整代码见 spec 第 4 节的请求/响应结构。

- [ ] **Step 3: 验证模型可导入**

Run: `python -c "from evals_core.dataset.schema import EvalBundleV2; print('OK')"`
Expected: OK

- [ ] **Step 4: Commit**

```bash
git add services/evals-core/src/evals_core/dataset/schema.py services/evals-core/src/evals_core/contracts.py
git commit -m "feat: add evals-core data models and API contracts"
```

---

### Task 3: SQLite 存储（result_store.py）

**Files:**
- Create: `services/evals-core/src/evals_core/storage/result_store.py`

- [ ] **Step 1: 创建 result_store.py** — 包含 init_db, insert_dataset, update_dataset_question_count, list_datasets, get_dataset, delete_dataset, insert_question, list_questions, delete_question, create_run, update_run_progress, complete_run, fail_run, get_run, list_runs, insert_run_detail, update_run_detail, list_run_details 等函数。数据库路径为 `data/evals/evals.db`，表结构见 spec 第 6.2 节。

- [ ] **Step 2: 验证数据库初始化**

Run: `python -c "from evals_core.storage.result_store import init_db; init_db(); print('OK')"`
Expected: OK

- [ ] **Step 3: Commit**

```bash
git add services/evals-core/src/evals_core/storage/result_store.py
git commit -m "feat: add evals-core SQLite result store"
```

---

### Task 4: 题集加载器（loader.py）

**Files:**
- Create: `services/evals-core/src/evals_core/dataset/loader.py`

- [ ] **Step 1: 创建 loader.py** — 包含 load_bundle_from_file, load_bundle_from_dict, list_bundle_files, export_bundle_to_dict 函数。使用 schema.py 的 EvalBundleV2 进行校验。

- [ ] **Step 2: Commit**

```bash
git add services/evals-core/src/evals_core/dataset/loader.py
git commit -m "feat: add evals-core dataset loader"
```

---

### Task 5: 题集管理器（manager.py）

**Files:**
- Create: `services/evals-core/src/evals_core/dataset/manager.py`

- [ ] **Step 1: 创建 manager.py** — 包含 create_dataset, import_bundle, get_dataset, list_datasets, delete_dataset, add_question, update_question, delete_question, list_questions, export_dataset 函数。调用 result_store 和 loader。

- [ ] **Step 2: Commit**

```bash
git add services/evals-core/src/evals_core/dataset/manager.py
git commit -m "feat: add evals-core dataset manager"
```

---

### Task 6: 评测器 + 套件运行器

**Files:**
- Create: `services/evals-core/src/evals_core/runner/base.py`
- Create: `services/evals-core/src/evals_core/runner/retrieval_eval.py`
- Create: `services/evals-core/src/evals_core/runner/answer_eval.py`
- Create: `services/evals-core/src/evals_core/runner/text2sql_eval.py`
- Create: `services/evals-core/src/evals_core/runner/sop_eval.py`
- Create: `services/evals-core/src/evals_core/runner/suite_runner.py`

> 合并提交，因为评测器之间有依赖关系（answer_eval 依赖 retrieval_eval 的 normalize_section_path）。

- [ ] **Step 1: 创建 base.py** — BaseEvaluator ABC（run_prediction + evaluate 抽象方法），注册表 register_evaluator/get_evaluator/list_evaluator_names

- [ ] **Step 2: 创建 retrieval_eval.py** — RetrievalEvaluator，从 docs-core 的 eval_retrieval.py 迁移核心逻辑（normalize_section_path, compute_section_hit, compute_section_mrr），通过 httpx 调用 /api/query

- [ ] **Step 3: 创建 answer_eval.py** — AnswerEvaluator，从 docs-core 的 eval_answer.py 迁移核心逻辑（normalize_eval_text, evaluate_correctness_check, is_refusal, citations_match_section_paths），通过 httpx 调用 /api/query

- [ ] **Step 4: 创建 text2sql_eval.py** — Text2SqlEvaluator，从 docs-core 的 eval_text2sql.py 迁移核心逻辑

- [ ] **Step 5: 创建 sop_eval.py** — SopEvaluator 骨架，run_prediction 和 evaluate 均返回"not yet implemented"

- [ ] **Step 6: 创建 suite_runner.py** — 包含 _build_evaluators, _average_scores, _run_single_question, _run_suite_thread, _compute_summary, start_eval_run, get_eval_run, list_eval_runs, compare_runs。使用 threading.Thread 异步执行评测，每完成一题更新 SQLite 进度

- [ ] **Step 7: 验证所有评测器可导入**

Run: `python -c "from evals_core.runner.suite_runner import start_eval_run, compare_runs; print('OK')"`
Expected: OK

- [ ] **Step 8: Commit**

```bash
git add services/evals-core/src/evals_core/runner/
git commit -m "feat: add evals-core evaluators and suite runner"
```

---

## Phase 2: API 路由

### Task 7: evals_routes.py

**Files:**
- Create: `apps/api-server/evals_routes.py`

- [ ] **Step 1: 创建 evals_routes.py** — FastAPI APIRouter，包含：
  - startup 事件：init_db()
  - GET /datasets, POST /datasets, POST /datasets/import, GET /datasets/{id}, DELETE /datasets/{id}
  - GET /datasets/{id}/questions, POST /datasets/{id}/questions, PUT /datasets/{id}/questions/{qid}, DELETE /datasets/{id}/questions/{qid}
  - GET /datasets/{id}/export
  - POST /runs, GET /runs/{id}, GET /runs, GET /compare
  - 调用 manager 和 suite_runner 的函数

- [ ] **Step 2: Commit**

```bash
git add apps/api-server/evals_routes.py
git commit -m "feat: add evals API routes"
```

---

### Task 8: 挂载路由到 main.py

**Files:**
- Modify: `apps/api-server/main.py`

- [ ] **Step 1: 在 main.py 的 sys.path 部分添加 evals-core 路径**

在现有 `sys.path.append(os.path.join(SERVICES_DIR, "engtools", "src"))` 之后添加：
```python
sys.path.append(os.path.join(SERVICES_DIR, "evals-core", "src"))
```

- [ ] **Step 2: 在 main.py 的 import 部分添加 evals_routes 导入**

在现有 `from knowledge_routes import knowledge_router, preview_router` 之后添加：
```python
from evals_routes import evals_router
```

- [ ] **Step 3: 在 main.py 的路由挂载部分添加 evals_router**

在现有 `app.include_router(preview_router, prefix="/api", tags=["Preview"])` 之后添加：
```python
app.include_router(evals_router, prefix="/api/evals", tags=["Evals"])
```

- [ ] **Step 4: 验证 API 启动**

Run: `python apps/api-server/main.py`
Expected: 服务启动，访问 http://localhost:8789/docs 可看到 Evals 路由组

- [ ] **Step 5: Commit**

```bash
git add apps/api-server/main.py
git commit -m "feat: mount evals routes in api-server"
```

---

## Phase 3: 前端 — packages/evals-ui

### Task 9: evals-ui 包骨架

**Files:**
- Create: `packages/evals-ui/package.json`
- Create: `packages/evals-ui/tsconfig.json`
- Create: `packages/evals-ui/src/index.ts`
- Create: `packages/evals-ui/src/types/eval.ts`
- Create: `packages/evals-ui/src/styles/index.less`
- Create: `packages/evals-ui/src/styles/variables.less`

- [ ] **Step 1: 创建 package.json** — 参照 docs-ui 的格式，name 为 @angineer/evals-ui，peerDependencies 包含 vue/ant-design-vue/pinia/@ant-design/icons-vue，dependencies 包含 @angineer/ui-kit

- [ ] **Step 2: 创建 tsconfig.json** — 参照 docs-ui 的格式

- [ ] **Step 3: 创建 types/eval.ts** — 定义 EvalDataset, EvalQuestion, EvalRun, EvalRunDetail, EvalCompareResult 等接口，与后端 contracts.py 对齐

- [ ] **Step 4: 创建 styles/variables.less** — 定义评测相关 CSS 变量（颜色、间距等）

- [ ] **Step 5: 创建 styles/index.less** — 导入 variables.less

- [ ] **Step 6: 创建 src/index.ts** — 统一导出所有组件、composables 和类型

- [ ] **Step 7: 安装依赖**

Run: `pnpm install`
Expected: @angineer/evals-ui 链接成功

- [ ] **Step 8: Commit**

```bash
git add packages/evals-ui/
git commit -m "feat: add evals-ui package skeleton"
```

---

### Task 10: 小组件（EvalLevelBadge + EvalScoreBar）

**Files:**
- Create: `packages/evals-ui/src/components/EvalLevelBadge.vue`
- Create: `packages/evals-ui/src/components/EvalScoreBar.vue`

- [ ] **Step 1: 创建 EvalLevelBadge.vue** — 接收 level prop（L1/L2/L3/L4），显示对应颜色的标签。L1=蓝, L2=绿, L3=橙, L4=红。使用 a-tag 组件。

- [ ] **Step 2: 创建 EvalScoreBar.vue** — 接收 label/score/maxScore/percentage props，显示进度条。使用 a-progress 组件，score >= 0.8 为绿色，0.5-0.8 为橙色，< 0.5 为红色。

- [ ] **Step 3: Commit**

```bash
git add packages/evals-ui/src/components/EvalLevelBadge.vue packages/evals-ui/src/components/EvalScoreBar.vue
git commit -m "feat: add EvalLevelBadge and EvalScoreBar components"
```

---

### Task 11: 测试集树（EvalDatasetTree.vue）

**Files:**
- Create: `packages/evals-ui/src/components/EvalDatasetTree.vue`

- [ ] **Step 1: 创建 EvalDatasetTree.vue** — 左栏组件：
  - Props: datasets（EvalDataset[]）, selectedId（string）
  - Emits: select（dataset_id）, import, create
  - 按类别分组显示（knowledge/sop/full_chain），使用 a-tree 组件
  - 底部显示统计信息和"导入""新建"按钮
  - 参照 KnowledgeManage.vue 左栏的树形管理风格

- [ ] **Step 2: Commit**

```bash
git add packages/evals-ui/src/components/EvalDatasetTree.vue
git commit -m "feat: add EvalDatasetTree component"
```

---

### Task 12: 题目卡片和列表（EvalQuestionCard + EvalQuestionList）

**Files:**
- Create: `packages/evals-ui/src/components/EvalQuestionCard.vue`
- Create: `packages/evals-ui/src/components/EvalQuestionList.vue`

- [ ] **Step 1: 创建 EvalQuestionCard.vue** — 单题卡片：
  - Props: question（EvalQuestion）, detail（EvalRunDetail | null）, expanded（boolean）
  - Emits: toggle（question_id）
  - 折叠态：EvalLevelBadge + question_id + 问题文本 + 状态标签（passed/failed/pending）
  - 展开态：系统回答 vs 标准答案左右配对、正确性校验结果、检索/SQL 分项得分

- [ ] **Step 2: 创建 EvalQuestionList.vue** — 题目列表：
  - Props: questions（EvalQuestion[]）, runDetails（Map<string, EvalRunDetail>）, loading（boolean）
  - Emits: toggle（question_id）
  - 顶部筛选栏：按 intent_level / status 筛选
  - 使用 a-collapse 或自定义展开/折叠逻辑渲染 EvalQuestionCard 列表

- [ ] **Step 3: Commit**

```bash
git add packages/evals-ui/src/components/EvalQuestionCard.vue packages/evals-ui/src/components/EvalQuestionList.vue
git commit -m "feat: add EvalQuestionCard and EvalQuestionList components"
```

---

### Task 13: 运行面板（EvalRunPanel.vue）

**Files:**
- Create: `packages/evals-ui/src/components/EvalRunPanel.vue`

- [ ] **Step 1: 创建 EvalRunPanel.vue** — 右栏组件：
  - Props: datasetId（string）, currentRun（EvalRun | null）
  - Emits: run, compare
  - 一键运行按钮（运行中时禁用并显示进度）
  - 综合得分（大数字显示 overall_score）
  - 分项指标进度条（retrieval/answer/sql/sop）使用 EvalScoreBar
  - 按意图层级统计（L1/L2/L3/L4 通过数）
  - 历史对比入口按钮

- [ ] **Step 2: Commit**

```bash
git add packages/evals-ui/src/components/EvalRunPanel.vue
git commit -m "feat: add EvalRunPanel component"
```

---

### Task 14: 导入弹窗 + 对比视图

**Files:**
- Create: `packages/evals-ui/src/components/EvalImportModal.vue`
- Create: `packages/evals-ui/src/components/EvalCompareView.vue`

- [ ] **Step 1: 创建 EvalImportModal.vue** — JSON 导入弹窗：
  - Props: visible（boolean）
  - Emits: update:visible, imported
  - 使用 a-upload 的 drag 上传模式，限制 .json 文件
  - 上传到 POST /api/evals/datasets/import

- [ ] **Step 2: 创建 EvalCompareView.vue** — 历史对比视图：
  - Props: visible（boolean）, runs（EvalRun[]）
  - Emits: update:visible
  - 两次运行选择器（a-select）
  - 各指标变化（↑↓箭头 + 颜色）
  - 逐题通过/失败变化列表

- [ ] **Step 3: Commit**

```bash
git add packages/evals-ui/src/components/EvalImportModal.vue packages/evals-ui/src/components/EvalCompareView.vue
git commit -m "feat: add EvalImportModal and EvalCompareView components"
```

---

### Task 15: Composables

**Files:**
- Create: `packages/evals-ui/src/composables/index.ts`
- Create: `packages/evals-ui/src/composables/useEvalDataset.ts`
- Create: `packages/evals-ui/src/composables/useEvalRun.ts`
- Create: `packages/evals-ui/src/composables/useEvalCompare.ts`

- [ ] **Step 1: 创建 useEvalDataset.ts** — 管理测试集数据：
  - datasets（ref<EvalDataset[]>）
  - selectedDataset（ref<EvalDataset | null>）
  - questions（ref<EvalQuestion[]>）
  - fetchDatasets(), selectDataset(id), importDataset(file), createDataset(data)
  - 调用 /api/evals/datasets/* 端点

- [ ] **Step 2: 创建 useEvalRun.ts** — 管理评测运行 + 轮询：
  - currentRun（ref<EvalRun | null>）
  - runDetails（ref<Map<string, EvalRunDetail>>）
  - isRunning（computed）
  - startRun(datasetId) — POST /api/evals/runs，启动 2 秒轮询
  - pollRun(runId) — GET /api/evals/runs/{id}，更新 currentRun 和 runDetails
  - stopPolling() — 停止轮询

- [ ] **Step 3: 创建 useEvalCompare.ts** — 管理历史对比：
  - compareResult（ref<CompareResult | null>）
  - compare(runIdA, runIdB) — GET /api/evals/compare

- [ ] **Step 4: 创建 composables/index.ts** — 统一导出

- [ ] **Step 5: Commit**

```bash
git add packages/evals-ui/src/composables/
git commit -m "feat: add evals-ui composables"
```

---

## Phase 4: Admin Console 集成

### Task 16: API 客户端 + 路由 + 导航

**Files:**
- Create: `apps/admin-console/src/api/evals.ts`
- Modify: `apps/admin-console/src/router/index.ts`
- Modify: `apps/admin-console/src/App.vue`
- Modify: `apps/admin-console/package.json`

- [ ] **Step 1: 创建 api/evals.ts** — 封装 /api/evals/* 调用，参照 api/knowledge.ts 的格式，使用 axios

- [ ] **Step 2: 修改 router/index.ts** — 添加 /evals 路由：
```typescript
{
  path: '/evals',
  name: 'evals',
  component: () => import('../views/EvalManage.vue')
}
```

- [ ] **Step 3: 修改 App.vue** — navItems 添加：
```typescript
{ key: 'evals', label: '测试集' }
```
handleNavClick 添加 evals 路由映射

- [ ] **Step 4: 修改 package.json** — dependencies 添加：
```json
"@angineer/evals-ui": "workspace:*"
```

- [ ] **Step 5: 安装依赖**

Run: `pnpm install`

- [ ] **Step 6: Commit**

```bash
git add apps/admin-console/src/api/evals.ts apps/admin-console/src/router/index.ts apps/admin-console/src/App.vue apps/admin-console/package.json
git commit -m "feat: add evals API client, route and navigation"
```

---

### Task 17: EvalManage.vue 页面

**Files:**
- Create: `apps/admin-console/src/views/EvalManage.vue`

- [ ] **Step 1: 创建 EvalManage.vue** — 三栏布局页面：
  - 使用 SplitPanes 组件（参照 KnowledgeManage.vue 的布局方式）
  - 左栏：EvalDatasetTree
  - 中栏：EvalQuestionList
  - 右栏：EvalRunPanel
  - 集成 EvalImportModal 和 EvalCompareView
  - 使用 useEvalDataset, useEvalRun, useEvalCompare composables
  - 使用 useTheme() 获取主题状态

- [ ] **Step 2: 验证前端页面可访问**

Run: `pnpm dev:admin`
Expected: 访问 http://localhost:3002/evals 可看到测试集页面

- [ ] **Step 3: Commit**

```bash
git add apps/admin-console/src/views/EvalManage.vue
git commit -m "feat: add EvalManage page with three-column layout"
```

---

## Phase 5: 集成与清理

### Task 18: 更新根 package.json 脚本

**Files:**
- Modify: `package.json`

- [ ] **Step 1: 添加 evals 相关脚本**

在 scripts 中添加：
```json
"eval:list": "python -c \"from evals_core.storage.result_store import init_db, list_datasets; init_db(); import json; print(json.dumps(list_datasets(), ensure_ascii=False, indent=2))\"",
"services:install": "pip install -e services/ai-inference -e services/angineer-core -e services/sop-core -e services/docs-core -e services/geo-core -e services/engtools -e services/evals-core"
```

更新已有的 services:install 命令添加 evals-core。

- [ ] **Step 2: Commit**

```bash
git add package.json
git commit -m "feat: add evals scripts to root package.json"
```

---

### Task 19: 端到端验证

**Files:** 无新增

- [ ] **Step 1: 启动后端**

Run: `python apps/api-server/main.py`
Expected: 服务在 8789 端口启动

- [ ] **Step 2: 验证 API 端点**

Run: `curl http://localhost:8789/api/evals/datasets`
Expected: `{"datasets":[]}`

- [ ] **Step 3: 导入测试题集**

使用 curl 或前端界面上传 tests/evals/knowledge_rag/ 下的 JSON 文件到 POST /api/evals/datasets/import

- [ ] **Step 4: 启动前端**

Run: `pnpm dev:admin`
Expected: 访问 http://localhost:3002/evals 可看到导入的测试集

- [ ] **Step 5: 运行评测**

在前端点击"运行评测"，验证轮询和结果展示

- [ ] **Step 6: 运行 lint**

Run: `pnpm lint`
Expected: 无错误

---

### Task 20: 清理旧评测代码（联调通过后执行）

**Files:**
- Delete: `services/docs-core/src/docs_core/evals/` 目录
- Modify: `apps/api-server/main.py` — 删除旧 /api/knowledge/evals/* 路由
- Delete: `apps/admin-console/src/views/components/KnowledgeEvalDrawer.vue`
- Modify: `services/docs-core/pyproject.toml` — 移除 evals 相关依赖（如有）
- Modify: `apps/admin-console/src/api/knowledge.ts` — 移除旧评测相关类型和 API 调用

> ⚠️ 此 Task 仅在新系统联调通过后执行。执行前需确认所有评测功能已迁移到新系统。

- [ ] **Step 1: 删除 docs-core 旧 evals 目录**

```bash
rm -rf services/docs-core/src/docs_core/evals/
```

- [ ] **Step 2: 删除 api-server 旧评测路由** — 从 main.py 中移除 /api/knowledge/evals/datasets, /api/knowledge/evals/questions, /api/knowledge/evals/run 等端点

- [ ] **Step 3: 删除旧前端组件** — 删除 KnowledgeEvalDrawer.vue，从 KnowledgeManage.vue 中移除引用

- [ ] **Step 4: 清理旧 API 类型** — 从 knowledge.ts 中移除 KnowledgeEvalQuestion, KnowledgeEvalDataset 等旧类型

- [ ] **Step 5: 更新根 package.json** — 移除旧 eval:knowledge-rag:* 脚本

- [ ] **Step 6: 运行 lint + harness**

Run: `pnpm lint && pnpm harness`
Expected: 全部通过

- [ ] **Step 7: Commit**

```bash
git add -A
git commit -m "chore: remove legacy evals code from docs-core and api-server"
```
