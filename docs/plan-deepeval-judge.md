# DeepEval 判分引擎替换（EVAL_ENGINE 开关）

> 状态：**已实施并合并**（2026-09-11）。默认 `EVAL_ENGINE=legacy`（行为不变）；
> 切换 = 服务器 .env 改 `EVAL_ENGINE=deepeval` 重启 aichat-api（nightly 在 aichat-api 进程内调度）。

## 设计边界

换「判分引擎」不换「评测骨架」：题集（487 题 Open RAG Benchmark 子集）、hit@k/citation/拒答/哨兵留痕、
judge 候选链纪律（绝不落到被测模型自判）、基线门禁、企微通知全部不动；只有 LLM 判分实现
从自研 prompt（SEMANTIC_EVAL_PROMPT）换成 DeepEval 指标层。

| 口径 | 实现 | 说明 |
|---|---|---|
| 语义判分 0–1（阈值 0.65 不变） | `GEval`（criteria 移植 v3 rubric 逐条一致，显式参数面 actual vs expected output） | 判分理由文本变英文（GEval 模板行为），不影响分数口径 |
| 新增 faithfulness（忠实度/防幻觉） | `FaithfulnessMetric`（answer vs retrieved contexts，取 prediction 的 evidences，上限 10 条×1000 字符） | 只展示不进门禁 |
| 新增 answer_relevancy | `AnswerRelevancyMetric` | 只展示不进门禁 |
| 新增 contextual_precision | `ContextualPrecisionMetric`（有 gold + contexts 时） | 只展示不进门禁 |
| 关键词断言 / 拒答 / 引用命中 | 保留自研（DeepEval 不做，这是我们的资产） | — |

- judge 模型路由：`DGXJudge`（deepeval `DeepEvalBaseLLM` 子类）内部复用 ai_inference 候选链
  （`_resolve_judge_candidates`：run 级 UI 指定 > EVAL_JUDGE_CONFIGS > EVAL_JUDGE_MODEL），
  `judge_used`/`judge_failover` 哨兵留痕语义不变。
- 失败语义：GEval 失败 → `semantic_evaluated=False` → 走原有关键词兜底 + nightly judge_fail 补判通道；
  扩展维度独立失败独立记 None，不污染 correctness。
- 成本控制：`EVAL_DEEPVAL_EXTRA=0` 关闭扩展维度（每题省 3~6 次 judge 调用）。

## 离线 A/B 结论（2026-09-11，存量 prediction 30 题双跑）

- legacy 均值 0.8867 vs DeepEval 0.8033（**−8.3pp 系统性偏严**），Spearman 秩相关 0.757（秩序保持）
- 0.65 阈值翻转 3/30；核读翻转理由：DeepEval 更严但多数站得住（如抓到"答案只盯 VIX 障碍期权、
  漏了期望的行权频率/模拟估值要点"这类 legacy 放水的实质遗漏），个别 0 分偏狠属边界题
- 扩展维度首批分布：faithfulness mean 1.00（n=10，覆盖受端点瞬时限速影响）、answer_relevancy mean 0.81、
  contextual_precision mean 0.91

## 切换操作与基线重钉

1. 服务器 `.env`：`EVAL_ENGINE=deepeval` → `docker compose up -d aichat-api`（重建注入 env）
2. **第一次 DeepEval nightly 的分数与旧基线不可直接比**（判分口径变严 ~8pp）——当晚报告出来人工核读，
   确认后该次 run 钉为新基线；旧基线保留归档备查（nightly.json 条目带 `eval_engine` 字段可识别口径）
3. nightly 时长会变长（每题 +3~6 次 judge 调用）：487 题全量预计 +1.5~2h；想压时长大数据量期可设
   `EVAL_DEEPVAL_EXTRA=0`（只留 correctness）
4. 回滚：`EVAL_ENGINE=legacy` 重启即恢复原判分链路

## 文件清单

- `services/evals-core/src/evals_core/runner/judge_deepeval.py`（DGXJudge + evaluate_via_deepeval）
- `services/evals-core/src/evals_core/runner/answer_eval.py`（EVAL_ENGINE 分发 + question/prediction 透传 + 新维度透传）
- `services/evals-core/src/evals_core/nightly/report.py`（扩展维度 median 列）/ `archive.py`（eval_engine 留痕）/
  `suite_runner.py`（run 汇总 eval_engine）
- `services/evals-core/tests/test_judge_deepeval.py`（11 例）
- `services/evals-core/pyproject.toml`（+deepeval>=4.0.0）、`.env.example`（EVAL_ENGINE/EVAL_DEEPVAL_EXTRA）
