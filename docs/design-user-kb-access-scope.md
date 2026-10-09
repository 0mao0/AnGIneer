# 设计：用户知识库访问范围 = 两级（组订阅 → 组内库）

状态：**草案 v2，待评审**（v2 = 2026-10-09 锚点全量重验后重写；v1 含一批未验证引用，已按 §9-6 口径清除）。
起因：admin 用户管理「可访问知识库」现为平铺库清单（`UserManage.vue` 的 `a-select mode="multiple"`），业主定版改造为两级——第一级「集」（组，对应一组独立 sqlite + qdrant collection），第二级组内库；一般整组授权，允许扣掉组内部分库；已订阅范围内用户勾选不再受 5 库上限约束（2026-10-09 三点口径确认：组级授权+组级上限→**改为无硬顶**、「选了 N 个组 M 个库就应该是 M 个库去检索」、「无硬顶，全订阅全选」）。

---

## 1. 术语与代码锚点

| 术语 | 定义（干什么用的） | 代码锚点（2026-10-09 全部重验） |
|---|---|---|
| 知识库组（组/集） | 一组知识库的逻辑+存储单元：整组共享**一个**组级 sqlite 文件、**一个** qdrant collection（同桶共享）；未登记组回退 `docs_core_vectors` collection | `docs_core/library_registry.py`：`GROUP_DEFAULTS`（standards→standards.sqlite/standards、dredgeai→dredgeai.sqlite/dredgeai、evals→evals_corpus.sqlite/evals_corpus 三个内置组各自独立单文件+单 collection；自定义组派生 `knowledge/groups/{group}.sqlite`）、`resolve_collection()` 未登记库回退 `get_qdrant_collection()` |
| 订阅（订阅集） | 用户对「组」的授权关系：勾整组 = 组内全部库（含**将来新增**）可用，可排除个库；散库（不属任何组的 `default`/未登记库）单独直选 | 新增 `user_group_subscriptions` / `user_library_direct`（§3.1） |
| 派生范围 | 请求时把订阅展开成实际可检索库集（= 各订阅组当前 active 库 − 排除 + 散库直选）| 新增 `services/shared/src/shared/subscription.py`（§3.4） |
| 已授权全集 | 本次允许检索的全部库集（登录用户 = 派生范围 ∩ 用户显式选择；未显式选择 = 派生范围**全选，无上限**；管理员 = 全部 active 库，同样无上限；API key 维持单库绑定不动） | `services/aichat-api/chat_auth.py` `enforce_bound_libraries`（:71-114）改造后语义（§4） |

## 2. 现状盘点（评审前必读的硬事实，全部经 2026-10-09 grep/读盘核验）

1. **5 库上限是活代码，不是休眠代码。** `max_chat_libraries()`（`services/aichat-api/chat_auth.py:63-68`，默认 5、env `ANGINEER_MAX_CHAT_LIBRARIES` 夹 1..10）在 `enforce_bound_libraries` 的 3 个 return 上生效：`:84` 管理员分支 `libs[:cap]`、`:93` 空/default 回退（恒 1 项，恒 no-op）、`:97` 会话用户分支 `libs[:cap]`。**截断是静默的**——选 7 库只查前 5 库，用户无感知。§4 R2 的「移除截断」针对的就是这三处。
2. **库清单真相源是双源，不是单源。** `docs_service.list_libraries()`（`docs_service.py:548-556`）主源 = `meta_store.list_libraries()` 读 `knowledge_meta.libraries`，`library_registry` 行只用来**补全** group_name/collection/status；`get_library()`（`docs_service.py:591`）循环 `list_libraries()`，不是「绕过 registry」。本地实测：`data/registry.sqlite`（library_registry 20 行 + library_groups）与 `data/knowledge/knowledge_meta.sqlite`（libraries 14 行）**并存**；「生产 2222 库」「仓内无 registry 文件」等旧文稿数字未经核验，本文不再引用任何未核验库数——派生算法按「两源都在/只有 meta 源」两分支设计，运行时以实况为准。
3. **请求级链路 = `main.py:412-414` 三步 + `chat_agent.py` 两处门控。** 链路：`normalize_library_ids`（`step09_query/protocols/contracts.py:77-85`，去重保序；空 → `[library_id or "default"]`）→ `enforce_bound_libraries`（成员校验+截断）→ 回填 `request.library_id = library_ids[0]`。隐式（无 @）请求经 `chat_agent.py:143-151` 回落到 `[default]` 单库，**不经成员校验**；`chat_agent.py:61-67` 的 `is_multi_scope` 仅在 >1 库时为真。**仓内不存在 `run_stream.py`**（全仓 grep 零命中），v1 写的「7 调用点」作废；**仓内亦不存在 `max_collections` 参数**（含 1..10 夹取的说法作废）——扇出层真正的门控是 `_retrieve_multi` 的 9-worker 线程池（§5）。
4. **`check_kb_access` / `check_kb_search` / `auth:check` / `READONLY` 在仓内不存在**（`-r` 全仓 grep 零命中，2026-10-09 重验仍成立）。成员判定唯一在途实现 = `chat_auth.py` 的两个函数：集合版 `enforce_bound_libraries`（:71-114，`main.py:412` 唯一调用）+ 单值版 `enforce_bound_library`（:28-60，注释自证「零生产调用方」，仅作旧语义回归基准）。403 只在「请求集 ⊄ 成员集」时触发；**越权 403 语义保留，静默截断移除**（§4 R2）。

## 3. 授权存储改造（shared/user_model.py）

### 3.1 新表

```
user_group_subscriptions (user_id, group_name, excluded_libraries JSON默认'[]')
  PRIMARY KEY (user_id, group_name)   -- 整组订阅；excluded_libraries 为订阅内排除（减法）
user_library_direct (user_id, library_id)
  PRIMARY KEY (user_id, library_id)   -- 散库/非组库直选（default、未登记库、逃生舱）
```

- 迁移策略：**新表 + 启动回填**。`init_db()` 时若 `user_group_subscriptions` 为空且 `user_libraries` 非空，把现有绑定按「库→组」反查映射回订阅（同组多库合并为一条订阅），映射不到的进 `user_library_direct`。`user_libraries` 降为回退层，`ANGINEER_KB_SUBSCRIPTION_V2=1` 后失效（开关默认关，回滚即回 5 库+截断语义）。

### 3.2 派生算法（四规则）

| # | 规则 | 失败行为 |
|---|---|---|
| R1 | 整组订阅 = 组内全部注册库 + 将来新增（派生发生在请求时，天然跟随注册表） | — |
| R2 | `excluded_libraries` = 订阅内减法，只对**该组**生效；散库直选不受组排除影响 | — |
| R3 | 组内当前成员 = `docs_service.list_libraries()` 按 `group_name` 过滤，**排除 retired/migrating**（源头排除，消费端不再二次猜）。内部双源口径照 §2-2：meta 主源给行、registry 给组归属；两源都给不出组归属 → 该用户派生为空 | registry 与 meta 都空 → 403「未绑定任何知识库」+ 日志，**不回退**「默认库/全库可见」 |
| R4 | 已退休/迁移中库：R3 的 group_name 过滤天然排除（`include_retired=False` 口径）；派生层不再单独维护「active 判定」，避免第二套真相源 | — |

### 3.3 协议扩展（三处同步）

- `User` dataclass（`services/shared/src/shared/user_model.py`）新增 `group_subscriptions: list[dict]`，形状 `[{"group": "...", "excluded_libraries": [...]}]`；
- `user_info()`（`GET /api/me` 与 `GET /api/auth/me` 共用响应体）新增 `accessible_libraries: List[str]` = 派生结果，**取代** `libraries`（§4 R6）；
- `chat_auth.py` 两个 enforce 函数（集合版 + 零调用方的单值版）**同步**换派生集——单值版虽无生产调用方，但它是 `test_auth_guard` 类回归基准，只改一版会造成两套成员语义；
- 写入侧：`create_user` / `update_user` 签名改为接收订阅（admin 端点 `GET/POST/PUT /api/users` 同步换协议，admin-web 为唯一消费方，无兼容层）；`update_user` 改订阅后**不失效会话**（订阅是检索范围不是身份，会话 TTL 不动）。
- admin 展示层：表格/编辑回显渲染派生结果；**admin 编辑页无派生缓存**（当前 `UserManage.vue:153 loadLibraries` + `:178 form.library_ids = [...record.library_ids]` 读的是列表响应快照）——列表接口逐用户调派生函数（N+1 IO：每用户 1 次 registry 查询 + 1 次 meta 查询；50 用户 <0.5s，量级可忽略，但评审时明确该代价）。

### 3.4 模块边界

订阅表留在 `services/shared/src/shared/user_model.py`（`User` 真相源；`services/docs-api/models/user.py` 与 `services/aichat-api/models/user.py` 仅为别名层）；派生所需的组解析走 `docs_core.library_registry` / `docs_service.list_libraries()` 读穿，**不新建缓存**（对齐 `library_registry.py` 头部「读穿不缓存」契约；`agent_tools._search_memo_key` 的 memo 缓存键自带 library_scope，不受影响）。aichat-api 经 `models/user.py` 别名层透传，无新耦合。

## 4. 请求链路改造（aichat-api / docs-core）

| # | 项 | 改造前（已核验） | 改造后 |
|---|---|---|---|
| R1 | `resolve_session_principal`（`chat_auth.py:13-25`） | `:24` `bound_library_ids = set(user.library_ids)`（登录时点快照） | = 派生结果（每请求一算，新建库自动进入范围） |
| R2 | `enforce_bound_libraries`（`chat_auth.py:71-114`） | 成员校验 + `[:cap]` **静默截断**×3（:84/:93/:97，默认 5） | **三处截断全部移除**；成员校验（非成员 → 403）保留。派生集 >20 时仅记 warning 日志 + 计数，**不 403、不截断** |
| R3 | 隐式默认检索（无 @） | `chat_agent.py:143-151`：`library_ids or [library_id or "default"]` → 恒查 default 单库（绕成员校验） | 派生制下隐式 = **派生范围全选**（= 业主「无硬顶，全订阅全选」口径）；隐式不再恒查 default |
| R4 | 用户端选择器上限 | `aichat-ui/constants.ts:3 MAX_LIBRARY_SELECTION=5` + `BaseChat.vue:574/:580`（label ≤5 + slice） | 上限移除；默认勾选 = 订阅派生集全选；显式选择只允许派生集子集，含非成员 → 403 可见报错（不再静默截） |
| R5 | 编辑页回显（admin） | — | admin 编辑页每次打开重新拉取派生结果（无缓存），避免旧快照勾选回显过期 |
| R6 | `libraries` 字段更名 `accessible_libraries` | admin 表格 `UserManage.vue:19` / `auth.ts`（:5 注释与 :31 消费）/ `aichat-ui` 两处 5 硬编码 | 统一走派生；admin 编辑页无缓存（R5） |

`agent_tools.py:564-589` 的 `_search_memo_key` 把 `sorted(library_scope)` 编进检索缓存键——派生集随注册表变化，键自动随之变化，**缓存不失效但命中率预期下降**，列为可接受回归，不单独设计。

## 5. 性能与延迟（诚实口径）

- 扇出成本单位 = **(collection, 检索路) 任务数**，不是库数：`retrieve_service._retrieve_multi`（`step09_query/retrieve_service.py`，:223 定义、:322 建 `ThreadPoolExecutor(min(9, len(jobs)))`，:210 `_MULTI_MAX_WORKERS=9`——三处 2026-10-09 重验）把请求按 collection 分组；
- 整组订阅（如标规规范集 ≈ 1 collection）×5 路 = 5 任务 < 9 worker → **一波完成，延迟近似不变**；跨组订阅 = 每多一个 collection 多 5 任务，延迟按波数（⌈任务数/9⌉）线性上升；
- 全订阅全选（本地 registry 20 组内库、未来 22 库 22 组场景）延迟线性上升——**业主 2026-10-09 口径接受：「选了 N 个组 M 个库就应该是 M 个库去检索」，宁可慢也要全**；403 上限闸（v1 的 FANOUT_CAP=20）取消，理由见 §8-B1；
- 上线前置验证 = §9-4 本地 20 库扇出实测 p50/p95（本地跑，不给「4c47 不可达」之类未核验前提留位置）。

## 6. 兼容与回滚

1. 新表 + 新键默认关（`ANGINEER_KB_SUBSCRIPTION_V2=0`）；开启后「截断移除 + 隐式默认 = 派生全选」属行为变更，**必须配套通知 + 回滚开关**；
2. 回滚动作 = 关 `V2` + 重启两后端（`users.sqlite` 新表保留不回滚）。**回滚数据洞（2026-10-09 评审 C-1）**：若 V2=1 期间订阅写入只进新表，回滚后 `user_libraries` 整个 V2 期间是空窗——该期间新建/修改的订阅全部丢失（效果 = 全员隐式恒查 default、显式 @ 403）。双写/接受丢失二选一见 §8-5，未拍板前该项不得进施工；
3. `auth_check.py` / `auth:check` 在仓内**不存在**（§2-4）——评审据此判断范围，勿按旧文档找代码。

## 7. 改造点清单

### 7.1 服务端（路径均为 2026-10-09 核验后的真实路径）

| 文件 | 现状（核验后行号） | 改法 |
|---|---|---|
| `services/shared/src/shared/user_model.py` | `User.library_ids`（:57）；`_library_ids_for_user`（:108-113，只读 user_libraries）；`init_db()`（:68-105）**只建 users/user_libraries/sessions 三表 + is_admin 列，无任何库种子代码**（v1「四种子库种子」系幻影，2026-10-09 全仓 grep 复核撤回）；`ensure_admin_user` 绑 `["default"]`（:363） | 加 2 张订阅表 + `derive_libraries_for_user()`；`User` 协议扩展（§3.3） |
| `services/shared/src/shared/subscription.py`（新） | 无 | 派生算法 R1–R4 单一落地（双源读取经 `docs_service.list_libraries()`，不自建第二条读路） |
| `services/aichat-api/chat_auth.py` | `:13-25` `resolve_session_principal`（:24 时点快照）；`:28-60` 单值版 `enforce_bound_library`（零生产调用方）；`:63-68 max_chat_libraries`；`:71-114` 集合版 `enforce_bound_libraries`（:84/:93/:97 截断，:94-96/:104/:111-113 403） | R1 派生替换 + R2 三处截断移除、>20 warning；两 enforce 函数**同步**改（§3.3） |
| `services/aichat-api/main.py` | `:412-414` normalize→enforce→回填；`:463-464/:534` is_multi_scope 条件图谱加载 | 适配派生集（无上限）；`:197` warmup 探针（`library_id="default"`）不动 |
| `services/aichat-api/chat_agent.py` | `:61-67 is_multi_scope`；`:106-116` multi 仅 >1；`:143-151` 空回退 `[default]` | R3 隐式 = 派生全选；multi 判定口径随派生集核对 |
| `services/aichat-api/models/user.py`、`services/docs-api/models/user.py` | 别名层 | 随 `shared/user_model.py` 签名同步 |
| `services/docs-api/users_routes.py` | `:26 UserItem.library_ids`；`:37/:43` 请求体 `library_ids`；`:63-67 _ensure_libraries_exist`（经 `get_docs_service().get_library()` 逐个查） | 订阅协议 + 派生字段；`_ensure_libraries_exist` 对「组订阅」改按组存在性校验 |
| `services/angineer-core/src/angineer_core/agent_tools.py` | `:564-589 _search_memo_key`（memo 键含 sorted(library_scope)）| **不改**（缓存键自动跟随派生集；§4 末段） |
| `services/docs-core/src/docs_core/step09_query/retrieve_service.py` | `:210 _MULTI_MAX_WORKERS=9`；`:223 def _retrieve_multi`（按 (collection, 路) 分组，`:322` 建 `ThreadPoolExecutor(min(9, len(jobs)))`；v1 写「:230-330」系行号偏差，重验后改正） | 不改结构；§9-4 用它在本地测 20 库扇出延迟 |
| `services/docs-core/src/docs_core/docs_service.py` | `:548-556 list_libraries()`（meta 主源 + registry enrichment）；`:591 get_library()` | 派生函数复用此读路；不新增旁路 |
| `services/docs-core/src/docs_core/library_registry.py` | `resolve_collection()` 未登记回退 `get_qdrant_collection()`；`list_libraries(include_retired=False)` | 消费方按 R3 用 `include_retired=False`；不动本文件 |

（v1 表中的 `run_stream.py`、`knowledge_retrieval.py:734`、`knowledge_data.py:915/936`、`docs-core 下 agent_tools.py` 四行作废：前两文件仓内不存在，后两处路径/行号不成立。）

### 7.2 前端

| 文件 | 现状（核验后） | 改法 |
|---|---|---|
| `apps/admin-web/src/views/UserManage.vue` | `:67/:81` 平铺 `a-select mode="multiple"`；`:19` 表格 tags；`:113 libraryOptions`；`:153 loadLibraries` | 两级选择：组可整勾 + 展开扣库 + 散库区；2026-10-09 落地为 `components/AccessScopeSelect.vue`（antd tree-select 无「按组聚合标签」能力故换自绘弹层）——选择框按授权单位聚合显示：整组勾满＝「组名（全部）」、组内勾 ≥2＝「组名（N）」、组内单勾＝库名；**列表同规则聚合**（`components/accessScope.ts` 单一落地，两处共用）；**两级清单默认按组折叠**（点组头左侧箭头展开，搜索命中自动展开）；**字段名 2026-10-09 业主改名：可访问知识库 → 授权知识库**（列头+两弹框标签；代码标识符不改）；弹框表单横向布局（标签与控件同行，克隆 EntityReviewDrawer 的 label-col）；勾选数据模型仍是库 id 列表，`serializeAccess`/payload 契约不变 |
| `apps/user-web/src/stores/auth.ts` | `:5` 注释记 5 库上限（与 aichat-ui/服务端同步值）；`:31` `activeLibraryId \|\| default_library` 链 | `accessible_libraries` + 取消上限消费；派生集合透传口径在 §3.3 |
| `packages/aichat-ui/src/constants.ts` + `BaseChat.vue` | `constants.ts:3 MAX_LIBRARY_SELECTION=5`；`BaseChat.vue:574`（label ≤5）`:580`（`.slice(0, MAX_LIBRARY_SELECTION)`） | 两处 5 → 读 auth store 派生集长度（R4）；2026-10-09 新增可选 `librarySections` prop（BaseChat `#dropdownRender` 渲染「组行整勾 + 组内库行单勾」，**组默认折叠、点组头箭头展开**；缺省平铺选项逐位不变） |
| `apps/user-web/src/views/ChatHome.vue` | `:135-149 libraryOptions` 按 `group_name === 'evals'` 过滤 `evalsLibraryIds`（**是**「评测库不进用户端选择器」逻辑，2026-10-09 重验恢复此定性）；`:251` `libraryIds` 会话保存 | 两级选择器沿用同一 evals 过滤做展示层；**服务端侧 evals 组默认不订阅**（§8-B2），前端过滤不再是唯一防线。2026-10-09 落地两级+人名：`/knowledge/libraries/groups` 构建 sections（内置组中文名 GROUP_LABELS 口径与 admin 一致）传 `AIChat :library-sections`，实测「外服 · DredgeAI 3/3」两级勾选联动正常 |

## 8. 设计结论与待评审确认项

**B1（已闭环）——上限 20 + 管理员派生全集 = 上线即锁死管理员，v1 方案作废。** v1 的 `FANOUT_CAP=20`（超限 403）与「管理员派生集 = 全部 active 库」互斥：管理员默认全选时派生集本地即 20+ 库（生产按 22 组 22 collection 布局可更多），每请求第一句就 403，等于上线即锁死管理员；普通用户订 2 个 20 库组同样被锁。v2 定版：**没有任何数量上限闸**——`[:cap]` 截断与超限 403 一并移除，成员校验（防越权 403）保留，>20 只记 warning + 计数；延迟代价按业主「无硬顶，全订阅全选」口径接受，代价口径见 §5。
**B2（已闭环）——新增库自动生效 + evals 排除上移。** ① 新库进任意已订阅组 → 下次派生自动进默认检索范围，属设计意图（「整组开发」语义），不设回溯审批；代价 = 大组新建库拖慢全组订阅者的默认检索（§5 线性项）。② evals 组：用户端 `ChatHome.vue:135-149` 已有前端过滤，但订阅制下必须**在服务端派生源头排除 evals 组**（管理员/整组订阅含 evals 时亦然），否则「评测语料不进对话检索」只剩前端一层纸；评测链路（`evals_core/nightly`、题库 run 直连）不走 chat 派生集，不受影响。
**待确认 3**：admin 用户列表 N+1 派生 IO（§3.3）接受与否。
**待确认 4**：「派生为空 → 403」回退边界：现 `chat_auth.py:88-93` 对空/default 请求恒回退 `default` 库，派生制下该回退是否保留（保留 = 零订阅用户仍可查 default；移除 = 一切经派生集，行为变更需配通知）。
**待确认 5（评审 C-1，回滚数据洞）**：V2=1 期间订阅保存是否双写 `user_libraries` 回退层。二选一：**建议 = 双写**——保存订阅时把派生集展开回写 `user_libraries` 作镜像（镜像不进读路径，读仍唯一走派生集，不引入第二真相源；回滚 = 关 V2 + 重启即恢复，零丢失）；备选 = 回滚接受订阅丢失（回滚后需 admin 逐用户手动重勾）。
**待确认 6（评审 C-2，游客 g:\<cookie\> 派生范围）**：游客无 session_user，`resolve_session_principal` 恒 False → `bound_library_ids=None`，现行为 = `chat_auth.py:99-104` 匿名分支（default 可查、@ 其它库 403）。V2 下两案：**建议 = 游客不设派生集，匿名分支原样保留**（游客授权面不放宽，与 2026-09-17 收紧口径一致）；备选 = 游客派生空集（隐式也不给查 default——行为变更，砍掉游客默认检索，需配通知）。

## 9. 验收清单

1. 双组订阅（公路+市政）+ 排除「公路/地基」：`GET /api/auth/me` → `accessible_libraries` = 两组 active 集 − 地基；组内新建库后下一次请求即含新库；
2. 派生集全选（≥20 库、≥4 collection）请求 → **全部库进检索**（`_retrieve_multi` 任务日志可数），无截断、无 403；
3. 未订阅库（含 retired/migrating）显式 @ → 403（防越权语义保留）；
4. 本地 20 库扇出延迟实测 p50/p95（对照单库基线）；
5. 回归基线（**跑前先 `git status` 查并发会话未提交改动**，MEMORY「并发提交 reflog 教训」同法）：`test_auth_guard / test_main_http_api_e2e / test_session_isolation / test_authz_wiring / test_evals_multi_library_retrieval_e2e / test_evals_http_contract / test_kb_migrator_group_bucket / test_table_retrieval_scoped / test_clause_resolve`；
6. 锚点纪律（本文 §2 已按此重验一轮）：引用任何文件:行号前先 grep；转述旧文档/旧会话的调用点描述一律标「待验证」。

## 10. 关联

- `docs/plan-kb-split-groups.md`（组/组文件/collection 设计源）
- MEMORY `migrated-path-lookup-miss-1007`（迁移漏查旧路径教训——派生排除 retired 时勿把「查不到=没有」当事实）
- MEMORY `auth-guard-migration-and-e2e-ports`（本地 4173/4174 双实例 + 8790/8791 端口拓扑——跑 e2e 前先 `docker ps` + `/health` 确认版本）
