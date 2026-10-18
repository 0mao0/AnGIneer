# 运维参数可视化设置系统 · 设计稿

> 2026-10-17 定稿（用户已确认架构方向与分期范围）；同日专家评审修订：首注时序与快照基线、bool canonical 序列化（§2.2-G）、nginx 改容器层、source=env 拒绝码、EMBEDDING 维度探比、间接读白名单、包归属补齐。本文所有文件:行号均为当日实测（含评审纠错的 parse_pipeline.py:1292），作为实施依据。

## 0. 背景与目标

生产运维参数现状（实测证据见 §10）：

| 痛点 | 事实 |
|---|---|
| 参数散落无目录 | 代码读点 202 个环境变量、236 处（2026-10-18 扫 `services/` 去 `.venv` 实测），`.env.example` 模板（247 行）只登常用集，无全量中文解释目录 |
| 改动成本高 | env_file 在容器创建时固化，改参数 = SSH 改 .env + `docker compose up -d` 重建（docker-compose.yml:33-34 等三处）；曾因 `restart` 不读新 env 致评测 915 题秒败（2026-09-25 实踩） |
| 生效时机不明 | 读法三档并存：import 期固化 / 懒单例 / 每请求动态，运维无法预判改完何时生效 |
| 无可视化面板 | admin 后台无任何参数页面 |

**目标**：adminweb 新增「设置」页（左菜单：参数设置 / 用户管理 / API 管理），参数设置建立 `data/platform/settings.json` 覆盖层，实现：

1. 参数目录全量登记（中文解释 + 三值视图：代码默认 / .env 当前 / settings 覆盖）
2. 业务运维旋钮页面双向编辑、热生效（不改 .env、不重建容器）
3. 五类模型配置（*_CONFIGS）页面编辑 + 热替换 + 保存前探针
4. `.env` 层参数只读展示 + 修改指引
5. 防遗漏：registry 防漂移校验脚本

**用户拍板记录**：
- 范围 = 旋钮 + **全部五件套 CONFIGS 页面编辑**（EMBEDDING 热替换一并本期内做）
- 覆盖范围 = 活跃变量全量登记（含防漂移脚本），测试夹具/脚本专用不登
- 本期不瘦身 .env（二期滚动迁移读点后再缩到基础设施）

## 1. 页面 IA 与路由（apps/admin-web）

```
adminweb header
  [设置按钮] ──→ /settings（嵌套路由，左菜单同页切换）
                   ├ ① 参数设置  /settings/params     （本期新增）
                   ├ ② 用户管理  /settings/users      （现 /users 迁入）
                   └ ③ API 管理  /settings/api-keys   （现 /api-keys 迁入）
```

改造点：

| 位置 | 现状（行号） | 改造 |
|---|---|---|
| `apps/admin-web/src/App.vue:28-33` | API 管理（文本按钮）+ 用户管理（TeamOutlined）经 `#user-menu` slot 注入 header | 两个按钮移除（迁入 /settings 左菜单） |
| `packages/ui-kit/src/components/layout/AppHeader.vue:121-123,172,206` | 已预留 `showSettings` prop + `settings-click` emit，未启用 | 启用：admin 布局下传 `showSettings`，点击跳 `/settings`；设置页内高亮设置按钮 |
| `apps/admin-web/src/router/index.ts` | 平铺单层路由 | `/settings/:tab(users|api-keys|params)` 嵌套；旧 `/users`、`/api-keys` 保留 redirect 到新路径（无外部书签依赖，admin 内部入口而已） |
| `apps/admin-web/src/App.vue:131-133` | UserManage/ApiKeyManage 显式不 KeepAlive | 维持不变（迁路由不迁语义：管理页改完即走） |
| `apps/admin-web/src/App.vue:136-141` | moduleItems = 项目库/知识库/经验库/评测集 | 不动（settings 不属于任何模块；activeModule 对 /settings/* 返回空串即可） |
| header 右上 AI 对话/架构图按钮（App.vue:22-27） | 保留 | 保留 |

左菜单做法：`/settings` 页内静态窄栏组件（native 路由高亮 + antd List/Menu），**不引** ui-kit SplitPanes（工作区分栏诉求不存在，只做导航栏）。

权限：adminweb 已有 AuthGate 全屏登录门（session token，非 admin 拒绝），设置页天然 admin-only，后端接口同样校验 admin（见 §5）。

## 2. 参数目录 registry（单一真相源）

文件：`services/shared/src/shared/settings_registry.py`（纯 Python 数据模块）。

### 2.1 登记口径

| 范围 | 处理 |
|---|---|
| `ANGINEER_*` 活跃变量 84 个（2026-10-18 实测） | 全量登记，按功能分组（约 7 组：路由与预检 / 证据上桌与预算 / 对话与 SOP / LLM 客户端运行参数 / 鉴权与游客 / 日志与观测 / 其它散项） |
| 五件套 `LLM/MINERU/POPO/EMBEDDING/RERANKER_CONFIGS` + `EVAL_JUDGE_CONFIGS` | 登记，单列「模型配置」组，编辑体验特殊（§4-B） |
| `NIGHTLY_*` / `WEBHOOK_*` / `NIGHTLY_SITE_URL` 等 | 登记（运行效果归评测组） |
| `DOCS_*` / `QDRANT_*` / `CHAT_DB_PATH` / `API_KEYS_DB_PATH` 等基础设施 | 登记，`source=env` 只读（改 .env 需重建容器，页面展示指引） |
| 路径散项（KNOWLEDGE_BASE_DIR、PARSE_RECORDS_DB_PATH、SOP_DATA_DIR 等） | 登记，只读 |
| 测试夹具专用（`TEST_LLM_CONFIG`、`QDRANT_TEST_URL` 等）、scripts 一次性探针、`VITE_*` 构建期注入 | **不登**（豁免白名单由防漂移脚本内置维护，见 §2.3） |

### 2.2 schema

```python
SettingSpec = {
  "name": str,            # 变量名，如 ANGINEER_CONTEXT_TOP_N
  "group": str,           # 组 id
  "desc": str,            # 中文解释（含定值依据，自带指向代码读点线索）
  "default": str|None,    # 代码默认值（无默认=未设时行为描述写进 desc）
  "type": "bool|int|float|str|json",  # secret 值一律按 str；敏感性由 sensitivity 单独决定
  "source": "settings|env",   # settings=页面可写；env=只读展示
  "sensitivity": "public|secret",  # secret：api_key/token 类，脱敏展示、密文输入框
  "effective": "live|lazy|restart", # live=动态读热生效；lazy=懒单例（有热换口则等效 live）；restart=需重建容器
  "bool_style": "zero_pad|word",    # 仅 type=bool：false 态序列化口径（见 §2.2/G）；true 态统一 "true"
  "related": list[str],   # 牵连提示 key（如 EMBEDDING→存量向量维度警示、GUEST_ROUNDS→guest_settings.json 钉死规则）
}
```

### 2.2-G canonical 序列化（os.environ 注入的唯一形态）

os.environ 只装字符串，registry 必须定死每类 canonical 形式，PUT 校验层**统一序列化后再落盘/注入**（前端永不直接塞原文）：

| type | canonical | 实测验算依据 |
|---|---|---|
| bool | `true`→统一 `"true"`；`false`→按条目 `bool_style` 输出 `"0"` 或 `"false"` | true 态 `"true"` 三类读点全命中：route_pre in ("true","1","yes","on")✓；mineru_parser.py:147 `!= '0'`✓；其 :148 `== 'true'`✓。false 态**无万能串**（`"0"` 会被 `=='true'` 类读对、`"false"` 会被 `!='0'` 类读反——mineru_parser.py:147 注入 `"false"` 即被读成 True）→ 按条目登记时实测就近读点口径：`!='0'` 类登 `zero_pad`（如 MINERU_PROXY_FALLBACK_ENABLED），`=='true'` 类登 `word`（如 MINERU_OCR_ENABLED），in 序列类两者皆通、取 `word` |
| int/float | `str(value)` | 所有读点都是 int()/float() 包裹 |
| json | `json.dumps(obj, ensure_ascii=False)` | 五件套 CONFIGS 等 |
| str/secret | 原文（secret 明文不回显） | — |

`effective` 判定依据（实测）：
- `live`：每请求/每调用动态读（route_pre.py:27-91、agent_tools.py:19-151/449-461、middleware/api_key_auth.py:57、guest_settings.py、popo model_utils.py:69-97 每推理、figure_describer.py 每图、answer_eval.py:94-114 每判分）
- `lazy`：懒单例（llm_client.py:1595-1611 首建后缓存；base_config.py:158-166 get_config 缓存）——凡本设计已接热换口（§4-B）的 lazy 项，展示等效「live（有热换口）」，否则标 restart
- `restart`：import 期固化（parse_pipeline.py:661-704,799-808 闸门与分流权重、kb_migration_routes.py:141-151、各 *_DB_PATH、CORS）

### 2.3 防遗漏 / 防漂移（机械保证）

`scripts/check_settings_registry.py`：
1. 扫 `services/**` 两类字面量读点（`os.getenv(...)` / `os.environ` 与 helper `_get_env_*("NAME")`；排除 `tests/`、`.venv`/`site-packages`、构建产物）→ 提取变量名集合 A
2. 与 registry 全集 B 对比：`A - B` = 「代码在读但未登记」→ 报错退出（CI/dev 可跑）
3. 豁免白名单（测试夹具/脚本探针/VITE_）内置在脚本里，白名单变更也要过 PR

这是「防止有遗漏」诉求的机械化兜底：以后任何代码新增 env 读点，registry 不登就无法通过校验。

扫描口径限制（2026-10-18 实测修订）：
- regex 只能抓**字面量**读点；间接读法（变量名是参数，如 `services/sop-api/docs_graph_client.py:23-24` `os.getenv(var)` 循环读、`os.environ.get(拼串)`）扫不出——checker 白名单 **第 III 区「已知间接读点清单」**（人工补登、PR 维护），并应定期人工比对新增间接读法。
- **helper 读法必须单独扫**：`_get_env_str("ANGINEER_TIMEOUT_READ", 60.0)` / `get_env_int(...)` 这类经函数转手的字面量读点，`os.getenv` 正则一概看不见（实测 49 个变量只走这条路）。checker 第 I 区须并列两条正则。
- **必须排除虚拟环境**：`services/angineer-core/.venv` 下 site-packages 会贡献 84 个三方变量（`COVERAGE_*` / `PYTEST_*` / `OPENAI_*` / `AZURE_*`），不排除则校验永不归零。

## 3. 存储布局

| 文件 | 角色 | 持久性 |
|---|---|---|
| `data/platform/settings.json` | 覆盖层：`{ "<VAR_NAME>": value, ... }`，只存「有覆盖」的键，删除键=回退 | data/ 卷，跨发版存活；三容器同源（docker-compose.yml:36/66/97 均挂 `../data:/app/data`；本地 dev 走 shared/paths.py resolve 同根） |
| `data/platform/settings_audit.jsonl` | append-only 审计：`{ts, operator, key, old→new(脱敏), src_api}` | 同上 |

写入协议（照抄 guest_settings.py:87-95 先例）：写 `.tmp` → `os.replace` 原子替换；读侧直接读文件（小文件直读，无缓存进程内副本带来的不一致——guest_settings 已验证该模式跨容器即时同步）。

首次启动 / 文件不存在：覆盖层为空，一切回落 .env 与代码默认——**零迁移成本上线，可回退**（页面清空全部覆盖 = 行为与改造前完全一致）。

## 4. 生效链路（设计核心）

```
                 ┌────────────────────────────────────────────┐
PUT /api/settings│  1) 探针（仅 CONFIGS 与 secret 类）失败→422 不落盘 │
   aichat-api ───┤  2) settings.json 原子写 + 审计追加              │
                 │  3) 本进程立即 apply_overlays()（aichat 即时生效） │
                 └────────────┬───────────────────────────────┘
                              ↓ 30s 内（mtime 轮询，三进程各自）
   各后端进程 watcher daemon 线程
     ├─ 动态旋钮：diff 后 os.environ 注入/还原 → 90 个读点零改动生效
     └─ CONFIGS：diff 命中已登记热换口 → 调 swap hook（§4-B）
```

### 4-A. 动态旋钮：os.environ 覆盖注入（零读点改动）

新增 `services/shared/src/shared/runtime_overlays.py`：

- `apply_runtime_overlays()`：读 settings.json → 注入键值进 `os.environ` → 常驻 daemon watcher 线程（间隔参数化，默认 30s，测试可注入更短；mtime 无变化零开销）。

**接入点时序（警告：首注不得早于 .env 载入）**——快照基线 = apply 执行时刻的 `os.environ` 全量快照，供 DELETE 还原；若快照时 .env 还没并入进程环境，「恢复默认」会把 .env 有值的键删成缺失、回落代码默认，违背 §8「DELETE→回 .env 值」。因此：

| 服务 | 接入点 | .env 就绪保证 |
|---|---|---|
| docs-api | `main.py:23` `ensure_env()` 调用**之后**、`main.py:25` 首个业务 import 之前 | config_validator 模块 import 期已 `load_dotenv()`（config_validator.py:19；接入点行 :21 import 即触发），快照天然含 .env |
| aichat-api | `main.py:43` `ensure_env()` 之后、业务 import 前 | 同上（main.py:41 import） |
| sop-api | sys.path 装配后、import fastapi 前；runtime_overlays 内部先 `ensure_repo_dotenv()`（复用 config_validator.py:64-69 的 .env 定位 + `load_dotenv(override=False)` 幂等）再 apply | 本地 dev 由 ensure_repo_dotenv 载入；容器 env_file 出生即有 |

保证不变量：**apply 之后任何业务模块 import 才发生**（所有 import 期固化读点仍赶得上）；watcher 后续重注不与 `load_dotenv()` 冲突（override=False 尊重已存在值，config_validator.py:19 / base_config.py:15 / llm_client.py:49 导入时调用均无碍）。runtime_overlays 是独立 shared 模块，不塞进 config_validator（避免耦合校验语义）。

- 注入语义：**settings 覆盖永远优先于 .env**（页面双向 = 用户最后一手）；Watcher 还原语义：某键被「恢复默认」→ 从 settings.json 删除 → watcher diff 发现 → `os.environ[key]` 还原为快照基线值（若本无则删除注入键）。
- 生效时限承诺：watcher 间隔 30s + aichat 进程 PUT 时即时 apply → 全集群 ≤30s。

> 这条链路的价值硬通货：**现有 202 个变量名（236 处读点）一行不改**，route_pre/agent_tools/判分候选链等热路径全部自动吃到新值。

### 4-B. CONFIGS 五件套：热换口（diff 触发，按进程注册）

| CONFIGS | 固化位（实测） | 热换口设计 |
|---|---|---|
| LLM_CONFIGS | ai-inference `llm_client.py`:1580-1589（_LLMClientProxy 属性访问重解析）、:1595-1611（双重检查锁首建）、:1614-1617（无锁替换）、:1620-1624（有锁置空）；构造快照 `load_llm_config_from_env`（llm_config.py:150-176） | watcher diff → 在已 import llm_client 的进程调 `reset_llm_client()`，下次 get 重建；`_LLMClientProxy` 经属性访问面即刻切换，持旧引用的在跑 run 自然跑完 |
| EMBEDDING_CONFIGS | doc-core `embedding_provider.py:333` 模块顶层单例 + `dense_retriever.py:121` 抓死引用，import 期固化（最重） | 新增 `step06_vectors/provider_service.py`：`get_default_embedding_provider()` + `replace_default_provider()`；`default_embedding_provider` 降级为 Proxy（照 _LLMClientProxy 模式：属性访问重解析）；dense_retriever.py:121 抓引用改经 getter；watcher diff → replace。**replace 后立即跑一次维度探比**（startup_guard.py:126-135 同口径：embed 测试句 → 与存量 collection 维度比对），不一致记日志 + 页面 related 告警常驻（put 时探针已先行阻断，此处兜底其它落盘来源）。**牵连警示常驻编辑区**：改 embedding ≠ 迁移存量向量，startup_guard 报告搬进页面展示；不做自动迁移 |
| RERANKER_CONFIGS | angineer-core `base_config.py:158-166` get_config() 首调后缓存（RERANKER 首请求即固化） | base_config 加 `invalidate_config()`（置 _config=None），watcher diff → 两进程各自调（base_config 被 docs-api/aichat 双面 import，hook 按注册进程执行——try-import 注册，未 import 该模块的进程静默跳过） |
| MINERU_CONFIGS | doc-core `mineru_parser.py:1039` import 期单例快照；`parse_pipeline.py:1292` 每新任务重读 env（半动态） | 快照单例补 reset；watcher diff → docs-api 进程 reset；per-task 路线天然随下一任务生效 |
| POPO_CONFIGS | model_utils.py:69-97 每次推理 `_popo_endpoints()` 现读 | **零口**：注入 os.environ 即生效，无需 hook |

HOT 兜底：任何 hook 执行异常只记日志+审计「apply 失败」告警（复用 WEBHOOK_SYSTEM 通道），绝不阻断文件写入；下一次 watcher diff 重试。

### 4-C. 附带口径（防误解）

- `NIGHTLY_*`/`WEBHOOK_*`：nightly 调度回路每轮 load_settings()（nightly_control.py:514-536 先例）即动态；`NIGHTLY_SCHEDULER` 本身是 startup hook 读一次（evals_routes.py:719-724）→ 标 `restart`，不做热换口。
- guest 档 `ANGINEER_GUEST_ROUNDS`：guest_settings.json 保存即钉死（design-guest-settings.md 定过契约）→ registry related 标注「改 env/页面不再影响已建档」，防运维误解。
- 判分 `EVAL_JUDGE_CONFIGS`：answer_eval.py:94-114 每判分现读 → live；registry related 提示「与 LLM_CONFIGS name 引用一致性」。

## 5. API 契约（归属 aichat-api）

新增 `services/aichat-api/settings_routes.py`，路由前缀 `/api/settings`；vite dev proxy（admin vite.config.ts）**新加一条** `/api/settings` → 8791（aichat）的代理规则，**必须置于 `:117` 的 `/api` 兜底（→ docs-api）之前**，否则被兜底吞掉；生产分流走容器层 nginx（见 §7，与 dev 层选择一致）。

| 方法+路径 | 语义 |
|---|---|
| `GET /api/settings` | 合并视图：registry 全条目 + 当前 effective 值 + 来源徽标（default/env/settings）+ 脱敏 + effective/lazy/restart 标注 |
| `GET /api/settings/registry` | 纯目录元信息（分组树、解释、默认值）——前端构建目录树用 |
| `PUT /api/settings/{name}` | body `{value}`；**registry 外的 name → 422，`source=env` 只读项 → 422 `{reason:"read_only_env"}`**；先按 type/bool_style 校验并统一序列化（§2.2-G），secret/CONFIGS 类先跑探针（§6）；通过 → 原子写 + 审计 + 本进程即时 apply |
| `DELETE /api/settings/{name}` | 恢复默认 = 从覆盖层删键；审计「revert」；watcher 还原 os.environ（CONFIGS 走 hook 重建） |
| `POST /api/settings/probe` | body `{name, value}`：单独试跑不落盘（UI「测试连通」按钮用） |
| `GET /api/settings/audit?limit=N` | 审计最近 N 条 |

鉴权：admin-only（会话 token 校验复用 docs-api users 同套管线；aichat-api 已引 admin 会话中间件先例——nightly settings 接口 evals_routes.py:588-612 即 admin 会话门槛）。

CONFIGS body 类型：JSON 数组（结构同现 LLM_CONFIGS：name/model/api_key/base_url/priority/enabled…），PUT 时后端跑对应探针：

| CONFIGS | 探针 | 失败处理 |
|---|---|---|
| LLM_CONFIGS | 用新配置起一次性 LLMClient 跑 chat「ping」（不 set 全局） | 422 + 原因，不落盘 |
| EMBEDDING_CONFIGS | 一次性 provider embed 一句话，**顺带比对存量向量维度**（startup_guard 同口径：不匹配 → 422 阻断落盘，防换模型造成静默劣化；存量迁移仍不做） | 同上 |
| RERANKER_CONFIGS | rerank 两条 1 句 | 同上 |
| MINERU_CONFIGS / POPO_CONFIGS | 端点 URL 连通握手（不跑整册解析） | 同上 |
| EVAL_JUDGE_CONFIGS | 元素须是 LLM_CONFIGS 已有 name（结构校验即可） | 同上 |

## 6. 安全与脱敏

| 场景 | 处理 |
|---|---|
| GET 回显 secret | `***` + 尾 4 位；明文永不回传前端（含 audit 接口） |
| secret 输入 | 密文输入框，空值=保持不变 |
| 落盘 | 明文只进 `data/platform/settings.json` 与 audit（data/ 已闭源/gitignore，与 .env 同级保护面） |
| 越权 | 非 admin PUT/DELETE → 403 |
| 并写冲突 | 仅管理页写（单写者）；`os.replace` 原子替换保证任何读侧读到完整版本，不保证多写者互斥（并发写不在威胁模型内） |
| 误改自伤 | registry `related` 提示（如 ANGINEER_CHAT_AUTH_REQUIRED 打开会瞬间全员 401）+ secret 类试跑前置；页面顶部显示「生效来源」徽标，settings 覆盖 .env 不隐瞒 |

## 7. 部署注意

- nginx（容器层，**零手工步骤**）：分流加进 `docker/nginx/nginx.conf`（git 内、deploy 自动生效，容器只读挂载）——浏览器流量走宿主机 `location /` → frontend 容器 nginx，容器内已有 `$aichat_upstream` 先例（nginx.conf:107-110 `/api/chat`），照抄一条 `/api/settings` location 指向 `http://aichat-api:8791`；宿主机 `ai-proxy-locations.conf` **不动**（它管 DGX/spark 外部 API，不管 AnGIneer 业务面分流）。
- vite 规则顺序（§5 已注）：`/api/settings` 必须在 `/api` 兜底之前。
- 服务器 .env：本期**不动**（覆盖层叠加，不删改原值）；二期瘦身另行评审。
- 本功能纯代码发布：标准 deploy（push 后自动重建容器，watcher/注入随新容器出生）；settings.json 首次为空 = 全部走 .env 现状，行为回退零成本。
- 本地 dev：`apply_runtime_overlays()` 同样工作（resolve_data_file 同根解析）；uvicorn --reload 与 watcher 线程同生共死，无特殊处理。

## 8. 测试计划

| 层 | 用例要点 |
|---|---|
| 单测（pytest） | apply/revert 快照还原；原子写；审计脱敏；registry checker（含白名单跳过+间接读清单+helper 读法）；五类探针（真实链路 + 可注入 fake 传输层）；**bool_style 两样式往返**（对齐 mineru_parser.py:143 `!='0'` 与 :144 `=='true'` 类读点各注入一轮验证读值正确）；canonical int/float/json 序列化 |
| 集成 | PUT LIVE 旋钮 → 同进程 os.getenv 立刻变 + 另进程（TestClient 双实例）≤30s watcher 变；PUT LLM_CONFIGS 探针失败 → 422 且 settings.json 未变；DELETE → 回 .env 值 + /health 无 config 错；audit 行完整 |
| 前端 | typecheck 必跑；三 tab 渲染、编辑抽屉（bool/int/str/json/secret 五控件）、搜索过滤、来源徽标、恢复默认回退 |
| 手工冒烟 | dev 起三服务改 `ANGINEER_GUEST_ROUNDS`/`LLM_CONFIGS` 验证热效 + 审计 + restart 类参数提示文案 |

## 9. 二期边界（本期不做）

- .env 瘦身（把 .env 中旋钮值迁到 settings.json 后从 .env 删除；读点路径本期不改）
- EMBEDDING 变更的自动存量向量迁移/重建（只警示不代做）
- 审计 UI 深化（时间线回放/一键对比 .env.example 基线）
- user-web 任何变更；qdrant/前端容器的参数化

## 10. 事实引用（供实施与评审核对）

| 事实 | 证据 |
|---|---|
| env_file 容器创建时固化，restart 无效 | docker-compose.yml:33-34/63-64/94-95；AGENTS.md 2026-09-25 实踩 |
| 三容器同挂 ../data:/app/data | docker-compose.yml:36/66/97 |
| guest_settings 原子写/每读先例 | `services/shared/src/shared/guest_settings.py:55-62,87-95` |
| ensure_env 接入时序 | `services/docs-api/main.py:21-23`；`services/aichat-api/main.py:41-43`；`services/sop-api/main.py:24`（无 ensure_env，本设计由 runtime_overlays 内 ensure_repo_dotenv 补齐）；.env 定位 `services/shared/src/shared/config_validator.py:64-69` |
| LLM 单例/替换口 | `services/ai-inference/src/ai_inference/llm_client.py:1580-1624`（Proxy/首建/替换/重置；当日实测行号）；构造快照同包 `llm_config.py:117,150-176` |
| EMBEDDING 双单例 import 固化 | `services/docs-core/src/docs_core/step06_vectors/embedding_provider.py:333`；`dense_retriever.py:121`；维度守卫 `step06_vectors/startup_guard.py:126-135` |
| RERANKER 懒单例 | `services/angineer-core/src/angineer_core/base_config.py:158-166`（load_config_from_env:126-154） |
| MINERU 单例+每任务重读 | `services/docs-core/src/docs_core/step03_mineru_parse/mineru_parser.py:1039,140-155`；`parse_pipeline.py:1292` |
| POPO 每推理现读 | `services/docs-core/src/popo/post_processing/model_utils.py:69-97` |
| /api/llm_configs 现状只读 | `services/aichat-api/main.py:342-356` |
| 动态读热路径代表 | angineer-core `route_pre.py:27-91`、`agent_tools.py:19-151,449-461`；evals-core `runner/answer_eval.py:94-114` |
| bool 读点口径分叉实测 | `mineru_parser.py:143` `!= '0'` 与 `:144` `.lower() == 'true'`（§2.2-G canonical 依据；原稿 147/148 已漂移，2026-10-18 复核） |
| watcher 先例 | aichat-api `nightly_control.py:514-536`（60s 轮询重读 JSON）；`main.py:184-221` daemon Thread 先例 |
| admin 会话门槛先例 | aichat-api `evals_routes.py:588-612`（nightly settings GET/PUT） |
| 容器 nginx 分流先例 | `docker/nginx/nginx.conf:107-110`（$aichat_upstream / /api/chat），同文件 :123-124/156-157 多处同构 |
| 间接读读点实例 | `services/sop-api/docs_graph_client.py:23-24`（os.getenv(var) 循环读） |
| 环境变量规模实测 | 2026-10-18 扫 `services/` 去 `.venv`：202 个变量名（`ANGINEER_*` 84）、236 处读点；其中 49 个变量只经 helper 读（`_get_env_str/int/float("NAME")`），`os.getenv` 正则扫不到；`.venv` 下 site-packages 另有 84 个三方变量 |
