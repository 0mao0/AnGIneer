# Meta SOP: L2 条款查找

## 元信息

- **ID**: meta_l2_clause_lookup
- **名称**: L2 条款应用 - SQL 优先检索链路
- **描述**: 处理条款应用类问题，优先通过 SQL 检索定位条款，SQL 失败或召回不足时回退到语义检索，最后由 LLM 生成回答。
- **适用层级**: L2

## 触发条件

用户问题涉及条款取值、章节内容、规范参数等，需要精确定位到具体条款或表格行。

## 实施步骤

### Step 1: SQL 检索

- **Tool**: docs_sql
- **Inputs**:
  - query: ${user_query}
  - library_id: ${library_id}
  - doc_ids: ${doc_ids}
- **Outputs**:
  - sql_results: result
  - sql_success: sql_success
- **Notes**: 优先调用 docs-core 的 Text2SQL / SQL 检索能力，利用 canonical 业务字段（clause_id, entity_tags, conditions, exam_tags）做精确过滤。

### Step 2: 语义检索托底

- **Tool**: docs_retrieval
- **Inputs**:
  - query: ${user_query}
  - library_id: ${library_id}
  - doc_ids: ${doc_ids}
  - top_k: 5
- **Outputs**:
  - retrieval_results: result
- **Notes**: 当 SQL 检索失败或召回不足时，回退到语义检索作为托底。

### Step 3: 生成回答

- **Tool**: llm_generate
- **Inputs**:
  - query: ${user_query}
  - sql_context: ${sql_results}
  - retrieval_context: ${retrieval_results}
- **Outputs**:
  - answer: result
- **Notes**: 基于 SQL 检索结果和语义检索结果，调用 LLM 生成回答。优先使用 SQL 结果，语义检索结果作为补充。

## Outputs

- answer: 最终回答文本
- sql_results: SQL 检索结果
- retrieval_results: 语义检索结果（托底）
- sql_success: SQL 检索是否成功
