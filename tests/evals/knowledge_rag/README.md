# Knowledge RAG Eval Templates

本目录用于存放 KnowledgeChat RAG 的离线评测样本。

## 文件说明

- `questions.jsonl`
  - 问题主表。
- `gold_retrieval.jsonl`
  - 标准检索命中项；对于拒答样本可留空，表示期望不返回证据。
- `gold_answers.jsonl`
  - 标准答案与必须引用项。
- `gold_sql.jsonl`
  - Text-to-SQL 样本与标准 SQL。
- `eval_retrieval.py`
  - 调用当前知识检索主链并计算 Recall@3、Recall@5、MRR，并额外统计拒答样本的空检索正确率。
- `eval_answer.py`
  - 调用当前知识检索主链并评估回答非空率、必须引用命中率、拒答正确率。

## 使用原则

- 每行一条 JSON 记录。
- `question_id` 必须在四个文件中保持一致。
- 没有对应 SQL 的问题，不需要写入 `gold_sql.jsonl`。
- 优先使用真实文档问题，覆盖命中、表格、定位和拒答等不同场景。
- 多文档样本可在 `doc_ids` 中同时填写多个文档，用于验证跨文档干扰。
- 对于拒答样本，`gold_retrieval.jsonl` 的 `gold_chunk_ids` 应为空数组。
- 对于拒答样本，`gold_answers.jsonl` 需要设置 `refusal_expected: true`。
- 对于重叠条文场景，`gold_chunk_ids` 和 `must_cite_target_ids` 可同时写入多个可接受命中项。

## 运行方式

- 检索评测：
  - `python tests/evals/knowledge_rag/eval_retrieval.py`
- 回答评测：
  - `python tests/evals/knowledge_rag/eval_answer.py`
- 一键运行：
  - `pnpm run eval:knowledge-rag`
