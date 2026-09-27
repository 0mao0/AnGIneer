# 需求：表格检索提速（L2/L3 题 TTFT 的最大单项）

> 状态：**观测完成（2026-09-26 晚，见 §9）——原 §2 根因与 §6 方向经实测修正，动刀口径以 §9 为准**。
> 发现于 2026-09-26 意图分类提速（`docs/req-intent-classify-latency.md`）本地验收期间，
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

## 9. 观测结果（2026-09-26 晚，动刀前基线）

工具与产物：微基准探针 `scripts/obs_table_retrieval_probe.py`（只读，三次独立对照：默认 / `--gc-off` / `--inflate-mb 400`），
数据快照 `data/ops/table-probe-20260926.json`；后端复测走 8791 现役 dev 实例（`logs/p0-decomp.log`）。
除注明「转述」外均为我验证过的实测。

### 9.1 规模曲线（涨幅归因的长期项：成立）

canonical_tables 规模（当前 meta 库 doc→library 映射回溯三份快照）：

| 快照 | 全库表数 | default 库表数 | default 库行数 | default 库 body JSON |
| --- | --- | --- | --- | --- |
| bak-20260822 | 125 | 38 | 297 | 0.02 MB |
| bak-recovery-20260906 | 1027 | 132 | 1347 | 0.26 MB |
| 现库（09-26） | 5373 | 1010 | 9305 | 0.89 MB |

default 库（chat 默认库，26 篇文档）表量 09-06→09-26 增长 **7.6 倍**、行数 **6.9 倍**——线性扫描基数放大
成立，解释「表格段从健康走向爆炸」的长期趋势。补充事实：每文档表数 default 库 p50=33 / p90=91 / max=99
（全库口径 p50=14 / p90=64 / max=116），**160 截断当前不触发**（`fetch_cap160_sum` = 全量表数），
§2「每文档最多 160 表」是真上限而非实际扫描量。

### 9.2 涨幅归因（短期项：3.88s→27.8s 不成立，改判如下）

- 09-21 之后 canonical 库无批量写入（数据文件 mtime 09-21 08:49）、表格链路代码无改动
  （09-20 后仅 c957f63 动 sparse/formula，不触 table）→ **09-24 与 09-26 的库与代码同态，「规模增长」解释不了这两天差值**。
- 「09-24 = 3.88s」第一手出处不可考（仓库内仅存于本文档转述，logs/ 与 git 历史均无此样本）——按转述对待，不作为基线。
- 19:01 三连样本 27.82→14.16→10.84s 递减，符合**进程内表格分支首次执行的冷启动 + 当晚环境负载**叠加；
  稳态值见 §9.3。当晚数值不再作为优化靶的绝对基线。

### 9.3 稳态分解（优化靶：default 库单次 retrieve 4.4~7.0s）

探针 3 条实锤题 × 3 轮（1010 表 / 26 文档，CPU 空闲；GC 关闭与 400MB 堆球囊对照均无差异）：

| 构成 | 实测 | 占比 | 说明 |
| --- | --- | --- | --- |
| **打分（score）** | **3.2~5.6s** | **~70%** | 逐行纯 Python 打分 |
| 整表文本重建（text_build） | 1.1~1.3s | ~20% | 每查询 **10.8k~12.8k 次调用**、去重后仅 920~958 张表（均 13 次/表） |
| SQL（list_canonical_tables） | 0.09~0.16s | <2% | 26 次、共拉 1010 表；单文档 fetchall 4ms（JSON 反序列化另 ~6ms） |

候选爆炸：每查询产出 **10.8k~12.8k 个候选**（row_key 策略逐命中行发候选，每候选携带整表文本），
排序后截断到 60——99.5% 的候选构建是白做的。

cProfile 热点（单次 retrieve，profiler 开销下放大 ~2 倍，比例可信）：

| 函数 | 每查询调用次数 | tottime |
| --- | --- | --- |
| `table_retriever.py:20 normalize_cell` | 631 万 | 3.8s |
| `query_normalizer.py:90`（replace_greek_formula_aliases 生成器步） | 2488 万 | 2.4s |
| `query_normalizer.py:110 normalize_match_text` | 124 万 | 1.9s（cum 12.4s） |

即：**打分大头不是算法差，是同一批表格文本/单元格在每个候选上反复重新归一化**——行文本、单元格、整表文本
全部无缓存，每查询重算百万次级。

### 9.4 打点盲区（验收前提，须先补）

- L2 条款查表题的主路径是 agent 工具 **`table_search` → `table_local_search`**（agent_port.py:149），
  该路径**没有任何检索分段计时**——日志只有 `table_search rerank 计时`（rerank 0.4~0.6s）。
  今晚复测：分类完成 21:49:15 → rerank 日志 21:49:23，中间 ~8s 即 table+formula 检索段，与探针 6.5s+formula 1.2s 吻合。
- `table=` 分段计时只在 agent 恰好走 `knowledge_search` 时出现（19:01 三样本即此路径）；两条路径共用同一个
  `TableRetriever.retrieve`。**动刀第一步：给 `table_local_search` 补与 knowledge_search 同款的分段计时**，
  否则验收 §4.1/§4.4 的前后对照没有口径。

### 9.5 对 §6 方向的修正（按实测性价比重排）

1. **打分产物按表缓存（原 ③ 扩容）**：把 normalize 后的表头/行文本/整表文本（乃至 schema/summary 文本）
   按 `table_id(+version)` 缓存，候选构建复用——**零召回风险**（纯记忆化，候选集不变），直击 ~70% score + ~20% text_build。
   仅缓存 `build_full_table_text`（原 ③）上限 ~1.2s，不足以单独达标。
2. **候选瘦身**：row_key 逐行发候选改按表聚合（保留最佳行元数据），候选数 12k→~1k 量级，构建+排序成本同步崩落。
3. **FTS5/索引化（原 ②）**：若 1+2 后仍不达标再上；改候选集分布，须带 §4.2 逐题召回对照。
4. **keyword LIKE 接线（原 ①）降级**：SQL 段实测仅 <2%（0.1s），且现有 keyword 只覆盖 title/caption/summary
   三列（canonical_sql_store.py:1400），接线收益小、漏召风险大——**不建议**。
5. **④（收窄 doc_nodes）维持原判**：L2/L3 默认全库无 scope 可收窄。

### 9.6 可达性判断

§3 主目标（table= 段 p50 ≤ 2s）：稳态 4.4~7.0s → 方向 1（缓存）预估降到 **~1.5~2.5s**（消除重归一化后
剩 token 化与逐行比对），叠加方向 2 后 **<1s 量级**——达标路径存在，且第 1 步零召回风险可先行。
L2 端到端 ttft 的另一半（30k 级 prompt prefill）不在本需求内。

### 9.7 观测遗留物与清理

- 探针脚本 `scripts/obs_table_retrieval_probe.py`（.gitignore 白名单已加）、
  数据 `data/ops/table-probe-20260926.json`。
- 后端复测产生 3 个测试会话 `obs-table-q1/q2/q3`（chat.sqlite + 内存池，可经 UI 或 GC 清理）。
- 复测用现役 dev 实例（20:02 启动）未动；本文所有后端数据来自 `logs/p0-decomp.log`。

## 10. 实施记录（2026-09-26 深夜，P0 落地）

改动四文件 + 新增回归测试，全部在 docs-core：

- `retrieval/table_retriever.py`：归一化产物按表缓存（`get_table_artifacts`，键=(doc_id, table_id)+内容指纹，
  LRU 8192，线程安全）；四个策略函数改用预归一化 haystack 快路径；行级候选聚合（`ANGINEER_TABLE_ROW_AGG=1`）。
- `retrieval/sparse_retriever.py`：`score_sparse_match` 加可选 `normalized_text` 快路径（不传行为逐位不变）。
- `retrieval/dense_retriever.py`：`score_text` 加可选 `normalized_haystack`/`tokens_pre_normalized` 快路径（同上）。
- `agent_port.py`：`table_local_search` 补分段计时（`table_search 分段计时(本地召回)`）+ 检索器异常 warning，
  对齐 knowledge_search 口径——§9.4 打点盲区已消除。
- 测试 `tests/test_table_retriever_cache.py`：缓存恒等性 / 指纹失效重建 / 聚合每表单候选，3 例全绿。

开关（`.env.example` 已登记注释行，代码默认即行为）：

| 开关 | 默认 | 语义 |
| --- | --- | --- |
| `ANGINEER_TABLE_TEXT_CACHE` | **开** | 纯记忆化；A/B 实测关/开最终候选**逐位一致**（3 实锤题），无需召回对照 |
| `ANGINEER_TABLE_ROW_AGG` | **关** | 改候选分布（top-20 表覆盖 1→20 / 7→20 / 10→20，零丢失）；nightly 对照后再定默认 |

探针对照（default 库 1010 表，3 题 × 3 轮，`data/ops/table-probe-20260926{,-after}.json`）：

| 指标 | 改造前 | 缓存开（warm） | 缓存+聚合（warm） |
| --- | --- | --- | --- |
| wall（3 题） | 4.4~7.0s | 0.95~2.2s（p50≈1.8s） | 0.9~1.8s（p50≈1.6s） |
| build_full_table_text | 1.08~1.28 万次 | **0 次**（首轮 1010=建缓存） | 0 次 |
| 候选产出 | 1.08~1.28 万 | 不变 | **2.4~2.8 千** |

§3 主目标（table= 段 p50≤2s）在探针口径已达标；聚合开关的 nightly 召回对照与 L2 端到端 ttft 复测
（需重启 dev 实例加载新代码——现役实例 reload_dirs 不含 docs-core）为剩余验收项。

回归验证（2026-09-26 深夜）：

- docs-core 套件 407 passed / 16 skipped / 0 failed（含新增 3 例）。
- 根套件（unit+angineer-core+aichat-api 等）1141 passed / **15 failed / 1 error**——失败全数位于
  knowledge_graph（step07 既有 NameError/迁移列缺失）、parse_resume_stages（figure_describe 期望漂移）、
  nightly 路由、parse_records/v1_resume，**与检索链零交集**，定性为干净树既有失败。
- 配方级验证：`table_local_search` 真实节点直调，新分段计时日志生效，
  table= 3.76/2.83/1.47s（首轮含建缓存）+ formula ≈0.9~1.7s，整段 2.4~5.1s（旧路径 ≈8s+）。

真链路验收（2026-09-26 23:08 重启 dev 实例后，用户 UI 实测 3 题；日志 `logs/backend.log` UTF-16LE 段）：

| 题 | table= 段（新） | table= 段（旧基线） | ttft（新） | ttft（旧基线，同晚） |
| --- | --- | --- | --- | --- |
| q1 船型尺度（重启后首个表格查询，冷缓存） | **2.94s**（table_search 路径，含建缓存） | ≈6.5s（探针稳态）/ 27.8s（19:01 样本） | 10858ms | 9359ms |
| q3 水深富裕高度（warm） | **2.61~2.65s**（knowledge_search 与 table_search 两路径各复测一次，一致） | 同上 | 8250ms | 8952ms |
| q2 码头前沿水深计算（L3，turns=2，35k prompt） | —— | —— | 11811ms | 22640ms |

- table= 段降幅实锤：6.5~8s → 2.9s（冷）/ 2.6s（warm），与探针预估一致；formula 0.9~1.7s 不变。
- ttft 读数受晚间 LLM 网关波动污染（同题检索段省了 3s+，但 LLM 首包部分从 ~1s 涨到 ~5s，q1 ttft 反高）——
  **ttft 的干净对照须同分钟 A/B 或白天复测**，单次跨分钟对比不作数；检索段收益以分段计时为准。
- L3 q2 ttft 22640→11811ms（turns 3→2、prompt 62k→35k），幅度大但 L3 多轮方差亦大，留待 nightly 判定。

首字反高的网关侧归因（2026-09-26 深夜，`ai-upstream.log` 实测）：q1 的 35B 答案调用 upstream_time
**2.223s（21:49 基线）→ 4.081s（23:16 复测）**，分类调用 1.7→2.94s——同端点同模型（/api/llm →
127.0.0.1:18004 ssh 隧道，Qwen3.6-35B-A3B），**LLM 服务耗时 +85% 是 ttft 反高的直接原因**（检索段省的
3s+ 被吃掉）。同窗口 llm2 端点（上游 100.86.101.0:8888）并发从 26/min 翻倍到 55~59/min（来源 IP 与
dev 同出口、OpenAI 客户端、单请求 8~15s，呈评测批特征）——负载翻倍与变慢时间窗吻合，但 18004 隧道远端
是否与 llm2 同机未查证，**归因定性为「LLM 服务变慢实锤 + llm2 洪流高嫌疑」而非定论**。

表格路启动预热补齐（同晚）：表格是三条检索路里唯一没有启动预热的一条（a03984f 向量/FTS、c957f63 formula），
且启动预热查询不触发表格分支。新增 `prewarm_table_artifacts(library_id)` 显式遍历建缓存
（default 库 1010 表实测 **1.10s**，warm 后 0.08s），挂入 aichat-api 启动预热线程，失败静默不影响服务；
重启后首个 L2 查表题直接进 warm 档（2.6s），不再有首查冷启动差价。

## 11. 分段计时落盘（方案 E，2026-09-27 凌晨）

> 术语定版（2026-09-27）：请求级的那条并行检索叫「**赌博式预检**」（代码/函数/开关英文用 speculative）；「**启动预热**」专指进程启动时灌缓存（向量/FTS/formula/表格产物，`prewarm_table_artifacts` 等）。两者不再混用。

动机：分段计时（table=/dense=/sparse=/formula=）此前只写 stdout——本机被 PowerShell 转码 UTF-16LE、
服务器随容器重建清零，验收数据获取靠字节级考古（§9 全程实踩）。目标：`tail data/ops/retrieval-*.jsonl` 即得。

**方案 E：数据随返回值上浮，引擎层落盘**（不重新耦合——docs-core 不 import 观测设施，依赖方向零变化）：

```
docs-core（数据生产）                     angineer-core（观测设施消费）
├─ agent_port 两配方返回值加 stage_times   ├─ agent_tools._record_retrieval_stages：
│   （本地召回分支）                        │   pop 选择性消费 → record_event("retrieval")
├─ retrieve_service 响应加 stage_times     │   （本地+HTTP 两分支都接）
│   （HTTP 分支，docs-api 路由透传）        └─ ops_metrics contextvar run_id 自动附带
└─ client.retrieve 返回 (items, stages)        （agent_loop 开跑 set_run_id，包内改动）
```

字段与实测行示例：

```json
{"ts_bj":"2026-09-27T00:05:29+08:00","kind":"retrieval","path":"table_search",
 "stages":{"table":1.7505,"formula":1.4175,"fuse":0.0024},"dur_ms":3170,
 "query":"码头前沿水深富裕高度 散货船 5万吨级 规范","task_type":"table_qa","top_k":20,
 "library_id":"default","run_id":"verify-e2e-01"}
```

边界语义（有意设计）：memo 命中与启动预热路径不经过记录点——没有检索发生就不记假数据；
stage_times 只在瞬时返回值里流转，不进 `_assemble_search_result`、不进 prompt/history（零膨胀）；
旧版 docs-api 容器无该字段时 client 返回 `{}`，调用方静默跳过（跨版本兼容）。

验证：docs-core 413 passed / angineer-core 252 passed（含新增 6 例：contextvar 三态、聚合跳记、
client 元组契约、stage_times 上浮）；端到端一行实写（上方示例行）；现役 dev 实例 23:41 日志实证
「表格归一化产物预热完成: 1010 表，耗时 4.18s」（启动预热在真进程生效）。

记录点边界：memo 命中的调用走壳层提前返回（不进 `_impl`），因此不会重复记录——一次真实检索执行记一条；
注意 route_parallel 的**赌博式预检**是真检索执行（经 memo 壳存入），也会记一条（L1 参数、与分类并行）；
启动预热（main.py 直调 knowledge_local_search）不记录。`data/ops/retrieval-*.jsonl` 可按 `run_id`
与 `ttft-*.jsonl`、`tool-*.jsonl` 关联。

**首跑实踩修复（2026-09-27 00:19）**：真链路首跑发现 retrieval 事件缺 `run_id`——agent_loop 的工具执行走
`ThreadPoolExecutor.submit`（agent_loop.py:484/497），而 **concurrent.futures 不传播 contextvars**
（不同于 asyncio.to_thread），工具线程读不到 loop 线程 set 的 run_id。修复：提交时显式
`contextvars.copy_context().run`（每次 submit 复制一份，同一 Context 对象不可并发 run）；
回归测试 `test_tool_thread_sees_ops_run_id_context` 用红/绿双向验证（无修复必红）。
首跑 live 数据（修复前实例）：table= 段 2.93s（knowledge_search 路）/ 2.98s（table_search 路）——
单条 L2 题两路各跑一次表格检索（赌博式预检路与真实工具调用路），两路均落盘可辨。

**修复后复测（2026-09-27 00:25，三题全表，run_id 修复已生效）**：

| 题 | ttft_ms | 真实工具调用（run_id 可 join） | 赌博式预检路（无 run_id） | table= 段 |
| --- | --- | --- | --- | --- |
| q1 船型尺度（L2） | 9109 | table_search dur 6968ms，table=5.07s | knowledge_search dur 6515ms，table=5.06s | **5.06 / 5.07（并发态）** |
| q2 水深计算（L3） | 10968 | knowledge_search dur 2920ms（formula=1.15，无 table） | knowledge_search dur 4639ms，table=3.23s | 3.23（仅赌博式预检路） |
| q3 富裕高度（L2） | 8282 | table_search dur 4454ms，table=2.77s | knowledge_search dur 4143ms，table=2.73s | 2.73 / 2.77 |

**新发现（待处理）：赌博式预检路与真实表格检索并发互拖（GIL）**——对照 00:19 顺序执行同题（table=2.93/2.98s），
00:25 两路并发时各涨到 5.06/5.07s。两路都在跑全库 1010 表纯 Python 打分，GIL 下无法真并行，只会互相膨胀；
且 L2/L3 题的 memo 键（content_qa vs table_qa）必不命中 → 预检路的表格扫描**纯浪费还拖慢关键路**。

**三角对照（2026-09-27 晨，钉死互拖归因）**：

| 场景 | table= 段 | 说明 |
| --- | --- | --- |
| 独跑（预检被既有条件跳过：短问+有上文） | **1.35s**（短问）/ 2.93s（q1 长问，00:19 顺序） | 真实 table_search 单独执行 |
| 并发（预检路 + 真实路同跑） | **5.06 / 5.07s** | 关键路被拖 ~70% |
| 探针（无后端、纯检索器） | 1.1~2.2s（warm） | 下界参照 |

根因分解（代码锚点）：预检产物只进 `_run_knowledge_search` 的 memo（agent_tools:343，键含 task_type=:291），
而 L2/L3 表题真实调用走 **table_search 工具——无 memo 壳**（直连 `ports.get_table_local_search()`），
结构性永不命中；table 分支的门是 query 文本判据 `_looks_like_table_query`（agent_port:108），
L1 参数的预检照样全库扫表。预检对 L1 概念题是真收益（有验收），对表题纯负担。

候选修法（未实施，先量化「预检关」对照）：A=命中 `_looks_like_table_query` 的查询整条跳过预检
（代价仅为极罕见「表题误分 L1」退回无预检态，无质量损失）；B=预检只跳 table 分支（表题 dense/sparse
同样吃不上，收益≈0）；C=给 table_search 加 memo（预检需预跑 table_qa，双倍浪费，否）。

**修法 A 已落地（2026-09-27 09:05，用户臂2评测收工后切换）**：

- `agent_port` 暴露公开别名 `looks_like_table_query`；`route_pre.fire_first_search_prewarm` 增加跳过门
  （表题整条不发预检），开关 `ANGINEER_SPECULATIVE_SKIP_TABLE` 默认开、=0 回旧行为（.env.example 已登记）。
- 复测四题（同题对照 00:25 预检并发态）：

| 题 | ttft 修复前→后 | table= 段 修复前→后 | 语义验证 |
| --- | --- | --- | --- |
| q1 船型尺度（L2） | 9109 → **6172ms（-32%）** | 5.06（并发互拖）→ **1.77s（独跑）** | 预检未发 ✓ |
| q3 富裕高度（L2） | 8282 → **6030ms（-27%）** | 2.77 → **1.20s（独跑）** | 预检未发 ✓ |
| L1 乘潮水位 | —— | —— | **预检照发（715ms）+ memo 命中（tool dur=0ms）** ✓ |
| q2 水深计算（L3） | 10968 → 13156ms | 3.23（预检白扫）→ 无预检 | turns 2→3、tokens 35k→40k，L3 多轮方差大不可直接比 |

观察与遗留：①L2 两题的 table= 已到独跑档且低于历史顺序值（缓存全暖生效）；②L3 的多轮膨胀
（turns/40k prompt）是另一案（req-chat-history-bloat）；③q2 这类 L3 的预检原本也是白扫（改写查询不命中
memo），表题词表恰好覆盖了它；④启动预热（表格产物缓存）不受影响，照常生效。

**10 题 UI 验收（2026-09-27 09:14~09:18，同日同实例）**：5 道 L2 表格题全部「无预检 + table= 独跑
1.41~2.26s」，其中 3 道单轮题 ttft 6.0~6.8s 档；词表外的条款题（重力式码头抗滑）预检照发、真实调用走
table_search 故 memo 未命中——已知残余（dense/sparse 1.6s，负担轻）。

**用户复核修正（重要）**：Q2/Q5 的双轮检索里，agent 的 knowledge_search 参数实测 =
content_qa + 原查询 + top_k=20——**与预检 memo 键完全一致**，即若预检照发，这两次调用会命中 memo。
但算总账仍是修法 A 占优：预检自身的表格扫描（3.4~5s）+ 与真实 table_search 的 GIL 互拖（+2.3s），
几乎吃光 memo 命中省下的 3.4s（Q2 模式两案检索段 ≈5s 打平），而单调用模式（3/5）稳赚 3s。
真正的大头是 Q2/Q5 ttft 19~22s 中的两轮 LLM + 30k prompt prefill（归 req-chat-history-bloat）；
下一个可选杠杆：同 (query, top_k) 的 table 段扫描结果短 TTL 复用（table_search 与 knowledge_search
同查询共扫一遍），收益对两种模式都为正——未实施。

**Q9 停止归因（用户质疑非本人点击，属实）**：`reason=should_stop` 是 **P4.3 闸门二**自动触发——
`make_budget_stopper(threshold=120_000)`（agent_configs.py:454）在 turn 结束估算 prompt 超 12 万 token
即优雅停止（该 run 实测 107,653 tokens，估算口径偏保守）——历史膨胀活案例，闸门按设计工作。

**思考过程耗时口径补齐（2026-09-27 上午，用户复核截图驱动）**：三处小改——
①进度标签提前切换（`apps/shared/chatTransport.ts`）：`turn_start` 且本 run 已见工具调用即切
「生成回答…」，不再把 LLM prefill 计入「检索规范库（xs）」（实测检索 1.8s 而标签显示 6s）；
②「意图判断」步带分类耗时：`RouteDebug.classify_ms` 新增（route_request 计时）、reason 与耗时合并
同一括号（如「…（依据…；耗时 2.7 秒）」）；
③新增收尾便签「生成完成：总耗时 x.x 秒，首字 x.x 秒（首字前的等待含意图判断、检索与 prompt 读取）」。
第 3 步「首轮直达」无需耗时——它就是第 2 步那次 tool 执行（注入语义说明）；第 4 步「执行计划」是
零耗时决策文本。活体验证：SSE 实测 classify_ms=2661 → note「耗时 2.7 秒」、收尾「总耗时 8.6 秒，
首字 6.9 秒」均如期出现。

**等待标签彻底对齐（同日 11:16，用户三连问驱动）**：①后端在分类开始时即发 stage 帧
（main.py event_stream，SSE 首帧实测为 `{"type":"stage","stage":"classify"}`）——此前首个 SSE 帧要等
分类完成，「意图理解…」标签曾与实际错位（真分类等待显示的是默认「思考中...」）；②transport 识别
stage 帧（chatTransport.ts）；③`BaseChat.progressText` 给「意图理解」「生成回答」也插值秒数
（此前仅检索段带秒数）——生成段的秒数即 prefill 时长。新时序：意图理解（xs，真分类）→ 检索规范库（xs）
→ 生成回答（xs，prefill）→ 首字出、标签撤下。表题无预检故无并行重叠；非表题预检并行在「意图理解」窗内。

**思考步骤耗时标签化（同日中午，用户截图驱动）**：耗时从文案移入结构化字段——`_add_note(detail, duration_ms)`
（agent_loop，SSE 与 run_end 双带）、`AgentLoopConfig.route_note_ms`（分类耗时接线）、生成完成便签带
run 总耗时；`format_route_note` 撤回文案合并。前端：步骤序号后统一渲染「耗时x.x秒」标签
（`ThinkingSteps.vue`，工具结果行里的重复耗时撤掉）、折叠头改为「N 步 · 总耗时 X · 工具 Y」
（总耗时=首末步骤事件墙钟差，`thinkingWallMs`；steps 全量携带 `atMs` 事件时间戳）。
零耗时标记步（首轮直达/执行计划）不渲染标签。实测：意图判断 dur_ms=2344、生成完成 dur_ms=10733 双端可见。

**「你好」异常复核（同日 12:15，用户实测驱动）**：用户一次 L0 闲聊实测 7.3s 后拒答，暴露两处归属缺陷并已修——
①无工具题（L0/直答）等待期标签卡「意图理解…」直到首字（transport 的 turn_start→generate 此前要求
`sawTool`，无工具题永不触发；7.3s 全程显示意图理解、而步骤只记 0.1s），现改为 turn_start 无条件切
「生成回答…」（该轮若调工具 tool_start 会切回检索）；②收尾便签此前要求 ttft 非空，拒绝/吐空收尾时不出账
（那 6.2s 无归属），现除错误/取消外一律出账，无首字时文案「生成结束：本轮未产出首字（按边界规则收尾）」。
复现结论：本机两次「你好」均正常（1.3s/1.8s、首字 0.7/1.4s、正常应答）——用户那次为模型/网关吐空偶发，
非代码路径问题。另：reload watcher 的「N changes detected」在无 .py 变化时也会刷（工作区扫描证实零变化、
进程未重启），属噪声；真 .py 变化才会 Reloading。
