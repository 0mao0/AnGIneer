# 题集卡（评测题集信息卡）设计

状态：已实现并发版（v0.2.87，commit 38528005；施工清单 plan-dataset-card.md 已按完结定式清理，git 历史可查）
来源：用户需求——评测管理页题目列表工具栏加「题集卡」按钮，一眼看清题集考什么

## 1. 需求

评测管理页（admin）题目列表工具栏右侧加「题集卡」按钮，弹层展示题集元信息：
发布方、测试类型（金融/法律/工程…）、题集目的、来源网址、题集分布、公开锚点成绩（leaderboard）。

## 2. 设计

### 2.1 数据层（services/evals-core）

- `eval_dataset` 表加 `meta TEXT` 列（JSON，默认 `'{}'`）：`result_store.py` 建表语句加列
  + 启动时 `ALTER TABLE ADD COLUMN` 兜底迁移旧库
- `schema.py`：`EvalDatasetMeta` / `EvalDatasetRow` 加 `meta: Dict[str, Any] = {}`
- `manager.py`：create / import_bundle / update_dataset / get_dataset / export_dataset 透传 meta
- `evals_routes.py`：`GET /datasets`、`GET /datasets/{id}` 返回 meta；`PATCH /datasets/{id}` 接受 meta；
  `POST /datasets/import` 存 meta

meta 结构（全可选，按需填）：

| 字段 | 类型 | 含义 |
|---|---|---|
| `publisher` | str | 发布方 |
| `domain` | str | 测试类型（金融/法律/工程/意图路由…） |
| `mode` | str | 喂法：整体RAG（全库检索）/ 单篇RAG（逐题圈定相关文档）/ 细糠Oracle（金证据直给） |
| `purpose` | str | 题集简介（测什么能力） |
| `source_url` | str | 来源网址 |
| `source_note` | str | 来源补充说明 |
| `distribution` | list[{label, count, note?}] | 题集分布；缺省时前端按 intent_level 自动统计 |
| `leaderboard` | list[{label, score, note?}] | 公开锚点成绩——只放官方论文/公开榜数字，不放自家 run 成绩 |

- meta 脏数据（非对象/解析失败）按 `{}` 兜底，接口不炸

### 2.2 前端（packages/evals-ui，admin-web 消费）

- `EvalQuestionList.vue` 工具栏右侧加「题集卡」按钮（`margin-left:auto` 靠右）
- 新组件 `EvalDatasetCardModal.vue`：克隆 `EvalRunCreateModal` 骨架（a-modal + 分节）
  - 有 meta：渲染发布方/类型/目的/来源（链接）/分布/leaderboard
  - 无 meta：基础信息（题数/分类/库/创建时间）+「未登记扩展信息」占位——**按钮始终显示**
- `EvalManage.vue` 已持有 `currentDataset`，作为新 prop 传入 `EvalQuestionList`
- 用户明确不要编辑 UI（2026-10-01）：meta 靠 bundle 导入/回填脚本维护

### 2.3 回填

- `scripts/backfill_dataset_meta.py`：**枚举 `manager.list_datasets()`**（题集 2026-09-28 起只存
  数据库，`data/evals/datasets/*.json` 是遗留副本）→ `manager.update_dataset` 写 meta；
  匹配规则 dataset_id 精确优先、title 兜底；默认 dry-run，`--apply` 才落库
- 内容按各题集已知信息撰写；FinanceBench 最全（Patronus AI / 金融 / SEC 问答 / 来源 / 题型
  metrics·domain·novel 各 50 / 官方三档锚点：现实 RAG 最优 50%、oracle 85%、16 配置汇总 47%）
- 生产侧：脚本进镜像白名单（`.dockerignore` 放行 + `Dockerfile.backend` COPY 清单两处同改），
  部署后在容器内重跑

## 3. 验收

- [ ] 旧库启动自动迁移，存量行 meta 默认 `{}`，evals-core 全量单测过（含 meta 存取/透传/迁移新用例）
- [ ] admin 页 FinanceBench 题集点「题集卡」弹出完整信息；自建题集弹基础信息
- [ ] bundle 导出再导入 meta 不丢
- [ ] 回填脚本本地跑完，逐题集 GET 验证

## 4. 边界

- leaderboard 只放公开锚点（判分口径在 note 标注）；自家 run 成绩不入卡
- 不做编辑 UI（后续要再加）
- user-web 不受影响（该页面仅 admin 使用）
