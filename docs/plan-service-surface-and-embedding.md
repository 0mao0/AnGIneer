# 计划 A + C1：服务化补全与嵌入式库化准备

> 状态：**第一批已执行**（2026-09-09，A1 内部解耦 + auth 收敛 + PoPo 内化 + B 项审查）；
> **A2/A3/C1 注入重构降级为触发式待命**（评审结论：DredgeAI 规范问答仍是前端 mock，无真实消费者，
> 不建空转的对外承诺面；触发条件 = DredgeAI 真要接入问答/检索/嵌入解析时）。
> 范围说明：本计划只做**服务面补全（A）**与**库化准备性重构（C1）**；
> 不发布任何新 PyPI 包（触发式，见 §5），不改向量引擎（计划 B 已完成）。

---

## 0. 已拍板的决策记录（不再讨论）

| # | 决策 | 理由 |
|---|---|---|
| D1 | **数据归属原则**：文档归属谁，解析就在谁那边跑 | DredgeAI 私有任务文档 → 本地解析合理；公共规范库 → 留 AnGIneer 中心化。两边都要的文档 = 双份演化坏味道，禁止 |
| D2 | **向量引擎唯一路径 = Qdrant** | 中心化与嵌入式同构（消费方 compose 加一个 sidecar 容器，实测 RSS 42–157MB）；sqlite 暴力矩阵在万本规模有内存悬崖，不得作为嵌入式推荐 |
| D3 | SQLiteVectorStore 的角色 | ① 生产回滚保险丝（一个发版周期）② 单测 fixture。**不进任何面向消费方的文档**；canonical_vectors 表下个版本 DROP+VACUUM |
| D4 | DredgeAI 集成：HTTP 为主，PyPI 库为备 | C# 业务后端只能 HTTP；其 Python 服务层（ai-gateway/compare-algo 等）可 pip |
| D5 | PoPo 内化进主仓库 | 上游最后提交 2026-07-31、定制 PR 从未被收、fork 是唯一部署源头 |
| D6 | 内网 → angineer.cn 出访已确认可行 | DredgeAI 生产可直接消费 AnGIneer 公网服务，无需内网再部署一套 |

---

## 1. 计划 A：HTTP 服务面补全（预计 2–3 天）

> **2026-09-09 评审更新**：A1 已执行完毕（见下「已执行」标注）；**A2/A3 降级为触发式待命**——
> DredgeAI 的规范问答/知识库页面仍是前端 mock，无真实消费者，现在建对外 API 是空转的承诺面。
> 触发条件：DredgeAI 真要接入问答/检索（aichat-ui 后端接通）时启动 A2+A3。

**目的**：让 DredgeAI（及未来任何应用）只用 HTTP + API key 完整消费解析/检索/问答能力，
消灭"跨服务直读 SQLite"的共享数据库反模式。

### A1 内部解耦（消灭跨进程直读）✅ 已执行（2026-09-09）

| 改动 | 位置 | 内容 |
|---|---|---|
| 新增内部端点 | `services/docs-api/retrieve_routes.py` | `POST /api/knowledge/internal/entity-search`（薄封装 GraphStore.search_entities，scope 透传）、`GET /api/knowledge/internal/doc-nodes?library_id=`（文档节点清单） |
| 客户端扩展 | `angineer-core/docs_retrieval_client.py` | 增加 `entity_search()` / `list_doc_nodes()` 方法 |
| 改双轨 | `angineer-core/agent_tools.py:659-665`（entity_search）、`policy_query.py:17-30`（_load_doc_nodes） | HTTP 优先、本地回退（与 knowledge_search 现有策略一致） |
| 加开关 | `ANGINEER_DISABLE_LOCAL_FALLBACK=1` | 服务化部署时强制全 HTTP；本地直查仅留作单进程降级兜底 |
| 收编裸连接 | `aichat-api/dream_cycle_routes.py:164,182` | 裸 `sqlite3.connect` 图谱库改走 docs-api 端点 |

**验收**：设 `ANGINEER_DOCS_API_URL` + `ANGINEER_DISABLE_LOCAL_FALLBACK=1`，
nightly「立即运行」小数据集全程无 fallback 告警日志。

**A1 执行结果（2026-09-09）**：retrieve_routes.py 新增 entity-search / doc-nodes / graph-append-note
三个内部端点；docs_retrieval_client 增加同名三方法 + `local_fallback_disabled()` 开关；
agent_tools.entity_search、policy_query._load_doc_nodes、_run_knowledge_stats、dream_cycle 孤儿实体
两处裸连接全部改为 HTTP 优先 + 开关可禁回退；新增 test_entity_search_dual_track.py 7 例全绿。

### A2 对外 API 面（v1 + API key）⏸️ 触发式待命

| 改动 | 位置 | 内容 |
|---|---|---|
| 对外检索 | docs-api | `POST /api/v1/knowledge/retrieve`，API key scope 强制限定 library，复用 internal/retrieve 的 service 层 |
| 对外问答 | aichat-api | `POST /api/v1/chat`（非 SSE 请求-响应形态 + 可选 SSE），内部走同一条 `run_policy_query` 链路（评测已验证的单一真相源），API key 绑 library |
| 合并漂移代码 ✅ 已执行（2026-09-09） | `aichat-api/models/` ↔ `docs-api/models/` | user/api_key 模型收敛到 `services/shared`（`shared/user_model.py` / `shared/api_key_model.py`，新增 `shared/paths.py` 数据路径解析）；两侧 `models/` 改为模块替换别名层（import 与 patch 语义不变）；中间件保持各自独立（路由策略本就不同：aichat 有 /api/chat/* 可选鉴权）。顺带清除 api_key.update_key 尾部死代码 |
| 集成契约文档 | `docs/integration-api.md` | 端点清单、鉴权头、scope 语义、错误码、产物格式——交付给 DredgeAI 的唯一对接文档 |

### A3 客户端 SDK 包：`angineer-docs-client`

- 内容：`RetrievedItem` 等 pydantic 契约 + HTTP 客户端（retrieve / stats / entity_search / doc-nodes / chat 五组方法）
- 定位：A2 服务端的**官方 Python 客户端**（OpenAI 模式：服务端 + pip SDK）；C# 侧不受影响，继续手写薄客户端
- 同时把 **embedding/reranker 客户端补进 `angineer-ai-inference`**（目前散落 docs-core/angineer-core，DredgeAI ai-gateway 做 RAG 时缺这两个件）
- 发布：走已验证链路（worktree → tag 映射 → OIDC trusted publishing 上 PyPI）

---

## 2. 计划 C1：嵌入式库化准备性重构（预计 2 天，不发布）⏸️ 触发式待命（PoPo 内化除外）

> **2026-09-09 评审更新**：PoPo 内化已执行（独立价值：摆脱 submodule 维护负担）；
> 其余注入重构（单例/路径/闸门/依赖卫生/evals 路径）降级为触发式——等第一个真实嵌入需求。

**目的**：让 docs-core + angineer-core 达到"可打包"状态（配置注入、无隐式全局态、
无 monorepo 布局假设）。这些重构对 AnGIneer 自身也是净化，不白做。
**做完不发布**——发布即承诺兼容性，等第一个真实嵌入需求出现再发（§5 触发式）。

| 改动 | 位置 | 内容 |
|---|---|---|
| PoPo 内化 ✅ 已执行（2026-09-09） | `services/docs-core/src/popo` | submodule 壳已删、2371 文件直接入库；`UPSTREAM_SYNC.md` 记录上游同步点（97d5601）；AGENTS.md 双 remote 段落已改写为"已内化"；deploy.yml 的 submodule update 已移除 |
| 单例注入 | `parse_pipeline.py` 等 ~10 处 | `get_docs_service()` 隐式调用 → `StageContext` 显式字段 |
| 路径注入 | `docs_core/paths.py:36-46` | 解析顺序改为：显式构造参数 > env > monorepo 探测 |
| 闸门可注入 | `parse_pipeline.py:598-665` | `_MINERU_GPU_GATE`/`_POPO_GATE`/`_FIGURE_DESCRIBE_GATE` 模块级单例 → 可注入实例（默认行为不变） |
| 依赖卫生 | `docs-core/pyproject.toml` | chromadb 拆 extra（当前 provider 默认早已不是它）；补声明 `angineer-ai-inference`（现用而不声明，靠环境碰巧装上） |
| evals 路径修复 | `evals-core/storage/result_store.py:11` | `__file__` 上推 5 层定位改为显式 db_path 注入（包安装到 site-packages 后必失效的硬伤） |

**验收**：docs-core 全量测试通过 + 本地解析一篇 PDF 冒烟通过 + 服务器解析一篇无回归。

**PoPo 内化的部署注意（已处理）**：deploy.yml 的 `git submodule update --init --recursive` 已移除
（仓库无 submodule 后其为 no-op）；服务器端 `git reset --hard` 跨越"submodule→普通目录"边界的行为
已在部署时实测验证（首次部署后目录内容正常、docs-core 329 测试全绿）。

**B 项审查结果（2026-09-09）**：全仓 grep import 期 DB/网络调用，仅剩 `embedding_provider.py` 模块级
`create_default_embedding_provider()`（含维度探测）一处——Qdrant 下为 O(1) HTTP collection 查询、
try/except 兜底不致命，相比 v0.2.34 的全表表决已无量级问题，保留现状并登记观察。

---

## 3. 执行顺序与依赖

```
A1（内部解耦）──▶ A2（对外 API 面）──▶ A3（SDK 包 + ai-inference 扩充）
                                          │
C1（库化准备）◀── A1 合并后开工（同改 agent_tools/检索边界，避免冲突）
```

- A1 先行合并：它动的检索调用边界与 C1 的单例注入是同一批文件
- A2/A3 与 C1 可并行（A2/A3 在 API 层，C1 在 docs-core 内核）
- 每阶段独立发版（按发版约定三处同步）

---

## 4. 风险与回滚

| 风险 | 缓解 |
|---|---|
| auth 合并影响登录态 | 合并后跑两侧现有 auth 相关测试 + 手工登录/退出冒烟；用户表不动 |
| PoPo 内化后部署链路 submodule 逻辑残留 | 先在服务器验证 git pull 行为，再合入；内化与部署验证同一窗口完成 |
| 嵌入式侧向量选型误导 | 集成文档只写 `provider=qdrant + sidecar`；sqlite provider 不出现在消费方文档 |
| 嵌入式 KB 与中心 KB 分裂 | D1 数据归属原则写入集成文档开头；跨边界的文档一律走 HTTP 集中解析 |

---

## 5. 触发式后续（不在本计划，仅登记）

| 项 | 触发条件 |
|---|---|
| C2：依赖闭包发 PyPI（angineer-docs-core / angineer-core / sop-core / tree-core） | DredgeAI 或其他应用**第一个真实嵌入需求**出现 |
| QA 引擎库化（RetrievalPort 抽象收尾） | 随 C2 顺势完成（存储已同进程，工作量主要是打包） |
| canonical_vectors 表 DROP + VACUUM | ~~下个版本（v0.2.42），回收 ~5GB~~ **已于 2026-09-09 提前执行完成**（5.0G→1.7G，nightly 验收无回归后用户豁免观察期）；回滚路径变更为 rebuild_vectors.py 重嵌回填 |
| evals.sqlite（已 1.2GB）保留策略 | 单独 backlog，不紧急 |
| DredgeAI 侧配合 | .env 已全部换 https（done）；Jenkins 凭据 LLM_CONFIGS 换 https（待用户操作）；L2/L3 对接待 A2 交付 |
