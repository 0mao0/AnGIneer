# S2 聚合臂 P0 配对实验预注册（041/016 首批）

- 日期：2026-11-07（跑前写死；跑后不得回改判读规则，只许追加「结果」节）
- 依据：`docs/plan-ls-routing.md` §4.2 S2 / §5 P0 / §5.1 P0 专项协议
- 机制：`services/angineer-core/src/angineer_core/aggregate_answer.py`（模型归类、代码从候选全集确定性计数）
- 状态：机制已施工；实验未跑

## 1. 参与门槛的 criterion 清单（预注册，跑前锁死）

寻址 = `(question_id, rubric_gold.criteria[i].i)`，与 lab-repo task.json 的 `C-00N` 等价（i == int(N)）。

| 题 | 参与 i | 条数 |
|---|---|---|
| harvey-fk-016 | i = 1..14（含 Dodged Bullet i=14 封闭世界判据） | 14 |
| harvey-fk-041 | i = 1..23（含 Dodged Bullet i=23 封闭世界判据） | 23 |
| 合计 | — | **37** |

## 2. 口径与检验方法（锁死）

- **micro**：37 条池的条目通过率（通过条数 / 37）。
- **macro**：016、041 两题逐题条目通过率的算术平均。
- **配对基线**：S1 臂（P5b R3 同配方，见 §4）在**同机制下重跑**（同一份落盘 enum_context）。
  P5b R3 历史 37/124 与基线 run-ca27eca3fcfe 16/124 仅作背景参照，**不作为配对对照**
  （016 在旧机制下无预读上下文——is_enumeration 不命中——候选暴露不对等，不可比）。
- **判读规则（主门槛）**：S2 在 37 条池上 micro 抬升，且 016 的 i=13（六年份额表）与
  041 的 i=22（唯一复现关系）两条聚合形态判据单独呈报；候选截断致总数算错＝**直接不通过**
  （对账段 complete/counts_sum_matches 任一 NO 即触发）。
- **判官**：内部通道 `rubric_eval`，判官 Qwen3.8-Flash-Next（同 P5b R3 口径）。
- **判官失败处理**：沿 rubric_eval 纪律——候选链全崩→JUDGE_FALLBACK→quality=None→
  计入 skipped 绝不假绿；部分批失败→缺失条目按 fail 计并标 partial_batches_failed。
  skipped 条目退出 micro 分母并单独呈报（不许静默）。
- **样本量声明**：37 条池为小样本，结论只作「机制是否继续」的门槛判定，不称显著；
  不做置信区间外推。

## 3. 召回缺口如实报告（复用主线①）

- p05 口径（doc_search limit=120 并集）：016 召回 9/12（候选 70）、041 召回 20/23（候选 43）。
- 本实验的 evals run 走 knowledge_search 全链路，`recall_audit`（主线①逐题对账）随 run
  自动落库；配对报告须引用其 matter 级读数并注明口径差异（不与 p05 硬比）。
- 结论表述必须带「候选全集≠金标全集」缺口标注。

## 4. 臂定义与运行手册（Phase B）

两臂**同码同候选**：enum_context 由 S1 臂落盘（`ANGINEER_ENUM_CONTEXT_DUMP_DIR`），
S2 臂逐字节复用（`ANGINEER_ENUM_CONTEXT_DIR`）。上下文门已放宽为「枚举或聚合」
（016 题面无枚举词，实证踩过）。

S1 臂 `.env`（P5b R3 配方 + 落盘）：

```
ANGINEER_ENUM_PREFETCH=1
ANGINEER_ENUM_PREREAD=1
ANGINEER_ANSWER_STRUCT=1
ANGINEER_QA_MAX_TURNS=12
ANGINEER_BUDGET_STOPPER_TOKENS=200000
ANGINEER_BUDGET_STOPPER_EST=180000
ANGINEER_ENUM_CONTEXT_DUMP_DIR=D:/AI/AnGIneer/data/scratch/harvey-lab/p0_enum_context
```

S2 臂在 S1 基础上追加（ANSWER_STRUCT 保持 1——非聚合题两臂行为一致）：

```
ANGINEER_ANSWER_AGGREGATE=1
ANGINEER_ANSWER_AGGREGATE_SPECS=D:/AI/AnGIneer/data/scratch/harvey-lab/p0_aggregate_specs.json
ANGINEER_ENUM_CONTEXT_DIR=D:/AI/AnGIneer/data/scratch/harvey-lab/p0_enum_context
```

步骤（本地 dev，NO_RELOAD 纪律：评测期间不动源码树）：

1. `.env` 写入 S1 臂变量 → 停 8791（`data/scratch/_restart_aichat.ps1`）→
   `Start-Process cmd -ArgumentList '/k','cd /d D:\AI\AnGIneer && pnpm dev:aichat-api'`（新窗口，日志重定向 `> data\scratch\aichat-api-p0s1.log 2>&1`）。
2. `python data/scratch/run_gate_closed_set.py`（十题串行，每题独立 run_id）。
3. 记录 10 个 run_id；核对 `p0_enum_context/` 落盘文件数（≥聚合+枚举题数）。
4. `.env` 改 S2 臂变量（同目录复用）→ 重启 → 再跑十题。
5. `python data/scratch/harvey-lab/tools/run_p0_pair_report.py --s1 <run_ids> --s2 <run_ids>`
   出配对报告，落 `data/scratch/harvey-lab/p0_pair_report.json`。

## 5. 维度规格（权威副本；运行时 JSON 见 p0_aggregate_specs.json）

语义取自**题面**（016 题面「(springing covenants don't count for this read)」与年份维度、
041 题面「lead underwriters / whether or not the deal priced」），不含金标答案内容；
016 四桶与 041 no-underwriter 桶为 §5.1 分母协议的预注册实现。unknown/unclassified
桶不退出分母（不许归类缺失由代码完备性兜底保证）。

```json
[
  {"match": "maintenance covenant", "question_hint": "harvey-fk-016",
   "dims": [
     {"name": "year", "kind": "free", "pattern": "^(?:19|20)\\d{2}$", "fallback_value": "unknown",
      "prompt_hint": "the year the credit agreement was signed (4-digit year)"},
     {"name": "covenant", "kind": "enum",
      "buckets": ["always_on", "springing", "out_of_population", "unknown"],
      "fallback_value": "unknown",
      "prompt_hint": "springing covenants stay in the population but never count as maintenance"}],
   "group_by": ["year"],
   "population_exclude": {"dim": "covenant", "value": "out_of_population"},
   "share": {"numerator_dim": "covenant", "numerator_value": "always_on",
             "denominator_exclude": [{"dim": "covenant", "value": "out_of_population"}]}},
  {"match": "lead underwriters", "question_hint": "harvey-fk-041",
   "dims": [
     {"name": "underwriter", "kind": "entity", "fallback_value": "unclassified",
      "prompt_hint": "the lead underwriter (lead bank) of the mandate, exactly as written in the excerpt",
      "prompt_extra": "Different firms with similar names are DIFFERENT entities — never merge them; if the matter had no underwriter, use no_underwriter"}],
   "group_by": ["underwriter"]}
]
```

## 6. 结果（跑后追加，不改上文）

- （待 Phase B）
