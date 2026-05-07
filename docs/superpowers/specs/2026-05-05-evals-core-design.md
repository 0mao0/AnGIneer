# evals-core 统一评测体系设计

> 日期：2026-05-05
> 状态：已确认

## 1. 目标

为 AnGIneer 建立完整的评测体系，覆盖 L1-L4 各层级在各类规范下的表现，作为程序迭代进步的量化基础。

### 核心需求

1. **测试题集管理**：树形组织、题目分类、题目-答案配对查看
2. **评测运行**：一键运行、实时进度、逐题结果、总体指标
3. **数据管理**：JSON 导入、规范格式导出
4. **历史对比**：多次运行结果对比，追踪回归/进步
5. **全链路覆盖**：知识库链路（检索/SQL/回答）+ SOP 执行链路 + geo/engtools 扩展点

### 非目标（首期）

- 报告导出为 JSON/Markdown（后续迭代）
- 完整的在线题目编辑器（首期仅支持上传 JSON + 手动添加单题）
- 自动化 CI 集成

## 2. 架构决策

### 2.1 后端：evals-core 作为库 + api-server 路由扩展

`evals-core` 作为独立 Python 包（`services/evals-core`），不直接暴露 HTTP 端口。`api-server` 新增 `/api/evals/*` 路由组，调用 evals-core 的函数。

选择理由：
- 与 docs-core、angineer-core 的集成模式一致
- 无需新端口，前端代理不变
- evals-core 可直接 import 其他服务包的模块
- 评测运行时调用查询链路无循环依赖（同进程内直接调用函数）

### 2.2 前端：独立 packages/evals-ui + admin-console 集成

`@angineer/evals-ui` 提供评测相关组件，`admin-console` 新增"测试集"tab 页面组合使用。

### 2.3 迁移策略

完全新建 evals-core 代码，前后端联调通过后再删除 docs-core 中的旧 evals 代码。不做任何删除或移动直到新系统可用。

## 3. 后端设计

### 3.1 目录结构

```
services/evals-core/
├── pyproject.toml
├── src/
│   └── evals_core/
│       ├── __init__.py
│       ├── dataset/                  # 题集管理
│       │   ├── __init__.py
│       │   ├── loader.py             # JSON 题集加载与校验
│       │   ├── manager.py            # 题集 CRUD（创建/删除/导入/导出）
│       │   └── schema.py             # 题集数据模型（Pydantic）
│       ├── runner/                   # 评测执行
│       │   ├── __init__.py
│       │   ├── base.py               # 评测器基类与注册
│       │   ├── retrieval_eval.py     # 检索评测
│       │   ├── answer_eval.py        # 回答评测
│       │   ├── text2sql_eval.py      # SQL 评测
│       │   ├── sop_eval.py           # SOP 执行评测（首期骨架）
│       │   └── suite_runner.py       # 评测套件编排 + 异步任务管理
│       ├── storage/                  # 结果持久化
│       │   ├── __init__.py
│       │   └── result_store.py       # SQLite 存储
│       └── contracts.py              # 对外契约（请求/响应模型）
```

### 3.2 依赖关系

```
evals-core
  ├── docs-core（知识库查询函数直接调用，不走 HTTP）
  ├── angineer-core（意图分类函数直接调用）
  ├── ai-inference（LLM 客户端）
  └── sop-core（SOP 评测，首期可选）
```

### 3.3 评测执行模式

异步 + 轮询：

1. `POST /api/evals/runs` → 后端启动线程池执行评测，立即返回 `run_id`
2. `suite_runner.py` 逐题执行：
   - 调用 `IntentClassifier.classify_intent()` 获取意图
   - 根据意图分发到对应评测器（retrieval/answer/text2sql/sop）
   - 每完成一题，更新 `eval_run_detail` 和 `eval_run.completed_questions`
3. 前端每 2 秒轮询 `GET /api/evals/runs/{run_id}`，获取已完成的题目和进度
4. 全部完成后，计算汇总指标并写入 `eval_run.summary_scores`

### 3.4 评测器基类

```python
class BaseEvaluator(ABC):
    @abstractmethod
    def run_prediction(self, question: Dict) -> Dict:
        """对单题执行预测调用。"""

    @abstractmethod
    def evaluate(self, question: Dict, gold: Dict, prediction: Dict) -> Dict:
        """对单题计算评测指标。"""
```

各评测器（retrieval/answer/text2sql/sop）继承基类，实现各自的预测和评估逻辑。

## 4. API 路由设计

在 `api-server` 中新增 `evals_routes.py`，挂载到 `/api/evals` 前缀。

### 4.1 题集管理

| 方法 | 路径 | 功能 |
|------|------|------|
| GET | `/api/evals/datasets` | 列出所有测试集 |
| POST | `/api/evals/datasets` | 创建空测试集 |
| POST | `/api/evals/datasets/import` | 导入 JSON 题集文件 |
| GET | `/api/evals/datasets/{dataset_id}` | 获取测试集详情 |
| DELETE | `/api/evals/datasets/{dataset_id}` | 删除测试集 |
| GET | `/api/evals/datasets/{dataset_id}/questions` | 获取测试集题目列表 |
| POST | `/api/evals/datasets/{dataset_id}/questions` | 向测试集添加单题 |
| PUT | `/api/evals/datasets/{dataset_id}/questions/{question_id}` | 编辑题目 |
| DELETE | `/api/evals/datasets/{dataset_id}/questions/{question_id}` | 删除题目 |
| GET | `/api/evals/datasets/{dataset_id}/export` | 导出测试集为规范 JSON |

### 4.2 评测运行

| 方法 | 路径 | 功能 |
|------|------|------|
| POST | `/api/evals/runs` | 启动评测运行（异步） |
| GET | `/api/evals/runs/{run_id}` | 查询运行进度/结果 |
| GET | `/api/evals/runs` | 列出历史运行记录 |
| GET | `/api/evals/compare` | 对比两次运行结果 |

### 4.3 运行流程

```
前端点击"运行评测"
  → POST /api/evals/runs { dataset_id }
  → 返回 { run_id, status: "running" }

前端轮询（每2秒）
  → GET /api/evals/runs/{run_id}
  → 返回 { status, progress: "12/25", completed_details: [...], summary: null }

评测完成
  → GET /api/evals/runs/{run_id}
  → 返回 { status: "completed", progress: "25/25", summary: {...}, details: [...] }
```

## 5. 前端设计

### 5.1 packages/evals-ui 目录结构

```
packages/evals-ui/
├── package.json
├── tsconfig.json
├── src/
│   ├── index.ts
│   ├── components/
│   │   ├── EvalDatasetTree.vue       # 测试集树形管理（左栏）
│   │   ├── EvalQuestionList.vue      # 题目列表（中栏主区域）
│   │   ├── EvalQuestionCard.vue      # 单题卡片（展开/折叠 + 答案配对）
│   │   ├── EvalRunPanel.vue          # 运行控制 + 指标面板（右栏）
│   │   ├── EvalScoreBar.vue          # 得分进度条组件
│   │   ├── EvalLevelBadge.vue        # L1-L4 层级标签
│   │   ├── EvalCompareView.vue       # 历史对比视图
│   │   └── EvalImportModal.vue       # JSON 导入弹窗
│   ├── composables/
│   │   ├── index.ts
│   │   ├── useEvalDataset.ts         # 测试集数据管理
│   │   ├── useEvalRun.ts             # 评测运行 + 轮询
│   │   └── useEvalCompare.ts         # 历史对比
│   ├── types/
│   │   ├── index.ts
│   │   └── eval.ts                   # 评测相关类型定义
│   └── styles/
│       ├── index.less
│       └── variables.less
```

### 5.2 admin-console 集成

1. 路由新增 `/evals` → `EvalManage.vue`
2. `App.vue` 的 `navItems` 增加 `{ key: 'evals', label: '测试集' }`
3. `EvalManage.vue` 使用 `SplitPanes` 三栏布局，组合 evals-ui 组件
4. 新增 `api/evals.ts` 封装 `/api/evals/*` 调用

### 5.3 页面布局

三栏布局（与知识库页面风格一致）：

- **左栏（~18%）**：测试集树形管理
  - 按类别分组：知识库评测 / SOP 评测 / 全链路评测
  - 支持导入 JSON、新建空测试集
  - 底部统计：N 个测试集 · M 题

- **中栏（~60%）**：题目列表与详情
  - 顶部：测试集标题 + 筛选（按层级/标签/状态）
  - 题目卡片列表：
    - 折叠态：L 标签 + question_id + 问题文本 + 状态标签
    - 展开态：系统回答/标准答案左右配对 + 正确性校验结果 + 思考链路

- **右栏（~22%）**：运行控制与指标
  - 一键运行按钮
  - 综合得分（大数字）
  - 分项指标进度条（检索/回答/SQL/SOP）
  - 按意图层级统计（L1/L2/L3/L4 通过数）
  - 历史对比入口

### 5.4 关键交互

**题目卡片展开/折叠**：
- 默认折叠，点击展开
- 展开后显示：系统回答 vs 标准答案（左右配对）、正确性校验结果、思考链路

**实时进度更新**：
- 点击"运行评测" → 按钮变为"运行中..." → 启动 2 秒轮询
- 每次轮询返回已完成的题目列表，前端逐题更新卡片状态
- 全部完成后停止轮询，右栏显示完整指标

**历史对比**：
- 右栏底部"历史对比"按钮 → 弹出两次运行的选择器
- 选择后展示对比视图：各指标变化（↑↓箭头）、逐题通过/失败变化

## 6. 数据模型

### 6.1 题集 JSON 规范（eval.bundle.v2）

兼容 v1，新增 `category` 和 `intent_level` 字段：

```json
{
  "dataset": {
    "dataset_id": "eval_knowledge_1",
    "title": "知识库基线评测集 1",
    "category": "knowledge",
    "description": "...",
    "schema_version": "eval.bundle.v2",
    "version": "1.0",
    "library_id": "default"
  },
  "items": [
    {
      "question_id": "q_001",
      "question": "航道通航宽度由哪些部分组成？",
      "task_type": "definition",
      "intent_level": "L1",
      "library_id": "default",
      "doc_ids": ["doc-89bc80c3"],
      "difficulty": "easy",
      "tags": ["doc-89bc80c3", "航道"],
      "retrieval": {
        "gold_section_paths": ["6 进港航道 / 6.4 航道尺度"]
      },
      "answer": {
        "gold_answer": "航道通航宽度由航迹带宽度、船舶间富裕宽度和船舶与航道底边间的富裕宽度组成。",
        "correctness_checks": [
          { "type": "contains_all", "keywords": ["航迹带宽度", "富裕宽度"] }
        ],
        "semantic_threshold": 0.55
      },
      "sop": {
        "expected_sop_id": "math_sop",
        "expected_steps": ["retrieve", "calculate"],
        "expected_result": { "value": 150.0, "unit": "m", "tolerance": 0.01 }
      }
    }
  ]
}
```

### 6.2 SQLite 存储模型

**eval_dataset 表**：

| 字段 | 类型 | 说明 |
|------|------|------|
| dataset_id | TEXT PK | 测试集 ID |
| title | TEXT | 标题 |
| category | TEXT | knowledge/sop/full_chain |
| description | TEXT | 描述 |
| schema_version | TEXT | 格式版本 |
| version | TEXT | 数据版本 |
| library_id | TEXT | 关联知识库 |
| question_count | INTEGER | 题目数 |
| source_file | TEXT | 来源 JSON 文件名 |
| created_at | TEXT | 创建时间 |
| updated_at | TEXT | 更新时间 |

**eval_question 表**：

| 字段 | 类型 | 说明 |
|------|------|------|
| question_id | TEXT | 题目 ID（与 dataset_id 组成复合 PK） |
| dataset_id | TEXT FK | 所属测试集 |
| question | TEXT | 问题文本 |
| task_type | TEXT | 任务类型 |
| intent_level | TEXT | L1/L2/L3/L4 |
| difficulty | TEXT | easy/medium/hard |
| tags | TEXT (JSON) | 标签列表 |
| library_id | TEXT | 关联知识库 |
| doc_ids | TEXT (JSON) | 关联文档 |
| retrieval_gold | TEXT (JSON) | 检索 gold 数据 |
| answer_gold | TEXT (JSON) | 回答 gold 数据 |
| sql_gold | TEXT (JSON) | SQL gold 数据 |
| sop_gold | TEXT (JSON) | SOP gold 数据 |
| sort_order | INTEGER | 排序 |

**eval_run 表**：

| 字段 | 类型 | 说明 |
|------|------|------|
| run_id | TEXT PK | 运行 ID |
| dataset_id | TEXT FK | 测试集 ID |
| status | TEXT | running/completed/failed |
| total_questions | INTEGER | 总题数 |
| completed_questions | INTEGER | 已完成题数 |
| started_at | TEXT | 开始时间 |
| completed_at | TEXT | 完成时间 |
| summary_scores | TEXT (JSON) | 汇总得分 |
| config_snapshot | TEXT (JSON) | 运行时配置快照 |

**eval_run_detail 表**：

| 字段 | 类型 | 说明 |
|------|------|------|
| id | INTEGER PK AUTO | 自增主键 |
| run_id | TEXT FK | 运行 ID |
| question_id | TEXT | 题目 ID |
| status | TEXT | pending/running/passed/failed/error |
| prediction | TEXT (JSON) | 系统预测结果 |
| scores | TEXT (JSON) | 各项得分 |
| error | TEXT | 错误信息 |
| latency_ms | INTEGER | 单题耗时 |

## 7. 迁移计划

### 阶段 1：新建（本次）

1. 创建 `services/evals-core` 完整模块
2. 创建 `packages/evals-ui` 完整模块
3. 在 `api-server` 新增 `evals_routes.py`
4. 在 `admin-console` 新增测试集页面
5. 前后端联调通过

### 阶段 2：清理（联调通过后）

1. 删除 `services/docs-core/src/docs_core/evals/` 目录
2. 删除 `services/api-server/main.py` 中旧的 `/api/knowledge/evals/*` 路由
3. 删除 `apps/admin-console/src/views/components/KnowledgeEvalDrawer.vue`
4. 删除 `tests/evals/knowledge_rag/` 下的旧评测脚本
5. 更新 `docs-core` 的 `__init__.py` 和 `pyproject.toml` 移除 evals 相关导出

## 8. 风险与待定

- **SOP 评测首期范围**：`sop_eval.py` 首期仅实现骨架，具体 SOP 执行评测逻辑待 sop-core 接入后完善
- **评测数据存放位置**：SQLite 文件放在 `data/evals/` 目录下，与 `data/knowledge_base/` 平级
- **并发安全**：同一时间只允许一个评测运行，后续可扩展为队列
