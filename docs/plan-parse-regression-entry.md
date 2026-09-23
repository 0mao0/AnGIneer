# 解析评测一键入口方案（A① 官方 markdown 口径 + A② ParseStruct 结构层口径）

2026-09-14。目标：**一条命令、本机跑、可选题量、结果可见** 地跑完 A①+A②，并把每次结果入档、与基线比 Δ。
本文是方案与评估，不是实现记录。

**结论先行**：零件全在（predict / A② / A① 三步都有现成脚本、本机都跑通过），新入口做的是**编排 + 归档 + Δ**，
不新建评测器。但评估后有 4 处前提与上一版设想不同，其中 1 处与"不上传生产"的硬约束直接相关、
1 处会让"首次入档基线"的读法出错——先修正这 4 条，方案才立得住。

---

## 一、前提修正（评估后与上一版设想的差异）

### 修正 1：「只在本机」覆盖"库与产物"，覆盖不了"推理"

| 环节 | 数据 | 去向 | 出本机？ |
|---|---|---|---|
| predict 页图 → 单页 PDF | OmniDocBench 页图 | 本机内存 | 否 |
| raw_parse（MinerU） | 页图 PDF | `MINERU_CONFIGS` → `https://angineer.cn/api/mineru`（生产网关 → GPU 机） | **是** |
| popo（LLM 增强） | 页文本 | `POPO_CONFIGS` → `https://angineer.cn/api/popo/v1` | **是** |
| structure 落盘 | jsonl / content.md | 本机 `data/knowledge_base/libraries/omnidocbench/` | 否 |
| A② 打分 | 本机 jsonl | 本机 | 否 |
| A① 打分 | 本机 markdown | 本机 Docker（18.1GB 镜像已在位） | 否 |

即：**"不上传生产环境"= 不写生产库、不落生产盘**（这一点能满足）；但**页图仍会经生产网关送到 GPU 做推理**。
本机 `.env` 里 MinerU/PoPo 只有 `dgx`（= angineer.cn）和 `company`（第三方）两个后端，没有本机后端。

要做到"数据也不出本机"，只有两条路，都不便宜：

| 路径 | 代价 |
|---|---|
| 本机自部署 MinerU | 本机无 GPU，CPU 推理约分钟级/页，200 页不可行 |
| 配内网直连 DGX 的地址 | 绕过生产网关，但仍出本机，且改 `.env` 会影响本机其它调试 |

→ 这是**决策点 D1**，需你定口径；我按"不写生产库即可"作为当前默认理解往下写。

### 修正 2：现有 A1/A2 基线不是"一次解析"的产物（实测）

| 对照 | 结果 |
|---|---|
| `D:/AI/omnidocbench_dl/full_html_preds/*.md` vs 库内 `parsed/content.md`（去 build_id 头） | **146 页逐字节相同，54 页不同** |
| 那 54 页差在哪 | **全部是表格：库里是管道表，预测里是 HTML 表**；非表部分逐字相同 |
| 时间证据 | 200 个 md 写入时间跨度 **0.33 秒**（真解析 200 页需 52 分钟，17.5 s/页） |

所以 A1 基线（文本 0.0725 / TEDS 0.9155 / 表格文字 0.0488）量的是
**"把 09-12 那批 jsonl 的 markdown 换个表格写法"** 的分数，不是一次 fresh 解析。
A2 基线（块召回 88.2% / 文本 0.7469 等）读的也是同一批 09-12 jsonl，只是打分器后来补过 caption/footnote 候选。

→ 含义：**新入口第一次跑出的数字一定会变**（真正的 fresh parse：重跑 MinerU/PoPo、用当前代码投影）。
这不是回归，是换了量尺的起点，首次入档应写成"新基线"而不是与旧数打 Δ。

### 修正 3：最容易假绿的一环是「页集合一致」

实测：`--limit 200 --seed 42` 的抽样**可嵌套**——`limit=50` 的页集合 ⊂ `limit=200` 的页集合
（同一 seed 下 `random.Random(seed).sample(images, N)` 对同一有序列表取样）。这是"可选题量仍能与基线比"的前提。

但三条路径对缺失页的容错不同：predict 失败页只进 `state.json` 的 failed；A② 跳过无产物页；A① 的 GT 过滤只看有 `.md` 的页。
**页集合不同的两次分不可比**（少评几页就会虚高或虚低）。

→ 归档必须记 `page_ids`，Δ 前先校验集合；集合不同则拒绝出 Δ，或按交集重算并显式标注"非官方重跑口径"。

### 修正 4：本地 docs-api 当前 degraded，predict 阶段必须钉死 5 阶段

本地 `http://localhost:8790/health` 实测（2026-09-14 04:08 启动，pid 70412）：

```
status: degraded — embedding 维度不匹配: 端点返回 256，向量库期望 1024
```

当前评测链是 `source_prep,convert,raw_parse,popo,structure`（不含 `fts`/`vectors`），**不受影响**；
但一旦顺手把建索引加进来就会失败——而 B 层素材检查恰恰依赖这两层。

→ 入口固定 5 阶段，**不提供**"顺手建索引"开关。

---

## 二、现有零件盘点（新入口要包的就是这些）

| 步骤 | 现成入口 | 依赖 | 200 页耗时 | 产物 |
|---|---|---|---|---|
| ① predict | `scripts/run_omnidocbench_eval.py predict [--in-process]` | 本机可导入的 docs_core + 网关 MinerU/PoPo | **52 分钟**（17.5 s/页） | `<preds>/<page_id>.md` + `state.json`；jsonl 落本机库 |
| ② A② 我们全链 | `scripts/eval_parse_struct.py`（默认 `--pred-source chain`） | 本机 jsonl，**不重解析、不用镜像、不用 GPU** | ~2 分钟 | `structure_result.json` + `structure_report.md` |
| ②' A② MinerU 原生 | 同上加 `--pred-source mineru` | 同篇 `mineru_raw/`（解析时已落，无额外成本） | ~2 分钟 | 同上 |
| ③ A① 官方 markdown | `scripts/run_omnidocbench_eval.py eval` | Docker + 18.1GB 镜像（本机已在位） | 10–20 分钟 | `*_metric_result.json` 等一整套 |
| 参考模型 / MinerU 的 md | **不需要跑** | 镜像自带（199/200 页） / 从 `origin.zip` 提取 | 0 | 固定不动 |

**新增的只有三件事**：编排、归档、Δ。评测口径本身一行不改。

---

## 三、流程

```
                 ┌──────────────── 本机（开发机）────────────────┐
  python scripts/run_parse_regression.py --limit 200 --seed 42
                 │
     ①抽样       │  _select_pages(data_dir, limit, seed) ──► 200 个 page_id
                 │        （与旧基线同 seed 时可嵌套比对）
                 │
     ②predict    │  页图 →PDF→ 本机 docs_core 解析链（5 阶段）
                 │   ├─ 落盘：库内 doc_blocks_graph.jsonl + content.md
                 │   └─ 出网：MinerU/PoPo → angineer.cn 网关 → GPU（仅推理，见修正 1）
                 │
   ┌─────────────┴────────────┬───────────────────────────┐
   │ ③ A② 我们全链            │ ③' A② MinerU 原生         │ ④ A① 官方 markdown
   │   读库内 jsonl           │   读同篇 mineru_raw/       │   content.md → 官方镜像
   │   ~2 min                 │   ~2 min                   │   10–20 min（可选跳过）
   └─────────────┬────────────┴──────────────┬────────────┘
                 │                           │
     ⑤归档        ▼                           ▼
        data/evals/parse_regression/<ts>/{meta.json, struct_chain.json,
              struct_mineru.json, official/*, summary.md, latest.json}
                 │
     ⑥Δ          │  与 baseline（或最近一次同 limit 的 run）逐指标比
                 │  页集合不一致 → 不出 Δ（只打印集合差异）
                 ▼
        控制台：本次 A① 三方表 / A② 两方表 / vs 基线 Δ 表
```

---

## 四、一键入口设计（草案）

### 4.1 CLI

```bash
# 默认：全跑（predict + A②×2 + A①），结果入档并与基线比 Δ
python scripts/run_parse_regression.py --limit 200 --seed 42

# 常用变体
python scripts/run_parse_regression.py --limit 50 --seed 42            # 小批快跑（子集，~15min）
python scripts/run_parse_regression.py --skip-predict                  # 复用现有预测，只重打分
python scripts/run_parse_regression.py --skip-official                 # 不跑 18GB 镜像（A① 空着）
python scripts/run_parse_regression.py --tag html-table-fix            # 给这次 run 命名
python scripts/run_parse_regression.py --baseline latest               # Δ 对比对象（默认）
```

| 参数 | 默认 | 说明 |
|---|---|---|
| `--limit` / `--seed` | `200` / `42` | 与既有基线同约定；抽样可嵌套 |
| `--predict-mode` | `in-process` | `in-process` 直接驱动 docs_core；`http` 走本地 docs-api（决策点 D2） |
| `--docs-api` | `http://localhost:8790` | 仅 `--predict-mode http` 用 |
| `--skip-predict` / `--skip-official` | 否 | 显式跳过；**跳过必须打印理由**，不静默 |
| `--out-root` | `data/evals/parse_regression` | 归档根（本机，gitignored） |
| `--baseline` | `latest` | `latest` \| `<ts>` \| 目录路径 \| `none` |

### 4.2 每一步的产物与失败语义

| 步骤 | 产物 | 失败时 |
|---|---|---|
| predict | `<preds>/<page_id>.md`、`state.json`（断点续跑） | 单页失败只记 failed；**总失败数写进 meta** |
| A②×2 | `struct_chain.json`、`struct_mineru.json` | 整步失败 → 该步留 `{"error": ...}`，其余步骤继续 |
| A① | `official/`（官方全套产物） | 镜像缺失/Docker 未起 → 跳过并写明原因 |
| 归档 | `meta.json`、`summary.md`、`latest.json`（指针） | — |
| Δ | 控制台 + `summary.md` 内 Δ 段 | 页集合不一致 → 不出 Δ |

### 4.3 归档布局

```
data/evals/parse_regression/
├─ baseline -> 20260914-0930-fresh-parse/      # 指针（符号链接或 latest.json）
├─ latest.json                                  # {ts, dir, limit, seed, page_ids_hash}
└─ 20260914-0930-fresh-parse/
   ├─ meta.json         # 见下表
   ├─ struct_chain.json # A② 我们全链（= eval_parse_struct 的 structure_result.json）
   ├─ struct_mineru.json
   ├─ official/         # A① 官方全套产物原样拷入（~2MB）
   └─ summary.md        # 人读：三方表 + 两方表 + Δ 表 + 本次环境
```

`meta.json` 字段（**页集合与版本是 Δ 的前提，不能省**）：

| 字段 | 内容 |
|---|---|
| `ts` / `tag` / `args` | 时间戳、命名、limit/seed/predict 模式 |
| `page_ids` + `page_ids_hash` | 本次实际参与评分的页 id 全集（Δ 校验用） |
| `git` | `git describe --tags --always --dirty` + branch + commit（**`-dirty` 必留**） |
| `runtime` | python 版本、docs-api pid/启动时间、Docker 镜像 digest（A① 用） |
| `mineru_version` | 汇总各篇 `mineru_raw/middle.json` 的 `_version_name`（版式一致性核查，沿用三方对比文档的做法） |
| `stages` | 固定 `source_prep,convert,raw_parse,popo,structure`（写入以示口径） |
| `timing` | 各步耗时 + predict 成功/失败/跳过计数 |
| `sources` | 参考模型 md 目录与版本、MinerU md 来源（`origin.zip` 提取） |

### 4.4 Δ 规则

1. **默认只与同 `limit`+`seed` 的基线比**（页集合天然相等）；
2. 集合不等 → 打印"本次 N 页 / 基线 M 页 / 交集 K"，**不出 Δ**；
3. `--limit` 更小时（子集），可选"按交集重算基线"——用官方产物里的**每页/每表数值取算术平均**
   （`*_text_block_per_page_edit.json`、`*_table_per_page_edit.json`、`*_table_per_table_TEDS.json`、
   `*_display_formula_per_page_edit.json`、`*_reading_order_per_page_edit.json` 都有），
   标注"**非官方重跑口径**"，且**首次使用前须用 `--limit 50` 与 `limit 200` 基线取交集实跑校验一次**；
4. Δ **不影响退出码**（这是评测入口，不是 CI 门禁）。

---

## 五、要你定的点（我不替你定）

| # | 问题 | 选项 | 影响 |
|---|---|---|---|
| D1 | 推理经生产网关出去，可接受吗？ | A. 可（"不上传"= 不写生产库）<br>B. 不可，需另配后端 | 决定方案是否成立；见修正 1 |
| D2 | predict 走哪条路？ | A. `in-process`（文档现行用法：无凭据、不吃长驻进程版本）<br>B. `http://localhost:8790`（与生产同一条路由） | A 与常驻 docs-api 共写同一 sqlite（锁风险）；B 改了代码必须重启 docs-api 才生效 |
| D3 | A① 默认跑吗？ | A. 默认跑（每次 +10–20 分钟）<br>B. 默认跳过，要 `--official` 才跑 | 影响单次成本 1.2h vs 1h |
| D4 | Δ 的默认基线取谁？ | A. 归档里的 `baseline` 指针<br>B. 最近一次 run | 决定"是否接受首次跑就被当基线" |
| D5 | 是否首次跑两次建噪声底？ | A. 是（200 页×2 ≈ 2h，或 50 页×2 ≈ 30min）<br>B. 否，先看趋势 | PoPo 是 LLM 步骤（`use_llm=False` 并不关它），同版本重跑可能有差；无噪声底则 Δ 只能当趋势 |
| D6 | 归档只留本机？（我的建议：是） | A. 只留本机，**数字**写进 `docs/`<br>B. 归档进版本控制 | 依据 3a3a5f2 的教训（部署 `reset --hard` 曾抹掉 pin 进 git 的基线，nightly 跑出假绿灯）；且 `.gitignore` 已排除 `data/evals/*` |

---

## 六、风险

| # | 风险 | 证据 | 影响 | 缓解 |
|---|---|---|---|---|
| R1 | 推理出网（修正 1） | `.env` 两条 `*_CONFIGS` 均指向外网 | 硬约束满足度存疑 | D1 定口径 |
| R2 | 与常驻本地 docs-api 共写同一 sqlite | pid 70412 在跑 | 数据库锁 / 任务互相干扰 | 跑前停 docs-api，或改 HTTP 模式 |
| R3 | 代码改了但 docs-api 没重启（HTTP 模式） | 长驻进程不热载 | 量到的是旧代码 | 启动前比对该进程启动时间与最新 commit 时间，早于则告警 |
| R4 | LLM 非确定性、噪声底未知（D5） | PoPo 是 LLM 步骤 | Δ 无法判显著 | 首次跑两次，或 50 页×2 建底 |
| R5 | 官方产物目录残留导致读到旧分 | `cmd_eval` 用 `glob('*_metric_result.json')[0]` | 假绿 | 每次 run 用全新目录（本方案保证） |
| R6 | 本地 docs-api degraded（修正 4） | `/health` 实测 256 vs 1024 | 一旦纳入 fts/vectors 就失败 | 钉死 5 阶段 |
| R7 | 200 页单次 1.2–1.5 小时，迭代慢 | 52min + 20min + 4min | 反馈慢 | `--limit 50` 子集（~15min）+ 交集 Δ |
| R8 | 新脚本被 gitignore 吃掉 | `scripts/*` + `**/scripts/*` 已忽略 | 提交后脚本丢失 | 加 `!scripts/run_parse_regression.py` 放行 |

---

## 七、实施步骤

| 步 | 内容 | 产物 |
|---|---|---|
| 0 | 入档现有基线：把 `full_html_result/*`（A①）与 `result_jsonl200{,_mineru}/`（A②）拷进 `data/evals/parse_regression/baseline-20260913/`，`meta.json` 里如实标注"**离线重投影 / 非同一次解析**" | 基线目录 |
| 1 | `services/evals-core/src/evals_core/parse_regression.py`：编排 + meta + Δ（纯函数可单测，不碰 DB/网络） | 模块 |
| 2 | `scripts/run_parse_regression.py`：CLI 薄壳，依次调 predict → A② → A① → 归档 → Δ | 脚本 |
| 3 | 单测：Δ 页集合校验（相等/不等/子集）、meta 字段完整性、跳过理由必填 | 测试 |
| 4 | `.gitignore` 放行脚本；`docs/parse-struct-eval.md` 补一节"一键入口"，并回填本次评估的两条认知（修正 1/2） | 文档 |
| 5 | 干跑校验：`--skip-predict --skip-official --limit 50`（复用现有预测）核对归档 + Δ 输出 | 干跑记录 |
| 6 | 提交（拆 commit：模块/脚本/测试 → 文档） | commit |
| 7 | 正式跑一次（`--limit 200`，≈1.2–1.5h）产出**首份 fresh-parse 基线**——**待 D1–D6 定后** | 基线 |

---

## 八、与现有文档的关系

| 文档 | 关系 |
|---|---|
| `docs/parse-struct-eval.md` | A/B/C 三层框架与 A② 口径的定义处；本方案是它的"一键入口"补充，不重复口径 |
| `docs/omnidocbench-baseline.md` | A① 口径与 200 页基线数字的登记处；本方案跑出的新数应回填此处 |
| `docs/parse-benchmark-comparison.md` | 三方对比与表格归因；本方案每次跑的三方表应与其版式一致 |
| 本文 | 只讲"怎么一键跑、怎么入档、怎么比 Δ"，以及评估后需要修正的 4 条前提 |

## 这次不做

- 不把 A①/A② 接进 nightly（结论已定：A 验证的是固定基准集上的 pipeline，B/C 才验证生产库）；
- 不改任何评测口径、不动 vendor 的 TEDS 实现；
- 不建索引（`fts`/`vectors` 不进 predict 阶段，见修正 4）；
- 不做 CI 门禁（Δ 不改退出码）。
