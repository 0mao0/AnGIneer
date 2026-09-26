# 需求：拒答专项 22→19 的逐题归因

> 状态：待认领。关联计划 `docs/plan-ttft-improvement.md`（§8 尾巴第 7 条），此前搁置原因「业主暂缓，待查时逐题核对」。
> 提出时间：2026-09-26。**注意本需求是「归因报告」不是「必须修复」**——先定性再决定要不要改。

## 1. 背景与现状证据

v0.2.77 首跑 nightly（2026-09-25，run `f413fc7c8c63`）整体是提升的：

| 指标 | 基线 | v0.2.77 首跑 | 方向 |
| --- | --- | --- | --- |
| 整体准确率 | 84.9% | 86.9%（904/1040） | ✅ +2.02pp（CI95 显著） |
| hit@5(doc) | 96.5% | 98.3% | ✅ +1.8pp |
| **拒答专项** | **22/39（56.4%）** | **19/39（48.7%）** | ⚠️ **-3 题（变差）** |

> 数据等级说明：整体/hit 数字来自 nightly 结论（可信）；「拒答 22→19」是 v0.2.77 发版时的口头结论，**认领后第一步须从数据复核这三个数字**（含 CI/置信区间），不要直接采信本文档。

拒答题集：`open-ragbench-refusal-v2`，39 题，`tags` 含 `refusal`（`data/evals/evals.sqlite` → `eval_question` / `eval_dataset`）。
基线指针：`data/evals/baseline/baseline_run.json`（当前 label：`R2 2026-09-05 v0.2.31+32`）。

**初步假设（待证伪）**：v0.2.77 起的「首轮直达」注入把检索证据直接塞进上下文，可能诱导模型对「相邻但不可回答」的证据强行作答，而非按预期拒答——即从「诚实拒答」翻成「牵强作答」。

## 2. 目标

给出**逐题定性报告**，回答三件事：

1. **是哪 3 道题**从「基线正确（拒答）」翻成「新版错误（作答）」？逐题给出基线与新版的 prediction、score、判定理由。
2. **每道题翻车的根因**是什么？分类到以下桶（可多选/可新增）：
   - 注入证据诱导作答（假设成立）
   - 提示词/守卫变更导致拒答边界移动（`REFUSAL_MARKERS`、`is_refusal_text`、guard 边界规则）
   - 检索命中变化导致模型认为「有证据可答」
   - 判分口径变化（例如文案漂移被判错，而非真实行为变化）
   - 纯噪声/模型随机性（同一版本重跑是否复现）
3. **结论与建议**：是「回归必须修」还是「可接受/口径问题」；若建议修，给出方向与验证方案（见约束）。

## 3. 复现与数据入口

- **数据在生产机**（nightly 内置，不进 git）：`/home/runner/AnGIneer/data/evals/evals.sqlite`
  - `eval_run`：`run_id` / `dataset_id` / `run_name` / `started_at` / `summary_scores`
  - `eval_run_detail`：`run_id` + `question_id` → `prediction` / `scores` / `all_scores` / `quality` / `status`
- 逐题对比思路：取 `run-f413fc7c8c63`（或 09-25 当天实际 run_id，须核实）中 `dataset_id='open-ragbench-refusal-v2'` 的 39 条 detail，与本基线 run 的对应 `question_id` 逐条比对正确性；挑出「基线对→新版错」的差集。
- 基线 run 的原始结果：`data/evals/baseline/open-ragbench-subset-v2-run-9b36737e39a8.baseline.json`（注意文件名是 subset-v2，须确认拒答子集结果是否在其中，否则用另一份基线产物）。
- 复跑单题：`scripts/open_ragbench`（compare/report/notify 是 evals-core 算法的 CLI 薄壳，改逻辑只改 `evals_core/nightly/`）。

## 4. 交付物

一份 Markdown 报告，含：

- 三个数字的复核结论（22→19 是否属实、差值是否有统计意义）。
- 3 道翻转题的：`question_id` / 问题原文 / 基线 prediction / 新版 prediction / 两边 score / gold。
- 每题根因判定（引用证据：证据条数、是否含 refusal 关键词、guard 是否触发、prompt 版本）。
- 是否复现（同版本重跑同题 2~3 次，区分真回归与噪声）。
- 处置建议（修/不修 + 若修的验证方案）。

## 5. 约束与风险

- **勿把「22→19」当既定事实**：AGENTS.md 明令转述归因须标注证据等级，本文档的数字是待验证主张。
- **区分「行为变化」与「判分口径变化」**：文案漂移曾被误判为拒答回归（历史实踩），逐题对比 prediction 原文而不是只看分数。
- **拒答题的「答对」定义要写清楚**：拒答题的判分是「正确拒答」而非「答出内容」；核对时先确认 `REFUSAL_MARKERS` / `is_refusal_text` 当前口径。
- **若决定改 prompt/守卫**：必须先过 39 题拒答专项 + nightly 整体（v0.2.74 教训：prompt 改动跳过专项验证直接发版出过事），且留回退开关。
- 只读排查，勿在生产机改代码或重跑全量 nightly 影响他人评测。

## 6. 可选延伸（非必须）

若归因指向「注入诱导作答」，这本身是注入机制的已知代价，值得顺带量化：注入开启 vs 关闭（`ANGINEER_FORCE_FIRST_SEARCH=0`）在 39 题拒答集的对比，为「注入是否该对拒答题让路」提供数据。
