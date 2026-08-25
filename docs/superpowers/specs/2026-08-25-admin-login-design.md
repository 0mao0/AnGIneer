# admin-web 账号密码登录设计

日期：2026-08-25
状态：设计已与用户确认（账号体系选 A，去掉后台 IP 白名单）

## 背景与目标

- 现状：admin-web 没有自己的登录页，`/admin/`、`/api/users`、`/api/api-keys` 依赖 nginx IP 白名单 + HTTP Basic Auth；管理员体验差（浏览器弹窗、密码随机生成、公网直接 403）。
- 目标：管理员在后台用「用户名 + 密码」登录；公网可直接打开 `/admin/` 登录页；管理接口由应用层会话鉴权保护，不再依赖 nginx Basic Auth。

## 已确认决策

1. 账号体系：复用现有 `users` 表（PBKDF2 + sessions），新增 `is_admin` 标记；首个管理员由 `.env` 的 `ADMIN_USER` / `ADMIN_PASSWORD` 在服务启动时引导创建。
2. 白名单：移除 nginx `geo $admin_allowed`，以及 `/admin/`、`/api/users`、`/api/api-keys`、`/docs`、`/redoc`、`/openapi.json` 上的 Basic Auth / IP 限制，公网直连，安全全靠账号密码 + 会话。

## 后端改动（docs-api / aichat-api）

### 1. 数据模型

`services/docs-api/models/user.py` 与 `services/aichat-api/models/user.py`（两份为同一结构、共享同一 DB）：

- `users` 表新增列 `is_admin INTEGER NOT NULL DEFAULT 0`。
- `init_db()` 增加兼容迁移：建表后尝试 `ALTER TABLE users ADD COLUMN is_admin ...`，捕获重复列错误（幂等，老库自动补列）。
- `User` dataclass 增加 `is_admin: bool = False`；`_row_to_user` 读取该字段；`create_user` 增加 `is_admin` 参数（默认 False）。
- 新增 `ensure_admin_user()`：读取 `ADMIN_USER` / `ADMIN_PASSWORD` 环境变量；用户不存在则创建管理员（绑定 `default` 库）；已存在则只补 `is_admin=1`、不改密码；缺 `ADMIN_PASSWORD` 时 `logger.warning` 并跳过创建（已存在用户仍提升）。

### 2. 会话接口

- `services/docs-api/models/v1_responses.py`：`SessionUserInfo` 与 `SessionMeResponse` 增加 `is_admin: bool = False`。
- `services/docs-api/routes/v1/auth.py`：`/login` 与 `/me` 返回 `is_admin`。
- `apps/user-web/src/stores/auth.ts` 的 `SessionUserInfo` 接口同步加可选 `is_admin`。

### 3. 管理接口鉴权

- 新增 `services/docs-api/admin_auth.py`，提供 `require_admin(request)` FastAPI 依赖：
  - 解析 `Authorization: Bearer` → `get_session_user(raw_token)`；
  - 无 token / 用户不存在 / 已停用 → 401；
  - 用户存在但 `is_admin != 1` → 403；
- `users_router` 与 `api_key_router` 增加 router 级 `dependencies=[Depends(require_admin)]`，覆盖 `/api/users`、`/api/api-keys` 全部方法。

### 4. 启动引导

- `services/docs-api/main.py` 启动时调用 `ensure_admin_user()`，日志输出：管理员已就绪 / 已创建 / `ADMIN_PASSWORD` 缺失告警。

## 前端改动（admin-web）

- 新增 `apps/admin-web/src/stores/auth.ts`（仿 user-web `stores/auth.ts`）：
  - state：`token`（localStorage 键 `ag_session_token`，与 user-web 同源共享，同一账号体系）、`user`、`checking`；
  - `login(username, password)`：`docsApiClient.post('/v1/auth/login')` → 保存 token → 校验 `user.is_admin`，非管理员则清理会话并抛「该账号无管理员权限」；
  - `refreshMe()`：`GET /v1/auth/me`，401/403 清理会话；
  - `logout()`。
- 新增 `apps/admin-web/src/components/AuthGate.vue`（仿 user-web AuthGate，文案「管理员登录」）：未登录 / 校验失败时渲染登录卡片，遮挡整个 app。
- `apps/admin-web/src/App.vue`：挂 `<AuthGate />`，仅已登录且 `is_admin` 时渲染主界面。
- 共享 `ag_session_token` 的行为说明：普通用户登录 user-web 后访问 `/admin/`，会被 `is_admin` 校验拦在登录页，不会越权；管理员登录后台后，同一会话在 user-web 也视为已登录（同账号体系，符合预期）。

## nginx 改动（docker/nginx/nginx.conf）

- 删除 `geo $admin_allowed` 整块。
- 删除 `/admin/`、`^/api/api-keys`、`^/api/users` 上的 `if ($admin_allowed = 0)` 与 `auth_basic` / `auth_basic_user_file`。
- 删除 `/docs`、`/redoc`、`/openapi.json` 上的 `if ($admin_allowed = 0)`；这三个端点变为公网可见（保留便于排障，如不需要可后续关闭）。
- 其余 location 不动；`docker/nginx/.htpasswd` 不再被引用（保留文件不影响，后续可清理）。

## 错误处理

- 登录失败：401「用户名或密码错误」（沿用现有）。
- 未带会话访问管理接口：401。
- 非管理员会话访问管理接口：403。
- 前端统一用登录卡片上的错误提示展示。

## 测试

- `tests/unit/test_unit_user_model.py`：`is_admin` 默认值、迁移幂等（重复 ALTER 不报错）、`ensure_admin_user`（创建 / 提升 / 缺密码不崩溃）。
- `tests/unit/test_unit_users_routes.py`：无 token 401、非管理员 403、管理员 200。
- `tests/unit/test_unit_user_auth.py`：login 响应含 `is_admin`。
- 前端：`vue-tsc` + `pnpm --filter @angineer/admin-web build`；user-web 同步跑 build（apiClient 共用）。
- 部署后手工验证：`/admin/` 公网可打开、管理员登录成功、普通账号被拒。

## 发布

- 主仓版本 0.2.14 → 0.2.15（功能 commit → chore 版本 commit → push origin main → GitHub Actions 自动部署，webhook 含提交明细）。
- 部署后：服务器 `/home/runner/AnGIneer/.env` 增加 `ADMIN_USER` / `ADMIN_PASSWORD`，重启 `docs-api`（随部署重启自动生效）。
- 组件仓库（docs-ui / aichat-ui / smartree-ui / ai-inference）无需变动：admin-web 与 docs-api 都在主仓。

## 边界情况

- 老库升级：`ALTER TABLE` 迁移幂等，重复执行不报错。
- 首个管理员引导在 `.env` 缺 `ADMIN_PASSWORD` 时不崩溃，仅告警。
- 管理员账号同时可登录 user-web（同账号体系，绑 `default` 库）。
- Basic Auth 移除后 `.htpasswd` 不再被使用，不删除文件以防回滚需要。
