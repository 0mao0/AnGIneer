# 设计：后台「游客设置」——免登录访客的库授权 / 轮数上限 / 开放开关

状态：**已施工已验收**（2026-10-17：业主四点口径确认定稿 → 当日落 main，commit `1822ac25`→`2b839fff` 共 8 个；单测/回归全绿、两前端包 vue-tsc 过、§5.3 真机端到端四项业主已人工验收）。
起因：后台用户管理只见真实账号（admin/欢/远），游客（免登录访客）的可用库、轮数上限、开放与否
全部藏在硬编码与服务器 `.env`（`ANGINEER_GUEST_ROUNDS`）里，无任何可视化入口——业主提出
「后台少了个游客的权限设置」。

---

## 1. 术语与代码锚点（2026-10-17 全部实读核验）

| 术语 | 定义 | 代码锚点（已核验） |
|---|---|---|
| 游客（访客） | 未登录且无 API key 的请求主体：有游客 cookie = `g:<id>` 桶，无 cookie = `ip:<hash>` 兜底桶 | `services/aichat-api/chat_auth.py:175-196`（`resolve_pool_owner`；cookie 名 `ag_guest_id` 在 :18） |
| 游客闸 | 轮数满阈 或 已 claim 身份 → 403 `login_required`（前端据此弹登录） | `chat_auth.py:199-222`（`guest_rounds_limit`/`guest_gate_blocked`）；调用点 `main.py:479-486` |
| 游客库校验 | 匿名分支：空/default → `["default"]`；显式其它库 → 403「未登录访问仅限默认知识库」 | `chat_auth.py:148-154`（`enforce_bound_libraries` 匿名分支） |
| 游客设置 | **本次新增**：`{enabled, rounds, library_ids}` 三键，持久化 JSON，后台可视化编辑 | 新增 `data/platform/guest_settings.json` |
| 游客虚拟行 | 用户管理列表里置顶的「游客」行（非数据库记录，前端合成）+ 编辑弹框 | `apps/admin-web/src/views/UserManage.vue` |
| 公开配置端点 | **本次新增**：游客端拉取「是否开放 + 允许库（含组/库名）」的免鉴权只读端点 | 新增 `/api/guest/config` |

存储先例（本次照抄的模式）：`services/aichat-api/nightly_control.py:110-146`
（`load_settings` 每调用直读文件；`save_settings` 先写同目录 `.tmp` 再 `os.replace` 原子替换）；
路径解析先例 `services/shared/src/shared/paths.py:18-23`（`resolve_data_file`，env 覆盖 > 仓库根 `data/`）。

## 2. 现状（硬事实，2026-10-17 全部实读核验）

1. **游客库范围硬编码 default**：匿名分支只放行 `default`（`chat_auth.py:148-154`）；「V2 订阅派生制」设计稿
   §8 待确认 6 定版「游客不设派生集，匿名分支原样保留」（设计稿文档已完结清理、git 历史可查 `e8ddfbfe` 引入）。
2. **轮数上限只认 env**：`guest_rounds_limit()` 读 `ANGINEER_GUEST_ROUNDS`（默认 30，`chat_auth.py:199-204`）；
   服务器 `.env` 目前是否带调试值不由代码保证（CHANGELOG 记过本地/服务器曾暂调 5 轮）。
3. **后台无任何游客入口**：`UserManage.vue` 只列 `usersApi.list()` 的真实用户；`apps/admin-web` 全仓 grep
   `游客|guest` 零命中（仅 archmap 文档性提及）；git 全历史无「游客设置」页面痕迹——本次属新增功能。
4. **游客前端无库选择器**：`ChatHome.vue:18-22` 游客态强制 `library-options=[]`、`library-sections=[]`、
   隐藏模型选择；`auth.ts:38` `effectiveLibraryId` 游客恒 `'default'`。
5. **游客订阅机制可复用**：`guest_gate_blocked` 的 403 载荷 `detail.code=login_required` 已被前端
   `ChatHome.vue:168-172`（`onChatError`）消费弹登录浮层——「关闭游客」可零新增前端机制复用此通道。
6. **端点落位无代理障碍**：`/api/guest/*` 不属于任何显式代理规则，生产前端 nginx 的 `location /api/`
   兜底（`docker/nginx/nginx.conf:96-105`）与两端 vite dev 代理的 `/api` 兜底都指向 docs-api，
   **nginx / vite 代理零改动**；AI 网关 nginx 无 `/api/guest` 冲突段（已实查 `ai-proxy-locations.conf`）。
7. **管理端鉴权现成**：`docs-api/admin_auth.py:7-18`（`resolve_admin_session`，Bearer 会话 + `is_admin`），
   `users_routes.py:22` 已用 router 级 `dependencies` 模式。

## 3. 设计

### 3.1 存储与生效优先级

```
data/platform/guest_settings.json          ← 单一真相源（data/ 卷，跨发版存活）
{ "enabled": true, "rounds": 30, "library_ids": ["default"] }

优先级：文件 > env(ANGINEER_GUEST_ROUNDS) > 30
  · 文件不存在（首装）→ 默认值 = 今天的行为（开放 / env 轮数 / 仅 default 库）
  · 文件存在但读坏     → fail-closed：enabled=false + 错误进后台展示（对齐 nightly 稿「读坏禁跑」哲学；
                          游客侧表现 = 403 login_required，可登录继续，非静默放宽）
  · 保存 = 原子写（.tmp + os.replace），同 nightly 模式
  · 运维预期（评审补）：文件一旦保存即钉死 rounds——此后改服务器 .env 的 ANGINEER_GUEST_ROUNDS 不再生效，
    要调回 env 语义须删文件（enabled/rounds/library_ids 三键同进退）
```

### 3.2 端点（全部放 docs-api；aichat-api 只读同一文件做闸门）

| 端点 | 鉴权 | 用途 |
|---|---|---|
| `GET /api/guest/settings` | 管理员（`resolve_admin_session`） | 后台编辑回显：`{enabled, rounds, library_ids, load_error}`（rounds=当前生效值；`load_error` 非空 = 文件读坏，同 nightly 展示惯例） |
| `PUT /api/guest/settings` | 管理员 | 保存三键；校验见 §3.6；返回保存后设置 |
| `GET /api/guest/config` | **公开**（游客端拉取） | `{enabled, rounds, groups:[{group_name, display_name, libraries:[{id,name}]}]}`——按允许集过滤后的分组库清单（形状复用 `/knowledge/libraries/groups`），只含允许库、不含其它库，evals 组永不出现 |

- 每请求直读文件（不缓存）——改配置**即时生效、零部署零重启**；docs-api 写 / aichat-api 读跨容器经 `data/` 卷天然同步。
  评审补：单次聊天请求（闸门 + 库校验）**共用一次加载**——闸门与 `enforce_bound_libraries` 在同一请求内，
  实现时把一次 `load` 结果经 `request.state` 或局部传参串联，避免同请求重复读文件两次。
- 新增 `services/shared/src/shared/guest_settings.py`：`load / save / effective_rounds / guest_library_ids / guest_enabled`；
  路径 `resolve_data_file("GUEST_SETTINGS_FILE", "platform/guest_settings.json")`。
- `enabled` 与 `rounds` 的读取**不依赖 chat.sqlite / store**（见 §3.3 闸序），store 降级只豁免轮数计数与 claim。

### 3.3 aichat-api 闸门改造

```
/api/chat/agent（main.py:479 现有闸位，不新增拦截层）——评审修正后的闸序：
  ① enabled 判定（读文件，不依赖 store）——owner 非 u:/k:（g: 与 ip: 都拦）：
     enabled=false → 403 login_required
  ② store 降级豁免（现状保持，fail-open 仅限以下两条）：store=None → 直返 False
  ③ g: 桶专有（ip: 桶永不进轮闸/claim 判定——现状 chat_auth.py:215 直返 False，勿顺手给 ip: 上轮闸）：
     轮数 ≥ 生效 rounds → 403 login_required（阈值来源换 shared）
     已 claim 的 g: 桶  → 403 login_required（现状不变）
  u:/k: 主体永远不受游客闸影响（现状保持）

库校验（chat_auth.py:148-154 匿名分支改）：
  允许集 S = guest_library_ids()（缺文件 = ["default"]）
  ├─ 空 / ["default"] → 展开为 S 全选（与登录用户 V2 隐式语义一致）
  ├─ 显式 @ x，x ∈ S  → 放行
  └─ 显式 @ x，x ∉ S  → 403（文案更新为「未登录仅可访问游客开放库」口径）
  评审补：展开不截断（对齐 V2 无上限口径）；S >20 仅记 warning（同 V2 观测口径，不 403 不截断）
```

### 3.4 admin-web：游客虚拟行（UserManage.vue）

```
列表置顶虚拟行（不进数据库、不参与真实 CRUD）：
┌────────────┬────────────┬────────┬──────────────┬────────┬──────┬──────────┐
│ 游客 <tag> │ 免登录访客 │ ✗ 禁用 │ 授权库聚合标签 │   —    │ 开关 │ 编辑     │
└────────────┴────────────┴────────┴──────────────┴────────┴──────┴──────────┘
· 启用开关 = enabled 行内直切（PUT）；失败回滚开关态
· 编辑弹框 = 可用知识库（复用 AccessScopeSelect 两级选择器，扁平勾选集存 library_ids，
  不走 V2 订阅序列化）+ 轮数上限（a-input-number，1–1000，展示当前生效值）
· 无「重置密码 / 删除」；管理员列开关禁用态；「最近登录」显示 —
· 授权库列标签复用 buildAccessUnits（accessScope.ts:35），显示口径与真实用户一致
· `load_error` 非空时（文件读坏）：游客行加醒目提示（页面顶部 alert），保存一次即恢复
· 弹框开时重拉库清单（循 R5 无缓存惯例）
```

### 3.5 user-web：游客选择器放开

```
ChatHome.vue：
  · 游客挂载时拉 GET /api/guest/config（替代游客态跳过 loadLibraryNames 的旧逻辑）
    → 注入 auth store 的游客库集合 / 库名 / 分组 sections；默认勾选 = 允许集全选
  · 选择器与 sections 不再对游客置空（模型选择仍隐藏，维持现状）
  · 关闭态（enabled=false）：进页照常可浏览可输入，发送 → 403 login_required → AuthGate（现有通道）
  · 登录/登出切换时重拉（沿用现有 watch 钩子追加一条）
auth.ts：
  · 新增 state：guestConfig（libraries/enabled 等）；libraries getter 游客态回退 guestConfig.libraries；
    effectiveLibraryId 游客态 = 勾选首项 || 允许集首项 || 'default'
  · 拉取失败：选择器回退空（组件自带降级），发送侧服务端仍兜底裁定
```

### 3.6 校验与拒绝语义（服务端为准）

| # | 规则 | 失败行为 |
|---|---|---|
| V1 | `library_ids` 至少 1 个（同用户创建校验口径） | 400 |
| V2 | 每个 id 必须真实存在（`get_docs_service().get_library()`） | 400 |
| V3 | evals 组库不进游客允许集（§8-B2「评测语料不进对话检索」延续）；UI 选择器同样不展示 evals 组 | 400 |
| V4 | `rounds` 必须为 1–1000 的整数 | 400（明确报错，不静默夹取） |
| V5 | 游客显式请求非允许库 → 403；隐式（空/default）→ 允许集全选 | 见 §3.3 |
| V6 | 轮数已累计的存量游客桶：提高阈值即续聊、降低即刻拦（计数为累计值，不做回溯重置） | — |

## 4. 改造点清单

### 4.1 新增/共享
| 文件 | 内容 |
|---|---|
| `services/shared/src/shared/guest_settings.py`（新增） | 加载/保存/规范化/优先级；fail-closed 读坏处理；原子写 |
| `tests/unit/test_guest_settings.py`（新增） | 默认值/优先级/读坏/原子写/越界拒绝 |

### 4.2 docs-api
| 文件 | 内容 |
|---|---|
| `services/docs-api/guest_routes.py`（新增） | 三端点（§3.2）+ 校验（§3.6）；挂 `/api/guest`，`GET/PUT settings` 用 `resolve_admin_session`，`config` 公开 |
| `services/docs-api/main.py` | include 新 router |
| `services/docs-api/tests/test_guest_routes.py`（新增） | 鉴权 401/403、校验 400、config 过滤形状 |

### 4.3 aichat-api
| 文件 | 内容 |
|---|---|
| `services/aichat-api/chat_auth.py` | `guest_rounds_limit` 改读 shared 生效值；`guest_gate_blocked` 增 enabled 判定（g:/ip:）；匿名库分支改允许集语义 |
| `services/aichat-api/main.py` | 无结构性改动（闸位 :479 复用） |
| `tests/aichat-api/test_chat_guest_gate.py` | 扩：关闭→403（**g: 与 ip: 都覆盖**）、u:/k: 不受影响、文件轮数覆盖 env、**store=None 时 enabled 闸仍生效**（防降级吞闸） |
| `tests/aichat-api/test_multi_library_endpoint.py`（或邻近） | 扩：游客允许集成员/非成员 403/隐式展开 |

### 4.4 admin-web
| 文件 | 内容 |
|---|---|
| `apps/admin-web/src/api/guest.ts`（新增） | `getSettings / saveSettings`（docsApiClient，`/guest/settings`） |
| `apps/admin-web/src/views/UserManage.vue` | 虚拟行 + 启用开关 + 编辑弹框（AccessScopeSelect + 轮数）；加载游客设置并入 onMounted |

### 4.5 user-web
| 文件 | 内容 |
|---|---|
| `apps/user-web/src/api/guest.ts`（新增） | `getConfig`（docsApiClient，`/guest/config`） |
| `apps/user-web/src/stores/auth.ts` | guestConfig state + libraries/effectiveLibraryId getter 适配 + 默认全选 |
| `apps/user-web/src/views/ChatHome.vue` | 游客拉配置构建 options/sections；选择器对游客放开；登录/登出重拉 |

**零改动面（明确登记）**：nginx（docker 与服务器网关）、vite 两端代理、chat-history（cookie 签发不变）、
`aichat-ui`（组件 props 本就支持游客传参）、community 投稿链路。

## 5. 测试与验收

1. 单测全绿：`tests/unit/test_guest_settings.py` + 扩后的 `tests/aichat-api/*` + `services/docs-api/tests/test_guest_routes.py`。
2. 前端两包 `vue-tsc` 过（`pnpm --filter @angineer/admin-web exec vue-tsc -b`、`@angineer/user-web` 同——两端 package.json 无 `typecheck` 脚本，`build` = `vue-tsc -b && vite build`）。
3. 本地端到端（真服务）：
   - 后台游客行改 library_ids 勾多库 → 游客端选择器即时出现多库（无重启）；游客 @ 非允许库 403 文案可见；
   - 关闭开关 → 游客照样进页可打字，发送弹登录浮层（403 login_required）；登录用户不受影响；
   - 轮数改 3 → 第 4 轮弹登录；改回 30 → 同一游客桶继续可聊（累计计数语义）；
   - 配置文件读坏（手工写半截 JSON）→ 游客聊天 403、后台显示错误、保存一次即恢复。
4. 回归基线：`test_chat_guest_gate`、`test_multi_library_v2`、`test_main_http_api_e2e` 等既有套件不红。

## 6. 非目标与已接受的取舍

- **不做** per-游客个体授权（游客无身份，只有全局策略）；不做游客用量看板。
- **不动**「`["default"]` 显式勾选 = 隐式全选」这一既有歧义（登录用户 V2 同款语义，统一保持）。
- **不动** community 公开页投稿链路（游客开关不拦投稿/评论，属另一产品面）。
- **不动** `steer` 端点（现状本就没有游客闸，本次不扩面）。
- **暴露面口径（评审修正）**：新端点 `GET /api/guest/config` 只含允许集库名/组名，**不扩大既有暴露面**；
  但须登记既有事实——`/api/knowledge/libraries/groups` 本就匿名可达且全量返回（`docs_router` 无依赖，
  `APIKeyAuthMiddleware` 只管 `/api/v1/*`），本次**不收敛**该面（属独立治理项，勿在本文档声称「匿名者只见允许集」）。
- **scope_hash 漂移（评审登记）**：管理员改 `library_ids` → 游客生效检索集变化 → 请求 `scope_hash_for`
  换桶，进行中的游客对话丢失服务端模型上下文（本地消息仍在、模型断上下文）。与登录用户 V2 派生集变化同族，
  属被动触发但可接受：游客侧无历史 UI、页面刷新即自愈。
- **存量页面勾选滞后（同上族）**：管理员移除某库后，已打开游客页仍勾着该库 → 该次请求 403（可见报错，
  与登录用户对非派生成员的 403 同款语义），刷新页面重拉 config 即恢复。

## 7. 关联

- `CHANGELOG.md` v0.2.67 段（无登录硬门 + 游客档 D2/D6/D12 机制来历）
- V2 订阅设计稿（已完结清理，git `e8ddfbfe`；§8-B2 评测语料不进对话检索、§8 待确认 6 游客不设派生集）
- `services/aichat-api/nightly_control.py`（运行时配置文件模式先例）
- `docs/design-user-kb-access-scope.md` 系列显示口径（accessScope.ts 聚合规则，两处共用勿分叉）
