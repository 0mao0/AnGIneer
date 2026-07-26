# 改进计划：Gap Analysis + Dream Cycle

> 基于 GBrain 设计思想，在 AnGIneer 现有架构上增量实现。
> 实施日期：2026-07-23

---

## 实施状态

| 阶段 | 内容 | 状态 |
|---|---|---|
| Phase 1 | Gap Analysis — 知识盲区分析 | ✅ 已完成 |
| Phase 2 | Dream Cycle 基础设施 — 模块骨架 + API | ✅ 已完成 |
| Phase 3 | Dream Cycle 5 个核心 Task | ✅ 已完成 |
| Phase 4 | 前端 DreamCycleView 管理面板 | ⬜ 待实施 |

---

## 一、Gap Analysis（已完成）

### 修改的文件

| 文件 | 改动 |
|---|---|
| `services/angineer-core/src/angineer_core/base_contracts.py` | 新增 `GapAnalysis` 数据模型；`AgentResponse` 新增 `gap_analysis` 和 `confidence_breakdown` 字段 |
| `services/angineer-core/src/angineer_core/dispatcher.py` | `_build_system_prompt` 增加盲区分析指令；新增 `_parse_gap_analysis` 解析方法；`dispatch()` 返回结果包含解析后的 gap 数据 |
| `packages/ui-kit/src/types/chat.ts` | `QueryResponse` 和 `AIChatMessage` 新增 `gap_analysis` / `confidence_breakdown` 字段 |
| `packages/ui-kit/src/composables/useAIChat.ts` | 数据映射链路新增 gap 字段透传 |
| `packages/ui-kit/src/components/common/BaseChat.vue` | 新增知识盲区面板 + 置信度说明面板 UI；关联的展开/折叠状态管理 |

### 配置

```env
ANGINEER_GAP_ANALYSIS_ENABLED=true   # 默认开启，设为 false 关闭
```

### 效果

LLM 回答末尾自动解析出：
- **知识盲区分析**：列出检索结果中未覆盖的方面及建议补充的文档类型
- **置信度说明**：高/中/低置信度分类标注

前端橙色警告色面板展示，默认折叠，可展开查看。

---

## 二、Dream Cycle（已完成）

### 新增文件

```
services/dream-cycle/
├── pyproject.toml
└── src/dream_cycle/
    ├── __init__.py          # 公开导出
    ├── config.py            # 环境变量配置（含所有阈值和开关）
    ├── report.py            # 报告数据模型（DreamCycleReport 等）
    └── runner.py            # 主运行器 + 5 个 Task 实现

services/api-server/
└── dream_cycle_routes.py    # API 路由（报告查看/手动触发/审核确认）

data/dream_cycle/
├── reports/                 # 每日 JSON 报告
└── audit/                   # 审计日志
```

### 5 个 Task

| # | Task | 实现逻辑 | 自动化边界 |
|---|------|---------|-----------|
| 1 | 实体去重检查 | 编辑距离 + aliases 交叉检测 | ≥0.95 自动合并，0.7-0.95 人工确认 |
| 2 | 矛盾关系检测 | 同一对实体在不同文档中的 `relation_type` 不同 | 全部人工审核 |
| 3 | 孤立实体清理 | 无入边无出边 + 非种子实体 | ≥14天自动标记 inactive，≥7天人工确认 |
| 4 | 过期知识标记 | 文档标题年份检测（简化版） | 全部人工审核 |
| 5 | SOP 健康统计 | 读取 `data/sops/index.json` 统计 SOP 数量 | 纯报告 |

### API 端点

| 方法 | 路径 | 功能 |
|---|---|---|
| `GET` | `/api/dream-cycle/reports` | 历史报告列表 |
| `GET` | `/api/dream-cycle/reports/{date}` | 某日完整报告 |
| `POST` | `/api/dream-cycle/run` | 手动触发一次运行 |
| `POST` | `/api/dream-cycle/tasks/dedup/confirm/{a}/{b}` | 确认合并两个实体 |
| `POST` | `/api/dream-cycle/tasks/dedup/dismiss/{a}/{b}` | 驳回去重建议 |
| `GET` | `/api/dream-cycle/health` | 健康检查 |

### 调度

```bash
# Linux cron（推荐）
0 2 * * * cd /path/to/AnGIneer && python -m dream_cycle.runner >> logs/dream_cycle.log 2>&1

# 或手动触发
curl -X POST http://localhost:8789/api/dream-cycle/run
```

### 配置

```env
DREAM_CYCLE_ENABLED=true
DREAM_CYCLE_DEDUP_AUTO_THRESHOLD=0.95
DREAM_CYCLE_DEDUP_REVIEW_THRESHOLD=0.7
DREAM_CYCLE_ORPHAN_MIN_AGE_DAYS=7
DREAM_CYCLE_ORPHAN_AUTO_CLEAN_DAYS=14
DREAM_CYCLE_TASK_TIMEOUT=1800
DREAM_CYCLE_LLM_MODEL=Qwen3.6-35B-A3B
```

---

## 三、待实施

### Phase 4: 前端 DreamCycleView 管理面板

`apps/admin-console/src/views/DreamCycleView.vue`：
- 报告列表（按日期展示，每项 Task 的发现数量）
- 点击展开详情（去重建议、矛盾列表、孤立实体）
- 确认/驳回/误报的交互按钮
- 近 30 天统计面板

---

## 四、风险缓解

- 所有自动删除仅标记 inactive，不物理删除
- 种子实体（`source_doc IS NULL`）永不处理
- 每个 Task 回调通过 try/except 捕获异常，不影响后续任务
- 所有自动操作写审计日志到 `data/dream_cycle/audit/`
- Dream Cycle 使用独立的 SQLite 只读连接 + 写操作排队

---

*文档版本：v1.0 | 最后更新：2026-07-23*
