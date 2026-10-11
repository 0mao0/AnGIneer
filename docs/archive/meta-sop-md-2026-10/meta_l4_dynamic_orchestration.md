# Meta SOP: L4 动态编排

## 元信息

- **ID**: meta_l4_dynamic_orchestration
- **名称**: L4 复杂计算 - 动态编排链路
- **描述**: 处理无预定义工程 SOP 的复杂/复合任务，由 Dispatcher 动态分解子问题、循环调用多种能力（docs-core、sop-core、engtools、LLM）完成。
- **适用层级**: L4

## 触发条件

用户问题为复杂计算或复合任务，没有现成单一工程 SOP 可承接，需要动态组合多种能力。

## 实施步骤

### Step 1: 问题分解

- **Tool**: llm_generate
- **Inputs**:
  - query: ${user_query}
  - task: decompose
- **Outputs**:
  - sub_problems: result
- **Notes**: 调用 LLM 将复杂问题分解为多个子问题，每个子问题可由单一能力处理。

### Step 2: 逐个子问题处理

- **Tool**: auto
- **Inputs**:
  - sub_problems: ${sub_problems}
  - library_id: ${library_id}
  - doc_ids: ${doc_ids}
- **Outputs**:
  - sub_results: result
- **Notes**: 对每个子问题，由 Dispatcher 动态选择 docs_retrieval、docs_sql、sop_run、calculator 等工具执行。支持多轮循环，直到所有子问题解决。

### Step 3: 结果融合与回答生成

- **Tool**: llm_generate
- **Inputs**:
  - query: ${user_query}
  - sub_results: ${sub_results}
- **Outputs**:
  - answer: result
- **Notes**: 将所有子问题的结果融合，调用 LLM 生成完整的自然语言回答。

## Outputs

- answer: 最终回答文本
- sub_problems: 分解的子问题列表
- sub_results: 各子问题的处理结果
