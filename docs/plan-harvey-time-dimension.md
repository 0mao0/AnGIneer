# 计划：给检索加时间维度（攻「最新/最近/多少」类 0% 题）

状态：待施工　日期：2026-10-20　前置：Harvey LAB Qwen3.8 臂 100 题已跑完

## 1. 背景与证据

Qwen3.8 臂（`docs/report-harvey-lab-100-qwen38.md`）把 0 判据题从 36 降到 16。这 16 题里有 **13 题问的是「最近/最新/多少」**，共同结构是：先按时间找出某类文档中最新的一篇，再回答那篇里的事实。

16 题清单（k = 判据数）：

| 类别 | 题 | 典型问法 |
|---|---|---|
| 信贷/融资先例 | 013(k4)、014(k3)、015(k3)、018(k1)、023(k4)、026(k3) | 最近的 MFN 条款；多少笔 covenant-lite |
| 资本市场/发行 | 036(k3)、040(k2)、044(k4) | 最近一笔发行；最大已关闭交易的承销商 |
| 反垄断/HSR | 004(k2)、008(k4) | 最近的反垄断案件；拿最新 HSR 申报当模板 |
| 重组计划 | 034(k2) | 最近确认的重整计划 |
| FDA/医疗 | 068(k3)、069(k3) | 每个 FDA 审批案件；最近一次谁做的 |
| IP 诉讼 | 079(k2)、081(k3) | 有没有庭审胜诉；最新的故意侵权案例 |

现状缺口：

- `doc_catalog` 没有日期字段；
- FTS 与向量检索都只按「相关性」排序，没有时间维度；
- 模型拿到的是「语义最像」的文档，不是「时间最新」的那篇。

## 2. 目标 / 非目标

目标：

1. 给 `doc_catalog` 增加文档日期与来源置信度；
2. `doc_search` 支持按日期排序与日期区间过滤；
3. 在上述 16 题上验证，至少 5 题离开 0 判据；001–030 不回归。

非目标：

- 不做全文时间线/事件抽取；
- 不改解析管线阶段（只读 `doc_blocks` 与文件 mtime）；
- 不做「按日期自动改写查询」的预取（先验证模型肯不肯用新参数）。

## 3. 设计

### 3.1 数据模型（`doc_catalog` 增三列，懒 ALTER）

| 列 | 说明 |
|---|---|
| `doc_date` | ISO 日期 `YYYY-MM-DD`，抽不到为空 |
| `date_source` | `text` / `filename` / `mtime` / `none` |
| `date_confidence` | `high` / `medium` / `low` / `none` |

置信度口径：

- `high`：正文首屏出现完整日期（"Dated as of July 16, 2024" / "DATED: 2024-07-16" / "as of March 3, 2025"）；
- `medium`：文件名含完整日期（`...-2024-07-16...` / `20240716`）；
- `low`：只抽到年份（`2024`），按 `YYYY-07-01` 落库并标 low；
- `none`：以上都没有，`doc_date` 为空，排序时排最后。

### 3.2 抽取实现

新增 `backfill_doc_dates(library_id)`（放 `docs-core/step09_query/doc_search.py`）：

1. 遍历 `doc_catalog` 的 `doc_id/file_name`；
2. 读 `doc_blocks` 第一页文本（`page_idx=0`，blocks 拼接 ≤ 4000 字符），正则按优先级匹配：
   - `dated\s+as\s+of\s+([A-Z][a-z]+\s+\d{1,2},\s+\d{4})`
   - `dated[:\s]+([A-Z][a-z]+\s+\d{1,2},\s+\d{4})`
   - `as\s+of\s+([A-Z][a-z]+\s+\d{1,2},\s+\d{4})`
   - ISO `(\d{4})-(\d{2})-(\d{2})`
3. 文件名正则：`(19|20)\d{2}[-_]?\d{2}[-_]?\d{2}`；
4. 兜底读源文件 mtime（`resolve_source_file(library_id, doc_id)`），标 `low`；
5. 批量 UPDATE，返回覆盖统计。

脚本入口：`scripts/backfill_doc_dates.py --library <id>`（复用 `backfill_catalog_all.py` 的库枚举）。

### 3.3 检索接口

`search_documents` 增参数：

```python
sort_by: Literal["date_desc", "date_asc"] | None = None
date_after: str | None = None   # YYYY-MM-DD
date_before: str | None = None
```

行为：

- 默认 `None`：保持现有相关性排序，逐字节不变；
- `date_desc`：有 `doc_date` 的候选按日期降序，空日期排最后；同日期按原分数；
- `date_after/before`：先过滤再排序；无日期的文档在显式区间过滤时**排除**（避免猜测）；
- matter/group 卡片的 `best` 取排序后第一篇；卡片带 `doc_date` 与 `date_source`。

HTTP：`POST /api/knowledge/internal/doc-search` 增同名字段。
Agent 工具 `doc_search`：schema 增 `sort_by` / `date_after` / `date_before`，描述写明「问最新/最近时用 `sort_by=date_desc`」。

### 3.4 开关与灰度

- 日期抽取只写数据，不改行为；排序只在显式传参时生效，天然灰度；
- 不设全局开关（不传参即旧行为）。

## 4. 验收

### 4.1 单元测试

- 抽取：正文日期 / 文件名日期 / 年份 / 无日期 四类；
- 排序：降序、空值最后、区间过滤排除空日期；
- 接口：不传参时结果与改造前一致（同一查询逐字段比对）。

### 4.2 评测（配对，同一模型、同一判官）

- 16 题：改造前后配对，**目标 ≥5 题判据数 > 0**；
- 001–030：criterion 不低于改造前 2 条判据（防回归）；
- 模型用当前默认 `Qwen3.6-35B-A3B`（与基线可比）；若时间允许再在 Qwen3.8 上复跑 16 题。

### 4.3 观测

- 16 题里实际调用 `sort_by=date_desc` 的题数（模型是否愿意用新参数）；
- 日期覆盖率：每库 `date_source` 分布。

## 5. 风险

| 风险 | 处理 |
|---|---|
| 扫描件/无日期文档多 | `date_source=none` 排最后；区间过滤时排除，不猜 |
| mtime 不可信（拷贝/迁移会变） | 只作 `low` 兜底，不参与高置信排序 |
| 正文日期被误抽（如合同里引用旧日期） | 只读第一页；优先 "dated as of" 句式；记录 source 便于回溯 |
| 模型不用新参数 | 验收里统计调用率；若 <50%，再考虑预取注入（P0.5 的教训：默认关） |

## 6. 施工顺序（估 1–1.5 天）

1. 抽取函数 + 单测（半天）；
2. 回填脚本，跑 `lab-firm-full`，看覆盖率分布（1 小时）；
3. `doc_search` 排序/过滤 + 接口 + 工具 schema + 单测（半天）；
4. 16 题配对 + 001–030 回归（半天）；
5. 记录到 `plan-harvey-enumeration-retrieval.md` 与报告。

## 7. 数据与命令

- 目录库：`data/evals/groups/evals_corpus.sqlite`（`doc_catalog`，21GB，勿重解析）；
- 评测脚本：`data/scratch/harvey-lab/tools/run_angineer_arm_par.py`、`grade_arm_par.py`；
- 基线：`data/scratch/harvey-lab/arm_report_angineer-100c.json`（Qwen3.6，100 题）；
- Qwen3.8 臂：`data/scratch/harvey-lab/arm_report_qwen38b.json`。

## 8. 参考

- `docs/report-harvey-lab-100-qwen38.md`（9.0% / 27.5%）
- `docs/plan-harvey-enumeration-retrieval.md`（P0–P2 全部实验记录）
- `docs/tech-report.md` §3.6（doc_catalog / doc_search 设计）
