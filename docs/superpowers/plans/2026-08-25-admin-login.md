# admin-web 账号密码登录 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 让管理员在 admin-web 用「用户名 + 密码」登录（复用现有 users 表 + 会话体系），并把管理接口鉴权从 nginx Basic Auth 迁移到应用层 `is_admin` 会话校验。

**Architecture:** 后端在 `users` 表加 `is_admin` 列（含幂等迁移），启动时用 `.env` 的 `ADMIN_USER` / `ADMIN_PASSWORD` 引导首个管理员；`/api/users` 与 `/api/api-keys` 挂 `require_admin` 依赖（Bearer 会话 + is_admin）；admin-web 新增登录页（AuthGate + Pinia store），token 与 user-web 共用 localStorage 键 `ag_session_token`；nginx 移除 IP 白名单与 Basic Auth，后台公网可直连。

**Tech Stack:** Python / FastAPI / SQLite、Vue 3 / TypeScript / Pinia / Ant Design Vue、nginx、Docker。

---

## 文件结构

- 修改 `services/docs-api/models/user.py`：`is_admin` 列 + 迁移 + `create_user` 参数 + `update_user` 参数 + `ensure_admin_user()`
- 修改 `services/aichat-api/models/user.py`：与 docs-api 同步同样的模型改动
- 修改 `services/docs-api/models/v1_responses.py`：`SessionUserInfo` / `SessionMeResponse` 加 `is_admin`
- 修改 `services/docs-api/routes/v1/auth.py`：login / me 返回 `is_admin`
- 新建 `services/docs-api/admin_auth.py`：`require_admin` 依赖
- 修改 `services/docs-api/users_routes.py`、`services/docs-api/api_key_routes.py`：挂 `require_admin`
- 修改 `services/docs-api/main.py`：启动调用 `ensure_admin_user()`
- 修改 `docker/nginx/nginx.conf`：移除 `geo $admin_allowed` 与所有 `auth_basic`
- 修改 `README.md`：管理端访问方式描述同步
- 新建 `apps/admin-web/src/stores/auth.ts`、`apps/admin-web/src/components/AuthGate.vue`
- 修改 `apps/admin-web/src/App.vue`、`apps/admin-web/src/stores/index.ts`
- 修改 `apps/admin-web/src/api/users.ts`、`apps/admin-web/src/views/UserManage.vue`（管理员标记 UI）
- 修改 `apps/user-web/src/stores/auth.ts`：`SessionUserInfo` 加可选 `is_admin`
- 修改 `package.json`：版本 0.2.14 → 0.2.15
- 测试：`tests/unit/test_unit_user_model.py`、`tests/unit/test_unit_aichat_session.py`、`tests/unit/test_unit_user_auth.py`、`tests/unit/test_unit_users_routes.py`、新建 `tests/unit/test_unit_admin_auth.py`

---

## Task 1: docs-api users 模型加 is_admin + 幂等迁移（TDD）

**Files:**
- Modify: `services/docs-api/models/user.py`
- Test: `tests/unit/test_unit_user_model.py`

- [ ] **Step 1: 写失败测试**

在 `tests/unit/test_unit_user_model.py` 的 `UserModelTests` 类末尾追加：

```python
    def test_is_admin_default_false(self):
        user = user_model.create_user("ivan", "Ivan", "secret123", ["lib-a"])
        self.assertFalse(user.is_admin)
        self.assertFalse(user_model.get_user_by_username("ivan").is_admin)

    def test_create_user_with_is_admin(self):
        user = user_model.create_user("judy", "Judy", "secret123", ["lib-a"], is_admin=True)
        self.assertTrue(user.is_admin)
        self.assertTrue(user_model.get_user_by_username("judy").is_admin)

    def test_init_db_adds_is_admin_column_to_legacy_table(self):
        conn = user_model._get_conn()
        conn.execute("DROP TABLE sessions")
        conn.execute("DROP TABLE user_libraries")
        conn.execute("DROP TABLE users")
        conn.execute(
            """
            CREATE TABLE users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT NOT NULL UNIQUE,
                display_name TEXT NOT NULL DEFAULT '',
                password_hash TEXT NOT NULL,
                is_active INTEGER NOT NULL DEFAULT 1,
                created_at TEXT NOT NULL,
                last_login_at TEXT
            )
            """
        )
        conn.commit()
        conn.close()
        user_model.init_db()
        user = user_model.create_user("kate", "Kate", "secret123")
        self.assertFalse(user.is_admin)
        user_model.init_db()  # 幂等：重复迁移不报错
```

- [ ] **Step 2: 运行测试确认失败**

Run: `python -m pytest tests/unit/test_unit_user_model.py -v`

Expected: FAIL —— `AttributeError: 'User' object has no attribute 'is_admin'`

- [ ] **Step 3: 最小实现**

`services/docs-api/models/user.py`：

1. `User` dataclass 在 `is_active: bool = True` 后加一行：

```python
    is_admin: bool = False
```

2. `init_db()` 的 `CREATE TABLE IF NOT EXISTS users` 里，`is_active` 行后加：

```sql
            is_admin INTEGER NOT NULL DEFAULT 0,
```

并在 `conn.commit()` 之前（三张表建完之后）加幂等迁移：

```python
    try:
        conn.execute("ALTER TABLE users ADD COLUMN is_admin INTEGER NOT NULL DEFAULT 0")
    except sqlite3.OperationalError:
        pass  # 已存在该列
```

3. `_row_to_user` 在 `is_active=bool(row["is_active"]),` 后加：

```python
        is_admin=bool(row["is_admin"]),
```

4. `create_user` 签名加参数，INSERT 语句加列：

```python
def create_user(
    username: str,
    display_name: str = "",
    password: str = "",
    library_ids: Optional[List[str]] = None,
    is_admin: bool = False,
) -> User:
```

```python
        cur = conn.execute(
            "INSERT INTO users (username, display_name, password_hash, is_active, is_admin, created_at) VALUES (?, ?, ?, 1, ?, ?)",
            (username, display_name.strip(), hash_password(password), 1 if is_admin else 0, _now()),
        )
```

- [ ] **Step 4: 运行测试确认通过**

Run: `python -m pytest tests/unit/test_unit_user_model.py -v`

Expected: PASS（新增 3 个 + 原有全部通过）

- [ ] **Step 5: 提交**

```bash
git add services/docs-api/models/user.py tests/unit/test_unit_user_model.py
git commit -m "feat(docs-api): users 模型新增 is_admin 与幂等迁移"
```

---

## Task 2: ensure_admin_user() 首个管理员引导（TDD）

**Files:**
- Modify: `services/docs-api/models/user.py`
- Test: `tests/unit/test_unit_user_model.py`

- [ ] **Step 1: 写失败测试**

在 `tests/unit/test_unit_user_model.py` 末尾追加：

```python
    def test_ensure_admin_creates_from_env(self):
        with patch.dict(os.environ, {"ADMIN_USER": "boss", "ADMIN_PASSWORD": "boss123456"}, clear=False):
            user = user_model.ensure_admin_user()
        self.assertIsNotNone(user)
        self.assertEqual(user.username, "boss")
        self.assertTrue(user.is_admin)
        self.assertEqual(user.library_ids, ["default"])

    def test_ensure_admin_promotes_existing(self):
        user = user_model.create_user("boss", "Boss", "secret123")
        self.assertFalse(user.is_admin)
        with patch.dict(os.environ, {"ADMIN_USER": "boss", "ADMIN_PASSWORD": "boss123456"}, clear=False):
            promoted = user_model.ensure_admin_user()
        self.assertTrue(promoted.is_admin)

    def test_ensure_admin_missing_password_no_crash(self):
        with patch.dict(os.environ, {"ADMIN_USER": "boss", "ADMIN_PASSWORD": ""}, clear=False):
            self.assertIsNone(user_model.ensure_admin_user())

    def test_ensure_admin_no_env_noop(self):
        with patch.dict(os.environ, {"ADMIN_USER": "", "ADMIN_PASSWORD": ""}, clear=False):
            self.assertIsNone(user_model.ensure_admin_user())
```

- [ ] **Step 2: 运行测试确认失败**

Run: `python -m pytest tests/unit/test_unit_user_model.py -k ensure_admin -v`

Expected: FAIL —— `AttributeError: module 'models.user' has no attribute 'ensure_admin_user'`

- [ ] **Step 3: 最小实现**

`services/docs-api/models/user.py`：

1. 文件顶部 `import os` 后加：

```python
import logging
```

2. `MIN_PASSWORD_LEN = 6` 之后加：

```python
logger = logging.getLogger(__name__)
```

3. `set_user_active` 函数之后加私有辅助：

```python
def _set_user_admin(user_id: int, is_admin: bool) -> bool:
    init_db()
    conn = _get_conn()
    try:
        cur = conn.execute("UPDATE users SET is_admin = ? WHERE id = ?", (1 if is_admin else 0, user_id))
        conn.commit()
    finally:
        conn.close()
    return cur.rowcount > 0
```

4. 文件末尾加：

```python
def ensure_admin_user() -> Optional[User]:
    """启动引导：.env 的 ADMIN_USER / ADMIN_PASSWORD 创建或提升首个管理员。"""
    username = (os.getenv("ADMIN_USER", "") or "").strip()
    password = os.getenv("ADMIN_PASSWORD", "") or ""
    if not username:
        return None
    existing = get_user_by_username(username)
    if existing is not None:
        if not existing.is_admin:
            _set_user_admin(existing.id, True)
            logger.info("管理员已就绪：%s（已提升 is_admin）", username)
            return get_user_by_id(existing.id)
        return existing
    if not password:
        logger.warning("ADMIN_USER=%s 已配置但 ADMIN_PASSWORD 未设置，跳过管理员创建", username)
        return None
    if len(password) < MIN_PASSWORD_LEN:
        logger.warning("ADMIN_PASSWORD 长度不能少于 %d 位，跳过管理员创建", MIN_PASSWORD_LEN)
        return None
    user = create_user(username, username, password, ["default"], is_admin=True)
    logger.info("已创建首个管理员：%s", username)
    return user
```

- [ ] **Step 4: 运行测试确认通过**

Run: `python -m pytest tests/unit/test_unit_user_model.py -v`

Expected: PASS（新增 4 个 + 原有全部通过）

- [ ] **Step 5: 提交**

```bash
git add services/docs-api/models/user.py tests/unit/test_unit_user_model.py
git commit -m "feat(docs-api): ensure_admin_user 首个管理员引导"
```

---

## Task 3: aichat-api 同步 users 模型（TDD）

**Files:**
- Modify: `services/aichat-api/models/user.py`
- Test: `tests/unit/test_unit_aichat_session.py`

背景：`services/aichat-api/models/user.py` 与 docs-api 版是同一套结构、共享同一 DB，必须保持列一致（aichat-api 的 `init_db()` 先跑时也要建出 `is_admin` 列）。

- [ ] **Step 1: 写失败测试**

在 `tests/unit/test_unit_aichat_session.py` 的 `AichatSessionTests` 类末尾追加：

```python
    def test_user_model_has_is_admin(self):
        loaded = user_model.get_user_by_id(self.user.id)
        self.assertFalse(loaded.is_admin)
        admin = user_model.create_user("boss", "Boss", "secret123", ["lib-a"], is_admin=True)
        self.assertTrue(admin.is_admin)
```

- [ ] **Step 2: 运行测试确认失败**

Run: `python -m pytest tests/unit/test_unit_aichat_session.py -v`

Expected: FAIL —— `TypeError: create_user() got an unexpected keyword argument 'is_admin'`

- [ ] **Step 3: 同步实现**

把 Task 1 Step 3 与 Task 2 Step 3 对 `services/docs-api/models/user.py` 的 6 处改动（`is_admin` dataclass 字段、`init_db` 建表列、`ALTER` 迁移、`_row_to_user`、`create_user` 参数与 INSERT、`logging`/`logger`、`_set_user_admin`、`ensure_admin_user`）原样应用到 `services/aichat-api/models/user.py`。

验证两份文件差异：

```bash
git diff --no-index --stat services/docs-api/models/user.py services/aichat-api/models/user.py
```

Expected: 无输出（两份文件完全一致）。

- [ ] **Step 4: 运行测试确认通过**

Run: `python -m pytest tests/unit/test_unit_aichat_session.py tests/unit/test_unit_user_model.py -v`

Expected: PASS

- [ ] **Step 5: 提交**

```bash
git add services/aichat-api/models/user.py tests/unit/test_unit_aichat_session.py
git commit -m "feat(aichat-api): users 模型同步 is_admin 与引导函数"
```

---

## Task 4: 会话接口返回 is_admin（TDD）

**Files:**
- Modify: `services/docs-api/models/v1_responses.py`
- Modify: `services/docs-api/routes/v1/auth.py`
- Test: `tests/unit/test_unit_user_auth.py`

- [ ] **Step 1: 写失败测试**

在 `tests/unit/test_unit_user_auth.py` 的 `LoginTests` 类末尾追加：

```python
    def test_login_response_includes_is_admin(self):
        resp = self._login()
        self.assertFalse(resp.user.is_admin)
        user_model.create_user("boss", "Boss", "secret123", ["lib-a"], is_admin=True)
        resp2 = self._login(username="boss", password="secret123")
        self.assertTrue(resp2.user.is_admin)

    def test_me_includes_is_admin(self):
        from routes.v1 import auth
        req = MagicMock()
        req.state.session_user = self.user
        with patch.object(auth, "get_docs_service") as mock_ks:
            mock_ks.return_value.get_library.return_value = MagicMock()
            resp = asyncio.run(auth.auth_me(req))
        self.assertEqual(resp.is_admin, self.user.is_admin)
```

- [ ] **Step 2: 运行测试确认失败**

Run: `python -m pytest tests/unit/test_unit_user_auth.py -v`

Expected: FAIL —— `AttributeError: 'SessionUserInfo' object has no attribute 'is_admin'`

- [ ] **Step 3: 最小实现**

`services/docs-api/models/v1_responses.py`：

```python
class SessionUserInfo(BaseModel):
    username: str
    display_name: str
    libraries: List[str] = Field(default_factory=list)
    is_admin: bool = False


class LoginResponse(BaseModel):
    token: str
    user: SessionUserInfo


class SessionMeResponse(BaseModel):
    username: str
    display_name: str
    libraries: List[str] = Field(default_factory=list)
    default_library: str = ""
    is_admin: bool = False
```

`services/docs-api/routes/v1/auth.py` 的 `auth_login` 返回字典加字段：

```python
    return LoginResponse(
        token=token,
        user={
            "username": user.username,
            "display_name": user.display_name,
            "libraries": user.library_ids,
            "is_admin": user.is_admin,
        },
    )
```

`auth_me` 的会话分支返回加字段：

```python
        return SessionMeResponse(
            username=session_user.username,
            display_name=session_user.display_name,
            libraries=existing,
            default_library=existing[0] if existing else "",
            is_admin=session_user.is_admin,
        )
```

`apps/user-web/src/stores/auth.ts` 的接口同步：

```ts
export interface SessionUserInfo {
  username: string
  display_name: string
  libraries: string[]
  default_library?: string
  is_admin?: boolean
}
```

- [ ] **Step 4: 运行测试确认通过**

Run: `python -m pytest tests/unit/test_unit_user_auth.py -v`

Expected: PASS

- [ ] **Step 5: 提交**

```bash
git add services/docs-api/models/v1_responses.py services/docs-api/routes/v1/auth.py tests/unit/test_unit_user_auth.py apps/user-web/src/stores/auth.ts
git commit -m "feat(docs-api): login/me 返回 is_admin"
```

---

## Task 5: require_admin 守卫 + 管理路由挂载（TDD）

**Files:**
- Create: `services/docs-api/admin_auth.py`
- Modify: `services/docs-api/users_routes.py`
- Modify: `services/docs-api/api_key_routes.py`
- Test: `tests/unit/test_unit_admin_auth.py`（新建）

- [ ] **Step 1: 写失败测试**

新建 `tests/unit/test_unit_admin_auth.py`：

```python
"""管理端 require_admin 守卫测试。"""
import os
import sys
import tempfile
import unittest
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../../services/docs-api")))
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../../services/docs-core/src")))
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../../services/angineer-core/src")))
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../../services/tree-core/src")))

import models.user as user_model  # noqa: E402
from admin_auth import resolve_admin_session  # noqa: E402
from fastapi import HTTPException  # noqa: E402


class AdminAuthTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(lambda: __import__("shutil").rmtree(self.tmp, ignore_errors=True))
        patcher = patch.object(user_model, "DB_PATH", os.path.join(self.tmp, "users.sqlite"))
        patcher.start()
        self.addCleanup(patcher.stop)
        user_model.init_db()

    def _req(self, token=""):
        req = MagicMock()
        req.headers = {"Authorization": f"Bearer {token}"} if token else {}
        return req

    def test_no_token_401(self):
        with self.assertRaises(HTTPException) as ctx:
            resolve_admin_session(self._req())
        self.assertEqual(ctx.exception.status_code, 401)

    def test_normal_user_403(self):
        user = user_model.create_user("alice", "Alice", "secret123", ["lib-a"])
        token = user_model.create_session(user.id)
        with self.assertRaises(HTTPException) as ctx:
            resolve_admin_session(self._req(token))
        self.assertEqual(ctx.exception.status_code, 403)

    def test_admin_ok(self):
        user = user_model.create_user("boss", "Boss", "secret123", ["lib-a"], is_admin=True)
        token = user_model.create_session(user.id)
        resolved = resolve_admin_session(self._req(token))
        self.assertEqual(resolved.username, "boss")

    def test_admin_routers_have_dependency(self):
        from users_routes import router as users_router
        from api_key_routes import router as api_key_router
        self.assertTrue(users_router.dependencies)
        self.assertTrue(api_key_router.dependencies)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: 运行测试确认失败**

Run: `python -m pytest tests/unit/test_unit_admin_auth.py -v`

Expected: FAIL —— `ModuleNotFoundError: No module named 'admin_auth'`

- [ ] **Step 3: 最小实现**

新建 `services/docs-api/admin_auth.py`：

```python
"""管理端会话鉴权：/api/users 与 /api/api-keys 的管理员守卫。"""
from fastapi import HTTPException, Request

from models.user import get_session_user


def resolve_admin_session(request: Request):
    """校验 Bearer 会话且用户 is_admin=1；通过则返回会话用户，否则抛 401/403。"""
    auth_header = (request.headers.get("Authorization", "") or "").strip()
    if not auth_header.lower().startswith("bearer "):
        raise HTTPException(status_code=401, detail="未登录或会话已失效")
    raw_token = auth_header[7:].strip()
    user = get_session_user(raw_token)
    if user is None or not user.is_active:
        raise HTTPException(status_code=401, detail="未登录或会话已失效")
    if not user.is_admin:
        raise HTTPException(status_code=403, detail="无管理员权限")
    return user
```

`services/docs-api/users_routes.py`：

```python
from fastapi import APIRouter, Depends, HTTPException
from admin_auth import resolve_admin_session

router = APIRouter(prefix="/api/users", tags=["Admin Users"], dependencies=[Depends(resolve_admin_session)])
```

`services/docs-api/api_key_routes.py`：

```python
from fastapi import APIRouter, Depends, HTTPException
from admin_auth import resolve_admin_session

router = APIRouter(prefix="/api", dependencies=[Depends(resolve_admin_session)])
```

- [ ] **Step 4: 运行测试确认通过**

Run: `python -m pytest tests/unit/test_unit_admin_auth.py tests/unit/test_unit_users_routes.py -v`

Expected: PASS

- [ ] **Step 5: 提交**

```bash
git add services/docs-api/admin_auth.py services/docs-api/users_routes.py services/docs-api/api_key_routes.py tests/unit/test_unit_admin_auth.py
git commit -m "feat(docs-api): 管理接口 require_admin 会话守卫"
```

---

## Task 6: 用户管理支持管理员标记（后端，TDD）

**Files:**
- Modify: `services/docs-api/models/user.py`（`update_user` 加 `is_admin`）
- Modify: `services/docs-api/users_routes.py`
- Test: `tests/unit/test_unit_users_routes.py`

- [ ] **Step 1: 写失败测试**

修改 `tests/unit/test_unit_users_routes.py` 的 `_create` helper，并追加测试：

```python
    def _create(self, library_ids=("lib-a",), is_admin=False):
        from users_routes import create_user_route
        req = MagicMock()
        req.username = "alice"
        req.display_name = "Alice"
        req.password = "secret123"
        req.library_ids = list(library_ids)
        req.is_admin = is_admin
        with patch("users_routes.get_docs_service") as mock_ks:
            mock_ks.return_value.get_library.return_value = MagicMock()
            return asyncio.run(create_user_route(req))
```

```python
    def test_create_with_is_admin_flag(self):
        created = self._create(is_admin=True)
        self.assertTrue(created.is_admin)

    def test_update_is_admin_flag(self):
        from users_routes import update_user_route
        created = self._create()
        req = MagicMock()
        req.display_name = "Alice2"
        req.library_ids = ["lib-a"]
        req.is_admin = True
        asyncio.run(update_user_route(created.id, req))
        loaded = user_model.get_user_by_id(created.id)
        self.assertTrue(loaded.is_admin)
```

- [ ] **Step 2: 运行测试确认失败**

Run: `python -m pytest tests/unit/test_unit_users_routes.py -v`

Expected: FAIL —— `AttributeError: 'UserItem' object has no attribute 'is_admin'`

- [ ] **Step 3: 最小实现**

`services/docs-api/models/user.py` 的 `update_user`：

```python
def update_user(
    user_id: int,
    display_name: Optional[str] = None,
    library_ids: Optional[List[str]] = None,
    is_admin: Optional[bool] = None,
) -> bool:
    init_db()
    conn = _get_conn()
    try:
        row = conn.execute("SELECT id FROM users WHERE id = ?", (user_id,)).fetchone()
        if row is None:
            return False
        if display_name is not None:
            conn.execute("UPDATE users SET display_name = ? WHERE id = ?", (display_name.strip(), user_id))
        if library_ids is not None:
            conn.execute("DELETE FROM user_libraries WHERE user_id = ?", (user_id,))
            for lid in library_ids:
                conn.execute("INSERT INTO user_libraries (user_id, library_id) VALUES (?, ?)", (user_id, str(lid).strip()))
        if is_admin is not None:
            conn.execute("UPDATE users SET is_admin = ? WHERE id = ?", (1 if is_admin else 0, user_id))
        conn.commit()
    finally:
        conn.close()
    return True
```

`services/docs-api/users_routes.py`：

```python
class UserItem(BaseModel):
    id: int
    username: str
    display_name: str
    is_admin: bool = False
    library_ids: List[str] = Field(default_factory=list)
    is_active: bool
    created_at: str
    last_login_at: Optional[str] = None


class CreateUserRequest(BaseModel):
    username: str = Field(..., min_length=1, max_length=100)
    display_name: str = Field(default="", max_length=100)
    password: str = Field(..., min_length=6, max_length=200)
    is_admin: bool = False
    library_ids: List[str] = Field(default_factory=list)


class UpdateUserRequest(BaseModel):
    display_name: str = Field(default="", max_length=100)
    is_admin: bool = False
    library_ids: List[str] = Field(default_factory=list)
```

`_to_item`：

```python
def _to_item(user: User) -> UserItem:
    return UserItem(
        id=user.id,
        username=user.username,
        display_name=user.display_name,
        is_admin=user.is_admin,
        library_ids=user.library_ids,
        is_active=user.is_active,
        created_at=user.created_at,
        last_login_at=user.last_login_at,
    )
```

`create_user_route` 调用改为：

```python
        user = create_user(req.username, req.display_name, req.password, req.library_ids, is_admin=req.is_admin)
```

`update_user_route` 调用改为：

```python
    ok = update_user(user_id, display_name=req.display_name, library_ids=req.library_ids, is_admin=req.is_admin)
```

- [ ] **Step 4: 运行测试确认通过**

Run: `python -m pytest tests/unit/test_unit_users_routes.py tests/unit/test_unit_admin_auth.py -v`

Expected: PASS

- [ ] **Step 5: 提交**

```bash
git add services/docs-api/models/user.py services/docs-api/users_routes.py tests/unit/test_unit_users_routes.py
git commit -m "feat(docs-api): 用户管理接口支持 is_admin 标记"
```

---

## Task 7: docs-api 启动引导管理员

**Files:**
- Modify: `services/docs-api/main.py`

- [ ] **Step 1: 实现**

`services/docs-api/main.py`：

1. 在 `from startup_recovery import reconcile_stale_parse_tasks` 后加：

```python
from models.user import ensure_admin_user
```

2. 在 `_reconcile_stale_parse_tasks_on_startup` 函数后追加：

```python
@app.on_event("startup")
def _bootstrap_admin_on_startup() -> None:
    try:
        user = ensure_admin_user()
        if user is not None:
            logger.info("管理员引导完成: %s (is_admin=%s)", user.username, user.is_admin)
    except Exception:
        logger.exception("管理员引导执行失败")
```

- [ ] **Step 2: 冒烟验证**

Run: `python -c "import sys; sys.path.insert(0, 'services/docs-api'); sys.path.insert(0, 'services/docs-core/src'); import main; print('import ok')"`

Expected: `import ok`（无导入错误）

- [ ] **Step 3: 提交**

```bash
git add services/docs-api/main.py
git commit -m "feat(docs-api): 启动时引导首个管理员"
```

---

## Task 8: nginx 移除白名单与 Basic Auth

**Files:**
- Modify: `docker/nginx/nginx.conf`
- Modify: `README.md`（管理端访问方式描述）

- [ ] **Step 1: 改 nginx.conf**

删除整个 `geo $admin_allowed { ... }` 块（含上方注释）。

`/admin/` 改为：

```nginx
        location /admin/ {
            alias /usr/share/nginx/html/admin/;
            index index.html;
            try_files $uri $uri/ /admin/index.html;
        }
```

`^/api/api-keys` 与 `^/api/users` 各自改为（去掉 `if` 与 `auth_basic` 两行）：

```nginx
        location ~ ^/api/api-keys {
            proxy_pass http://api_server;
            proxy_set_header Host $host;
            proxy_set_header X-Real-IP $remote_addr;
            proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
            proxy_set_header X-Forwarded-Proto $scheme;
            proxy_read_timeout 300s;
            proxy_send_timeout 300s;
        }
```

`/docs`、`/redoc`、`/openapi.json` 各自去掉 `if ($admin_allowed = 0) { return 403; }` 一行，保留 `proxy_pass` 与 `proxy_set_header Host $host;`。

- [ ] **Step 2: 更新 README 管理端访问描述**

在 README「公网部署安全」列表里，把 Basic Auth / 白名单相关条目替换为：

```markdown
- 管理后台 `/admin/` 公网可直连，使用账号密码登录（账号体系见用户管理）；管理接口 `/api/users`、`/api/api-keys` 由应用层会话鉴权（需 is_admin 标记）保护
```

- [ ] **Step 3: 校验 nginx 语法**

Run: `docker compose -f docker/docker-compose.yml config -q`

Expected: 退出码 0，无输出（仅校验 compose 可解析；nginx 语法在部署时由容器内 `nginx -t` 兜底，若本机有 nginx 也可 `nginx -t -c docker/nginx/nginx.conf`）。

- [ ] **Step 4: 提交**

```bash
git add docker/nginx/nginx.conf README.md
git commit -m "feat(nginx): 移除管理端 IP 白名单与 Basic Auth，改应用层登录"
```

---

## Task 9: admin-web 登录 store

**Files:**
- Create: `apps/admin-web/src/stores/auth.ts`
- Modify: `apps/admin-web/src/stores/index.ts`

- [ ] **Step 1: 实现 store**

新建 `apps/admin-web/src/stores/auth.ts`：

```ts
import { defineStore } from 'pinia'
import { docsApiClient } from '../../../shared/apiClient'

export interface AdminSessionUser {
  username: string
  display_name: string
  is_admin: boolean
  libraries: string[]
  default_library?: string
}

/** 管理员会话：账号密码 → 会话 token；与 user-web 同源共享 ag_session_token。 */
export const useAdminAuthStore = defineStore('adminAuth', {
  state: () => ({
    token: (typeof localStorage !== 'undefined' ? localStorage.getItem('ag_session_token') : null) ?? '',
    user: null as AdminSessionUser | null,
    checking: false,
  }),
  getters: {
    isAuthed: (state) => Boolean(state.token),
  },
  actions: {
    async login(username: string, password: string) {
      const resp = await docsApiClient.post<{ token: string; user: AdminSessionUser }>(
        '/v1/auth/login',
        { username, password }
      )
      if (!resp.user.is_admin) {
        localStorage.removeItem('ag_session_token')
        this.token = ''
        this.user = null
        throw new Error('该账号无管理员权限')
      }
      localStorage.setItem('ag_session_token', resp.token)
      this.token = resp.token
      this.user = resp.user
    },
    async refreshMe() {
      if (!this.token) return
      this.checking = true
      try {
        const me = await docsApiClient.get<AdminSessionUser>('/v1/auth/me')
        if (!me.is_admin) {
          this.logout()
          throw new Error('该账号无管理员权限')
        }
        this.user = me
      } catch (e: any) {
        this.user = null
        if (e?.apiError?.status === 401 || e?.apiError?.status === 403) {
          this.logout()
        }
        throw e
      } finally {
        this.checking = false
      }
    },
    async logout() {
      try {
        if (this.token) {
          await docsApiClient.post('/v1/auth/logout')
        }
      } catch {
        // best-effort：本地一定清理
      }
      localStorage.removeItem('ag_session_token')
      this.token = ''
      this.user = null
    },
  },
})
```

`apps/admin-web/src/stores/index.ts` 改为：

```ts
/** 状态管理出口 */
export { useThemeStore } from '@angineer/ui-kit'
export { useAdminAuthStore } from './auth'
```

- [ ] **Step 2: 类型检查**

Run: `pnpm --filter @angineer/admin-web exec vue-tsc --noEmit`

Expected: 无类型错误

- [ ] **Step 3: 提交**

```bash
git add apps/admin-web/src/stores/auth.ts apps/admin-web/src/stores/index.ts
git commit -m "feat(admin-web): 管理员登录 store"
```

---

## Task 10: admin-web AuthGate 登录组件

**Files:**
- Create: `apps/admin-web/src/components/AuthGate.vue`

- [ ] **Step 1: 实现组件**

新建 `apps/admin-web/src/components/AuthGate.vue`：

```vue
<template>
  <div v-if="!auth.isAuthed || authFailed" class="auth-gate">
    <div class="auth-card">
      <h2>管理员登录</h2>
      <p class="auth-hint">请输入管理员账号</p>
      <a-input
        v-model:value="username"
        placeholder="用户名"
        :disabled="auth.checking"
        class="auth-field"
        @press-enter="handleLogin"
      />
      <a-input-password
        v-model:value="password"
        placeholder="密码"
        :disabled="auth.checking"
        class="auth-field"
        @press-enter="handleLogin"
      />
      <div v-if="errorText" class="auth-error">{{ errorText }}</div>
      <a-button type="primary" block :loading="auth.checking" @click="handleLogin">
        进入
      </a-button>
    </div>
  </div>
</template>

<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { useAdminAuthStore } from '../stores/auth'

const auth = useAdminAuthStore()
const username = ref('')
const password = ref('')
const errorText = ref('')
const authFailed = ref(false)

onMounted(async () => {
  if (!auth.isAuthed) return
  try {
    await auth.refreshMe()
    authFailed.value = false
  } catch {
    authFailed.value = true
  }
})

async function handleLogin() {
  errorText.value = ''
  if (!username.value.trim() || !password.value) {
    errorText.value = '请输入用户名和密码'
    return
  }
  try {
    await auth.login(username.value.trim(), password.value)
    authFailed.value = false
  } catch (e: any) {
    errorText.value = e?.message || '登录失败，请检查账号密码'
  }
}
</script>

<style scoped>
.auth-gate {
  position: fixed;
  inset: 0;
  z-index: 9999;
  display: flex;
  align-items: center;
  justify-content: center;
  background: var(--bg-primary);
}
.auth-card {
  width: 360px;
  padding: 32px 28px;
  border-radius: 12px;
  background: var(--panel-bg);
  border: 1px solid var(--border-color);
  box-shadow: 0 12px 40px rgba(0, 0, 0, 0.25);
  color: var(--text-primary);
}
.auth-card h2 {
  margin: 0 0 8px;
  font-size: 20px;
}
.auth-hint {
  margin: 0 0 20px;
  color: var(--text-secondary);
  font-size: 13px;
}
.auth-field {
  margin-bottom: 12px;
}
.auth-error {
  margin: 8px 0;
  color: #ff4d4f;
  font-size: 13px;
}
</style>
```

- [ ] **Step 2: 类型检查**

Run: `pnpm --filter @angineer/admin-web exec vue-tsc --noEmit`

Expected: 无类型错误

- [ ] **Step 3: 提交**

```bash
git add apps/admin-web/src/components/AuthGate.vue
git commit -m "feat(admin-web): 管理员登录页 AuthGate"
```

---

## Task 11: admin-web App.vue 挂登录门

**Files:**
- Modify: `apps/admin-web/src/App.vue`

- [ ] **Step 1: 改模板**

`<a-app>` 之后、`.app-container` 之前插入 `<AuthGate />`；`.app-container` 加 `v-if`：

```vue
    <a-app>
      <AuthGate />
      <div v-if="authStore.isAuthed && authStore.user?.is_admin" class="app-container" :class="appClass">
```

- [ ] **Step 2: 改脚本**

在 `import { AppHeader, useTheme, type NavItem } from '@angineer/ui-kit'` 附近加：

```ts
import AuthGate from './components/AuthGate.vue'
import { useAdminAuthStore } from './stores/auth'
```

在 `const router = useRouter()` 附近加：

```ts
const authStore = useAdminAuthStore()
```

- [ ] **Step 3: 构建验证**

Run: `pnpm --filter @angineer/admin-web exec vue-tsc --noEmit && pnpm --filter @angineer/admin-web build`

Expected: 无类型错误；`✓ built`

- [ ] **Step 4: 提交**

```bash
git add apps/admin-web/src/App.vue
git commit -m "feat(admin-web): 后台挂管理员登录门"
```

---

## Task 12: 用户管理 UI 支持管理员标记

**Files:**
- Modify: `apps/admin-web/src/api/users.ts`
- Modify: `apps/admin-web/src/views/UserManage.vue`

- [ ] **Step 1: 改 users.ts**

```ts
export interface AdminUserItem {
  id: number
  username: string
  display_name: string
  is_admin: boolean
  library_ids: string[]
  is_active: boolean
  created_at: string
  last_login_at: string | null
}

export const usersApi = {
  list: (): Promise<AdminUserItem[]> => docsApiClient.get('/users'),
  create: (data: { username: string; display_name: string; password: string; is_admin: boolean; library_ids: string[] }): Promise<AdminUserItem> =>
    docsApiClient.post('/users', data),
  update: (id: number, data: { display_name: string; is_admin: boolean; library_ids: string[] }): Promise<{ status: string }> =>
    docsApiClient.put(`/users/${id}`, data),
  resetPassword: (id: number, password: string): Promise<{ status: string }> =>
    docsApiClient.post(`/users/${id}/password`, { password }),
  setActive: (id: number, active: boolean): Promise<{ status: string }> =>
    docsApiClient.post(`/users/${id}/${active ? 'activate' : 'deactivate'}`),
  del: (id: number): Promise<{ status: string }> =>
    docsApiClient.delete(`/users/${id}`),
}
```

- [ ] **Step 2: 改 UserManage.vue 表格**

`columns` 在「备注」后加一列：

```ts
  { title: '管理员', key: 'is_admin', width: 80, minWidth: 70 },
```

`#bodyCell` 模板里，「启用」分支前加：

```vue
          <template v-else-if="column.key === 'is_admin'">
            <a-switch
              :checked="record.is_admin"
              size="small"
              @change="(checked: boolean) => handleAdminToggle(record, checked)"
            />
          </template>
```

- [ ] **Step 3: 改 UserManage.vue 表单**

`form` reactive 加字段：

```ts
const form = reactive({ username: '', display_name: '', password: '', is_admin: false, library_ids: [] as string[] })
```

「新建用户」弹窗「初始密码」后加：

```vue
        <a-form-item label="设为管理员">
          <a-switch v-model:checked="form.is_admin" />
        </a-form-item>
```

「编辑用户」弹窗「备注」后加同样的 `a-form-item`。

`resetForm` 加 `form.is_admin = false`；`openEdit` 加 `form.is_admin = record.is_admin`。

`handleCreate` 的 `usersApi.create({ ... })` 加 `is_admin: form.is_admin,`。

`handleUpdate` 的 `usersApi.update(...)` 改为：

```ts
    await usersApi.update(editingUser.value.id, {
      display_name: form.display_name.trim(),
      is_admin: form.is_admin,
      library_ids: form.library_ids,
    })
```

`handleToggle` 后加：

```ts
async function handleAdminToggle(record: AdminUserItem, checked: boolean): Promise<void> {
  try {
    await usersApi.update(record.id, {
      display_name: record.display_name,
      is_admin: checked,
      library_ids: record.library_ids,
    })
    record.is_admin = checked
    message.success(checked ? '已设为管理员' : '已取消管理员')
  } catch (e: any) {
    message.error('操作失败: ' + (e.message || e))
  }
}
```

- [ ] **Step 4: 构建验证**

Run: `pnpm --filter @angineer/admin-web exec vue-tsc --noEmit && pnpm --filter @angineer/admin-web build`

Expected: 无类型错误；`✓ built`

- [ ] **Step 5: 提交**

```bash
git add apps/admin-web/src/api/users.ts apps/admin-web/src/views/UserManage.vue
git commit -m "feat(admin-web): 用户管理支持管理员标记"
```

---

## Task 13: 全量验证 + 发版 + 服务器配置

**Files:**
- Modify: `package.json`（版本号）

- [ ] **Step 1: 全量单元测试**

Run: `python -m pytest tests/unit -q`

Expected: 全部 PASS，无失败

- [ ] **Step 2: 双前端构建**

Run: `pnpm --filter @angineer/admin-web build && pnpm --filter @angineer/user-web build`

Expected: 两个 app 均 `✓ built`

- [ ] **Step 3: 版本号 0.2.14 → 0.2.15**

`package.json`：

```json
  "version": "0.2.15",
```

```bash
git add package.json
git commit -m "chore: 版本号 0.2.14 → 0.2.15"
git push origin main
```

Expected: push 成功后 GitHub Actions 自动部署（webhook 含提交明细）。

- [ ] **Step 4: 服务器 .env 写入管理员账号**

SSH 到服务器，追加（`<密码>` 换成 6 位以上的强密码，或由执行者生成后告知用户）：

```bash
ssh root@124.221.238.70 "grep -q '^ADMIN_USER=' /home/runner/AnGIneer/.env || echo 'ADMIN_USER=<管理员用户名>' >> /home/runner/AnGIneer/.env; grep -q '^ADMIN_PASSWORD=' /home/runner/AnGIneer/.env || echo 'ADMIN_PASSWORD=<密码>' >> /home/runner/AnGIneer/.env"
```

- [ ] **Step 5: 重启 docs-api 并验证**

```bash
ssh root@124.221.238.70 "cd /home/runner/AnGIneer/docker && docker compose up -d docs-api"
```

等 10 秒后验证（登录接口返回 `is_admin: true`；`/admin/` 公网 200；`/api/users` 无 token 401）：

```bash
curl -s -X POST http://127.0.0.1/api/v1/auth/login -H 'Content-Type: application/json' -d '{"username":"<管理员用户名>","password":"<密码>"}'
curl -s -o /dev/null -w '%{http_code}\n' http://124.221.238.70/admin/
curl -s -o /dev/null -w '%{http_code}\n' http://124.221.238.70/api/users
```

Expected: 登录返回含 `"is_admin":true`；`/admin/` 200；`/api/users` 401。

- [ ] **Step 6: 交付**

告知用户：管理员账号、登录地址 `http://124.221.238.70/admin/`、普通用户仍走 `http://124.221.238.70/`。

---

## Self-Review

**Spec 覆盖：**
- is_admin 列 + 幂等迁移 → Task 1、Task 3
- `.env` 引导首个管理员 → Task 2、Task 7
- login/me 返回 is_admin → Task 4
- require_admin 挂 `/api/users`、`/api/api-keys` → Task 5
- admin-web 登录页（store + AuthGate + App 挂载）→ Task 9、10、11
- 用户管理里可指定管理员 → Task 6（后端）、Task 12（前端）
- nginx 移除白名单与 Basic Auth → Task 8
- 测试、构建、发版、服务器 `.env` 配置 → Task 13

**类型一致性：**
- 后端统一用 `is_admin`（模型字段 / Pydantic 字段 / 路由参数）。
- 前端统一用 `is_admin`（`AdminSessionUser` / `AdminUserItem` / 表单字段）。
- 会话 token 统一用 `ag_session_token`。

**占位符扫描：** 无 TBD/TODO；Task 13 中的 `<密码>` / `<管理员用户名>` 是执行期输入的变量，执行时替换为实际值。
