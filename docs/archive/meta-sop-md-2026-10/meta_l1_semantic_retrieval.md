# Meta SOP: L1 语义检索

## 元信息

- **ID**: meta_l1_semantic_retrieval
- **名称**: L1 概念解析 - 语义检索链路
- **描述**: 处理概念解析类问题，通过语义检索获取知识库内容，再由 LLM 生成回答。
- **适用层级**: L1

## 触发条件

用户问题属于概念解析、定义解释、内容理解类，无需精确条款定位或计算。

## 实施步骤

### Step 1: 语义检索

- **Tool**: docs_retrieval
- **Inputs**:
  - query: ${user_query}
  - library_id: ${library_id}
  - doc_ids: ${doc_ids}
  - top_k: 5
- **Outputs**:
  - retrieval_results: result
- **Notes**: 调用 docs-core 语义检索能力，获取与用户问题最相关的知识片段。

### Step 2: 生成回答

- **Tool**: llm_generate
- **Inputs**:
  - query: ${user_query}
  - context: ${retrieval_results}
- **Outputs**:
  - answer: result
- **Notes**: 基于检索结果，调用 LLM 生成自然语言回答。

## Outputs

- answer: 最终回答文本
- retrieval_results: 检索命中的知识片段列表
