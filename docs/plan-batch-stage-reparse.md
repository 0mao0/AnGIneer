# 批量阶段重解析：改造方案

> 目标：给"批量解析"补上**任意阶段子集**能力，并顺手修掉"阶段表三处硬编码"这个已知漂移源。
> 状态：方案（未实施）。实现顺序见文末「实施顺序」。

## 1. 目标与现状

| | 现状 | 缺口 |
|---|---|---|
| 单文档按阶段跑 | 阶段抽屉每阶段"启动" → `POST /knowledge/documents/{doc_id}/stages/{stage_key}/retry`，语义是**从该阶段跑到末尾**（安全，但省不掉下游的贵阶段） | 不能跑**任意子集**（例如只重建 `fts`+`vectors`，或只想跳过 `figure_describe`） |
| 单文档任意子集端点 | `POST /knowledge/documents/{doc_id}/parse?stages=…` 已存在（`services/docs-api/docs_routes.py:1696-1717`） | 前端**无任何调用方**；且它直接调 `create_parse_task`，绕过了重试路径里的僵尸任务清理 |
| 批量 | `POST /knowledge/parse/batch-retry` 只收 `doc_ids`（`docs_routes.py:859-889`），内部逐个走 `retry_parse_task(doc_id)`（`services/docs-core/src/docs_core/parse_pipeline.py:1079-1112`）→ **不接 parse_options** | 批量只能全量重跑 |

因此本次增量只有两条：**批量** + **任意子集**。阶段元数据接口是它们的配套（否则弹框只能再抄一份阶段表）。

## 2. 后端

### 2.1 让重试路径能带 `parse_options`（关键：不要绕开它）

`retry_parse_task` 里有**僵尸任务恢复**逻辑（`parse_pipeline.py:1085-1104`）：节点卡在 `processing` 但后台线程已死（进程重启、部署打断）时，把旧任务标 `failed` 并放行重跑。批量重试的价值有一半在这，所以不要照 `parse_document_stages` 那样直接调 `create_parse_task`，而是让重试路径接受 `parse_options` 并透传：

```python
# parse_pipeline.py:1079
def retry_parse_task(self, doc_id: str, parse_options: Optional[Dict[str, Any]] = None) -> ...:
    ...                                      # 现有僵尸清理逻辑一字不动
    return self.create_parse_task(           # 原来未传 parse_options
        library_id=node.library_id,
        doc_id=doc_id,
        file_path=file_path,
        parse_options=parse_options or {},   # 新增透传
    )
```

`create_parse_task(library_id, doc_id, file_path, parse_options=None)` 定义在 `parse_pipeline.py:1005-1043`，第 4 个参数会原样交给 `_run_parse_task`，后者用 `parse_options.get("stages", "all")` 取阶段过滤（`:1126`）。

### 2.2 批量端点加 `stages`

```python
class BatchRetryRequest(BaseModel):        # docs_routes.py:859
    doc_ids: List[str]
    stages: Optional[List[str]] = None     # 新增
```

```python
# batch_retry_parse_tasks（docs_routes.py:864-889）
stage_list, opts = None, None
if request.stages:
    stage_list = resolve_stage_order(request.stages)  # 未知阶段 → ValueError → 400（一次校验，不逐 doc）
    opts = {"stages": stage_list, "use_llm": True}    # 与现有两个 stages 端点同款
...
result = parse_orchestrator.retry_parse_task(doc_id, opts)  # stages 为空时 opts=None → 行为与今天完全一致
```

契约：

| 入参 | 行为 |
|---|---|
| 省略 / `[]` | **与今天完全相同**（全量重跑），不引入行为变更 |
| `["fts","vectors"]` | 只重置并运行这两个阶段，其余阶段记录保留（`parse_pipeline.py:1130-1134`：`all` 清空全部阶段记录，子集只重置目标阶段） |
| 含未知 key | `400 {"detail": "未知阶段: [...]"}` |

返回沿用现有 `{status, started, failed, results[], errors[]}`——逐 doc 部分成功，前端必须展示失败明细。

### 2.3 阶段元数据接口

```
GET /knowledge/parse/stage-registry
→ [{ key, step, title, kind, depends_on, destroys }, ...]     # 按 _PIPELINE_ORDER 排序
```

- 数据源是 `STAGE_REGISTRY`（`parse_pipeline.py:734-747`，`step` 已统一为位次 1..9）
- 新增声明式字段 `destroys`：只给 `structure` 标 `["figure_description"]`
- 弹框的依赖提示**由该字段驱动**，而不是在前端写死"structure 必须配 figure_describe"

> 若要省掉这个接口，最小替代是把 9 阶段表收敛成前端**一份**共享常量（替换 `DocStageStepper.vue` 与 `PDF_Viewer.vue` 各自那份）。但那就回到"靠人同步"的老问题——本仓库已经因此漏过一次 `figure_describe`（抽屉整行不渲染），故推荐做接口。

## 3. 前端（admin-web）

### 3.1 新增 `BatchParseModal.vue`

骨架直接复刻现成三件：`BatchUploadModal.vue`（批量 + 确认即发起）、`BatchDeleteModal.vue`（勾选列表/全选/半选）、`KnowledgeParseWorkspace.vue:386-430` 的解析设置弹框（选项表单）。

```
┌ 批量解析（已选 117 篇）──────────────────────────────────┐
│ 预设： [从某阶段起到末尾 ▾]   全量 | 从…起 | 仅重建索引 | 自定义 │
│                                                          │
│ ☐ 1 源文件准备   ☐ 2 格式转换   ☐ 3 MinerU解析            │
│ ☐ 4 PoPo强化     ☑ 5 结构化      ☑ 6 图描述(VLM)          │
│ ☐ 7 SQLite+FTS   ☑ 8 向量索引    ☐ 9 知识图谱             │
│                                                          │
│ ⚠ 结构化会重建 doc_blocks_graph.jsonl，已勾"图描述"重新生成； │
│    若取消勾选，已有的图描述将丢失且不可恢复（当前库内 2042 条）│
│ ⓘ 将进入队列按提交顺序执行（MinerU / PoPo 闸门各 1、图描述 2）│
└──────────────────────────────────────────────────────────┘
```

- 阶段清单来自 §2.3 接口（取不到时回退那份共享常量）
- **依赖保护**：勾中"会重建 jsonl"的阶段（当前即 `structure`）却未勾 `figure_describe` → **自动补上**并说明原因；允许手动取消，但警示升级为红色——保留"我就是要省这一次 VLM"的自由，同时不让它悄悄发生
- 预设语义与既有行为对齐：**"从某阶段起到末尾"就是阶段抽屉那条路径的批量版**（等价于逐篇调 `/stages/{key}/retry`）
- 提交：过滤掉 `RUNNING_STATUSES` 的选中项，再调 `batchRetryParseTasks(docIds, stages)`

### 3.2 接线与类型

| 文件 | 改动 |
|---|---|
| `apps/admin-web/src/api/knowledge.ts:111-118` | `batchRetryParseTasks(docIds, stages?)`，body 多带 `stages` |
| `apps/admin-web/src/components/KnowledgeStats.vue:912-952` | `onBatchParseClick` 由"直接发起"改为"打开弹框"，确认后走原逻辑（保留现有 `RUNNING_STATUSES` 过滤与成功/失败提示） |
| `packages/docs-ui/src/types/knowledge.ts:177-180` | `KnowledgeParseOptions` 加 `stages?: string[]`（供工作台单文档路径后续复用） |
| `packages/docs-ui/src/composables/useKnowledgeParse.ts:85-93` | `buildParseOptionsPayload` 带上 `stages`（默认不传，行为不变） |

## 4. 风险与边界

| 风险 | 处理 |
|---|---|
| **图描述被抹掉** | 弹框默认补齐 `figure_describe`。这是唯一"有损的省法"，必须显式取消才生效 |
| 117 篇一起提交 | 逐个 `arrival_seq` 排队，MinerU / PoPo / 图描述三处闸门各自限流（默认 1 / 1 / 2）→ 会长时间排队；弹框提前说明，列表与抽屉可见 `queued` |
| 部分失败 | 沿用 `errors[]` 逐条展示（文档不存在、正在解析中、缺 file_path） |
| 重复提交 | `retry_parse_task` 对正在解析的节点抛 `ValueError`；前端已过滤 `RUNNING_STATUSES` |
| 子集运行的记录语义 | 只重置目标阶段记录、其余保留（`parse_pipeline.py:1130-1134`），故"仅重建 fts+vectors"不会动 structure 的产物 |
| `use_llm` | 与现有两个 stages 端点保持一致（`True`），本次不引入新开关 |

## 5. 验证

1. **后端单测**：`stages` 含未知 key → 400 且只校验一次；`stages` 省略 → 断言 `retry_parse_task` 收到 `None`（行为不变）；带 stages → 断言 `create_parse_task` 收到 `{"stages": [...], "use_llm": True}`
2. **前端**：`pnpm --filter @angineer/admin-web exec vue-tsc -b`、`pnpm --filter @angineer/docs-ui typecheck`
3. **手动**：勾 `structure` 自动补 6；取消 6 出红色警示；三个预设的勾选态正确；提交载荷含 `stages`
4. **端到端（本地、会改动数据，需单独确认）**：对 1 篇文档分别跑 `["fts","vectors"]`（应只重置这两阶段、结构产物与图描述不动）与 `["structure"]`（jsonl 被重写、`figure_description` 归零；因 `fts` 未跑，`canonical_chunks` 暂时仍带旧描述——这正是"退化延迟发作"的形态）

## 6. 不做

- 不引入任务队列 / 优先级 / 并发上限（沿用现有闸门）
- 不做"自动只重跑失败阶段"的推断（本方案是显式勾选）
- 不改 `parse_document_stages`（单文档 `?stages=`）的现有行为——它与新路径有重叠，清理另开一轮
- 不碰 `packages/docs-ui/src/utils/knowledge.ts` 里那份 6 步老阶段表（已确认仓内无调用方，但删除属对外 API 变更，另行评估）
- 不 commit、不 push（按 `AGENTS.md` 契约需明确指令）

## 7. 实施顺序

1. `parse_pipeline.py`：`retry_parse_task` 增 `parse_options` 透传（+ 单测）
2. `docs_routes.py`：`BatchRetryRequest.stages` + 校验与透传（+ 单测）；`GET /knowledge/parse/stage-registry`
3. `parse_pipeline.py`：`StageDef` 增 `destroys` 字段，`structure` 标注
4. 前端：共享阶段常量 → `BatchParseModal.vue` → `KnowledgeStats.vue` 接线 → 类型与载荷
5. 全量回归：后端 `pytest tests/unit services/docs-core/tests services/docs-api/tests`；前端两个包的 typecheck
