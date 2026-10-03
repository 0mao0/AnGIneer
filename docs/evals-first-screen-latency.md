# evals 单题集首屏慢：实测归因与提速改动（2026-10-03）

用户报「0.2.88 部署上去之后，evals 单个测试集的加载还是很慢」。本文是部署机上做的实测归因
与随后的改动记录，数字均为现场实测（部署机 HEAD `b0361625`，即 v0.2.88 + 一处检索热修）。

## 1. 结论

后端不慢，慢在**下载的字节**与**串行往返的次数**：

- 容器内直测所有 evals 接口 `upstream_time` 在 2–330 ms（1040 题的题目列表 170 ms、
  运行明细 light 330 ms），SQL 索引健康（`idx_eval_question_dataset`、`idx_eval_run_detail_run`）；
- 但一次点击题集要发 **6 个串行请求**，gzip 后合计约 730 KB，其中大半是列表页一处都不渲染的字段。

一次点击 5 秒的账（网关日志 14:18:59→14:19:04 实测）：

| 项 | 耗时 | 来源 |
|---|---|---|
| 服务器计算 | 0.56 s | 6 个请求 `upstream_time` 求和 |
| 数据在链路上 | ~2.5 s | 730 KB gzip ÷ 实测 ~276 KB/s |
| 串行往返纯等待 | ~1.9 s | 6 趟 × ~0.3–0.5 s，且 `await` 逐个串联 |

## 2. 载荷分解（容器内逐字段实测，gzip）

| 链路 | 全量 | 列表真正用到 | 无用占比 |
|---|---|---|---|
| 题目列表 `open-ragbench-subset-v4.1`（1040 题） | 253 KB | 70 KB | gold 占原始 1978 KB 的 68%（`retrieval_gold` 1012 KB + `answer_gold` 335 KB） |
| 题目列表 `gdp-pdf-v1`（100 题） | 118 KB | 35 KB | gold 占原始 813 KB 的 84%（`rubric_gold` 437 + `answer_gold` 204 + `retrieval_gold` 45） |
| 运行明细 `?light=1`（1040 题） | 169 KB | 24 KB | `scores` 占原始 1211 KB 的 84%（1015 KB，主体是判分理由长文本） |

## 3. 根因（三条，均挂代码位置）

1. **服务端分页/跨全量筛选（`5e68e1a`）没有前端调用点**：全仓库 `list_questions_page` 只有
   `evals_routes.py` 路由自身一处调用；`useEvalDataset.fetchQuestions` 不传任何参数，
   `EvalQuestionList` 仍是"全量拿回 → 前端 filter → 前端 slice"。
2. **列表级 light（`b9c67b3`）只裁了"展开单题"**：列表走的 `list_run_details(light=True)`
   保留 `scores`；`_strip_heavy_prediction_fields` 只作用于单题详情。
3. **点击链路串行且重复**：`onDatasetSelect` 先 `await` 文档树（只服务于"新增评测"的文档范围选择），
   再串行三个请求；右栏 `EvalRunPanel` 自动选中时的 `ensureDetails` 与 `fetchLastRun`
   各发一次**完全相同**的明细请求（网关日志每次点击都有两条同样的明细 GET）。

## 4. 本次改动（阶段 1–3，均为 opt-in，默认行为不变）

后端（`fields` 参数默认不传即旧行为）：

- `GET /datasets/{id}/questions?fields=summary`：列表投影，只取 UI 渲染的列，八个 gold 列不回传
  （`result_store._QUESTION_SUMMARY_COLUMNS`）；分页路径同样支持。
- `GET /datasets/{id}/questions/{qid}`（新）：单题原文，含 gold——展开/编辑按需取回。
- `GET /runs/{id}?fields=status`：明细投影，只回 `status/quality/error/latency_ms`；
  `light=1` 语义保持不变（单题详情、题集卡等仍按 light 取分）。
- `suite_runner._enrich_run_details` 改走列表投影读题目：补元信息用不到 gold，
  而全量读会把 1040 题的 gold 各解析一遍。

前端：

- `onDatasetSelect` 并行化（`Promise.all`），文档树改为不阻塞 + 过期响应丢弃（token 防串台）。
- `fetchLastRun` 的明细改走 `fetchRunDetails`（pending 去重 + 缓存），消灭重复请求。
- 列表/轮询统一走 `fields=summary` / `fields=status`；展开单题时
  `onQuestionExpandDetail` 同时取回该题完整运行详情与该题 gold 原文。
- `fetchQuestion` **原地合并**进 `questions`：换数组引用会触发 `EvalQuestionList`
  的分页 watch 把用户弹回第 1 页。

预期：1040 题集一次点击 730 KB gzip / 6 趟 → 约 105 KB gzip / 3 趟（`节点树 10 + 题集 1 +
题目列表 70 + 运行列表 2 + 运行明细 24`）。

## 5. 未做（阶段 4）

把 `EvalQuestionList` 的筛选/分页接到服务端（`5e68e1a` 的 SQL 侧能力已就绪），首屏只取
当页 20 行。触发条件：题集规模继续增长、或首屏仍需进一步压缩；需要同步改
"筛选跨全量"的分页交互与题号一致性回归。

## 6. 验证

- `python -m pytest services/evals-core/tests -q`（全量通过，含新增
  `test_list_projection.py`：投影按 `PRAGMA table_info` 推导 gold 列清单，将来新增
  `*_gold` 列而投影漏排除会直接红）
- `python -m pytest tests/unit/test_unit_evals_list_projection_routes.py -q`（7 passed）
- `pnpm --filter @angineer/admin-web build`（vue-tsc + vite 均通过）
- 线上复测（浏览器实际下载量，注意必须带 `--compressed`，否则测的是未压缩体）：

  ```bash
  curl -s --compressed -o /dev/null -w 'size=%{size_download} total=%{time_total}\n' \
    'https://angineer.cn/api/evals/datasets/open-ragbench-subset-v4.1/questions?fields=summary'
  curl -s --compressed -o /dev/null -w 'size=%{size_download} total=%{time_total}\n' \
    'https://angineer.cn/api/evals/runs/<run_id>?fields=status'
  ```

  部署后应看到题目列表 ≈70 KB、运行明细 ≈24 KB（改动前分别是 253 KB / 169 KB）。
