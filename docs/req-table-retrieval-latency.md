# 需求：表格检索提速（L2/L3 题 TTFT 的最大单项）

> 状态：待认领。发现于 2026-09-26 意图分类提速（`docs/req-intent-classify-latency.md`）本地验收期间，
> 与该需求相互独立：分类链路 P0 已落地（同日 commit），本需求针对检索链中的 **table= 段**。
> 验收口径与代码锚点见文末。

## 1. 背景与现状证据

L2 表格题 / L3 计算题的首字延迟 20~45s，逐段计时定位后，大头不在分类（P0 已把快路径/预热做好）、
不在正文检索（dense/sparse 段健康），而在**表格检索段**：

| 检索段 | 实测（2026-09-26 晚，本地、机器空闲） | 判定 |
| --- | --- | --- |
| dense（向量） | 0.85~3.24s | 正常（a03984f 预热生效） |
| sparse（FTS） | 0.09~2.04s | 正常 |
| rerank | 0.6~1.3s/次 | 正常 |
| **table（表格库）** | **10.84s / 14.16s / 27.82s** | **爆炸；历史参照 09-24 = 3.88s（单样本）** |

日志实锤（`logs/p0-retest.log`，19:01~19:02）：

```
19:01:49 knowledge_search 分段计时(本地召回): dense=1.49s sparse=0.70s clause=0.00s table=27.82s fuse=0.01s items=20 query='依据《海港总体设计规范》确定5万吨级散货船的设计船型尺度'
19:02:16 … table=14.16s … query='某5万吨级散货船…试计算码头前沿水深'
19:02:38 … table=10.84s … query='码头前沿水深富裕高度 散货船 5万吨级 规范'
```

用户体感对照（同会话 5 题，`chat-mui9pfcm-qc6p86`）：L2/L3 题 ttft 19938~25390ms，
L1 概念题不进 table 段仅 1250~6625ms——**table 段只在 L2 表格题/L3 计算题触发，是它们 TTFT 的最大单项**。

另注：ttft_ms 的计时起点在 agent 循环开始（`agent_loop.py:856`），不含分类等待；L2/L3 慢的大头就是
table 段 + 30k 级 prompt prefill。本需求修前者；后者（大 prompt/历史膨胀）另案。

## 2. 根因（代码实锤）

`services/docs-core/src/docs_core/step09_query/retrieval/table_retriever.py:283-326` `TableRetriever.retrieve`：

```
for node in doc_nodes:                ← 遍历全库文档（非候选文档）
    list_canonical_tables(doc_id=node.id, keyword=None, limit=max(30, top_k*8))
        ↑ keyword 预筛参数存在但硬传 None —— 钩子留了没接线
    for table in tables:              ← 每文档最多 160 张表全拉
        每表 3~4 种策略逐行纯 Python 打分：
        retrieve_schema_candidates / retrieve_row_key_candidates /
        retrieve_text_row_candidates / retrieve_summary_candidate
        且每个候选都重新 build_full_table_text(table)（整表文本反复重建）
```

无索引、无分页、无预筛，O(全库文档 × 表 × 行) 线性扫描。当年 a03984f 的分页/预热优化
只覆盖了向量矩阵与 FTS（dense/sparse），表格路是漏网的第三条路。

涨幅归因（3.88s→27.8s）待证：最可能是库内表量/文档规模增长（v4 数据集 188 篇、素材重建等）
放大了扫描基数；历史样本仅 1 条，**动刀前先补观测**。

## 3. 目标

- **主目标**：`table=` 段 p50 ≤ 2s（回到与 dense/sparse 同量级）。
- **分解目标**：L2 表格题端到端 ttft 显著下降（对照基线见 §6）。
- **不追求**：L1 概念题（不受此段影响）；答案 LLM prefill（另案）。

## 4. 验收标准

1. 分段计时 `table=` 段：同题本地实测 p50 ≤ 2s（≥3 轮）。
2. **召回质量不劣化**：nightly 整体与表格相关题（查表/取值类）命中不低于基线；keyword 预筛 /
   索引化不得缩小召回集导致漏召（逐题对照候选集）。
3. 新增行为有开关，默认值经实测后再定。
4. 一份实测报告：改动前后 table= 段分布、L2 表格题 ttft 对照、召回对照。

## 5. 复现与数据入口

- 本地复现：起 dev 后端（docs-api 8790 + aichat-api 8791），发 L2 表格题
  （如「依据《海港总体设计规范》确定5万吨级散货船的设计船型尺度」），grep 分段计时。
- 日志锚点：`docs_core.step09_query.agent_port | knowledge_search 分段计时(本地召回)`、
  `retrieve_service | retrieve_knowledge 分段计时`、`angineer_core.agent_tools | knowledge_search rerank 计时`。
- TTFT 口径：只认 `agent run TTFT ... ttft_ms`（不含分类等待）；观测落盘 `data/ops/ttft-*.jsonl`。
- 已知坑：本地 uvicorn dev 带 `--reload`，Windows 下杀进程要连 spawn worker 一起杀（孤儿 worker
  占 8791 会把请求打到旧代码，plan-ttft-improvement §8.5 同款）。
- 规模参照：库内 canonical 表 ~5554 张（2026-09 表格体检口径）。

## 6. 建议方向（按性价比排）

1. **接上 keyword 预筛**（钩子现成）：`list_canonical_tables` 的 keyword 传查询关键词做 SQL 级预筛，
   不再每文档全拉 160 表。
2. **表级文本建 FTS5 索引**：schema/row_key/summary 文本入索引，打分前置到 SQL——与 dense/sparse 同款待遇。
3. **`build_full_table_text` 按表缓存**：每候选重建整表文本是纯浪费，表内容不变可缓存。
4. **复查 doc_nodes 圈定**：确认是否必须全库遍历；scope 有 library_id/doc_ids 时按范围收窄。

## 7. 约束与风险

- **不许为快牺牲召回**：预筛/索引改变候选集分布，nightly 与表格题专项必须对照（同意图分类提速需求的教训）。
- 动刀前先补观测：分段计时已在，先跑一轮采集 table= 分布与表库规模曲线，把「3.88s→27.8s」的涨幅归因钉死。
- 开关可回退；口径只认分段计时与 ttft_ms，别拿端到端墙钟顶替。

## 8. 交付物

- 代码改动 + 开关 + 分段计时对照脚本。
- 实测报告：table= 段前后分布、L2 表格题 ttft 对照、召回逐题对照、表库规模与涨幅归因。
- 若结论是「收益不足/风险过大」也接受——量化证据留档即可。
