# M3.1 实施方案：figure_describe 进 Pipeline

> 状态：待执行｜版本：v1.0｜日期：2026-08-28
> 前置基线：v2 评测 run-b812e082733c（487 题 / 110 篇论文）：整体 86.0%，hit@5(doc) 96.1%，answer 88.5%

## 0. 目标与数据依据

| 现状（v2 基线） | 目标 |
| --- | --- |
| text-image 78.6% / text-table-image 78.4%（text 92.2%） | 图题正确率拉近 text 水平 |
| 68 道错题中 28 道是图题（41%）；27 道近阈值错题（语义分 0.4~0.65）中 19 道是图题 | 近阈值题转化率最大化 |
| 库内 117 篇文档共 2042 个图块：362 个已有描述、1680 个待生成 | 描述全量生成 + 全量可检索 |

**为什么有图名（caption）还要图描述**：caption 只说"图是关于什么的"（如 `Fig. 1. Sketchmaps of the speech quality assessment models`），图描述说"图里画了什么、数值趋势是什么"（如"双通路系统，SSL+ECAPA-TDNN 算 SIM 余弦相似度，另一支路按 NISQA/BVCC/SOMOS 标准预测 MOS"）。问"图中 2000-2010 年指标怎么变化"这类题，答案在图的内容里，caption 无法作答。

**v1 的历史教训（本次已实锤）**：v1 的 362 条图描述写进了 `doc_blocks_graph.jsonl`，但全库检索仅 11 条进了索引——`canonical_builder.py:173-176` 的消费逻辑是"仅当图块无正文（caption）时才用描述兜底"，有 caption 的图块描述被全部跳过。本方案必须同时修这个消费缺陷，否则描述做得再多也不生效。

## 1. 核心设计：新增 `figure_describe` 阶段

### 1.1 阶段位置

`parse_pipeline.py` 的 `STAGE_REGISTRY` 与 `_PIPELINE_ORDER`：

```
... → popo(3.2) → structure(4) → 【figure_describe(4.5)】→ fts(5) → vectors(6) → graph(7)
```

- **kind = SOFT**（与 popo/vectors/graph 同级）：VLM 挂了只标记失败，文档照常入库（v2 最后 2 篇 solo 回退已验证此容错路径）
- **depends_on = ["structure"]**（需要 `doc_blocks_graph.jsonl` + 图片文件）
- **verify 复用** `_verify_doc_blocks_graph_input`

### 1.2 阶段执行逻辑（`_run_figure_describe`）

1. 读 `parsed/doc_blocks_graph.jsonl`，筛 `block_type ∈ {image, figure, chart, image_block}` 且 `figure_description` 为空的块（断点续跑天然支持）
2. 逐张调 VLM，沿用现有脚本的自由描述 prompt（v1 已验证）
3. 写回 jsonl 对应节点的 `figure_description` 字段 —— **JSON 落点**
4. 单图失败只记 error 不阻塞同文档其他图；整文档 0 产物且全部失败时才标阶段失败
5. 并发闸：仿 `popo_inference_slot` 加 `_FifoGpuGate(FIGURE_DESCRIBE_MAX_CONCURRENCY)`（默认 1）；单图超时 120s + 重试 1 次

### 1.3 SQLite / 向量 / 图谱落点（零新存储代码）

jsonl 写回后由现有阶段自动携带：

- **step05 fts**：`canonical_builder` 建 chunk 入 FTS5（可检索）
- **step06 vectors**：chunk 正常向量化入向量库
- **step07 graph**：`graph_rebuilder.py:152` 已透传 `figure_description` 进图谱节点

## 2. 核心逻辑归位

- **新增** `services/docs-core/src/docs_core/step04_structure/figure_describer.py`：从 `scripts/open_ragbench/generate_figure_descriptions.py` 抽提 `describe_image` / 图块筛选 / jsonl 写回逻辑；入参改为 `library_id/doc_id`，去掉硬编码 `DOCS_ROOT` 与 `lib-b07ed174`
- **环境变量**（沿用 PoPo 命名风格）：

| 变量 | 默认值 | 说明 |
| --- | --- | --- |
| `FIGURE_DESCRIBE_ENABLED` | `1` | 阶段总开关 |
| `FIGURE_DESCRIBE_VLM_URL` | `https://ai.bim-ace.com/chat/v1/chat/completions` | VLM 端点 |
| `FIGURE_DESCRIBE_VLM_API_KEY` | 无（必填） | 鉴权 |
| `FIGURE_DESCRIBE_VLM_MODEL` | `Qwen3.6-35B-A3B-FP8` | 多模态模型 |
| `FIGURE_DESCRIBE_MAX_CONCURRENCY` | `1` | 并发闸 |
| `FIGURE_DESCRIBE_TIMEOUT` | `120` | 单图超时（秒） |

- **顺手修安全隐患**：删除脚本中硬编码的 API key 默认值，改纯环境变量读取
- `scripts/open_ragbench/generate_figure_descriptions.py` 保留为薄 CLI 包装（调 docs-core 模块），供手动补跑

## 3. 消费逻辑修正（关键 bug fix）

`services/docs-core/src/docs_core/step05_sqlite_fts/rebuild/canonical_builder.py:173-176` 现状：

```python
text = str(raw_block.get("text") or raw_block.get("content") or "").strip()
# 图表块通常没有正文文本；用 VLM 生成的图描述作为可检索文本
if not text and raw_block.get("image_path") and raw_block.get("figure_description"):
    text = str(raw_block.get("figure_description") or "").strip()
```

改为**拼接**（caption 与描述都进索引）：

```python
text = str(raw_block.get("text") or raw_block.get("content") or "").strip()
# 图块的可检索文本 = caption + VLM 图描述（拼接而非空位兜底，否则有 caption 的图描述永不生效）
if raw_block.get("image_path") and raw_block.get("figure_description"):
    desc = str(raw_block.get("figure_description") or "").strip()
    text = (text + "\n" + desc).strip() if text else desc
```

影响面：仅图块（image_path 非空）的 chunk 文本变化；无描述的图块行为不变。这是 M3 系列唯一的算法侧改动——修复"描述从未被索引"的消费缺陷，非调参。

## 4. 存量回填（117 篇文档）

新增批量回填脚本 `scripts/open_ragbench/backfill_figure_descriptions.py`：

1. 对全部 117 篇调单阶段重试 API：`POST /api/v1/documents/{doc_id}/stages/figure_describe/retry`（生成 1680 条描述）
2. 依次 retry `fts`、`vectors`（本地计算，无外部 API 依赖，除 embedding 在线接口）
3. 断点续跑（跳过已有描述的图块）；日志落 `data/open_ragbench/logs/`

成本估算：1680 张图 × 1 次 VLM 调用，并发 4 约 1.5~2 小时；fts/vectors 重建为本地操作。

## 5. 验证方案（A/B + CI 门禁）

| 步骤 | 内容 | 判定标准 |
| --- | --- | --- |
| A/B 对比 | 回填后重跑 v2 全量 487 题 | 整体分提升且 bootstrap CI 下限超过 0.86 |
| 图题子集专项 | v2 报告拆 text-image(131) + text-table-image(51) 分项 | 两项正确率显著提升 |
| 回归保护 | 跑 smoke-v1（25 题）对比基线 | overall/refusal 回落不超容差 0.05 |
| 拒答保护 | refusal-v2（39 题，此前未跑）首跑 | 图描述不得导致拒答率下降 |

## 6. 测试

- `tests/docs-core/` 新增：figure_describer 单测（mock VLM 响应、断点跳过、缺图容错）、阶段注册/顺序/soft 回退测试
- `canonical_builder` 拼接逻辑单测（有 caption+描述 / 仅描述 / 仅 caption 三态）
- 回填脚本单测（沿用 tests/unit 风格）

## 7. 风险与回退

| 风险 | 对策 |
| --- | --- |
| VLM 中途挂（如 PoPo vLLM 曾 502） | soft 阶段 + 断点续跑 + 单图隔离；挂了重跑回填脚本即可 |
| 描述质量差反而误导 | A/B 不过则 `FIGURE_DESCRIBE_ENABLED=0` 全局关闭；消费侧拼接对无描述图块无影响 |
| 索引不一致 | 回填统一重跑 fts+vectors，新旧文档索引同构 |
| PoPo vLLM 502 导致 2 篇（2404.09358v3 / 2405.01105v3）solo 回退入库缺 popo 强化 | 记入报告备注（2/110 影响可忽略）；vLLM 恢复后可对这两篇重跑 popo 阶段 |

## 8. 执行顺序与验收

```
① docs-core 新增 figure_describer 模块 + 注册阶段 + 消费逻辑修正 + 单测
② 回填脚本 + 117 篇回填（生成 → fts → vectors）
③ smoke 回归 → v2 全量 A/B → refusal-v2 首跑
④ v2 报告生成（report.py --manifest v2）+ README benchmark 表更新
```

**验收标准**：v2 图题分项（text-image / text-table-image）正确率显著提升、整体 CI 下限 > 0.86、冒烟不回落、新增单测全绿、AGENTS.md/README 相关小节同步更新。
