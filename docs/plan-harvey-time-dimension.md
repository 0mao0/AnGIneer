# 计划：给检索加时间维度（攻「最新/最近/多少」类 0% 题）

状态：已施工并收口（2026-10-20；验收 4/5 未达标 §10；实体取最新 §11；读页/章节修复 §12–13）　日期：2026-10-20　前置：Harvey LAB Qwen3.8 臂 100 题已跑完

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

## 9. 施工结果（2026-10-20）

### 9.1 已落地

| 层 | 改动 |
|---|---|
| 数据模型 | `doc_catalog` 增 `doc_date` / `date_source` / `date_confidence`；`ensure_catalog` 懒 ALTER，`idx_doc_catalog_date` |
| 抽取 | `backfill_doc_dates(library_id)`：正文首屏（≤4000 字）→ 文件名 → mtime；`scripts/backfill_doc_dates.py --library … [--limit N]` |
| 检索 | `search_documents(sort_by=date_desc/date_asc, date_after, date_before)`；默认不传参路径逐字节不变 |
| 接口 | `POST /api/knowledge/internal/doc-search` 三个同名字段；`docs_retrieval_client.doc_search` 透传 |
| 工具 | `doc_search` schema 增 `sort_by`（enum）/`date_after`/`date_before`，描述写明「问最新/最近用 date_desc」 |
| 测试 | `services/docs-core/tests/test_doc_search.py`（抽取/回填/排序/过滤/默认不变）、`tests/docs-api/test_doc_search_time_params.py`（接口透传） |

计划外但必要的精度修正（实测数据驱动）：

- 英文孤立年份不抽——法律语料首屏常见 `123 F.3d 2094`、表格单元格 `2026 Standard`、xlsx 文件属性时间戳；首版按计划抽「年份 → low」，lab-firm-full 9009 篇里 5283 条 low 多为此类噪声，`date_max` 到 2094，直接毁掉「最新」排序；
- 所有来源统一日期合理性闸门 `[1900, 今天+366 天]`，未来日期丢弃；
- mtime 只作展示/兜底：排序排在正文/文件名日期之后，且**不参与** `date_after/date_before` 过滤（拷贝/迁移会改 mtime，语料里 57% 只有 mtime 且集中在入库当天）；
- 中文日期（`2024年7月16日` / `2024年7月`）一并支持，否则中文库这条通道空一半。

lab-firm-full 回填（9009 篇，24s）：`text` 3726 / `filename` 159 / `mtime` 5124；`high` 3726、`medium` 57、`low` 5226；日期区间 1998-06-12 – 2026-10-15。

### 9.2 验收结果（Qwen3.6-35B，判官 gpt-5.5，同语料）

| 口径 | 改造前 | 改造后 | 目标 |
|---|---|---|---|
| 16 题 criterion | 8/46 = 17.4%（同代码控制臂） | 10/46 = 21.7% | ≥5 题离开 0 判据 |
| 16 题里离开 0 判据 | — | **4 题**（004/018/044/069） | ≥5 题（**未达标**） |
| 001–030 criterion | 21/206 = 10.2%（10-18 臂） | 25/206 = 12.1% | 不低于改造前 2 条（**达标**） |
| 38 题 all-pass | 2/38（10-18 臂同 38 题） | 5/38 = 13.2% | — |

控制臂说明：10-18 的 `arm_report_angineer-100c.json` 早于 HEAD 上 P2/P3 等检索改动，不能直接当「改造前」。故 16 题另跑一臂 `time16-before`（同一 HEAD、同一进程环境，仅把 `doc_search` 工具 schema 恢复成不带日期参数），与 `time38` 同日晚间隔 1 小时。两臂差 +2 条判据（8→10）、all-pass 0→3；逐题看是 018/034/044/069 各 +1、069 +2，013 −1、036 −2，**净 +2 ≈ 0.7 个标准误，不显著**。

### 9.3 观测（计划 §4.3）

- `doc_search` 调用率：38 题里 13 题调用（34%）；调用过 `doc_search` 的题里 11 题的调用带日期参数（85%）——**参数本身很好用**；
- 16 道目标题里只有 5 题调用 `doc_search`、**4 题用了 `sort_by=date_desc`（25%）**，低于计划设的 50% 阈值；
- 用了日期参数的 4 题（013/014/023/026）判据数全为 0；加分题（004/018/044/069）都没调 `doc_search`（走 knowledge_search/doc_read）。**因此本轮 +2 条不能归因于时间维度**。

### 9.4 结论与下一步

结论：时间维度已作为**通用能力**落地（任何库、任何调用方；不传参零影响），但**本轮没证明它能改善「最新/最近」题**。两个结构性原因：

1. **工具选择**：目标题里模型多数直接走 `knowledge_search`，根本进不了 `doc_search`（25% < 50% 阈值，命中计划 §5 风险行）；
2. **候选集太宽**：`sort_by=date_desc` 是全局日期排序，实体型问题（「Lumos 最近一笔信贷协议」）里目标 matter 会被更晚的其它 matter 挤到第 37 位（013 实测：相关性第 13 → 日期第 37），反而掉判据。

下一步（按计划 §5 风险表，均默认关）：

1. 对「最新/最近/最近一次/哪一年」做**路由级预取**：先按实体/主题过滤，再 `doc_search(sort_by=date_desc)`，把候选注入第一轮（P0.5 形态，`ANGINEER_*` 开关默认关）；
2. `doc_search` 增 matter/客户过滤参数（如 `matter_contains`），让「实体内最新」成为一次调用而不是靠模型拼；
3. 观测项继续记：日期参数调用率、`date_source` 分布、目标题判据数。

## 10. 预取注入实验（2026-10-20 晚，负结果，默认关）

按 §9.4 第 1 条实现 `date_prefetch`（`services/angineer-core/src/angineer_core/date_prefetch.py`）：

- 入口 `build_date_context`：日期意图判定（最新/最近/latest/most recent…）→ 复用 `enum_prefetch.rewrite_queries` 的 3 条检索式 → 对每条跑 `search_documents(sort_by="date_desc")` → 按 group 取最新一篇（mtime 排除）→ 注入 ≤15 组、≤4 KB 候选；
- 接线：`agent_policy._prefetch_context`（枚举优先、日期其次），挂在 L1 与 complex 两档的 `enum_context` 通道；
- 开关 `ANGINEER_DATE_PREFETCH` 默认 **0**，库白名单 `ANGINEER_DATE_PREFETCH_LIBRARIES` 默认 `*`；任一步失败返回 None（不影响原链路）。

16 题配对（同判官、同语料、同晚）：

| 臂 | criterion | 日期参数使用 |
|---|---|---|
| 对照（工具 schema 不带日期参） | 6/43 = 14.0% | — |
| 只开日期工具（`time38`） | 10/43 = 23.3% | 4/16 |
| 预取注入（本实验） | **4/43 = 9.3%** | 11/16 |

读法：注入把日期参数使用率从 4/16 拉到 11/16，但判据数反而下降——模型把预取候选当成「候选全集」，不再自己检索（018 1→0、040 1→0、044 1→0、069 3→1）。这与 P0.5 的教训一致：**预取注入默认关，不启用**。036 判分端点挂起，未计入（两臂同口径剔除）。

结论：时间维度的正确用法仍是「模型主动调 `doc_search(sort_by=date_desc)`」；要突破工具选择瓶颈，应做**实体/案件过滤参数**（让一次调用就能表达「X 的最新一篇」），而不是把候选塞进系统提示词。

## 11. 实体内取最新（2026-10-20 深夜，机制已验证）

按 §10 结论实现 `entity_contains`（`doc_search` / HTTP / 客户端 / 工具 schema 四处同名）：

- 第一步**实体定位**：用 FTS 查提到实体的文档，经 `doc_catalog` 映射到它们所属的 group（matter/folder/doc）；
- 第二步**范围收窄**：候选只保留这些 group 内的文档，再按 `filename_contains` / `sort_by` / 日期区间处理；
- 组内 `best` 规则：给了 `filename_contains` 时，命中文档排在组内最前——避免「同组分数更高的别的文书」顶掉目标（013 之前拿到的是 perfection-certificate）；
- 只给 `entity_contains` 不给 query 时，返回该实体的全部文档（配合 `sort_by=date_desc` 就是「这家的最新文件」）；
- 实体未命中返回 `error`（含实体名），提示换关键词，不静默返回空。

手工验证（lab-firm-full）：

```
entity_contains="Lumos Analytics", filename_contains=["credit agreement"], sort_by="date_desc"
→ entity: matched_docs=189, matched_groups=10, scoped_docs=1
→ 1008-00001 | 2023-03-09 | credit-agreement-execution.docx   ← 正是题 013 的答案文档
```

冒烟（题 013，label `entity-smoke`）：模型第一次把 `filename_contains` 写成字符串被 schema 拒绝，第二次改用
`entity_contains=Lumos Analytics` + `filename_contains=["Credit Agreement"]` + `sort_by=date_desc`，拿到上面那张唯一卡片；
但**最终答案仍改答 SAFE**（`executed-safe-canopy-growth.docx`，称其 MFN 在 Section 5），没有采用检索到的信贷协议。判官 gpt-5.5 端点
两次挂起（无返回），该次未能出分；按答案内容预计 0–1/4。

结论：检索侧已经能表达并命中「实体内最新一篇」，剩余瓶颈是**模型拿到正确卡片后的作答选择**（它继续用 knowledge_search 找 SAFE 并改判）。
下一步只有两条路：L1 对实体型问题强制先走 `doc_search(entity+filename+date_desc)` 并把结果作为首选证据；或把「实体+文件类型+最新」
做成预置查询模板。两者都需要新的对照臂与判官稳定性保障。

## 12. 权威卡片 + 读页修复（2026-10-20 深夜，仍差一步）

1. **`authoritative` 卡片**：`doc_search` 在 entity+filename+`sort_by` 唯一命中时，结果带
   `authoritative={doc_id,title,doc_date,instruction:"必须基于该文档作答"}`。题 013 冒烟：模型第二次调用就用上
   `entity_contains=Lumos Analytics + filename_contains=["Credit Agreement"] + sort_by=date_desc`，拿到 1 张卡并 `doc_read` 了
   `doc-91692dd9`（信贷协议）。
2. **但 `doc_read` 用全词 AND 匹配**（"MFN Most Favored Nation"）0 命中后回落到整篇开头（security agreement 段落），模型据此判
   「信贷协议没有 MFN 条款」。
3. **修 `doc_read`**：AND 无命中 → OR 回退，按命中词数排序（避免 "most" 命中无关段落），并去掉 most/the 等虚词。验证：同 query 现在
   命中 MFN 相关段落（p1 定义），模型承认信贷协议存在（`credit-agreement-execution.docx`，2023-03-09），但仍未读到
   Section 2.15(d)-(e)，结论仍是「信贷协议没有 MFN」。

结论：检索（实体+类型+日期）与读页已能把正确文档和 MFN 相关段落送到模型手里；缺口变成**按章节定位条款**——需要按标题/章节读
（`doc_read` 增 `section` 参数，或按 title 树切块检索），已超出本计划（时间维度）范围。判官 gpt-5.5 当晚持续挂起，四次冒烟均未出分。

## 13. 按章节读（2026-10-20 深夜，机制上线、题仍不过）

`doc_read` 增 `section` 参数（HTTP / 客户端 / 工具 schema 同步）：在文档块序列里找 `Section 2.15` / `§ 2.15` / `2.15.`，
从该标题所在块往后读 8 块；找不到则回退普通读页，并回 `section_found=false`。工具描述写明「找条款/章节用 section」。

题 013 第五次冒烟（label `section-smoke`）：模型用上 `entity_contains + filename_contains + sort_by=date_desc`，拿到唯一卡片并
`doc_read` 了该信贷协议；但它**没使用 `section`**（不知道条款号是 2.15），而是 `head` 读了 4000 字符——正好在 Section 2.15（第 20 页）之前截断；
最后仍答「Lumos 的 MFN 在 SAFE 里，信贷协议没有 MFN 条款」。

结论：**时间维度这条线到此为止**。检索层（实体定位、日期排序、区间过滤、权威卡片）和读页层（OR 回退、词数排序、按章节读）都已够用，
几十页的合同里翻到第 20 页这件事属于「章节先验」——模型不知道条款号时，任何关键词匹配都只能到定义页。要过这类题，需要题目级先验
（如按文档类型给「MFN → 2.15」的条款索引），那是条款知识库的方向，不是检索时间维度。

判官 gpt-5.5 当晚持续挂起（4 次冒烟 + 036 均未出分），以上结论基于人工读答案。




