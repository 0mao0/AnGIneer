# docs-api 表格解析产物补充「单元格级坐标」设计（table_cells 估计版）

日期：2026-08-24

## 背景与目标

读标（tender-read）基于 docs-api 的解析结果做基准库字段抽取，每个字段需要在 PDF 上做「溯源高亮」。
目前 `doc_blocks_graph.jsonl` 的 table 块只有整表 bbox / page_bboxes / table_header_bbox，拿不到单元格级位置。

现状折中：
- 原生文本 PDF 用 pdf.js 文本层反查坐标（扫描件无效）；
- 扫描件表格用「行文本长度加权」估算行区域（不精确，可能偏差一两行）。

目标：在 `doc_blocks_graph.jsonl` 的 table 块新增 `table_cells`（单元格级 bbox），
由 docs-api 服务端统一估算并落盘，DredgeAI 直接消费，替换前端 pdf.js 反查与行估算。

## 已确认的产品决策

1. 走 A 路线：服务端几何重建（估算），不做 MinerU 补丁（B 路线暂缓，将来可升级）。
2. 输出单元格级 `table_cells`（A1），不做行级 `table_rows` 过渡。
3. 单元格字段：`row` / `col` / `rowspan` / `colspan` / `page_idx` / `bbox` / `text`；
   bbox 按所在页宽高归一化到 0~1（与现有块 bbox 同一坐标系），节点保留 `page_width` / `page_height` 供换算。
4. 节点级新增 `table_cells_source: "estimated"`，标记坐标为估算来源（为将来识别坐标升级预留，DredgeAI 可据此决策）。
5. 跨页表格：按页区域高度比例分配行，每行/单元格归属到估计页码；与 `page_bboxes` 语义一致，每页输出该页的单元格。
6. 行列编号、文本与 `table_html` / `table_row_keys` 保持一致，方便按行列关联。
7. 不考虑向后兼容（新软件）：老 jsonl 缺 `table_cells` 由一次性回填脚本补齐，不做运行时回退。

## 架构

沿用现有「04 生成 → 05 透传/失效 → docs-api 透出」链路，与 `table_semantics` 完全同构：

- 新模块 `step04_structure/shared/table_cells.py`（04 生成、05 重建共用一份实现）；
- 04 结构化阶段在 popo 合并之后调用 enrich 写入 jsonl；
- 05 重建 `adapt_graph_node` 透传；表格 HTML/表题/脚注被编辑时与 `table_semantics` 一并清空；
- docs-api 块模型透出字段；轻量摘要接口将字段归入 heavy_keys 排除。

## 算法设计

### 1. 网格解析 `parse_table_grid(html)`

- 独立解析器，不复用 `parse_table_html`（它把 colspan 展开成重复文本，丢失结构信息）。
- 用占位矩阵 `occupied[row][col]`：逐行扫描，跳过被上方 rowspan 占用的列；
  单元格放置为 `(row, col, rowspan, colspan, text)`，并占满 `rowspan × colspan` 区域。
- 输出：`cells` 列表 + `rows_count` / `cols_count`。

### 2. 行条带估算 `estimate_row_bands`

- 行权重 = 该行覆盖单元格的文本总长度（跨行单元格按 rowspan 均摊到各覆盖行）。
- 行高 = bbox 高 × 该行权重占比；总权重为 0 时均匀切分。

### 3. 列条带估算 `estimate_col_bands`

- 列权重 = 覆盖该列的单元格文本总长度（跨列单元格按 colspan 均摊）。
- 列宽同理；总权重为 0 时均匀切分。

### 4. 单元格 bbox

- `cell.bbox` = 行条带（`row .. row+rowspan-1`）与列条带（`col .. col+colspan-1`）的并集；
  合并单元格天然得到合并后区域。

### 5. 跨页分配

- 区域集合解析顺序：
  1. 节点带 `page_bboxes`（popo 合并场景）→ 每页区域；
  2. 否则查找同文档后续连续页的「空壳」table 节点（0 行、bbox 横向重叠）；
     存在则主区域 + 空壳区域组成跨页区域集合；
  3. 找不到续页区域 → 全部单元格归属节点自身 `page_idx` 与 bbox。
- 行按区域高度占比分配到各区域（`rows × height_i / Σheight`），行号保持全局顺序。
- 区域内行条带在该区域 bbox 内计算；`cell.page_idx` = 区域页码；`cell.bbox` 为所在页归一化坐标。
- 空壳匹配仅限连续后续页 + 横向重叠，避免误并。

### 6. 语义约定与已知限制

- `col` 采用视觉网格列号（占位矩阵语义，正确处理 rowspan/colspan）。
  注意：`table_semantics` 用的 `parse_table_html` 是「colspan 展开 + 忽略 rowspan」的既有简化，
  含 rowspan 的表里两者 `col` 编号会不同；`row` 序号与单元格 `text` 仍一致。这是有意选择——几何溯源需要正确网格。
- `text` 使用与 `table_html_utils.clean_table_text` 一致的空白归一化（strip + 内部连续空白折叠），
  与 `table_html` 单元格文本一致。
- 嵌套表格（`table_nest_level > 1`）不特殊处理，沿用现有 HTML 解析同构的限制（与 `table_semantics` 相同）。
- `bbox` 已是 0~1 归一化坐标，估算直接在整表 bbox 内进行；节点 `page_width` / `page_height` 仅透传，不参与计算、不改写。

## 数据模型

table 节点新增：

```json
{
  "table_cells": [
    { "row": 0, "col": 0, "rowspan": 1, "colspan": 2, "page_idx": 4, "bbox": [0.089, 0.137, 0.911, 0.156], "text": "条款号" },
    { "row": 1, "col": 1, "rowspan": 1, "colspan": 1, "page_idx": 4, "bbox": [0.30, 0.17, 0.91, 0.20], "text": "招标人" }
  ],
  "table_cells_source": "estimated"
}
```

- `text` 与 `table_html` 单元格文本一致（空白归一化）。
- 行列编号与 `table_html` 网格位置一致（含 rowspan/colspan）。

## 接入点

| 位置 | 改动 |
| --- | --- |
| `shared/table_cells.py` | 新增：网格解析、行/列条带、跨页分配、`build_table_cells`、`enrich_graph_nodes_table_cells` |
| `solo2json_pipeline.py` | `table_semantics` enrich 之后调用 table_cells enrich；stats 并入返回 |
| `graph_rebuilder.py` | `adapt_graph_node` 透传 `table_cells` / `table_cells_source` |
| `graph_editor.py` | 表格内容（HTML/表题/脚注）变化时与 `table_semantics` 一并清空两字段 |
| `docs-api/models/v1_responses.py` | Block 增加 `table_cells` / `table_cells_source` 字段 |
| `docs-api/routes/v1/documents.py` | Block 构造透出两字段 |
| `docs-api/docs_routes.py` | 摘要接口 heavy_keys 增加两字段 |
| `scripts/backfill_table_cells.py` | 一次性回填存量 jsonl（幂等，不重跑 MinerU/popo/LLM） |

## 测试

- 网格解析：colspan / rowspan / 合并单元格 / 空单元格 / 行列数正确。
- 条带估算：文本加权、零权重均匀、单行单列、合并单元格并集。
- 跨页：`page_bboxes` 分配、空壳页匹配与分配、无续页回退。
- enrich：写入字段、非 table 跳过、stats 正确。
- 05 透传与编辑失效。
- docs-api 块模型透出与摘要排除。
- 回填脚本幂等（重复执行结果一致，其余字段不变）。

## 手工验收

- 用现有跨页表格文档（41 行投标人须知前附表）：回填后抽查 `row/col/text` 与 `table_html` 一致。
- 渲染 PDF 对应页并叠加单元格 bbox，肉眼检查行级对齐与跨页页归属。
- DredgeAI 侧确认 `table_cells` 字段可见并可直接用于高亮。

## 发布

随下一个 docs-api 版本一起发布；版本号按主仓发布流程（改主仓版本号 + README 版本表 + tag）。
