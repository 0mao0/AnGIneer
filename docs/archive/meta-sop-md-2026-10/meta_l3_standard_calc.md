# Meta SOP: L3 标准计算

## 元信息

- **ID**: meta_l3_standard_calc
- **名称**: L3 标准计算 - SOP 识别与执行链路
- **描述**: 处理标准计算类问题，先检索定位标准/公式，匹配 sop-core 中的标准 SOP，执行计算后由 LLM 生成回答。
- **适用层级**: L3

## 触发条件

用户问题涉及已知参数的具体计算，且存在预定义的工程 SOP 可承接。

## 实施步骤

### Step 1: 标准/公式检索定位

- **Tool**: docs_retrieval
- **Inputs**:
  - query: ${user_query}
  - library_id: ${library_id}
  - doc_ids: ${doc_ids}
  - top_k: 3
- **Outputs**:
  - formula_context: result
- **Notes**: 调用 docs-core 检索能力，定位与用户问题相关的标准条文和公式。

### Step 2: 匹配标准 SOP

- **Tool**: sop_match
- **Inputs**:
  - query: ${user_query}
  - formula_context: ${formula_context}
  - parameters: ${parameters}
- **Outputs**:
  - matched_sop_id: result
  - sop_args: sop_args
- **Notes**: 根据检索到的公式上下文和用户提供的参数，匹配 sop-core 中的标准 SOP。

### Step 3: 执行标准 SOP 计算

- **Tool**: sop_run
- **Inputs**:
  - sop_id: ${matched_sop_id}
  - args: ${sop_args}
- **Outputs**:
  - calc_result: result
- **Notes**: 调用 sop-core 执行标准 SOP 计算，获取计算结果。

### Step 4: 生成回答

- **Tool**: llm_generate
- **Inputs**:
  - query: ${user_query}
  - formula_context: ${formula_context}
  - calc_result: ${calc_result}
- **Outputs**:
  - answer: result
- **Notes**: 基于公式上下文和计算结果，调用 LLM 生成包含计算过程的自然语言回答。

## Outputs

- answer: 最终回答文本
- formula_context: 检索到的公式/标准上下文
- matched_sop_id: 匹配到的标准 SOP ID
- calc_result: 计算结果
