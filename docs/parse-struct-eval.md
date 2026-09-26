# ParseStruct：结构层解析评测（jsonl 口径）

## 评测体系：A / B / C 三层

按"**验证对象**"划分（不是按工具划分）——pipeline 的产物本体是 jsonl，markdown 是它的投影：

| 层 | 验证对象 | 口径 / 工具 | 输出形态 | 台上选手 |
|---|---|---|---|---|
| **A. 解析结果质量** | pipeline 的产物（jsonl 本体 + 它的 markdown 投影） | ① 官方 OmniDocBench 口径（jsonl→markdown，别人的评测器）<br>② **ParseStruct / ParseStructComparison**（jsonl 块层，我们的脚本） | 分数 | ① 三方：参考模型 / MinerU 的 md / 我们的 md<br>② 两方：MinerU **原生 content_list** / 我们的 jsonl |
| **B. 素材传递性** | jsonl → canonical → chunk → 向量 | 覆盖率与一致性断言（**已固化进 nightly**，见下） | **缺失清单**（不是分数） | 只有我们 |
| **C. 端到端效果** | agentic chat | nightly_openRAG（检索命中 + 答对） | 分数 | 跑在评测语料上的任何系统 |

### 三条使用纪律

1. **A 的两个口径并列报，不能互相替代**。同一个 GT，两种刻度：ParseStruct 量 jsonl 本体；
   官方 markdown 口径量"jsonl + 投影"。差值本身是有效信息——**差值 = 投影损耗**
   （实测：表格 TEDS 0.9172 vs 0.8821，差的 3.6 个点就是 HTML 表被拍成管道表造成的，改投影后两者追平）。
   官方 markdown 口径同时兼任 **markdown 交付面**的验收（markdown 有自己的消费者：前端预览/编辑、
   导出、step07 图谱抽取、agent 的 table_lookup），不只是 jsonl 的影子。
2. **参考模型只在 A① 能上场**（它只吐 markdown、没有坐标）；MinerU 两个台都能上，但用的是它**不同的产物**
   （A① 用它的 markdown、A② 用它的原生 content_list）——所以"MinerU 的分数"必须带口径。
3. **B 是断言不是评测**：它答"内容有没有原样送到检索层"，答不了"chunk 边界切得对不对"、
   "section_path 语义对不对"（这两件三层都答不了，因为没有对应标注）。所以 B 的产物是缺失清单，
   适合做 CI 断言，不必做成常设分数体系。

### B 的固化位置（2026-09-13）

| 项 | 内容 |
|---|---|
| 实现 | `evals_core/material_parity.py`（数据源可注入，单测不碰真实 DB） |
| 运行 | `evals_core/nightly/pipeline.py` 的 `_material_health` 步骤：每晚评审**开跑前**先跑，best-effort——体检自身失败只记日志，不影响结论，也不侵入解析链 |
| 配置 | `data/evals/nightly_settings.json`：`parse_health_enabled`（默认 true）、`parse_health_libraries`（默认 [] = 全部库）、`parse_health_max_docs`（默认 200，按产物修改时间倒序） |
| 产物 | `data/evals/nightly/<date>/material_parity.json|md`（含每篇缺失清单） |
| 告警 | severity ∈ {warn, fail, error} 时额外推一条企微到 SYSTEM 群（不改动原有结论消息） |
| 手动复查 | `python scripts/run_material_health.py --libraries <lib> --max-docs N [--json out.json]`；退出码 0=ok / 1=warn,fail / 2=体检失败，可接 CI |

**检查项**（逐文档）：① 内容落地（`content_json` 有文本而 `plain_text` 为空）；② 块→chunk 覆盖
（块文本是否出现在该文档的 chunk 文本里，空白无关、取前 24 字符，容许 2% 缺口）；
③ chunk→向量（有 chunk 而向量点为 0）；④ 索引存在（canonical 有无记录）。
**按设计不入索引的块不参与 ②**：页眉/页脚/页码、`layout_category=furniture`、`is_active=0`
——不排除会造成 94% 的假阳性（实测：default 库未覆盖率 3.3% → 0.19%）。

**② 的探针取 `plain_text_corrected or plain_text`**（2026-09-14）：链路构建 canonical/chunk 时
优先消费 PoPo 校正后的字段，只比 `plain_text` 会把"被校正改写过的块"一律报成未覆盖。实踩：
一篇论文的 4 个公式块因 PoPo 把左端 `V_{s}=` 校正成 `V=` 而全部失配（前 24 字符探针必然打不中），
改用 corrected 后 **0 失配**——内容确实送达了检索层，只是以校正后的形式。

**符号改动单列报出（不计 fail）**：`symbol_mismatch`（链路自己打的标）表示 PoPo 校正改动了
公式符号，属**数据质量信号**——`V_{s}` → `V` 丢下标，语义变了。体检每晚报计数与样例
（`blocks_symbol_mismatch` + `symbol_mismatch_samples`，进摘要与结论卡片那一行），
但**不判 fail**：它答的是"校正对不对"，不是"内容有没有送到"。

**④ 只对"计划建索引"的文档断言**（2026-09-14，判定依据是 `doc_parse_stages` 的事实，不是排除名册）：

| 阶段事实（`fts` 行） | 处理 |
|---|---|
| 无记录（只跑部分阶段入库，如评测库） | **豁免并计数**（未计划建索引，不是缺陷） |
| 状态 `skipped` | 豁免并计数（明确不适用） |
| 状态 `completed` 但 canonical 无行 | **照报**（状态说建完、实际没写进去） |
| 状态 `running`/`pending`/`failed`/`partial` | **照报**（中断未完成） |

为什么这么定：服务器上的 `omnidocbench` 评测库只跑 5 阶段（`run_omnidocbench_eval.py` 的 `PARSE_STAGES`
不含 `fts`/`vectors`），却在每晚的素材检查里固定报 11 篇"未索引"；而 `default` 库那篇
《JTS 154-2018 防波堤与护岸设计规范》是真的被服务重启打断 fts、索引被清空（状态卡在 `running`）——
**同一套断言必须能同时区分这两者**，按库加白名单做不到（白名单会让该库的真问题也永远隐身）。
豁免**不可静默**：篇数同时进摘要文本与 nightly 结论卡片那一行，否则 stage 记录被弄丢时体检会静默转绿。

首次真实运行发现（2026-09-13，各取最近 10-12 篇）：

| 库 | 内容未落地 | 块→chunk 未覆盖 | severity |
|---|---|---|---|
| default | 27 块 | 31/15923（0.19%） | fail |
| lib-b07ed174（nightly 语料） | 181 块 | 25/3335（0.75%） | fail |
| omnidocbench（修复后重解析） | **0** | **0/108** | **ok** |

生产两个库的"内容未落地"是**修复前解析的存量产物**（那五类块当时被整类吃掉），重新解析后才会消失
——体检会在每晚提醒这个积压，这正是它该做的事；若**新**解析文档仍报此项，则是链路回归。

命名约定：**ParseStruct 是我们自建口径的名字，不可声称为 OmniDocBench 官方分数**。

## 为什么要另建一套口径

官方 OmniDocBench 端到端评测只吃 **markdown**：把我们的 `content.md` 交给官方评测器，由对方的
正则把 markdown 再切回块，位置是**字符偏移**，再与 GT 的块（真 bbox）匹配。它量的是
「交付的 markdown 有多好」，而 **RAG 检索吃的是 canonical jsonl / SQLite / 向量那一层**——
块层级、section_path、chunk 边界、表格检索表示在 markdown 里根本不存在，官方口径一个都不量
（详见 `docs/omnidocbench-baseline.md` 的口径说明）。

本口径不绕 markdown：直接拿 `doc_blocks_graph.jsonl` 的块（真 bbox）与 GT 的 poly 做**几何对齐**，
量 RAG 真正依赖的那层。**不需要 18GB 镜像、不需要 GPU、不重跑解析**（读已落盘产物，200 页跑完约 2 分钟）。

## 怎么跑

```bash
python scripts/eval_parse_struct.py \
    --state data/evals/omnidocbench/predictions_eval200/state.json \
    --out data/evals/omnidocbench/result_jsonl200
# 可选：--gt <OmniDocBench.json> --library-dir <documents 目录> --iou-min 0.3
#       --filter-prefix <文件名前缀> --limit <页数>
```
产物：`structure_result.json`（逐页明细）+ `structure_report.md`（报告）。

## 一键入口（A①+A② 编排、归档、Δ）

一条命令、本机跑、可选题量、结果入档并与基线比 Δ。**不新建评测器**：调的还是上面这两个脚本，
新做的只有编排 + 归档 + Δ（`evals_core/parse_regression.py` + `scripts/run_parse_regression.py`）。

```bash
# 【一键】全跑：predict → A②×2 → A① → 归档 → Δ（200 页实测 ≈50min：predict 45min + A② 38s×2 + A① 3.2min）
python scripts/run_parse_regression.py --limit 200 --seed 42

# 干跑：复用现成预测、不跑 18GB 镜像（~4min，只验归档与 Δ）
python scripts/run_parse_regression.py --skip-predict --skip-official --limit 50 \
    --predictions data/evals/omnidocbench/predictions_eval200

# 把既有离线产物入档为参照基线（不跑任何评测器）
python scripts/run_parse_regression.py --import-official <官方产物目录> \
    --import-chain <structure_result.json> --import-mineru <...> --tag baseline-YYYYMMDD --note "..."
```

数据集/GT/三方表两列**自动探测**（`OMNIDOCBENCH_DATA` 环境变量 > 仓库内 `data/omnidocbench` >
`D:/AI/tools/OmniDocBench_data` > `~/OmniDocBench_data`；两列源同理由
`OMNIDOCBENCH_{REF,MINERU}_RESULT` 或 `D:/AI/omnidocbench_dl/{ref_result,mineru_only_result}` 探测），
所以本机真一键；探不到才报错并列出候选，`--data-dir` / `--gt` / `--sources-*` 可显式覆盖。

| 参数 | 默认 | 说明 |
|---|---|---|
| `--limit` / `--seed` | 200 / 42 | 与既有基线同约定；抽样是 `random.Random(seed).sample(排序全集, limit)`——**不同 limit 不构造嵌套**（50⊂200 是 09-17 实测巧合；1000 vs 200 实测交集仅 190/200），跨规模比对以 `--delta-mode intersect` 或分母口径说明为准 |
| `--predict-mode` | `in-process` | 直驱 docs_core，不吃 HTTP/管理员凭据；改代码即时生效（http 模式量的是长驻进程的旧代码） |
| `--skip-predict` / `--skip-official` | — | 必须显式给，**跳过理由写进 meta 与 summary**，不静默 |
| `--baseline` | `baseline` | `baseline`(指针) / `latest` / `none` / `<run_id>` / 目录 |
| `--delta-mode` | `strict` | 页集合不等时 `strict` 不出 Δ；`intersect` 按交集重算 A①（**非官方重跑口径**） |
| `--set-baseline` | — | 把本次 run 钉为基线（首次跑自动成为基线） |

**归档布局**（`data/evals/parse_regression/`，本机 gitignored；数字回填本文件与 `omnidocbench-baseline.md`）：

```
<root>/latest.json                 最近一次 run 指针
<root>/baseline.json               钉住的基线指针
<root>/<run_id>/{meta.json, summary.md, struct_chain.json, struct_mineru.json, official/, gt_subset.json}
```

`meta.json` 里 **`page_ids` + `page_ids_hash` 是 Δ 的前提**（页集合不同的两次分不可比——
少评几页会虚高或虚低）；另记 git describe（含 `-dirty`）、抽样参数、阶段（固定 5 阶段）、
MinerU 版本、各步耗时、跳过/失败项。

**两条必须知道的量尺事实**（否则数字会被读错）：

1. **推理仍出本机**：predict 的页图经 `MINERU_CONFIGS`/`POPO_CONFIGS` 送到生产网关背后的 GPU。
   "不上传生产"= 不写生产库、不落生产盘（满足）；要做到数据也不出本机只能本机自部署 GPU
   （本机无 GPU，200 页不可行）。评测用的是 OmniDocBench 公开基准集页图，不是私有文档。
2. **20260913 那份旧基线不是一次 fresh 解析**：它是 09-12 那批 jsonl 的 markdown **换个表格写法
   重投影**（200 个 md 写入时间跨度 0.33 秒；146 页与库内逐字相同、54 页只差表格写法）。
   数字已登记在 `docs/omnidocbench-baseline.md` 的"HTML 表投影"列；**归档目录已于 2026-09-17
   按用户要求清理**（只留 09-17 之后的 run），需要它当对照时用同一条命令重建：
   `python scripts/run_parse_regression.py --import-official D:/AI/omnidocbench_dl/full_html_result
   --import-chain data/evals/omnidocbench/result_jsonl200/structure_result.json
   --import-mineru data/evals/omnidocbench/result_jsonl200_mineru/structure_result.json
   --tag baseline-20260913`（`meta.kind=offline-reprojection`；与它比 Δ 量的是"换量尺的差"，
   工具会打印此警告，不是回归判据）。

**A② 表里两列 TEDS/公式相似度相同不是 bug**：我们的 `table_html` 是 MinerU HTML 原文搬运
（逐字相等），公式文本同源——这两项两侧必然同分；差异只在块切分（召回率、文本相似度）。

### 投影损耗实证：行内公式 `$` 定界符（2026-09-17，P0）

**现象**：A① 公式 Edit_dist 我们 0.1119 vs MinerU 0.0976（我们差 1.4pp），**同一批数据 A② 公式相似度
却两边完全同分**（67.21%）——两个口径结论相反。

**定位**（官方逐样本产物 `*_display_formula_result.json` 里带 gt/pred/norm_gt/norm_pred/edit）：
- 差距高度集中：38 个公式页里 **30 页与 MinerU 逐项相同**，总差 0.543 中 **0.457（84%）来自单页**
  `page-8f6792bd`（手写中文算式页）：GT `$$25\;+\;20=45$$`、MinerU md `再算 $20+7=27$ 。`、
  我们 md `再算   20+7=27 。` → 官方按公式取块时把中文上下文一起计入，edit 0.60。
- 上游核对：MinerU `content_list` **原文就带 `$`**，我们的 `content_json` span 类型也齐
  （`{'type':'equation_inline','content':'20+7=27'}`）→ **丢在 `extract_plain_text` 把 span 拍平那一步**。
- 全批规模：MinerU 原文 **2328 个 `$`**，我们 md **只剩 22 个**（行内公式 span 1152 个、73 篇受影响）。
- A② 为什么看不见：A② 口径"去空白/花括号后串比对"，恰好把这类差异抹平了——**两个口径要并列报**这条纪律的实证。

**修法**：`collect_from_spans` 拍平时保留 `equation_inline` 的 `$…$`（已带定界的不重复包）。

**效果**（200 页同 seed，噪声底 0 → Δ 即改动）：文本 Edit_dist **−2.42pp**、公式 Edit_dist **−1.49pp**、
公式 CDM **+0.74pp**、表格各项 Δ0；代价是阅读顺序 +0.17pp（1 页 artifact：列表项加 `$` 后官方解析器
块切分变了，内容一字未改）。

**顺带排除**（数据否掉，未按猜测改）：`^{\prime}` vs `'` 这类写法差异只值 0.0031（≈1.4pp 差距的 2%）；
另两页的差来自上游（MinerU 自己把公式截断、GT 6 个公式它只检出 3 个），投影层救不了。

**噪声底已实测 = 0（2026-09-17，方案 D5 落地）**：`--limit 50 --seed 42` 连跑两次，页集合相同
（`page_ids_hash=6ec62f69d356`），两次是**完全独立的解析**（50 个 doc_id 零交集、各自重新走
MinerU+PoPo+structure），结果 **16 项指标 Δ 全 0.00pp，50 个预测 md 逐字节相同**（sha256 全等）。
归档 `data/evals/parse_regression/20260917-13{56,09}-noise{1,2}/`，对比用
`--republish <run2> --baseline <run1>` 或看 run2 的 summary.md Δ 段。

含义与边界：
- **Δ≠0 = 真差异**（代码/数据改动带来的），不是抖动 → 解析侧改动可以直接用 A 层验收，不必凑大样本；
- 只证明**可复现**，不证明某个 0.3pp 的变化"有意义"——那是量级判断，不是噪声判断；
- 适用范围：本机链 + 当前网关的 MinerU/PoPo 版本；**上游模型或 POPO 配置变更后应重测一次**
  （确定性来自上游，不来自我们）。

**predict 阶段固定 5 阶段、不建索引**：`source_prep,convert,raw_parse,popo,structure`
（`fts`/`vectors` 不进评测链）。建索引会引入与本层无关的变量（embedding 后端、向量库状态），
且正是 B 层素材检查的验证对象，混进来会让两层的锅分不清。

## 口径定义

| 环节 | 规则 |
|---|---|
| 页 ↔ 文档 | `state.json` 的 page_id → doc_id；缺失时按 `source/` 文件名兜底 |
| 坐标 | GT `poly`（扁平列表）→ bbox，按 `page_info.width/height` 归一；我们的 `bbox` 本身就是 0–1 归一 |
| 类目映射 | GT 类目 → 我们的 `block_type`，见 `parse_struct/categories.py`；caption/footnote 按**父块指针**映射（我们是 paragraph 块 + `caption_block_uid`） |
| 匹配 | IoU ≥ 0.3，或预测块中心落在 GT 框内，或 GT 框被预测块覆盖 ≥ 60%（三条并集，应对两侧块粒度不一致） |
| caption 匹配 | 边距放宽到 6%（caption 贴在表/图外面，且我们多数情况下没有它的独立 bbox） |
| 文本比较 | 覆盖分组后两侧各自拼接，再算归一化编辑距离，分母取较长者（恒 0–1） |
| 表格 | 官方 TEDS，**HTML↔HTML 直比**（不过 markdown，vendor 见 `parse_struct/_vendor/omnidocbench/`） |
| 公式 | LaTeX 去风格化（去空白/花括号/`\left`/转义）后串比对，**非 CDM** |
| 阅读顺序 | 匹配块的 GT `order` vs 我们的 `block_seq`：相邻对顺序正确率 + Kendall tau |
| 分母 | GT 侧只进"我们有对应类目"的类目（`categories.py` 的 `UNMAPPED_GT` 排除）；我们侧排除 `UNMAPPED_OURS` |

**关键设计：覆盖分组**。两侧块粒度经常不一致（实测：GT 把公式数组按行标 7 个
`equation_isolated`，我们合成 1 个块）。逐块硬比会把"整段 vs 单行"算成全错（公式一度只有 0.07），
故把互相覆盖的 GT 块归为一组、两侧各自拼接后再比一次。

## 基线

### 现行基线（1000 页，2026-09-26，折账后扩样）

run `20260926-1305`（`page_ids_hash=b7661b3a53a1`，`baseline.json` 已指向它）。**先折账再扩样**：
同日上午先跑了 200 页折账（`20260926-1203`，同页集合 `fee2959a7a67`），把短行标题提升与续接
重归属折进基线并逐项核对判据，然后才扩到 1000 页——两步走保证每次 Δ 纯归因。

**折账 Δ（200 页，`20260926-1203` vs `20260918-1340`，判据全部命中）**：

| 指标 | 改前 | 改后 | Δ | 对应改动 |
|---|---|---|---|---|
| A② 块召回率 | 90.25% | 91.04% | +0.79pp | 短行标题（预期 +0.76pp） |
| A② 命中文本相似度 | 85.78% | 90.62% | +4.84pp | 续接重归属（预期 +4.85pp） |
| A② 全部文本相似度 | 76.87% | 82.03% | +5.16pp | 同上 |
| A① 文本 Edit_dist | 0.0407 | 0.0436 | +0.29pp | markdown 空行的已知代价（预期 +0.26pp） |
| A①/A② 表格 TEDS | — | — | 0 | 预期 0 |

**1000 页基线绝对值**（A② 结构层 / A① 官方口径）：

| A② | 值 | A① | 值 |
|---|---|---|---|
| 块召回率 | 89.73% | 文本 Edit_dist | 0.0418 |
| 预测块被解释率 | 87.10% | 表格 TEDS / 仅结构 | 89.87% / 92.36% |
| 块文本相似度（全部/命中） | 79.53% / 89.81% | 表格文字 Edit_dist | 0.0759 |
| 表格 TEDS(A②) | 90.85% | 公式 Edit_dist / CDM | 0.1064 / 96.71% |
| 公式相似度 | 60.14% | 阅读顺序 Edit_dist | 0.1386 |
| 相邻对 / tau | 96.83% / 90.95% | | |

**读数须知**：
- **1000 页集合 ⊉ 200 页集合**（交集 190/200，`random.sample` 不同 k 不嵌套）——与 200 页
  各基线的绝对值**不可直接互比**，公式相似度 −7pp、tau −1.9pp 主要是样本结构变化
  （1000 页里 newspaper/magazine 等复杂版式占比更高），不是回归；
- MinerU 版本 3.4.5(n=999) + **3.4.4(n=1)**（1 页主端点失败走 company 备端点兜底，版本混入如实记）；
- 耗时：predict 4.43h（15.96s/页）+ A②×2 ≈3.6min + A① 23min ≈ **4.9h 端到端**；
- A② 的逐类目/逐文档类型明细见归档 `struct_chain_report.md`（1000 页后小样本类目
  caption/code/list_group 的数字明显变稳）。

### 200 页基线（2026-09-18，DGX MinerU 修复后重钉；已被 20260926-1203 折账接替）

`20260918-1340-baseline-post-dgxfix`（`page_ids_hash=fee2959a7a67`，与前几批同页集合；
`baseline.json` 已指向它）。

**重钉的原因**：DGX 那台 MinerU 的 RTDetr 手补丁把 transformers **4.x** 的张量按 **5.x** 语义取轴
（`intermediate_reference_points[-1]` 应为 `[:, -1]`），于是**单页解析一直用的是第 0 层 decoder 的框**
（多页直接崩）。修好后重跑，解析输出变了 → **旧归档基线是"错轴"产出**。
DGX 侧根因/修法/回滚见 `D:\AI\DGX\DGX-SPark部署经验.md` §5.7。

Δ vs 上一批 `20260918-0927-p2-caption-geo-final`（**同代码、同 MinerU 3.4.5(n=200)、同页集合**，
差异只反映这次修复；区间内其他提交只动 chat，未碰解析/评测）：

| 指标 | 修复前 | 修复后 | Δ |
|---|---|---|---|
| A② 块召回率 | 88.73% | **90.25%** | +1.52pp |
| A② 预测块被解释率 | 90.94% | **91.50%** | +0.55pp |
| A② 块文本相似度（全部 / 命中项） | 75.18% / 85.50% | **76.87% / 85.78%** | +1.68 / +0.27pp |
| A② 阅读顺序 tau / 相邻对 | 92.59% / 97.19% | **92.88% / 97.31%** | +0.29 / +0.12pp |
| A① 文本 Edit_dist | 0.0482 | **0.0407** | −0.75pp |
| A① 公式 Edit_dist / CDM | 0.0975 / 95.85% | **0.0891 / 96.68%** | −0.84pp / +0.83pp |
| A① 阅读顺序 Edit_dist | 0.1361 | **0.1287** | −0.73pp |
| A① 表格 TEDS / 表格文字 Edit_dist | 91.58% / 0.0485 | 89.45% / 0.0753 | **−2.13pp / +2.68pp** |

**表格那 −2.13pp 集中在 3 张表，且性质混杂，不是整体变差**：73 张里 61 张持平、3 张变好、9 张变差，
跌幅几乎全由这 3 张贡献（逐表 TEDS）：

| 表 | 前 → 后 | 性质 |
|---|---|---|
| `notes_1ba14cb3…_60` | 0.990 → 0.439 | 行被**过分割**（5 行 17 格 → 9 行 27 格） |
| `notes_1ba14cb3…_74` | 0.994 → 0.426 | 新结果带 `rowspan`（"北方地区"跨两行，**结构上更贴近真实表**），GT 是扁平写法 → TEDS 反而扣分 |
| `page-dca64e05…png` | 0.787 → 0.176 | **真失败**：3 行 3850 格、`colspan="101"`（检测框吞了整页，表模型失控） |

三类要分开对待：只有第三类是真崩（可加一道"列数/格数荒谬即拒绝或回退"的闸），前两类要先定 GT 口径。
**均未修。**

**测量时必须知道的一件事**：旧归档（`20260917-*`、`20260918-0534/0700/0927`）都是**修复前**的解析
输出。它们的 Δ（同代码前后比）仍然有效，但**绝对值不可与本次及以后同尺比较**。

**本归档曾是 title 短行提升上线前口径**（2026-09-26 的 `20260926-1203` 折账跑已把短行标题与
续接重归属折进基线，Δ 三项判据全部命中，见上节；预期数字：A② 块召回 90.25%→91.01%、
title 召回 79.2%→85.7%，A① 仅文本 +0.26pp 空行代价——实测 +0.29pp，落在判据内）。

证据：`data/evals/parse_regression/20260918-1340-baseline-post-dgxfix/`（`publish.json` 的 `delta`、
`official/predictions_quick_match_table_per_table_TEDS.json`）。

### fresh 基线（200 页，2026-09-17，一键入口首次跑）

`scripts/run_parse_regression.py --limit 200 --seed 42`（v0.2.65、`page_ids_hash=fee2959a7a67`，
与既有基线同页集合），归档 `data/evals/parse_regression/20260917-0837/`（逐类目/逐文档类型的明细
见同目录 `struct_chain_report.md`）。

| 指标 | 我们全链 | MinerU 原生 content_list | 离线重投影基线（09-12 jsonl） |
|---|---|---|---|
| 块召回率 | 88.25% | 77.79% | 88.25% |
| 预测块被解释率 | 90.58% | 81.95% | 90.58% |
| 块文本相似度（命中项） | 85.44% | 83.84% | 85.45% |
| 块文本相似度（全部） | 74.68% | 63.08% | 74.69% |
| 表格 TEDS | **0.9176** | 0.9176 | 0.9172 |
| 公式相似度 | 67.21% | 67.21% | 67.26% |
| 阅读顺序（相邻对 / tau） | 97.35% / 0.9294 | 97.30% / 0.9272 | 97.35% / 0.9294 |

（MinerU 两列 TEDS/公式相同是已知事实：我们的 `table_html` 是 MinerU HTML 原文搬运、公式文本同源，
差异只在块切分。fresh 列与离线列逐项差 ≤0.06pp → 那两处修复不影响本批 200 页的可评指标，
且"重投影 vs fresh"在结构层同样同尺。）

### 题注指针（2026-09-18，P2 已修）

题注（caption）在我们这里不是独立块类型，而是靠父图/表的 `caption_block_uids` **指针**被 A②
识别为 `figure_caption` / `table_caption`（见 `evals_core/parse_struct/categories.py` 的
`CAPTION_KIND`）。原先指针**只**来自文本匹配，needles 取自 MinerU 的 `image_caption` /
`table_caption` 字段——MinerU 不给该字段就完全无兜底。P2 补了几何兜底
`geometric_caption_uid`：同页、候选是文本类块、水平重叠 ≥ 候选宽度 50%、垂直间距 ≤ 4.5% 页高、
候选高度 ≤ 6% 页高，图题先看下方 / 表题先看上方，只取最近一块
（间距与高度阈值取自 GT 实测：caption 高度中位 1.7% 页高、p90 5.5%）。

判据预先定好（跑之前写的）：**caption 召回明显上升 → 保留；`text_block` 召回不许掉；其余不应动**。

| A② 指标（200 页同页集合） | before（无几何兜底） | after | Δ |
|---|---|---|---|
| figure_caption 召回 | 54.67% | **62.67%** | +8.00pp |
| table_caption 召回 | 58.49% | **79.25%** | +20.75pp |
| text_block 召回 | 94.86% | 94.86% | 0 |
| 块召回率 | 88.25% | **88.73%** | +0.48pp |
| 预测块被解释率 | 90.58% | **90.94%** | +0.36pp |
| 块文本相似度（全部） | 74.81% | **75.19%** | +0.37pp |
| 表格 TEDS / 公式相似度 | 91.76% / 67.21% | 同 | 0 |
| 阅读顺序 tau | 92.94% | 92.59% | −0.35pp |

- 判据通过：caption 两类大涨、`text_block` 未动、TEDS/公式未动。**tau −0.35pp 不是排序退化**——
  我们块的 `block_seq` 一个都没变，变的只是"被匹配上的集合"变大；用长度门槛砍掉长候选后 tau 回到
  92.95%，说明这 0.35pp 由极少数元素决定、随门槛离散跳变，不构成质量信号。
- **精度必须如实记**：新增挂载 58 处，对 GT 逐项核对 → 落在 GT 题注框 24.1%、落在 GT
  **text_block** 框 41.4%、GT 里两处都对不上 34.5%。即**约四成新指针指向 GT 标的正文**
  （报版"图在上、正文在下"）——这是几何判题注的天花板，长度门槛只减量、不提纯（见下表）。
- **产品影响面小**：`caption_block_uids` 的**唯一**消费方是 docs-ui 预览联动
  （`useWorkspaceLinkage.ts` 的 `captionRefs` 高亮）；canonical / FTS / 向量一律读 `caption`
  **字段**（`canonical_builder.py:487`），markdown 投影的表格分支同样只读 `caption` 字段。
  所以错挂不会污染检索文本，只在预览里多一块高亮。
- 长度门槛取舍（`_MEDIA_CAPTION_MAX_CHARS`，默认 0=不限）：门槛提高会同时砍掉对的和错的，
  **精确率基本不动**（22.5%~26.5%），代价是召回，故默认不限。

| 长度门槛 | 挂载数 | 落在 GT 题注 | 落在 GT 正文 | 图题注召回 | 表题注召回 | tau |
|---|---|---|---|---|---|---|
| 不限 | 58 | 24.1% | 41.4% | 62.67% | 79.25% | 92.59% |
| ≤100 字 | 49 | 24.5% | 36.7% | 60.00% | 77.36% | 92.59% |
| ≤80 字 | 43 | 23.3% | 32.6% | 60.00% | 77.36% | 92.59% |
| ≤60 字 | 40 | 22.5% | 32.5% | 60.00% | 75.47% | 92.95% |
| ≤40 字 | 34 | 26.5% | 26.5% | 60.00% | 73.58% | 92.95% |

证据：`data/evals/parse_regression/20260918-0534-p2-caption-geo/ab_struct_before.json`
与 `ab_struct_after.json`（官方 A② 评测器产物）。

**全链复算（2026-09-18，归档 `20260918-0927-p2-caption-geo-final`）**：200 页全链跑一遍，
Δ vs `20260917-1452-p0-dollar-200` 与上面的结构层 A/B 逐项一致（块召回 +0.48、被解释率 +0.36、
块文本相似度 +0.38、相邻对 −0.16、tau −0.35、公式相似度 +0.03、TEDS 0）。
**A① 侧 Δ 全部落到个别页的重解析抖动上，与 P2 无关**（逐页比对：公式只 1 页有差异，
+0.0202 摊到 38 页正好等于汇总的 +0.05pp；文本 4 页有差异且相互抵消；
表格与阅读顺序精确 Δ0）。这与"markdown 投影不解引用指针"的代码级结论一致。

（同目录 `20260918-0534-p2-caption-geo` 是全链跑在**空转**代码上的那次，除证明 Δ0 外无参考价值；
`20260918-0700-p2-caption-geo` 是它的重跑，predict 阶段撞上 MinerU 端点故障丢了 17 页
（主端点 `IncompleteRead` + 备端点 DNS 失败），已补齐后由上面那次 `--skip-predict` 复用归档。）

**A① 不受本项影响（可证）**：A① 读的是 markdown 投影，`_render_node` 的 image/table 分支只读
`plain_text` / `caption` **字段**，从不解引用 `caption_block_uid(s)`——指针变化不可能改变 markdown 字节。

**踩坑记录：一次"精确 Δ0 的空转"**。P2 首版把几何读取写成 `row["bbox"]`，而结构行里只有
`bbox_abs_x1..y2` + `page_width/page_height`（没有任何 `bbox` 键）→ 函数在入口就返回空串，
200 页全链 A/B **每一项都精确 Δ0**（不是"接近 0"）。单元测试却全绿，因为夹具是我自己臆想的
`bbox` 形状。两条教训：① **精确 Δ0 是"改动没生效"的信号**，不是"改动无害"；② 夹具必须用真实
行形状——`tests/unit/test_unit_media_caption_geometry.py` 末尾的
`TestGeometryActuallyFiresEndToEnd` 走真实入口 `build_structured_from_rawfiles` 断言兜底必须产出
指针，就是为这类"字段名漂移"补的闸。

**顺带确认的提速办法**：评测语料库文档目录留有 `mineru_raw/`，结构层可独立重算
（`build_structured_index_for_doc`，200 篇 ≈10s），所以 A② 的 A/B 不必重跑 MinerU——50 分钟降到
1 分钟；A① 仍必须走全链（它吃 markdown）。

### 短行标题提升（2026-09-18，title 召回 79.2%→85.7%）

**诊断先行**。基线 510 个 GT 标题里 106 个没匹配上（召回 79.2%）。逐条查这 106 个的落点：

| 落点 / 去向 | 数量 | 说明 |
|---|---|---|
| 位置上我们放的是 `paragraph` | **93** | 其中文本**本来就对**的 70 个（54 逐字相同 + 16 相似度 ≥0.8） |
| 落在 `image` / `page_header` 上 | 9 | 版面重叠，非本项可解 |
| 页面上根本没有这段文本 | 34 | **MinerU 真丢**，不是类型判错 |

所以杠杆在"类型判错"这一档：MinerU 把"独立单行短文本"输出成 `paragraph`，而 GT 标成 `title`。

**先否证了三条更省事的路**：

- **PoPo 没有额外信号**：`parsed/popo/enriched_blocks.json` 的 `type` 完全镜像 `source_label`——
  200 篇里 PoPo 把 **0 个**非 title 块改标为 title。指望 PoPo 补标题类型是死路（有数据）。
- **`middle.json` 的行数信号是废的**：hybrid/OCR 路径下每个 `para_blocks` 的 `lines` 都只有 1 条
  （整段算一行），行数不构成判据；`spans` 也没有 `size`（字号）字段，字号判据用不了。
- **文本形态规则是噪声源**（实测精确率，200 页）：

| 子规则 | 提升块数 | 真落在 GT 标题上 | 精确率 |
|---|---|---|---|
| 阿拉伯编号 `1.1` | 141 | 45 | 31.9% |
| 结尾冒号 | 25 | 8 | 32.0% |
| 英文短行 | 149 | 30 | 20.1% |
| 【】括号开头 | 33 | 6 | 18.2% |
| 中文序号 `一、` | 2 | 2 | 100%（样本仅 2 例，不可用） |
| **短行 `h≤1.5% 页高 且 ≤24 字`** | 115 | 70 | **60.9%** |

把这批形态规则合起来用（块召回 **−2.54pp**）比不用差得多——**不要把它们加回来**。
唯一净收益为正的判据是"短行"，它同时是排除项之外唯一有区分度的几何量。

**最终判据**（`solo_engine.is_short_standalone_heading`）：`paragraph` 且高度 ≤1.5% 页高 且 ≤24 字，
并排除 署名（本报记者/通讯员/摄/BY/Staff Writer）、项目符号项（▶ · - 等）、书后索引条目
（`market share, 248, 260`）、报头日期行、页面联系方式、句中标点（说明是被切短的句子）、
破折号引导与转版标记（`——`、`上接/下转`）。

**A/B（真实代码路径，两侧同码同参）**：把 200 篇的 `mineru_raw/` 拷到临时库，用真实入口
`build_structured_from_rawfiles` 各重建一次——对照组 monkeypatch 掉判据（等价于改前），实验组原样。
对照组 A② 结果与归档基线**逐位相同**（块召回 0.9024802705749718、tau 0.9288306309479467），
证明这条重建路径忠实可比。

| A② 指标（200 页同页集合） | 对照（改前） | 实验（改后） | Δ |
|---|---|---|---|
| title 命中 | 404 / 510 | **437 / 510** | **+33**（召回 79.2%→85.7%） |
| text_block 命中 | 1873 / 1946 | 1868 / 1946 | −5 |
| 块召回率 | 90.248% | **91.009%** | **+0.761pp** |
| 总命中 | 3202 | 3229 | +27 |
| 阅读顺序 tau | 92.883% | 92.878% | −0.005pp（块序未变，非排序退化） |

**A① 官方 markdown 口径：七项指标两侧逐位相同**（文本 0.0759 / 公式 0.0891 + CDM 0.9668 /
表格 TEDS 0.8945 + 仅结构 0.9137 + 文字 0.0753 / 阅读顺序 0.1301）。
**这不是"没生效"**——markdown 确实变了 23 个文件（`投资评级说明：` → `# 投资评级说明：`），
说明官方评测器会把 `#` 标记归一化掉：本项只动结构层，不动交付面。

**精度必须如实记**：最终 62 个提升块里，真落在 GT 标题上的约六成；剩下的是**署名/名单/地址**
一类（`郭东亮 王玉玲`、`Guardian staff`、`无锡：江苏省无锡市金融一街8号国联金融大厦12楼`）。
这类**无法用规则再分**：署名"郭东亮 王玉玲"与真栏目名"行业 经纬"在文本形态上完全同构
（都是 2–4 汉字 + 空格 + 2–4 汉字），继续收紧会连增益一起切掉。这是本判据的天花板。
好消息是测试集里 33/37 个新增命中来自**报纸版面的栏目名与文章标题**（`美丽乡村`、`区域经济`、
`法治视角 FaZhiShiJiao`、整条新闻标题），是真实改善而非刷分。

**层级语义**：提升发生在主循环里、改的是 `row` 自身（不只是局部变量——后续 caption 收集等步骤
还会读 `row["block_type"]`，只改局部变量会让同一行在不同步骤里类型不一致）。层级上：
正文页提升的标题取 `level = 当前最深标题 + 1`；**必须给具体 level**——留 `None` 的话
`canonical_builder.infer_title_level` 会按默认 `1` 处理，把它当顶级标题、把 `section_path` 冲散
（评测语料全是单页文档，整页判 `cover`/`front_matter`，走的是 `front_matter_flat` 分支，验证不到这条，
故由单测 `test_promoted_title_gets_level_not_none_in_body` 钉住）。

单测闸：`tests/unit/test_unit_short_line_title.py`（20 例，含"走真实入口"的端到端闸与各条排除项的反例）。

### 续接文本重归属（2026-09-19，块文本相似度 85.78%→90.64%）

**先把"文本保真"拆开算账**。命中组的文本误差质量合计 390.2，三类性质完全不同：

| 误差来源 | 组数 | 占误差质量 | 性质 |
|---|---|---|---|
| **空文本** | 100 | **25.6%** | 单列（见下） |
| 公式串表示约定 | 186 | 15.0% | 只动指标不动质量（官方 CDM 96.68% 说明公式本身是好的） |
| 其余 OCR/格式差异 | 2457 | 59.4% | 弥散，组均仅 0.094；39.4% 已逐字相同、25.6% 在 0.95 以上（多为格式差异）——要更强的识别模型，补丁修不动 |

**"空文本"这一列的真相不是漏文本，而是错归属。** 200 篇产物里有 121 个 `paragraph` 的
`plain_text` 为空；查成因：`content_list_v2` 空、`middle.json` 的 `para_blocks` **也空**，
但同一 bbox 在 `preproc_blocks`（预处理阶段）**有完整文本**——112 例可找回，合计 18,328 字符。
再往下查才发现关键：**112 例里 111 例的文本已经存在于别的块中**。即 MinerU 的段落装配把
续接段落并进了前一块的文本，却在 content_list_v2 里留下一个 **bbox 正确、content 为空**的空壳。
实测承载块 **105/105 都是同页紧邻的前一个 `paragraph`**，且被并文本是它的**结尾后缀**
（109 例可干净切分）。

不修的后果有两个：① 承载块的 bbox 只覆盖它自己那块版面，文本里却混着相邻区域的内容——
检索命中后引用高亮落在错区域，chunk 边界也不对；② 空壳与 GT 对齐时文本相似度恒为 0。

**修法**：从承载块尾部摘掉这段文本、写回空块——两边都不重复，且 bbox 与文本重新一致
（`_reattach_merged_continuation_text`，在跨页续接合并之后跑）。文本不在结尾（7 例）、
前面没有可承接的 paragraph（4 例）、文本过短（1 例）一律不动，宁可保留现状也不制造重复文本。

**A/B（真实代码路径，对照=把规则关掉）**——对照组逐位复现了"短行标题提升"那次的实验组
（块召回 91.009% / title 437 / text 1868），可作交叉验证：

| A② 指标（200 页同页集合） | 对照 | 实验 | Δ |
|---|---|---|---|
| **块文本相似度（命中项）** | 85.79% | **90.64%** | **+4.85pp** |
| **块文本相似度（全部）** | 77.64% | **82.05%** | **+4.40pp** |
| 其中 `text_block` 类目 | 80.23% | **87.97%** | **+7.74pp** |
| 块召回率 | 91.009% | 91.037% | +0.028pp（命中 +1） |
| 阅读顺序 tau | — | — | 不变（块序未动） |

比预估的 +3.3pp 更高，因为**承载块也受益**（它的文本不再混着别的区域的内容），两块同时改善。
小幅反向：`figure_footnote` −2.87pp、`figure_caption` −0.67pp（组数只有 9 / 47，属分组拼文本的旁效）。

**A① 官方 markdown 口径：文本 Edit_dist 0.0759 → 0.0785（+0.0026 变差），其余六项不变**。
机理已核实：切分在 markdown 里**插入了一个空行**（32 个文件有差异），而官方口径按字符流比对，
多一个换行就算差异。这是"结构层正确、交付面轻微代价"的取舍——RAG 吃的是结构层，故净收益为正；
若要两边都拿，可在 markdown 投影里把续接对渲染成不带空行的同段（未做，记为后续可选项）。

单测闸：`tests/unit/test_unit_continuation_text_reattach.py`（18 例，含走真实入口
`build_structured_from_rawfiles` 的端到端闸与"文本只许出现一次"的反例；已验证把规则关掉后
端到端用例会红）。

**⚠ 上面"承载块 105/105 都是同页"是语料假象（2026-09-20 更正）**：OmniDocBench 语料
**1350 篇全是单页文档**（每篇 = 原 PDF 切出的一页，`docMeta.pageCount` 全为 1），
结构上不可能出现跨页续接。换到真实多页文档上量，同页只是少数形态——见下节。

### 跨页续接重归属（2026-09-20，生产库实测 +140 处）

**动机来自评测盲区**：单页语料让"跨页"这一整类现象在 A② 里**恒为 0 例**，
首版只做同页也能拿到 +4.85pp；但那不是 MinerU 的性质，是语料的性质。
拿生产库 `lib-b07ed174`（117 篇真实多页论文/报告）量空 paragraph 的去向：

| 620 个空 paragraph | 例数 | 占比 |
|---|---|---|
| 同页规则已覆盖 | 79 | 12.7% |
| ├ 文本落在**上一页末段**（本次可修） | **167** | 26.9% |
| ├ 文本在同页但中间隔图/表（未做） | 18 | 2.9% |
| ├ 文本在两页以前（疑模板套话巧合，不做） | 11 | 1.8% |
| └ 前序所有块里都找不到该文本 | 344 | 55.5% |

**修法**：同页找不到承载块时，退一步取**上一页最后一段正文**。三道守卫都由数据定：

| 守卫 | 167 例上的实测 | 挡掉什么 |
|---|---|---|
| 上一页末文本断在句中（`_page_last_text_ends_cut` 读 middle.json preproc） | 167/167 为真 | 与本页 bbox 无关的独立证据，防后缀巧合 |
| 本页上方没有任何正文段落 | 167/167 为真 | 真·页首；页中部的空块不认跨页续接 |
| 上一页承载块之后只剩页眉/页码/页脚（不越过媒体块） | 扫描口径 | 越过图表去凑后缀的，实测多是模板句巧合 |

**A/B（真实代码路径，对照=把跨页分支关掉，`_prev_page_flow_tail` 直接返回 None）**：

| 库 | 文档 | 重归属 off → on | 产物文本有变化的文档 | 错误 |
|---|---|---|---|---|
| `lib-b07ed174`（生产，英文论文/报告） | 117 | 79 → **219（+140）** | 67 | 0 |
| `lib-261558be`（生产，中文规范/工程） | 78 | 8 → 11（+3） | 3 | 0 |
| omnidocbench 评测子集（权威 state.json 映射） | 200 | 109 → 109 | **0（逐位相同）** | 0 |

评测子集**零变化**是预期的，也是可验证的最强形式：本次改动不可能污染 A①/A② 的既有数字。
生产侧抽样核对切分正确性（承载块尾部 + 空块拼起来正好还原原文）：

| 文档:块 | 承载块尾部（切后） | 新归属给空块的文本（开头） |
|---|---|---|
| `v1-04019f290d42:2:23` → `:3:3` | …the threshold leads to noticeable improvements, as expected. Specifically, S4 | achieved a minimum a-DCF of 0.1109, with an SV-EER of 7.75% … |
| `v1-0c4632d99c5d:6:6` → `:7:2` | …because its focus on multi-task training rather | than pretraining and because its multi-task results underperform its single-task method … |
| `v1-0c4632d99c5d:8:9` → `:9:3` | …consistent-within-task | kernel parameters. This visualization suggests that architecture search is a useful surrogate … |
| `doc-eef87de9:8:17` → `:9:2`（中文） | …多年日最高气温≥35℃ | 日数为18天，多年日最低气温≤5℃日数为9天。 |

单测闸扩到 28 例（新增 `CrossPageReattachTests` 8 例 + 跨页端到端 2 例）；
**已验证把跨页分支关掉后 3 个用例转红**（含"文本真的跨过页边界搬过去"的端到端例），不是空转。
复现用 A/B 脚本：`scripts/analyze_reattach_ab.py`（任意库，off/on 两臂对比重归属计数与产出的
(block_uid, plain_text) 指纹）。

### 存量回填的成本构成与「不动富化」决定（2026-09-20 试点实测）

服务器试点（`lawbench` 整库 60 篇 188s；`lib-b07ed174` 8 篇公式/图最密的 735s）实测：
**非 LLM 部分约 19s/篇**（规则 + 图描述 + fts + 向量），**LLM 富化约 3.0s/公式**。
全量 281 篇外推 ≈ 9~10 小时：公式 8,318 个 ≈ 7h（`lib-b07ed174` 4.3h + `default` 2.6h 占九成）、
标题仲裁 ≈ 1~2h、非 LLM ≈ 1h。

**决定：不改公式富化的批量策略（2026-09-20，用户拍板）**。理由有实据：`batch=3`
（`formula_semantics.py:271`）配「整批失败重试一次 + 二分拆组兜底」本就是为**整批 JSON
解析失败**留的余量——批越大越容易整批解析失败，回退路径反而让调用次数暴涨，故合并调用
未必更快。试点 85 公式恰好 29 次调用（85÷3），说明**一次重试/拆组都没触发**，耗时是纯成本
而非失败重烧。另需注意：canary 里 `llm_status: error: Expecting value` 出在**标题仲裁**
那条路，与公式富化不是同一条链路；顶层 `llm_status` 也只反映标题仲裁，公式状态看
`formula_semantics.llm_status`。表格语义**不烧 LLM**（试点中富化 6 张表、LLM 调用数为 0）。

### PoPo 推理静默失败与「非空校验」（2026-09-20）

**现象**：全库 1,639 篇 PoPo 产物里，模型判定几乎为零——`contd≥0` 只有 30、`table_merge≥0`
为 **0**、`level≥0` 只有 627，且集中在 6 篇（lib-7582b086×3 / default×2 / DredgeAI×1）；
我们重跑的 128 篇里 `popo_signal.injection.applied=0`、`title_level_review.popo_signals=0`。

**定性实验（本地，真实文档 `v1-01eb389690b6`）**：完整跑一遍 popo 阶段 → 模型**正常返回**
`contd` 3 对 / `level` 21 个 / `image` 9 个（47~54s）；把这份产物换上再跑 structure →
`injection.applied=3, rejected=0`、`merge.applied=3`，步骤显示"PoPo 信号注入 applied 3"。
**采纳链路是通的，之前不是"没采纳"而是"没有东西可采纳"。**

**根因（代码级）**：`popo/model_utils.popo_generate` 在所有端点都失败时只 `return ""`、不抛异常
（`model_utils.py:166`），子进程退出码仍为 0 → 阶段记 `done`、产物判定全 `-1`、无人察觉。
原始响应摘要统计（1,890 篇，按"是否真调用过"区分）：

| 任务 | 没问（无候选，合理） | **问了却回空** | 问了有回 |
|---|---|---|---|
| contd | 84% | **13%（245 篇）** | 3% |
| title | 81% | 13%（247） | 5% |
| image | 80% | 15%（276） | 5% |

注意"回空"**未必是失败**——没有续接对时模型回空是合法答案；真失败的唯一痕迹是
`POPO endpoint ... failed` 这行 print（探针脚本已落 `contd/title/image_chunk_*.json` 与 summary）。

**修法**：`popo_enhance._run_script` 改为返回子进程输出；推理步骤扫这行 → 命中即抛
`PopoEndpointUnavailableError`（popo 是 `STAGE_KIND_SOFT`，失败不阻塞后续解析），并把判定计数写进
阶段步骤详情（`判定 contd N / level N / image N`，前端阶段抽屉可见）。

**这个异常类型是必须的**：`parse_pipeline._is_transient_popo_failure` 只认
`TimeoutExpired`/`CalledProcessError`，裸 `RuntimeError` 会被判成永久失败 → 绕过
`POPO_INFERENCE_RETRIES` 直接回滚、白丢该篇判定。故在分类器里加一条类型判定
（`services/docs-core/tests/test_popo_gate.py::test_popo_endpoint_unavailable_goes_through_retry` 钉住）。

单测 10 例（`tests/unit/test_unit_popo_inference_guard.py`）+ 重试接线 1 例；**把
`_popo_endpoint_failures` 关掉后 3 例转红**、**去掉瞬时分类后重试用例转红**；真路径验证：
端点指向死地址 → `[failed] PoPo 4B 推理 端点失败 3 次`（此前是静默 done）。

**两个待查**：① 模型有 title 输出的 102 篇里，最后只有 6 篇的 `level` 落到产物（中间又丢一截）；
② PoPo 相对 solo 规则是否有**增量**——本次 1 篇里 solo 自判 3 处续接 + 2 处文本重归属、PoPo 判 3 对，
是否同一批未逐对核对。

### MinerU `effort` 旋钮调查：不是白拿的旋钮（2026-09-20）

`effort` 是 hybrid 引擎的**公开 API 参数**（`mineru/cli/api_request.py` 的 `effort` 字段，
`_validate_parse_effort` 只收 `medium|high`；`middle.json._effort` 会回显），我们一直是默认
`medium`。官方 CLI help 原文：medium「图/图表分析**关闭**」、high「更高精度 + **支持图/图表分析**」。

同页实测（MinerU API 直调，只改 effort）：

| 页面 | medium | high | 差异 |
|---|---|---|---|
| 纯文字页 | 18.79s，md 7321 字符 | 22.78s（×1.21） | md **逐字相同**（文字识别无变化） |
| 图表页（3 图 + 1 表） | 6.21s，`chart.content = ""` | 22.78s（**×3.67**） | `chart.content` 变成完整 markdown 数据表（+994 字符） |

**结论：不开**。三条理由都有据：

1. **对 A① 有害**：该页 GT 把 3 个图都标成 `figure`（`text: None`），high 多吐的近千字符
   GT 里不存在（官方文本口径按字符流比对）。
2. **对我们的检索当前无效**：数据落在 `content_list_v2` 的 `chart.content`，而我们的
   `extract_plain_text` 对 `chart` 只取 `chart_caption`/`chart_footnote`、**明确丢弃 content**
   （`solo_engine.py:126-129`）→ 开 high 后我们这条链一个字都不变。
3. **成本 ×3.7**（图表密集页）且影响所有解析（生产/nightly/回填），DGX 并发与显存预算需重算。

要吃这份收益是一个**独立立项**：改 `extract_plain_text` + 开 high + 处理与 GT 标注（图 vs 表）
和 `figure_describe` 阶段的重叠。**先验"数据能不能流到我们这条链"再谈调参**——这一步漏验会白跑
一轮 GPU 实验（本次差点踩到）。

### 测量盲区：官方 TEDS 跨时段不可复现（2026-09-19 发现）

同一份 production markdown、同一条评测命令：09-18 评出 `table TEDS=0.8945 / 仅结构 0.9137`，
09-19 重评得 `0.8921 / 0.9107`；而**文本（0.0407）、公式（0.0891 / CDM 0.9668）、阅读顺序
（0.1287）逐位复现**。同一场次内重跑则完全一致（同 md 连跑两次七项逐位相同）。

结论与约定：**A① 的 TEDS 只有"同场次 A/B"可比，跨时段/跨归档的绝对值不可直接比较**
（差 ≤0.003 的 TEDS 变化不能当信号）。本文两份改动的 A① 结论（title 提升的"七项零变化"、
本次重归属的"文本 +0.0026"）都是同场次对照得出的，成立。未查明机理（评测器/容器/负载均可能）。

### 历史基线（200 页，2026-09-12，离线重投影口径）

### 总览

| 指标 | 值 | 说明 |
|---|---|---|
| 块召回率 | **87.2%** | GT 待评块 3634 个命中 3170 |
| 预测块被解释率 | 90.4% | 我们 3852 个可评块中参与匹配 3484（低=多出块） |
| 块文本相似度（命中项） | **0.8479** | 只看匹配上的块＝识别质量，n=2666 |
| 块文本相似度（全部） | 0.7290 | 漏检块按 0 计入，n=3101 |
| 表格 TEDS | **0.9183** | HTML↔HTML 直比，n=74 |
| 公式相似度 | 0.4939 | LaTeX 去风格化串比（非 CDM），n=150 |
| 阅读顺序（相邻对 / tau） | **97.5% / 0.9321** | 193 页 |

### 按类目

| GT 类目 | GT 块数 | 召回率 | 文本相似度(命中项) | 表格 TEDS |
| --- | --- | --- | --- | --- |
| text_block | 2006 | 95.0% | 0.8392 | — |
| title | 517 | 77.4% | 0.9399 | — |
| header | 243 | 72.8% | 0.9250 | — |
| equation_isolated | 200 | 99.0% | 0.5006 | — |
| page_number | 145 | 89.7% | 0.9518 | — |
| figure | 139 | 92.1% | — | — |
| footer | 103 | 86.4% | 0.9489 | — |
| figure_caption | 75 | **10.7%** | 0.8636 | — |
| table | 74 | 100% | — | **0.9183** |
| table_caption | 53 | 58.5% | 0.8703 | — |
| table_footnote | 24 | 83.3% | 0.8653 | — |
| page_footnote | 17 | 35.3% | **0.0000** | — |
| figure_footnote | 17 | **11.8%** | 0.0805 | — |
| list_group | 13 | **0.0%** | — | — |
| code_txt | 8 | 25.0% | 0.0000 | — |

### 按文档类型

| data_source | 页数 | GT 块 | 召回率 | 文本相似度 | 表格 TEDS | 顺序相邻对 |
| --- | --- | --- | --- | --- | --- | --- |
| PPT2PDF | 37 | 211 | 0.777 | 0.6716 | 0.9429 | 0.983 |
| book | 36 | 517 | 0.863 | 0.7550 | 0.9974 | 0.966 |
| academic_literature | 23 | 384 | 0.935 | 0.7403 | 0.8808 | 0.994 |
| newspaper | 20 | 1150 | 0.888 | 0.7153 | 0.7879 | 0.976 |
| colorful_textbook | 19 | 274 | 0.821 | 0.6973 | 0.9475 | 0.965 |
| exam_paper | 19 | 378 | 0.913 | 0.7244 | 0.9780 | 0.990 |
| research_report | 19 | 215 | 0.884 | 0.8257 | 0.9258 | 0.953 |
| magazine | 18 | 273 | 0.813 | 0.7112 | — | 0.975 |
| note | 12 | 199 | 0.965 | 0.8701 | 0.9814 | 0.993 |
| historical_document | 1 | 33 | 0.182 | 0.1368 | — | 0.600 |

## 这套口径查出的问题（按优先级）

1. **caption 图注没落地（2026-09-18 P2 已修，13%→62.7% / 58.5%→79.3%）**：09-12 时
   `figure_caption` 召回仅 10.7%、`table_caption` 58.5%；加几何兜底后 62.67% / 79.25%
   （A/B 与精度见上节"题注指针"）。历史归因：caption 不是独立块，而是父节点的 `caption` 文本字段
   + 指针，指针**只**来自 MinerU 的 `image_caption` / `table_caption` 字段，不给就没有兜底。
   **剩余未修的**：约 34.5% 的 GT 题注仍捕不到（GT 那边没有对应标注文本可对），且新挂载约四成
   指向正文；要再上一个台阶需要把题注做成**独立块**（而不是父块指针），VLM 图描述属独立 stage
   `figure_describe`，**不在评测链的 5 个 stage 里**，故评测链完全没有图描述（生产有，落
   `figure_description`，canonical 会与 caption 拼接进可检索文本）。
2. **`page_footnote` 等 5 类块的文本被链路吃掉（已修，本次）**：`extract_plain_text` 缺
   `chart` / `page_footnote` / `page_aside_text` / `code` / `algorithm` 五个分支，落到末尾
   `return ""` → `plain_text` 为空 → `build_node_text` 无 content_json 兜底 → canonical chunk 为空
   → **FTS/向量索引里没有这段**；markdown 投影同样只读 plain_text，也不含。实测受影响：评测语料
   209 篇中 **54 块**重获文本（chart 22、旁注 20、参考脚注 6、代码 5、算法 1），合计约 7100 字符。
   修复后原有 `page_footnote` 的"召回 35.3% / 文本相似度 0.0000"这类假差会消失。
   **注意：存量解析产物与本文基线数字均为修复前口径，需重新解析才会变。**
2b. **上述修复的检索侧验证（2026-09-13，由本项目自测——OmniDocBench 不具备检索/FTS 能力）**：
   这 25 篇此前**从未建过索引**（评测用的 5 阶段链不含 `fts`/`vectors`）。用生产入口
   `build_sqlite_index_from_graph` + `rebuild_document_vectors` 重建后自测：
   - 目标文本进入 `canonical_chunks.text_clean`：抽样 8/8；
   - **全库不限定文档**的关键词检索（生产函数 `search_chunk_fts`，CJK bigram + BM25）：
     **12/12 进前 100，其中 10 篇第 1**；
   - **语义检索**（Qdrant 向量，生产 embedding 链）：**10/12 进前 10，其中 10 篇第 1**；
     两个非第 1 的案例是查询本身歧义（单字旁注"卷"）与通用片段（"(a) original data" 在别处重复），
     非检索失败——这两条内容在向量库中确认存在；
   - **因果反证**：把 chart/page_footnote/page_aside_text/code/algorithm 的 `plain_text` 置空后
     重建 canonical，探针字符串从 chunk 文本消失（4/4）——可检索性来自本次修复。
   - **本验证的边界**：① 自建探针，非基准；② 只证明"内容被两种检索召回"，**不衡量端到端检索质量**
     （hit@5、问答正确率需要带 gold 的问题集，OmniDocBench 提供不了，要用 nightly 那类体系）；
     ③ 探针查询串须用完整文本——实测截断到 30 字符会让一篇排第 1 的内容掉出前 10（假阴性）。
   复现脚本：`scripts/reindex_parse_docs.py`（重建 + 探针，`--reindex` 才写库）。

3. **`list_group` 完全未建模**（0/13）：GT 有列表容器概念，我们没有对应结构。
4. **公式串相似度 0.49**：主因不是识别错，而是**多行数组的表示约定不同**（GT 用 `{l}`，
   MinerU 用 `\begin{array}{l}`）——这条指标只适合作回归跟踪，不能当质量绝对值；要绝对值得用 CDM。
5. **表格 TEDS 0.9183 低于 book(0.9974) 的短板在 newspaper 0.7879 / academic_literature 0.8808**，
   与之前 markdown 口径的指向一致（复杂版式的表格）。
6. **title 类型漏检（2026-09-18 已修，召回 79.2%→85.7%）**：MinerU 把"独立单行短文本"输出成
   `paragraph`，GT 标成 `title`——106 个漏检里 93 个是这一档。加"短行"判据后 A② 块召回
   +0.761pp、A① 无变化（见上节"短行标题提升"）。**剩余未修的**：34 个漏检标题的文本
   MinerU 根本没提取出来（真丢），要再上一个台阶得动识别本身，不是类型判据。

## 盲区与维护约定

- **不是官方分数**：这是自定义口径，只做内部回归跟踪（同规则前后可比）。对外可比数字只能来自
  官方 markdown 口径或官方镜像。
- **阈值是约定**：IoU 0.3 / 覆盖 0.6 / caption 边距 6% 都会影响数字——重跑对比时必须用同一套阈值
  （脚本参数默认值即基线口径）。
- **chunk 层未覆盖**：本口径量到"块"，chunk 边界（`canonical_builder` 的块拼接）与 section_path
  正确性还没量；RAG 检索直接吃这两样，是下一步该补的。
- **TEDS 不得本地改写**：`_vendor/omnidocbench/table_metric.py` 与官方逐位一致是可比性前提，
  要改行为请改我们自己的输入归一（见该目录 SOURCE.md）。
- **A① 的阅读顺序含"口径弃权页"（2026-09-18 查明，P3 侦察）**：官方
  `get_order_paired`（`src/dataset/end2end_dataset.py:240`）里 `gt` 只收
  `gt_position != [""]` 的项，而 GT 项的 `gt_position` 取 `item['order'] or item['position'][0]`
  ——**`order == 0` 是 falsy**，于是每个有 order-0 标注的页，那一项被静默丢掉；再加上
  `read_order_gt = [x for x in read_order_gt if x]` 把 0 值也滤了。
  实测本批 200 页 `order_edit` 均值 0.1361，其中 **8 页恒为 1.000 满分**
  （`gt=[4]` 单个表、`pred=[]`：这些页里唯一幸存的 order 项是表，而表匹配项的
  `pred_position` 为空串，被 `matched` 过滤掉）——**对所有模型一视同仁，谁也拿不到分**。
  扣掉这 8 页后均值 0.0997。进一步拆：198 页里 116 页 edit=0、50 页"漏块主导但顺序正确"、
  9 页混合、**真乱序只有 23 页**（其中 newspaper 8、colorful_textbook 4）。
  结论：**P3（阅读顺序）该按"23 页真乱序"评估，别拿 0.1361 这个含恒 1.0 弃权页的数去对标参考模型的
  0.1168**（后者是全量榜分数，页集合本就不同）；我们全链的顺序严格继承 MinerU 的 `block_seq`
  （markdown 投影按 `(page_idx, block_seq)` 排），本身还比 MinerU 高 0.001pp。
