# 计划：C1 引擎解耦 Seam 4——agent_tools 检索/图谱配方 → RetrievalPort

> 状态：**代码已落地**（2026-09-19；commit `73f6c3a` 引擎接线+适配器、`bccf08f` 测试改造；未 push。
> 执行偏差：①七端口而非六——`_build_relevant_citations` 执行中发现也依赖 query_normalizer，
> 增 `relevant_citations` 端口；②验收 3 天然满足——引擎 pyproject 本就无 docs-core 依赖；
> ③生产冒烟/nightly 对照/发版待用户授权 push 后部署验证）
> 关系：`docs/plan-service-surface-and-embedding.md` C1「库化准备性重构」的最后一块；
> 模式照抄已验证的 Seam 1-3（`angineer_core/ports.py` 注册表，commit `6d235ce`）
> **边界原则（修订要点）**：端口只切「本地召回配方」一层（五路召回 + fuse + 表格兜底），
> 装配/rerank/引用层留引擎——`_assemble_search_result` 调引擎自己的
> `retrieval_pipeline.rerank_candidates`，HTTP/本地双轨编排用的 `docs_retrieval_client`
> 也是纯引擎模块；这两层若跟着平移会造成 docs-core 反向 import angineer_core，依赖倒挂。

---

## 0. 目标与验收线

**一句话**：`agent_tools.py` 里 ~450 行 docs-core 检索/图谱配方平移进 docs-core 侧适配器
（端口只切「本地召回配方」层；装配/rerank/HTTP 双轨编排留引擎），引擎只留端口调用；平移不改任何逻辑。

**验收（全部满足才算完）**：
1. `rg "docs_core" services/angineer-core/src` → **0 命中**（注释也不留；现存两注释含该字样会挡验收，须顺手改文案：`retrieval_pipeline.py:168`、`policy_query.py:48`）
2. `rg "engtools" services/angineer-core/src` → **0 命中**（本次发现 agent_tools:92 还有第三重耦合，`from engtools.BaseTool import ToolRegistry`）
3. `services/angineer-core/pyproject.toml` 的 `dependencies` 摘掉 `angineer-docs-core` → 只剩 `angineer-ai-inference + pydantic + python-dotenv + requests`
4. `import angineer_core.agent_tools` 实测不加载 docs_core/engtools
5. `tests/angineer-core` + `tests/aichat-api` + `services/evals-core/tests` + `tests/unit` 全绿（`tests/unit` 允许 7 例预存失败：parse_resume_stages×4 / parse_recovery×1 / v1_resume_endpoint×2，stash 干净树对比确认无新增）
6. 生产冒烟：`POST /api/chat/agent` 200 且回答带正常检索引用（配一个知识库内的问题验证，不只闲聊）
7. **nightly 小数据集对照**：跑一轮小数据集（如 `--limit 50`），与最近一份同口径结论比对，无异常回退
8. 用户确认版本号后发版（预计 v0.2.69，定性 **refactor**——全程零行为变化，无 fix）

**非目标（明确不做）**：C2 发版工程（独立仓库/PyPI workflow，chat-history 与引擎各自发 PyPI 是后续独立决策）；docs-core 内部库化；任何检索配方/判分逻辑的行为改动。

---

## 1. 战场清单（精确到行，基于 commit `e047723`）

### 1.1 要搬走的代码（`services/angineer-core/src/angineer_core/agent_tools.py`）

> 行号基于 commit `e047723`，**以函数名为准**（行号易漂）。

| 函数 | 现状位置 | 去向 |
|---|---|---|
| `_looks_like_table_query` + `_TABLE_QUERY_HINTS` | 16-37（仅被配方引用，引擎无其他调用方，已核实） | 随配方一起搬 |
| `_run_knowledge_search` 的**本地召回分支**（291-392：KnowledgeQueryRequest 构建、dense/sparse/clause 三路 + formula/table 条件路、fuse、同 table_id 完整表格文本兜底；含 254 行 query 归一化 import） | 228-392 | docs-core 适配器 `knowledge_local_search(...)` |
| `RetrieverAdapter.table_search` 的**本地召回分支**（587-622） | 543-642 | docs-core 适配器 `table_local_search(...)` |
| `RetrieverAdapter.entity_search` 的**本地图谱直查分支**（681-688：resolve_graph_db_path + GraphStore） | 644-732 | docs-core 适配器 `entity_local_search(...)` |
| `_local_knowledge_stats`（771 起：docs_core.paths 两个路径解析 + 两个 sqlite 直查） | 766-898 | docs-core 适配器 `local_stats(library_id)` |
| `EngtoolAdapter` 内 `from engtools.BaseTool import ToolRegistry`（92，handler 闭包里） | 76-117 | `engtool_registry()` 端口函数 |
| `sop_runner.py:27-30` 模块级 try/except engtools import（`ToolRegistry = None` 兜底） | 25-32 | 同一 `engtool_registry()` 端口——SopRunner 的 BaseTool 直调改经端口取 registry；None 兜底语义保留 |

**留在引擎的**（不动）：
- dataclass 与纯函数：`AgentTool`/`ToolResult`、`MarkerAllocator`、`_assign_cites`/
  `_keep_per_doc_blocks`/`_items_to_evidences`/`_entities_to_evidences`/`_serialize_model`/
  `_serialize_value`、`_context_top_n`。
- **装配层**：`_assemble_search_result` / `_build_relevant_citations`——它们调引擎自己的
  `retrieval_pipeline.rerank_candidates`（Seam 1-3 已端口化降级链），是引擎代码，不是耦合。
- **双轨编排层**：`_run_knowledge_search` / `table_search` / `entity_search` 的
  HTTP 优先分支（`docs_retrieval_client` 是纯引擎模块，已核实零 docs_core import）+
  `local_fallback_disabled()` 硬错误分支 + entity 无实体时回退 `_run_knowledge_search` 的编排。
  这三个函数**整体留在引擎**，只是把本地分支的函数体换成端口调用。
- `_run_knowledge_stats`（735-763，HTTP requests 优先）整体留引擎，本地兜底换端口。
- 四个 Adapter 类外壳（`EngtoolAdapter`/`RetrieverAdapter`/`StatsAdapter`/`SopRunnerAdapter`）。

**明确不存在**：初稿写过 `graph_append_note` 图谱工具——它在 `docs_retrieval_client.py` +
`dream_cycle_routes.py`（aichat-api 侧），不经引擎，**本缝无此端口**。agent_tools 里唯一的
图谱耦合就是 entity_search 的 GraphStore 直查分支（上表）。

### 1.2 引擎侧新增（照抄 Seam 1-3 模式）

`services/angineer-core/src/angineer_core/ports.py` 扩展注册项（现有 `register_local_nodes_loader`/`register_local_rerank` 不动）：

```python
# 查询归一化（中文数字条款号→阿拉伯数字，HTTP 与本地两路共用，须在双轨分叉前调用）
QueryNormalizerFn = Callable[[str], str]
# 知识库本地召回配方：dense/sparse/clause + 条件 formula/table 五路 + fuse + 表格文本兜底。
# 返回 {"items": [...]} 或 {"error": ..., "detail": {...}}（与现 363 行失败语义一致）
KnowledgeLocalSearchFn = Callable[..., Dict[str, Any]]
# 表格/公式本地召回配方，返回语义同上（"表格检索全部失败"）
TableLocalSearchFn = Callable[..., Dict[str, Any]]
# 图谱本地直查：GraphStore 分支（含 resolve_graph_db_path 默认路径解析），返回实体列表
EntityLocalSearchFn = Callable[..., List[Any]]
# _local_knowledge_stats 语义（两个 sqlite 直查聚合）
LocalStatsFn = Callable[[Optional[str]], Dict[str, Any]]
# 返回 engtools ToolRegistry（惰性 import 移入适配器）
EngtoolRegistryFn = Callable[[], Any]

def register_agent_search(normalize_query=None, knowledge_local=None,
                          table_local=None, entity_local=None,
                          local_stats=None, engtool_registry=None): ...
# 各参数允许单独传 None 清除对应项（测试需要）
```

未注册时的降级语义（与 Seam 1-3 一致）：警告 + 空结果/工具不可用，**不 import 具体包、不 raise**。
具体到本缝：
- `normalize_query` 未注册 → 原样返回 query（归一化是命中率优化，非正确性依赖）
- `knowledge_local`/`table_local` 未注册 → 双轨编排的本地分支返回
  `{"error": "本地检索端口未注册"}` 形态（保持现有 error dict 契约，模型侧可消化）
- `entity_local` 未注册 → 返回空实体列表（与图谱无匹配同形，触发既有的正文回退）
- `local_stats` 未注册 → `{"error": ...}`；`engtool_registry` 未注册 → LookupError 同现状
  （`sop_runner` 消费同一端口：`ToolRegistry is None` 时保持现有「ToolRegistry not available」报错路径）

### 1.3 适配器落点（docs-core 侧新建）

`services/docs-core/src/docs_core/step09_query/agent_port.py`：
- 五个配方函数 = 搬家代码 + import 调整（`docs_core.xxx` 全限定改包内相对 import），**逻辑零改动**
- `normalize_query`：包 `query_normalizer.normalize_chinese_clause_numbers`
- `entity_local_search`：包 `resolve_graph_db_path` + `GraphStore`；`KG_DB_PATH` 环境变量回退
  留在引擎编排层（686 行），端口只吃解析好的 `db_path`
- `engtool_registry()`：内部做 `from engtools.BaseTool import ToolRegistry`
- **本文件零 import `angineer_core`**（ai_inference 本来就依赖、可用）——验收 1/2/4 的 rg 与 import 实测会拦

### 1.4 注册点（唯一认识所有实现的地方）

`services/aichat-api/main.py` 的 `_register_engine_ports()`（现有函数，追加注册）。nightly/evals 在 aichat-api 进程内跑，注册一处全cover。

### 1.5 直接消费方（改接线）

- `services/angineer-core/src/angineer_core/agent_configs.py:9`（从 agent_tools import 一批名字——纯名不动）
- `agent_loop.py:28` / `tool_codec.py:12` / `policy_query.py:103`（只用 AgentTool/ToolResult/MarkerAllocator，纯名不动）
- `services/aichat-api/chat_agent.py:76`（MarkerAllocator，不动）

### 1.6 要重写的测试

| 测试 | 处理方式 |
|---|---|
| `services/angineer-core/tests/test_entity_search_dual_track.py` | 测的是双轨编排（fake HTTP client），**留引擎**——编排层没搬；本地直查分支注册 fake `entity_local` |
| `services/angineer-core/tests/test_context_topn.py` | 纯 `_context_top_n` + `_assemble_search_result`——**全留引擎**（装配层没搬），无需改 |
| `tests/angineer-core/test_agent_tools.py` | 配方断言（`_run_knowledge_search`/`_local_knowledge_stats`，127/155/219 行）改注册 fake 适配器；`_assemble_search_result`/`_build_relevant_citations`/`_assign_cites` 断言**原样留**（88/65 行） |
| `tests/angineer-core/test_meta_query.py`（StatsAdapter） | 注册 fake `local_stats` |
| `tests/angineer-core/test_evidence.py` / `test_agent_configs.py` / `test_agent_loop.py` / `test_scope_enforcement.py` 中 mock `docs_core.*` 或 `_run_knowledge_search` 的用例 | 全部改注册 fake（模式参考 `tests/angineer-core/test_retrieval_pipeline.py` 的 `test_rerank_candidates_not_degraded_uses_local`，注意 finally 里清注册防串味） |
| docs-core 侧新增 `tests`（配方本体：五路召回 + fuse + 表格兜底 + stats 聚合） | 从引擎侧测试里把**stub 掉检索器后仍走真实配方**的部分搬过去，语义不变 |

**纪律**：装配层/编排层测试只改「怎么喂实现」，不改断言对象；新增 docs-core 侧测试只覆盖搬过去的配方本体。

---

## 2. 实施顺序（每步独立 commit、独立可部署）

1. **Step 1**：`ports.py` 扩展（六个注册项）+ `agent_port.py` 适配器骨架（先搬 `knowledge_local_search` 一条链：五路召回 + fuse + 表格兜底 + `normalize_query`）+ main.py 注册。引擎 `_run_knowledge_search` 的本地分支改调端口。**跑全量测试**。
2. **Step 2**：`table_local_search` + `entity_local_search` + `local_stats` + `engtool_registry` 四条链照搬（`sop_runner` 的 engtools import 一并改经端口）。引擎内 docs_core/engtools import 清零（含 254 行 query_normalizer——归一化已走端口）。**跑全量测试**。
3. **Step 3**：③收尾——pyproject 摘 `angineer-docs-core`；import 重量实测（`import angineer_core.agent_tools` 不加载 docs_core/engtools）；`Dockerfile.backend` 无需动（`COPY services/ services/` 全覆盖新文件，**.dockerignore 只白名单 scripts，不受影响**）。
4. **Step 4**：全量回归（5 个测试套件）+ 生产冒烟（带检索引用的问题）+ nightly 小数据集对照。
5. **Step 5**：报版本号（预计 v0.2.69）+ 定性依据（**refactor，零行为变化**），**获用户确认后** `pnpm release v0.2.69`。

**git 纪律**：不 push 就没部署；每步 push 前确认工作区除当步文件外无杂散改动（用户的 `KnowledgeStats.vue` WIP 曾两次挡发版——见 `git stash` 处理先例）；commit message 照仓库风格（`refactor(core): ...` 前缀 + 中文 why）。

---

## 3. 环境与操作坑（本会话实踩记录）

- **PowerShell 的 `Set-Content`/`Out-File` 会把 UTF-8 文件写成 GBK**——改含中文的文件一律用编辑工具或 `python` 脚本（`open(..., encoding='utf-8', newline='')`），写完用 `python -c "open(p, encoding='utf-8')"` 验证
- **ssh 传复杂命令/中文/嵌套引号必坏**：脚本一律 base64（`[Convert]::ToBase64String` → `echo <b64> | base64 -d | ...`）；ssh 用 `C:\Windows\System32\OpenSSH\ssh.exe`（Git Bash 的 ssh 有中文 HOME 编码问题）
- **生产验证**：`POST https://angineer.cn/api/chat/guest` 拿 cookie → `POST /api/chat/agent`（body base64 传），判据看 run_end 帧 `payload.messages` 末条 content；部署是否完成看 `gh run list --branch main --limit 1`
- **机械替换话术类字符串后必查「混血串」**（旧尾巴残留，如 `...相关答案支持最终结论`）：用脚本二次清扫再跑测试
- **deploy 会在容器重建瞬间 502**（frontend nginx 已改 `resolver 127.0.0.11` 自愈，属正常窗口）

---

## 4. 背景速览（已完成的前置，勿重复做）

| 项 | commit | 内容 |
|---|---|---|
| ① 惰性 `__init__` | `39bff75` | PEP 562，轻量子模块 import 520ms→29ms |
| Seam 1-3 | `6d235ce` | `ports.py` 注册表 + 节点加载/phrase-rank/线契约三缝 |
| ③部分 | `e048daa` | pyproject 摘 `angineer-sop-core` |
| 拒答话术 | `e047723` | 顺路改动，与解耦无关但动了同一批测试文件，冲突时注意 |

**已验证的回归基线**：`tests/angineer-core`+`tests/aichat-api` = 264 绿；`services/evals-core/tests` = 102 绿；`tests/unit` 7 例预存失败（parse_resume/recovery/v1_resume 一族，时序 flaky，stash 对比法确认无新增）。
