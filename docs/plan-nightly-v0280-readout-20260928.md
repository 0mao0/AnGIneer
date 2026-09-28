# 交接：09-28 早读 nightly（v0.2.80 首个定时跑验收）

> 2026-09-27 晚写。01:00 北京时区定时跑是 v0.2.80（2ddf9d4，09-27 白天部署）上线后首轮全量 1040 题。
> 本篇只列"读什么、对照什么、什么算过"，判定动作在读完之后另做。

## 0. 前置事实：归档在哪个位置

分挡布局（commit 28a87f4，每次派发一挡）是否已部署决定读法：

```
28a87f4 已 push+部署 ──> data/evals/nightly/2026-09-28/runs/<01xx-6hex>/{nightly.json,report.md,material_parity.*}
未 push（现状默认）  ──> data/evals/nightly/2026-09-28/{nightly.json,report.md}   旧当日单档
```

- 看板夜间测试页：新布局下同日每跑一行；旧布局当日多跑仍是覆盖后的最后一条。
- 取数统一走原生 ssh：`/c/Windows/System32/OpenSSH/ssh.exe -o BatchMode=yes root@124.221.238.70 '…'`；
  容器内读库用 `docker exec -i angineer-aichat-api python3 -`（evals.sqlite 只读 URI 模式，2.6G，勿全表扫）。

## 1. 读数清单（按优先级）

| # | 读什么 | 对照基准 | 什么算过 |
|---|---|---|---|
| 1 | 门禁结论（配对 CI vs 钉基线）+ 总分 | 09-27 16:33 手动跑 885/1040 = **85.1%**；前一晚 84.42% | CI 覆盖 0 且无红线即绿；85%±1pp 内视为 v0.2.80 水位成立 |
| 2 | 题级翻转数（vs 16:33 那次逐题配对） | 噪声地板 **6.2~6.9%/对**（64~72 题，1040 题口径，09-24~27 三对实测） | ≤~70 题即正常波动；净差 ±5 题内无方向含义 |
| 3 | table 段耗时（stage_times，data/ops 打点） | 历史参照 3.88s（09-24）；P0 真链路实测 2.6s；事故区间 10.8~27.8s | 稳定 ≤3s；>5s 先查网关晚间波动（已知可达 2 倍）再怀疑代码 |
| 4 | ttft（分类并行默认开后的首轮定时全量） | 生产 A/B 中位数 6055→**3204ms**；分类 p50 1078ms 达标 | 中位数 ≤3.5s 量级；注意 ttft_ms 口径不含分类段 |
| 5 | ROW_AGG 开关的召回对照（P0 收口遗留项） | 开关关时 nightly 召回 | hit@5(doc) 不降即默认定版成立；降则默认改回关 |
| 6 | 意图分类需求 §3.3 的 nightly 项（09-26 记"明晚出"） | 需求文档 §3.3 预注册口径 | 照文档判，不看这里 |
| 7 | material_parity 卡片行 | 上一晚 severity | fail→warn 改善或持平；判读规则见素材卡片行记忆（只有未落地/超容差覆盖判问题） |

## 2. 已知干扰（读数前先排除）

- 晚间网关波动可达 2 倍：耗时类读数异常先跑 8791 健康检查 + 清理孤儿 worker，再对比同日 16:33 类白天跑。
- 判分缺失若出现：看条目 `judge_missing` 字段（阈值内放行已可见），别从总分倒推。
- error sidecar：旧布局下若同日既出结论又挂过一条，看 `same_day_error`；新布局下各挡独立，无此合并问题。

## 3. 读完之后的两个动作（不在本篇内做）

- 若 28a87f4 未部署：分挡功能今晚未生效，属预期，别按新布局找不到目录当故障报。
- 翻转池若显著 >7%：先逐题 sha1 答案配对复核（方法见 [[nightly-single-run-noise-floor]] 探针法），再谈归因。

## 4. 验收清单（可执行版 —— 09-27 21:1x 实测核准）

> §1 只写了「读什么、算过什么」；本节把「读什么」钉成 run_id 与命令，把「算过」钉成数。前置值全部实测，不是假设。
>
> **2026-09-27 晚更新：本版主体已从 v0.2.80 换成 v0.2.81**（v0.2.80 已含 7 个提交之上的发版）。
> 原计划「v0.2.80 首个定时跑」这个档案不再存在——v0.2.80 的全量首跑是 09-27 16:33 那次手动跑（`run-dacc6f593228`，885/1040）。
> 下述 3 个口径坑（matrix 口径、table 段两层量级、ttft 全量≠A/B）与版本无关，仍然成立；涉及版本/布局的条目已按本版改写。

### 4.1 前置核准（已实测，勿再假设）

| 项 | 实测值 | 对读法的影响 |
| :--- | :--- | :--- |
| 部署版本 | **v0.2.81**（v0.2.80 `2ddf9d48` 已是上一版；本版含 7 个提交 + 发版 commit） | 09-28 那次是 **v0.2.81 首跑**，不再是「v0.2.80 首个全量」 |
| 分挡布局 `28a87f4` | **本版已含** | 归档落 `<date>/runs/<HHMM-6hex>/`（每跑一挡）——同日多跑不再互相覆盖；取数见 4.3/4.5 |
| 判分口径 `2ce08ee` | **本版已含**（「已拒但标记不可见」豁免 + V11 相关性标注） | 09-28 分数与 16:33/01:00 两个基线**不可同口径比较**，只能并列引用 |
| `ANGINEER_ROUTE_PARALLEL` | `=1`（容器 env 可见） | 第 6 项 = 并行默认开下的首轮定时全量 |
| `ANGINEER_TABLE_ROW_AGG` | **未设 ⇒ 代码默认 `"0"`（关）** | **第 5 项按现状会空转，见 4.2①** |
| `WEBHOOK_SYSTEM` / `WEBHOOK_OWNER` | 均已设 | nightly 结论两群都发，正常 |
| 调度器 | `settings` `enabled=true / hour=1 / minute=0`；`.env NIGHTLY_SCHEDULER=1`；09-27 01:00 实跑过（`run-d20ba12076cd` 起于 01:00:59） | 09-28 01:00 应触发。证据等级=配置值＋历史实跑，非本轮实证 |
| 素材检查（09-27 挡） | `severity=ok`，`docs_with_issues=0`，`issues=[]` | 第 7 项基准 = ok，判据是**不退化** |

### 4.2 两处口径（① 已定版了结，② 仍生效）

**① 第 5 项（ROW_AGG）—— 已定版：保持默认关，不做对照（2026-09-28 用户拍板，理由「收益太小」）。本项不再读。**
结论依据（复议时复用）：它作用于**主路**（`TableRetriever` 同时被 `retrieve_service` 使用，即 `knowledge_search`，一次 nightly 1039 次，不是只管那 1~2 次 `table_search`）；
**动机已消失**——P0 要解决的是候选爆炸→table 段 6.5~8s，现开关**关着**实测 `stages.table` 2.20s（09-27）/2.32s（09-28），≤3s 已达标；
**原判据测不出失败模式**——行聚合是同表内合并，文档仍在 ⇒ `hit@5(doc)` 结构性不敏感（现状 text-table 0.95、text-table-image **1.0** 近满），「hit@5(doc) 不降即定版」恒真。
将来若要复评，敏感指标是 `text-table`/`text-table-image` 的 `hit@1(sec)`/`hit@5(sec)` 与正确率（0.6182/0.9091/0.8033、0.7551/0.898/0.6792），且 114 题单晚配对只能抓 ≳8~10pp 的效应——别拿整体行或单晚下结论。

**② 第 2 项的翻转数必须自己算，不能读 `nightly.json` 的 `matrix`。**
`matrix` 是**对钉基线**（`base_label=v4-new-baseline-2026-09-24`）的配对，实测正常值就是 107~114 题（10~11%）：

| 挡 | 对钉基线 `pf+fp` | 占比 |
| :--- | ---: | ---: |
| 09-26 `run-303b8c4112e9` | 107 | 10.3% |
| 09-27 `run-dacc6f593228` | 114 | 11.0% |

拿这个数去比「≤70 题」会误报红线。`regression_items` / `fixed_items` 也不是矩阵全量（09-27 是 50/20，矩阵是 56/58），别当计数用。

### 4.3 基准钉死（认 run_id；三个旧口径基准只作并列引用）

| 角色 | run_id | 起点→终点（北京） | 分数 | 可用性 |
| :--- | :--- | :--- | :--- | :--- |
| §1 写的「16:33 手动跑」 | `run-dacc6f593228` | 09-27 16:33 → 19:48 | 885/1040 = **0.851** | v0.2.80 + 旧判分口径 → **只能并列，不作水位对照** |
| §1 写的「前一晚」 | `run-d20ba12076cd` | 09-27 01:00 → 03:39 | 878/1040 = **0.8442** | 同上（v0.2.79） |
| 门禁钉基线 | `run-1c950da3c4e4` | 09-24 10:17 | 883/1040 = 0.849 | **仍有效**——门禁自己就是拿它对现在的跑，口径随代码走 |

⚠️ 归档读法（本版分挡生效后）：
- 每跑一挡，路径是 `data/evals/nightly/2026-09-28/runs/<HHMM-6hex>/{nightly.json,report.md,material_parity.*}`；一个日目录下可能有多挡（定时 + 手动各一挡）。
- **仍以 `eval_run` 表的 run_id 为准**（挡位名只是目录，不是身份）；同日多跑不再互相覆盖，这正是本版要修的问题。
- 旧形态的历史日子（含 09-27）仍是平铺的 `data/evals/nightly/2026-09-27/nightly.json`——那份已被 16:33 覆盖过（01:00 那次的结论只存于 `eval_run`/`eval_run_detail`）。

### 4.4 逐项：读哪里 / 判据 / 坑

| # | 读哪里 | 判据 |
| :--- | :--- | :--- |
| 1 | `nightly/2026-09-28/nightly.json` 的 `state`/`gate_reasons`/`overall_score` | `state=green` 且 `gate_reasons=[]`；`overall_score` 落 0.841~0.861（85%±1pp）即 v0.2.80 水位成立 |
| 2 | 自算配对翻转（见下方命令）。⚠️ **vs `run-dacc6f593228` 已不是同版本/同口径对**（那是 v0.2.80 + 旧判分） | 降级为**诊断**：翻转池暴涨（≳15%）才去追；水位判定以第 1 项门禁为准 |
| 3 | `data/ops/retrieval-20260928.jsonl` 中 `path=table_search` 的 `stages.table` | **≤3s（以 stage_times 层为准）**；样本量 1~2 条/跑，单跑不可判，须跨多跑累计 |
| 4 | `data/ops/ttft-20260928.jsonl`，按 `ts_bj` 卡 01:00~04:00 窗取中位数 | **不劣于 09-27 同口径窗口**（01:00 窗 p50 **5279ms**、16:33 窗 p50 **5647ms**）；**不要拿 3204ms 做判据**，见下方坑 |
| 5 | —— | **已定版（09-28 拍板）：ROW_AGG 保持默认关、不做对照**，本项不再读；依据见 4.2① |
| 6 | 照 `req-intent-classify-latency.md` §3.3 | 已被 §9.1 闭环（84.42% vs 钉基线 84.90%，CI95 [-2.5,+1.5] 跨零）；09-28 作 v0.2.80 复验，判据同上=不低于 0.849 |
| 7 | `nightly/2026-09-28/material_parity.json` 的 `severity` | 保持 `ok`（判读规则见素材卡片行记忆：只有未落地/超容差覆盖判问题） |

**第 3 项的坑（计划里两个量级混写了）**：09-27 实测同一 run 内——
`stages.table = 2.2008s`（+formula 0.8285 → 该次检索 `dur_ms=3031`），而同一 run 的工具层 `table_search` `dur_ms = 6814`，差 3.8s 是 HTTP/队列开销。
⇒ §1 的「3.88s / 2.6s」是 stage_times 层，「事故区间 10.8~27.8s」是工具层（09-27 工具层两样本 6.81s / 24.33s）。**判据只认 stage_times 层**，工具层仅记录。

**第 4 项的坑（判据取自不同总体）**：§1 写的「中位数 ≤3.5s 量级」源自 5 题 L1 的生产 A/B（6055→3204ms，且预检 5/5 命中，`tool dur=0ms`）——那是**最好情形**。
同口径实测 1040 题全量（`ttft-20260927.jsonl`，按窗口切）：

| 窗口 | n | p50 | p90 | max |
| :--- | ---: | ---: | ---: | ---: |
| 09-27 01:00（前一晚定时） | 1039 | **5279ms** | 15023ms | 209018ms |
| 09-27 16:33（手动全量） | 1040 | **5647ms** | 18982ms | 229551ms |

⇒ 全量混合（含 table/text-image 长 prompt）本来就在 5.3~5.6s，拿 3204ms 判会**误报失败**。第 4 项按「不劣于上表两个窗」判；要判 A/B 口径请另跑 5 题 L1 探针，别用 nightly 读数。

### 4.5 读数命令（取数统一走原生 ssh；以下均已实测跑通）

> 容器内**没有** `sqlite3` CLI；`python3 -c` 的嵌套引号过 ssh 易坏，一律用远端 heredoc。
> `eval_run.started_at/completed_at` 存的是 **UTC**，北京 = +8。

```bash
SSH=/c/Windows/System32/OpenSSH/ssh.exe
H='root@124.221.238.70'

# 第 1 项：先列当日的挡，再取最新一挡的结论（分挡已生效；旧形态日子无 runs/）
$SSH -o BatchMode=yes $H 'ls -1 /home/runner/AnGIneer/data/evals/nightly/2026-09-28/runs/ 2>/dev/null || ls -1 /home/runner/AnGIneer/data/evals/nightly/2026-09-28/'
$SSH -o BatchMode=yes $H 'docker exec angineer-aichat-api python3 -c "import json,glob;fs=sorted(glob.glob(\"/app/data/evals/nightly/2026-09-28/runs/*/nightly.json\")) or [\"/app/data/evals/nightly/2026-09-28/nightly.json\"];d=json.load(open(fs[-1]));print(fs[-1]);print({k:d.get(k) for k in (\"run_id\",\"state\",\"overall_score\",\"correct\",\"total\",\"delta\",\"delta_ci95\",\"base_label\",\"verdict\",\"gate_reasons\")})"'

# 先拿 09-28 的 run_id（同日可能多跑，别认目录）
$SSH -o BatchMode=yes $H 'docker exec -i angineer-aichat-api python3 - <<"PY"
import sqlite3
c=sqlite3.connect("file:/app/data/evals/evals.sqlite?mode=ro",uri=True).cursor()
for r in c.execute("select run_id,started_at,completed_at,total_questions from eval_run where dataset_id=? order by started_at desc limit 5",("open-ragbench-subset-v4",)):
    print(r)
PY'

# 第 2 项：题级翻转（A 固定 = §1 的对照 run-dacc6f593228；把 B 换成上面拿到的 09-28 run_id）
$SSH -o BatchMode=yes $H 'docker exec -i angineer-aichat-api python3 - <<"PY"
import sqlite3
db=sqlite3.connect("file:/app/data/evals/evals.sqlite?mode=ro",uri=True); c=db.cursor()
q=lambda r: dict((a,(b,d)) for a,b,d in c.execute(
    "select question_id,status,quality from eval_run_detail where run_id=?",(r,)))
A,B=q("run-dacc6f593228"),q("run-<09-28_run_id>")
ks=sorted(set(A)&set(B))
o2b=sum(1 for k in ks if A[k][1]=="correct" and B[k][1]!="correct")
b2o=sum(1 for k in ks if B[k][1]=="correct" and A[k][1]!="correct")
print("n=%d flip=%d (%.1f%%) net=%+d"%(len(ks),o2b+b2o,100.0*(o2b+b2o)/len(ks),b2o-o2b))
PY'

# 第 3 项：table 段（stage_times 层为准；工具层仅记录）
$SSH -o BatchMode=yes $H 'cd /home/runner/AnGIneer/data/ops && grep "table_search" retrieval-20260928.jsonl; echo ---; grep "table_search" tool-20260928.jsonl'

# 第 4 项：ttft 中位数（卡 01:00~04:00 窗；必须滤掉 ttft_ms=null，否则排序会 TypeError）
$SSH -o BatchMode=yes $H 'cd /home/runner/AnGIneer && python3 - <<"PY"
import json
rows=[json.loads(l) for l in open("data/ops/ttft-20260928.jsonl",encoding="utf-8") if l.strip()]
v=sorted(d["ttft_ms"] for d in rows if d.get("ttft_ms") is not None and "2026-09-28T01:"<=d["ts_bj"]<"2026-09-28T04:")
n=len(v); print("n=%d p50=%dms p90=%dms max=%dms"%(n,v[n//2],v[int(n*0.9)],v[-1]))
PY'

# 第 7 项：素材卡片（与结论同一挡目录下）
$SSH -o BatchMode=yes $H 'cat /home/runner/AnGIneer/data/evals/nightly/2026-09-28/runs/*/material_parity.json 2>/dev/null || cat /home/runner/AnGIneer/data/evals/nightly/2026-09-28/material_parity.json'
```

### 4.6 未决（需用户拍板，别自行执行）

- **4.2① 第 5 项开关 —— 已了结（09-28）**：定为保持默认关、不做对照，不动 `.env`、不重建容器。
- **分挡已随 v0.2.81 部署**（09-27 晚）：09-28 同日多跑各占一挡、不再互相覆盖 —— 本条目已了结（09-28 01:00 实测落 `runs/0100-3d3e60/`，四件同挡、企微双群送达）。
