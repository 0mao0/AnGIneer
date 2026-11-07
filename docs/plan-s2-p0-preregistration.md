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

- 2026-11-07 01:28–02:16 执行；作答 Qwen3.6-35B-A3B、判官 Qwen3.8-Flash-Next（deepeval，两臂同款）。
- **37 条池 micro：S1 5/37（13.5%）→ S2 8/37（21.6%），delta +3；候选截断一票否决未触发（两臂 complete=True）。按 §2 主门槛＝通过。**
- 逐题：001/005/009/021/031/045/080 两臂逐分一致（同上下文确定性复用实证）；**041 4/23→8/23（+4）；016 1/14→0/14（−1）**。
- 聚合形态判据 i=13（016 份额表）/ i=22（041 唯一复现）：双臂皆 False——聚合表形态本身未换来这两条通过。
- **归因（对账日志铁证）**：016 归类 24/50（backstop 26、excluded 17）＝unknown 泛滥，population 近空→份额全 0→判据全灭；041 归类 38/47（backstop 9）＝抽取质量够。约束在**摘录深度**（1500 字摘录装不下 covenant 条款细节，按需加深只对「零词命中」触发）与归类 prompt 的不猜测纪律，非机制缺陷——机制侧（表渲染/对账/兜底/落盘复用）全部按设计工作。
- 判官翻案风险：016 的 S2 失败理由多为「未提及/归为 unknown」，与对账数字一致，非判官口径问题。
- **遗留（另案）**：①主线 recall_audit 对枚举臂 run 的 retrieved_items 口径为 0/N——枚举/聚合臂候选走 doc_search/doc_read，不落 retrieved_items，属对账盲区（本实验召回缺口以 p05 口径 016 9/12、041 20/23 为准）。
- 原始 run_id 见 `data/scratch/harvey-lab/p0_pair_report.json`；报告工具 `tools/run_p0_pair_report.py`。

### 迭代 2（2026-11-07 上午，机制修正验证，非预注册实验）

- 机制追加：预读上下文尾部机器索引行（PREREAD INDEX）＋「归类失败信号驱动二次加深」——
  第一遍归类后只对兜底 matter 重读 4000 字（doc_read，不占 90k 主上下文），分批二次归类，
  升级成功的兜底行、仍失败保持兜底。spec v2 加 `"deepen": true`（016/041）。
- 两臂重跑（S1 臂同配方重刷 dump，S2 臂=deepen 开）：**37 条池 S1′ 11/37（29.7%）vs
  S2′ 10/37（27.0%），−1，本轮未过门槛**；全 124 条 S1′ 38 = S2′ 38。与迭代 1（+3）合并看，
  S2 对池的净效应在已知噪声带内（±5 题/12% 翻转地板），单轮比较不可分辨。
- **加深机制效果分题**：041 归类 38/47→44/47（兜底 9 个重读升级 6 个），判分 8→9——有效；
  016 兜底 26 个重读 26、仅升级 1——无效。
- **016 定论**：瓶颈不是摘录深度，是 matter→代表文档选择（best.doc_id 常非信贷协议本体，
  covenant 细节不在该文档）。解锁钥匙=文档类型路由（credit agreement 优先），属检索层工程，
  归「枚举检索」根因线（Harvey 根因 #1），不在 S 层边界内。
- **S 层②施工结论**：机制四件（确定性计数/对账/兜底/加深）全部按设计工作；041 聚合表
  稳定正贡献；按收缩纪律，S2 迭代到此收线，不再烧算力；016 移交检索层根因线。
- 迭代 2 run_id 与报告：`data/scratch/harvey-lab/p0_pair_report_iter2.json`。

### 迭代 3（2026-11-07 上午，宽度假设验证——被实验否定后回退）

- 机制尝试：`_preread_candidates` per_matter 1→2 捕获第二代表文档，PREREAD INDEX v2
  （doc_ids 升级 {mid:[doc1,doc2]}，向后兼容），二次加深改读「主文档 2000 + 第二文档 2000」。
  假设来自离线测量（016 best≠细节文档 4/7、细节文档排组内第 2-3 篇）——但该排名用 rowid 序，
  非 doc_search 的 FTS 组内序，事后被实验纠错。
- 实测（016/041 两题）：**016 纹丝不动**（upgraded 1/26、classified 25/50、判分 1/14）；
  **041 回归**（upgraded 6→1、classified 44/47→39/47、判分 9→8）——每文档减半到 2000 字
  丢掉了迭代 2 靠 4000 字深度换来的归类。
- **处置与回退**：加深恢复「主文档单篇 4000 字」（深度优先）；per_matter=2 捕获与索引 v2
  保留（零成本，供未来文档类型路由类机制使用）。恢复确认实跑：041 classified 44/47、
  upgraded 6/9、判分 9/23（run-288e63c0c7f6），与迭代 2 齐平。
- **016 定论维持**：深度、宽度都到顶后 25/50 仍不可归类——剩余假设只剩上游（候选集缺席
  5/12、match 模式检索词不指向 covenant 章节），全部归「枚举检索」根因线；S 层侧不再迭代。
- 教训入账：**离线排名测量必须用与线上同源的排序口径（FTS 序），rowid/relpath 序只能当
  弱线索**；「假设→实验→否定→回退」全程两小时，成本可控。

### P0b 确定性校验件三件套（2026-11-07 施工＋冒烟，随主线③④⑤）

- **⑤安全终态**：SAFE_TERMINAL_CODES 共享（no_evidence/unsupported_reference/tool_error_json
  三个整答替换型）；struct/closed_set/audit 三 guard 补 code 检查（消灭「偶然不覆盖」），
  aggregate 保护清单同步扩容。
- **③引用贯通**：预读构建期按闭集 matter 分配 run 级 K 号（随 PREREAD INDEX v3 携带
  cites），S1/S2 渲染行内补 [K]，guard 以 4 元组 extras 携 citations、经最终 assistant
  消息 meta 并入 run_end/policy_query 引用集（aggregate_tool_citations 口径去重）。
  前端与评测零改动（K 前缀复用；Harvey 无 gold_target_ids → citation_hit 天然 N/A）。
  **冒烟实证（016/041 S2 臂）**：citations 40/89 条、答案内 [K] 25/44 个且 ⊆ citations
  （§1.3 契约达成）；recall_audit 对这两题的 citations_only 口径从「没记录」变为有料
  （①盲区部分修复：回退条件补「retrieved_items 空且 citations 非空→citations_only」，
  四形态语义测试覆盖）。
- **④numeric 答案槽**：答案尾行 `FINAL: <值>` 协议（answer_format 注入约定，run 级配置）
  → policy_query 解析上浮 `prediction.final_answer` → numeric_eval 优先读槽、无槽回退
  尾行启发式（两臂同一判分出口）。**冒烟实证（OfficeQA 2 题）**：final_answer 上浮有值、
  判分走槽（WRONG 而非 SHAPE_FAIL——答案内容错，机制正常）。
- 单测：angineer-core 275 绿（+13）、evals-core recall_audit/numeric 41 绿；无预注册实验
  （本批为契约件，验收=契约达成）。

---

## 7. 枚举检索根因线·第一刀（2026-11-07，回答链生产修复）

016 移交单的开工记录。**离线测量**（函数调用精确复现线上 FTS 排序——修正迭代 3 的结论：
doc_search 可离线复现，rowid 口径才不可）把 35 个金标 matter 的损失钉到四层：
①bm25 每计划窗口 2400 行（"credit agreement" 31 chunk 只活 1 行）②归组候选截断 400
（**硬编码在 `ranked = _order(...)[:400]`，matter 在 matter 视图蒸发**）③matter 卡上限 40
④闭集帽 50；另有 041 的 q2/q3 死查询（语料级 0 FTS 命中）。

**第一刀设计**（doc_search 生产工具参数化、默认行为不变；枚举臂传高值）：
- doc_search 增参 `max_matters`/`group_candidates_cap`/`window_rows`（0=默认）；归组截断
  改按分数排序截断（旧按插入序，多计划窗口放大后后位计划的低分文档整批挤出——
  典型查询候选 ≤ 上限时无差异）；matters 卡透出 `score` 字段（加法）。
- enum_prefetch：帽 50→85、自适应摘录（85k 预算摊薄，floor 900）、死查询题面词兜底重试、
  并集改按跨查询最高分排序（首见序会让先发查询的低分 matter 挤掉后发查询的金标）、
  归组截断/窗口传高值（6000/4800）。

**离线复测（决定性）**：金标入闭集 **27/35 → 34/35**（016 11/12、041 23/23 全捞回）。
分层修除实录：归组截断（§6 误标「400」实为 ranked[:400] 硬编码）修掉 4 个（1042/1013/
1013-00002/1027）、matter 卡 80 修掉 2 个、帽 85+score 排序并集修掉 2 个。
**残余 1 个**：016-1010（并集 109 名、分 2.0）——单查询相关性弱（题面词在其文档只有
擦边命中），属**排序质量**问题，下一刀（候选：group score 聚合口径 max→sum、
多查询计票、词级 OR 通道）。
**风险与纪律**：doc_search 默认路径行为不变（参数 0）；工具默认值是否跟随放开待实测
数据；自适应摘录 floor 900 字保底、深度由二次加深兜底。

### 第一刀线上验证（2026-11-07 傍晚，S2 臂 016/041 复跑）

- **041（归因题）：判分 10/23——历史最佳**（此前 9/23）。候选 85（覆盖率红利兑现：
  金标 23/23 入集）、归类 71/85=84%、加深升级 2。
- **016（份额题）：仍 1/14**。候选 85、金标 11/12 入集（覆盖率修复到位），但归类塌方：
  **classified 7/85、兜底 78**（加深仅升级 4/78）。病灶确认移到**抽取段**——match 模式
  读页用题面词定位段落，covenant 细节段落与题面词不匹配（与测量 §6 的词汇鸿沟同源），
  料进锅了但刀切不到位置。属移交单的「match 检索词质量」半边，下一刀
  （候选：doc_read match 词源换成归类维度词、section 定位、或 deepen 读全文分页扫描）。
- 读数口径：S1 臂（struct）本轮答案异常短（2.1k/2.7k 字符，此前 14-25k），未影响 S2
  结论；两侧判分均单轮、不作门槛。run_id：S1 run-dc22f26b2e7c/run-c44af77b1e38、
  S2 run-ec1e1f1e4af8/run-983171b3e5c9。
