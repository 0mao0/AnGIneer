# 评测卡片增强设计

## 概述

针对评测集 UI 的5项修改，涉及 `EvalQuestionCard.vue` 前端组件和 `evals-core`/`angineer-core` 后端服务。

## 修改清单

### 1. 题目文本可编辑与保存

**范围**：前端 `EvalQuestionCard.vue`

**方案**：
- `eval-question-card__text` 的 `<span>` 改为双击进入编辑模式
- 编辑模式下显示 `<a-textarea>`，失焦或 Ctrl+Enter 保存
- 调用 `PUT /datasets/{dataset_id}/questions/{question_id}` API，更新 `question` 字段
- 通过 `emit('updated')` 通知父组件刷新数据

**后端**：无需改动，API 已支持。

### 2. 分析链路逐步展示

**范围**：后端 `suite_runner.py` + 前端 `EvalQuestionCard.vue`

**方案**：
- 后端：在 `_run_single_question` 执行 `run_prediction` 时，分阶段写入中间结果到 `result_store`
  - 阶段1（意图识别完成）：写入 `prediction.intent`、`stage_timings.intent`
  - 阶段2（检索/SOP路由完成）：写入 `prediction.citations`/`prediction.sop_trace`、`stage_timings.retrieval`
  - 阶段3（Prompt拼装完成）：写入 `stage_timings.prompt`
  - 阶段4（LLM回答完成）：写入完整 prediction，status 改为 completed
- 前端：`thinkingChain` computed 根据 `detail.prediction` 中已有的字段动态生成步骤
  - 有 intent 数据 → 显示步骤1
  - 有 citations 或 sop_trace → 显示步骤2
  - 有 prompt timing → 显示步骤3
  - 有 answer → 显示步骤4
  - 未到达的步骤不显示

### 3. Prompt 拼装计时

**范围**：后端 `dispatcher.py`

**方案**：
- `_dispatch_semantic()` 中，在 Prompt 拼装阶段增加计时 `stage_timings["prompt"]`
- `_dispatch_sop()` 中，已有 `stage_timings["sop_route"]`，补充 SOP 步骤执行计时

**前端**：已支持读取 `stage_timings["prompt"]`，无需改动。

### 4. 移除 L3 关键词校验

**范围**：后端 `sop_eval.py`

**方案**：
- `SopEvaluator.evaluate()` 中，不再执行关键词校验（`evaluate_correctness_check`）
- 直接走 LLM 语义评判，`check_details` 返回空数组
- 前端"正确性校验"区块在 `checkDetails.length === 0` 时不显示（已实现）

### 5. L3 SOP 步骤左右对照展示

**范围**：后端 `dispatcher.py` + `_query_helper.py` + `sop_eval.py` + 前端 `EvalQuestionCard.vue`

**后端方案**：
- `dispatcher.dispatch()` 返回结果增加 `sop_trace` 字段
- `sop_trace` 从 `dispatcher.memory.step_records` 提取，结构：
  ```json
  [{
    "step_id": "step_1",
    "step_name": "查设计船型尺度",
    "tool": "knowledge_search",
    "inputs": {"query": "..."},
    "outputs": {"D": 16.0, "B": 45.0},
    "duration": 1.23,
    "status": "success",
    "error": null
  }]
  ```
- `_query_helper.run_eval_query()` 透传 `sop_trace`
- `SopEvaluator.run_prediction()` 将 `sop_trace` 写入 prediction

**前端方案**：
- 当 `intent_level === 'L3'` 且 `prediction.sop_trace` 存在时，用左右对照布局替代"分析链路"
- 左列：SOP 步骤定义（步骤名、工具、输入描述）
- 右列：实际执行结果（输出值、耗时、状态 ✓/✗）
- 底部：最终答案区域

## 文件改动清单

| 文件 | 改动 |
|------|------|
| `packages/evals-ui/src/components/EvalQuestionCard.vue` | 修改1(可编辑) + 修改2(逐步展示) + 修改5(SOP对照) |
| `services/evals-core/src/evals_core/runner/suite_runner.py` | 修改2(增量写入) |
| `services/evals-core/src/evals_core/runner/sop_eval.py` | 修改4(移除关键词) + 修改5(透传sop_trace) |
| `services/angineer-core/src/angineer_core/dispatcher.py` | 修改3(prompt计时) + 修改5(sop_trace) |
| `services/evals-core/src/evals_core/runner/_query_helper.py` | 修改5(透传sop_trace) |
