# Harvey LAB 两道判分口径：内部 evals 通道 vs 外部 harness

日期：2026-10-18。样本：firm-knowledge 前 30 题（harvey-firm-knowledge-v1）。
目的：回答「对外报的 AnGIneer 成绩，用哪条通道判、能不能和 GLM-Legal 19.2% 比」。

## 1. 两条通道的组成

| 维度 | 外部 harness（lab-core） | 内部 evals 通道（evals-core） |
|---|---|---|
| 题面 | `task.json.instructions` | 题库 `eval_question.question`（同一来源导入） |
| 被测系统 | 产品 `/api/chat/agent`（SSE，单轮交付 `response.md`） | `answer_eval` RAG 链（检索→生成） |
| 判分器 | `lab_core.evaluation.scoring.score_rubric` | `evals_core.runner.rubric_eval.run_rubric_item` |
| 判分粒度 | **一条 criterion 一次判官调用**，只加载该条 deliverables | **一批 8 条 criterion 一次调用**（`GDP_RUBRIC_BATCH=8`） |
| 判官 prompt | `rubric_criterion.txt`：英文，任务标题 + 交付物全文 + match_criteria 原文 | 中文系统提示「严格、保守」+ 编号 rubric 清单，输出 `{index,pass,reason}` |
| 判官温度 | 0.0（不接受 temperature 的模型不发） | 0.1 |
| 判官模型 | `gpt-5.5`（经网关 `angineer.cn/api/llm2`，`LAB_JUDGE_SKIP_STRUCTURED=1` 关结构化输出） | `EVAL_JUDGE_MODEL` = Qwen3.8-Flash-Next（同网关 llm2） |
| 聚合 | all_pass = 全部 criterion pass；score=1.0/0.0 | 同口径（all_pass / mean_criteria） |
| 失败处理 | 判官异常→`error` verdict（不计 pass） | 判官候选链全崩→score=None→skipped（不假绿） |

两点口径差必须对外标注：

1. **官方默认是双判官**（`claude-sonnet-4-6` + `gpt-5.5` 平均，`lab-standard-dual-v1`）。
   本臂为控成本只用 `gpt-5.5` 单判——GLM-Legal 19.2% 若是双判官结果，则不完全同口径。
2. 外部通道的判官走我们的网关、且关了 structured output；模型版本以网关实际路由为准，
   `judge_model` 字段只记录请求名。

## 2. 同批答卷的实测（30 题 / 206 条 criterion）

同一批 `response.md`，同一套 rubric，只换判分通道：

| 通道 | all-pass | criterion pass | 与外部逐条一致 | 判分耗时（30 题） |
|---|---|---|---|---|
| 外部 harness（gpt-5.5 单判） | 2/30 = **6.7%** | 7/206 = **3.4%** | — | ~20 分钟 |
| 内部（Qwen3.8-Flash-Next） | 2/30 = **6.7%** | 12/206 = **5.8%** | **97.6%**（201/206） | **3.3 分钟** |
| 内部（判官换 gpt-5.5） | 2/30 = **6.7%** | 12/206 = **5.8%** | 97.6%（同一批 5 条） | 3.2 分钟 |

关键读数：

- **all-pass 完全一致**（同为 012、018 两题）——对外主指标可直接比。
- **criterion 差 2.4pp，方向单一**：5 条分歧全是「内部判 pass、外部判 fail」，没有反向。
- **判官模型不是变量**：内部 prompt 下把判官从 Qwen 换成 gpt-5.5，206 条逐条判定 100% 相同
  （包括那 5 条分歧）。差异来自判分 prompt 的批次化与「任何偏差即 fail」的措辞，
  不是模型强弱。
- 成本差 6 倍：内部一次判 8 条、3.3 分钟；外部逐条判、20 分钟。

## 3. 可比性结论

| 用途 | 用哪条通道 | 理由 |
|---|---|---|
| 对外报 AnGIneer 主成绩 | **外部 harness**（all-pass） | 与 GLM-Legal / 官方榜同判分器；但需注明单判官 |
| 日常回归 / 夜间门禁 | 内部 evals 通道 | all-pass 与外部一致、快 6 倍；criterion 只作诊断，不对外 |
| 跨版本比较 | 同一通道内比 | criterion 口径差 2.4pp 且单向，跨通道比 criterion 会虚高 |

内部通道的 5 条宽松项集中在「matter/文档是否被明确点名」这类边界判据上：外部逐条判
要求 match_criteria 原文里的对象逐字出现，内部批量判更容易接受同义指代。要把内部
criterion 拉齐，可把批次降到 1 并改用英文逐条 prompt——但会失去 6 倍成本优势，不建议。

## 4. 复现

```powershell
# 外部：逐条判（gpt-5.5，经网关）
python data/scratch/harvey-lab/tools/grade_arm.py --label angineer

# 内部：同批答卷重判（不重跑生成）
python data/scratch/harvey-lab/tools/rescore_internal.py --arm internal --judge Qwen3.8-Flash-Next
python data/scratch/harvey-lab/tools/rescore_internal.py --arm internal-gpt --judge gpt-5.5
```

产物：`internal_rescore_internal.json`、`internal_rescore_internal-gpt.json`、
`arm_report_angineer.json`。
