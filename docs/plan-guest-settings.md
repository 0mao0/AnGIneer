# 后台「游客设置」施工计划（库授权 / 轮数上限 / 开放开关）

> **For agentic workers:** REQUIRED SUB-SKILL: 用 subagent-driven-development（推荐）或 executing-plans 逐任务执行。步骤用 `- [ ]` 复选框跟踪。

**Goal:** 在后台用户管理列表置顶「游客」虚拟行，可视化配置免登录访客的三件事——可用知识库、轮数上限、开放/关闭；游客端放开库选择器（模型选择仍隐藏）；关闭态=进页可浏览、发送第一条才弹登录。设计稿：`docs/design-guest-settings.md`（已定稿，2026-10-17 业主四点口径确认）。

**Architecture:** 单一真相源 = `data/platform/guest_settings.json`（`{enabled, rounds, library_ids}`，原子写，优先级 文件 > env `ANGINEER_GUEST_ROUNDS` > 30）。读写都在 docs-api（`/api/guest/*` 三端点，settings 管理员鉴权、config 公开）；aichat-api 只读同一文件做闸门与库校验（跨容器经 `data/` 卷即时同步，零缓存零重启）。前端 admin-web 合成虚拟行复用现有选择器/开关组件；user-web 新增 guestConfig state + 选择器数据源切换。

**Tech Stack:** Python 3.11 / FastAPI（docs-api、aichat-api）/ pytest + unittest / Vue 3 + ant-design-vue + vue-tsc / pnpm。

**日期:** 2026-10-17。

---

## 已核实的代码事实（施工前先信这些，别重新考古）

| # | 事实 | 位置 |
|---|---|---|
| F1 | 游客闸现状：`guest_rounds_limit()` 只读 env；`guest_gate_blocked(owner, store)` 两参、`store=None` 直返 False、非 `g:` 直返 False（`ip:` 永不进轮闸，勿改） | `services/aichat-api/chat_auth.py:199-222`（ip: 直返在 :215） |
| F2 | 匿名库校验现状：空/default → `["default"]`；显式其它 → 403 | `chat_auth.py:148-154`（`enforce_bound_libraries` 匿名分支） |
| F3 | 端点接线：`enforce_bound_libraries(raw_request.state, library_ids)` :465 → `guest_gate_blocked(owner, store)` :479（403 detail.code=`login_required` :480-486）——同一 `raw_request.state`，是单请求共读的天然挂点 | `services/aichat-api/main.py:463-486` |
| F4 | 运行时配置文件原子写先例：`load_settings` 每调用直读；`save_settings` 写 `.tmp` + `os.replace` | `services/aichat-api/nightly_control.py:110-146` |
| F5 | 路径解析：`resolve_data_file(env_key, filename)`，env 覆盖 > 仓库根 `data/` | `services/shared/src/shared/paths.py:18-23` |
| F6 | 管理端鉴权现成：`resolve_admin_session`（Bearer + is_admin，401/403）；users_routes 用 router 级 `dependencies` 模式 | `services/docs-api/admin_auth.py:7-18`；`services/docs-api/users_routes.py:22` |
| F7 | docs-api 挂 router 模式：`from users_routes import router as users_router` → `app.include_router(users_router)`；sys.path 已含 `shared/src` | `services/docs-api/main.py:17-19,30,135` |
| F8 | `get_docs_service().get_library(id)` 返回的库对象带注册表 enrichment 的 `group_name`；`list_grouped_libraries()` 返回 `[{group_name, display_name, libraries:[{id,name,...}]}]` | `services/docs-core/src/docs_core/docs_service.py:548-557,591-595,634-670` |
| F9 | 常量：`EVALS_GROUP = "evals"`、`FANOUT_WARN_THRESHOLD = 20`（V2 观测口径） | `services/shared/src/shared/subscription.py:23,31` |
| F10 | 前端游客现状：ChatHome 对游客强制 `library-options=[]`、`library-sections=[]`、隐藏模型选择；`effectiveLibraryId` 游客恒 `'default'`；`login_required` 弹 AuthGate 通道已有 | `apps/user-web/src/views/ChatHome.vue:18-22,160-172`；`apps/user-web/src/stores/auth.ts:37-38` |
| F11 | admin-web 现状：`columns` 7 列（用户名/备注/管理员/授权知识库/最近登录/启用/操作）；`openEdit` 开弹框前 `loadLibraries()`（R5 无缓存）；列表标签复用 `buildAccessUnits`；`AccessScopeSelect` props = `modelValue/groups/loose` | `apps/admin-web/src/views/UserManage.vue:159-167,222-231,155-157`；`apps/admin-web/src/components/AccessScopeSelect.vue:82-86` |
| F12 | 测试锚点：aichat 游客闸测试 `_FakeStore`（guest_rounds/guest_is_claimed）+ setUp env 隔离；匿名语义测试在 `test_multi_library_auth.py:90-96`；V2 匿名在 `test_multi_library_v2.py:181-186`；端点匿名 403 在 `test_multi_library_endpoint.py:178-185`（`["default","lib-secret"]` 显式集）；docs-api 测试风格 = pytest + TestClient + `monkeypatch.setattr(模块, "get_docs_service", ...)` | 同左各文件 |
| F13 | 命令：apps 无 `typecheck` 脚本，`build = "vue-tsc -b && vite build"` → 类型检查跑 `vue-tsc -b`；根 harness = `python -m unittest discover -s tests -p "test_*.py"` | `apps/admin-web/package.json:9`、`apps/user-web/package.json:9`、`package.json:20` |
| F14 | `/api/guest/*` 无显式代理规则 → 生产 nginx `location /api/` 兜底与两端 vite dev `/api` 兜底都到 docs-api——**零代理改动** | `docker/nginx/nginx.conf:96-105`；两端 `vite.config.ts`（dev 与 admin dev 的 /api 段） |

## 边界（不在本计划内，设计稿 §6 定版）

- 不做 per-游客个体授权 / 用量看板；不收敛 `/api/knowledge/libraries/groups` 本就匿名可达的暴露面（独立治理项）。
- 不动 steer 端点、community 投稿链路、chat-history（cookie 签发）、`aichat-ui` 组件、chat.sqlite。
- 不改「`["default"]` 显式勾选 = 隐式全选」歧义（与登录用户 V2 同款语义）。

## 提交纪律

每个任务收尾 commit（**push 必须逐次取得用户明确指令**，AGENTS.md 2026-09-13）；本计划不写 CHANGELOG（发版时按 `pnpm release` 流程补）；设计稿已含全部取舍登记，实现与设计冲突时先改设计稿再改码。

---

## Stage 1：shared/guest_settings.py（单一真相源，TDD）

### Task 1.1: 写失败测试

**Files:**
- Create: `tests/unit/test_guest_settings.py`

- [ ] **Step 1: 全文件写入**

```python
"""shared.guest_settings 单元测试（游客设置三键：默认/优先级/读坏 fail-closed/校验/原子写）。"""
import json
import os
import shutil
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../../services/shared/src")))

from shared import guest_settings  # noqa: E402


class GuestSettingsTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(lambda: shutil.rmtree(self.tmp, ignore_errors=True))
        self.path = os.path.join(self.tmp, "guest_settings.json")
        self._env = patch.dict(os.environ, {"GUEST_SETTINGS_FILE": self.path})
        self._env.start()
        self.addCleanup(self._env.stop)
        os.environ.pop("ANGINEER_GUEST_ROUNDS", None)

    def _write_raw(self, text):
        with open(self.path, "w", encoding="utf-8") as fh:
            fh.write(text)

    def _write(self, cfg):
        self._write_raw(json.dumps(cfg, ensure_ascii=False))

    # ---- 默认与优先级 ----

    def test_defaults_when_file_absent(self):
        cfg = guest_settings.load_guest_settings()
        self.assertTrue(cfg["enabled"])
        self.assertEqual(cfg["rounds"], 30)
        self.assertEqual(cfg["library_ids"], ["default"])
        self.assertEqual(cfg["load_error"], "")

    def test_env_rounds_when_file_absent(self):
        with patch.dict(os.environ, {"ANGINEER_GUEST_ROUNDS": "5"}):
            self.assertEqual(guest_settings.effective_rounds(), 5)

    def test_file_overrides_env(self):
        self._write({"enabled": True, "rounds": 7, "library_ids": ["default"]})
        with patch.dict(os.environ, {"ANGINEER_GUEST_ROUNDS": "5"}):
            self.assertEqual(guest_settings.effective_rounds(), 7)

    # ---- 读坏 fail-closed（对齐 nightly「读坏禁跑」哲学） ----

    def test_corrupt_json_fail_closed(self):
        self._write_raw("{ 半截")
        cfg = guest_settings.load_guest_settings()
        self.assertFalse(cfg["enabled"])
        self.assertTrue(cfg["load_error"])

    def test_invalid_content_fail_closed(self):
        self._write({"enabled": True, "rounds": 0, "library_ids": []})
        cfg = guest_settings.load_guest_settings()
        self.assertFalse(cfg["enabled"])
        self.assertTrue(cfg["load_error"])
        self.assertEqual(cfg["library_ids"], ["default"])  # fail-closed 回默认集

    # ---- 规范化（保存路径） ----

    def test_normalize_rejects(self):
        for bad in (
            "not-dict",
            {"enabled": "yes", "rounds": 30, "library_ids": ["default"]},
            {"enabled": True, "rounds": 0, "library_ids": ["default"]},
            {"enabled": True, "rounds": 1001, "library_ids": ["default"]},
            {"enabled": True, "rounds": True, "library_ids": ["default"]},
            {"enabled": True, "rounds": 30, "library_ids": []},
            {"enabled": True, "rounds": 30, "library_ids": ["  "]},
        ):
            with self.assertRaises(ValueError):
                guest_settings.normalize_guest_settings(bad)

    # ---- 原子写 ----

    def test_save_roundtrip_and_atomic(self):
        saved = guest_settings.save_guest_settings(
            {"enabled": False, "rounds": 3, "library_ids": ["guifan", " default "]}
        )
        self.assertEqual(saved["library_ids"], ["guifan", "default"])  # 去空白
        cfg = guest_settings.load_guest_settings()
        self.assertEqual(
            cfg,
            {"enabled": False, "rounds": 3, "library_ids": ["guifan", "default"], "load_error": ""},
        )
        self.assertFalse(os.path.exists(self.path + ".tmp"))

    def test_save_creates_parent_dir(self):
        nested = os.path.join(self.tmp, "platform", "guest_settings.json")
        with patch.dict(os.environ, {"GUEST_SETTINGS_FILE": nested}):
            guest_settings.save_guest_settings({"enabled": True, "rounds": 30, "library_ids": ["default"]})
        self.assertTrue(os.path.exists(nested))

    # ---- 帮助函数 ----

    def test_helpers(self):
        self._write({"enabled": False, "rounds": 9, "library_ids": ["a", "b"]})
        self.assertFalse(guest_settings.guest_enabled())
        self.assertEqual(guest_settings.effective_rounds(), 9)
        self.assertEqual(guest_settings.guest_library_ids(), ["a", "b"])


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: 跑红**

```powershell
python tests/unit/test_guest_settings.py -v
```

预期：`ModuleNotFoundError: No module named 'shared.guest_settings'`（或 shared 缺 guest_settings 属性）——红即对。

### Task 1.2: 实现 shared/guest_settings.py

**Files:**
- Create: `services/shared/src/shared/guest_settings.py`
- Test: `tests/unit/test_guest_settings.py`

- [ ] **Step 1: 全文件写入**

```python
"""游客设置（docs/design-guest-settings.md）：免登录访客的开放开关 / 轮数上限 / 可用知识库。

存储 data/platform/guest_settings.json（原子写，同 nightly_control.py 模式）；
优先级：文件 > env(ANGINEER_GUEST_ROUNDS) > 30；文件缺失 = 默认值（今天的行为）；
文件存在但读坏 → fail-closed（enabled=false + load_error 上报，后台展示、保存一次即恢复）。
每请求直读不缓存：docs-api 写 / aichat-api 读跨容器经 data/ 卷即时同步。
"""
import json
import logging
import os
from pathlib import Path
from typing import Any, Dict, List

from shared.paths import resolve_data_file

logger = logging.getLogger("shared.guest_settings")

SETTINGS_ENV = "GUEST_SETTINGS_FILE"
ENV_ROUNDS = "ANGINEER_GUEST_ROUNDS"
DEFAULT_ROUNDS = 30
ROUNDS_MIN, ROUNDS_MAX = 1, 1000
DEFAULT_LIBRARY_IDS = ["default"]


def settings_path() -> Path:
    return Path(resolve_data_file(SETTINGS_ENV, "platform/guest_settings.json"))


def _env_rounds() -> int:
    try:
        return max(ROUNDS_MIN, int(os.getenv(ENV_ROUNDS, str(DEFAULT_ROUNDS)) or DEFAULT_ROUNDS))
    except ValueError:
        return DEFAULT_ROUNDS


def normalize_guest_settings(raw: Any) -> Dict[str, Any]:
    """规范化三键（保存与读取共用）；结构/类型/范围非法即 ValueError（PUT 转 400）。"""
    if not isinstance(raw, dict):
        raise ValueError("guest_settings 顶层必须是 JSON 对象")
    enabled = raw.get("enabled", True)
    if not isinstance(enabled, bool):
        raise ValueError("enabled 必须是布尔值")
    rounds = raw.get("rounds", DEFAULT_ROUNDS)
    if isinstance(rounds, bool) or not isinstance(rounds, int) or not (ROUNDS_MIN <= rounds <= ROUNDS_MAX):
        raise ValueError(f"rounds 必须是 {ROUNDS_MIN}–{ROUNDS_MAX} 的整数")
    libs_raw = raw.get("library_ids", list(DEFAULT_LIBRARY_IDS))
    if not isinstance(libs_raw, list):
        raise ValueError("library_ids 必须是数组")
    libs = [str(x).strip() for x in libs_raw if str(x).strip()]
    if not libs:
        raise ValueError("library_ids 至少需要 1 个知识库")
    return {"enabled": enabled, "rounds": rounds, "library_ids": libs}


def _fail_closed_defaults(reason: str) -> Dict[str, Any]:
    logger.error("guest_settings 不可用，按 fail-closed 关闭游客: %s", reason)
    return {
        "enabled": False,
        "rounds": _env_rounds(),
        "library_ids": list(DEFAULT_LIBRARY_IDS),
        "load_error": reason,
    }


def load_guest_settings() -> Dict[str, Any]:
    """读取生效设置（含 load_error）。文件缺失 → 默认；读坏/内容非法 → fail-closed。"""
    path = settings_path()
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {
            "enabled": True,
            "rounds": _env_rounds(),
            "library_ids": list(DEFAULT_LIBRARY_IDS),
            "load_error": "",
        }
    except (OSError, ValueError) as exc:
        return _fail_closed_defaults(f"{type(exc).__name__}: {exc}")
    try:
        cfg = normalize_guest_settings(raw)
    except ValueError as exc:
        return _fail_closed_defaults(str(exc))
    cfg["load_error"] = ""
    return cfg


def save_guest_settings(cfg: Any) -> Dict[str, Any]:
    """规范化 + 原子写（同目录 .tmp + os.replace，同 nightly 模式）；返回落盘设置。"""
    normalized = normalize_guest_settings(cfg)
    path = settings_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(normalized, ensure_ascii=False, indent=1), encoding="utf-8")
    os.replace(tmp, path)
    return {**normalized, "load_error": ""}


def guest_enabled() -> bool:
    return bool(load_guest_settings().get("enabled"))


def effective_rounds() -> int:
    return int(load_guest_settings().get("rounds") or DEFAULT_ROUNDS)


def guest_library_ids() -> List[str]:
    return list(load_guest_settings().get("library_ids") or DEFAULT_LIBRARY_IDS)
```

- [ ] **Step 2: 跑绿 + 相邻回归**

```powershell
python tests/unit/test_guest_settings.py -v
python -m unittest discover -s tests/unit -p "test_*.py"
```

预期：全绿（既有 tests/unit 不红）。

---

## Stage 2：aichat-api 闸门与库校验（TDD）

### Task 2.1: 游客闸测试扩展（先红）

**Files:**
- Modify: `tests/aichat-api/test_chat_guest_gate.py`

- [ ] **Step 1: setUp 增加文件隔离**（现 :90-97 的 env patch 处）

old：
```python
    def setUp(self):
        self.chat_auth = _load_chat_auth()
        self.addCleanup(lambda: sys.modules.pop("chat_auth", None))
        # 隔离外部 env：本地 .env 可能带 ANGINEER_GUEST_ROUNDS 调试值（如实测期=5），
        # 边界用例按默认 30 写死
        self._env_patch = patch.dict(os.environ, {"ANGINEER_GUEST_ROUNDS": "30"})
        self._env_patch.start()
        self.addCleanup(self._env_patch.stop)
```

new：
```python
    def setUp(self):
        self.chat_auth = _load_chat_auth()
        self.addCleanup(lambda: sys.modules.pop("chat_auth", None))
        # 隔离外部 env 与游客设置文件：本地 .env 可能带 ANGINEER_GUEST_ROUNDS 调试值、
        # data/platform/guest_settings.json 可能已被手工改过——默认语义用例必须「无文件」
        self._tmp = tempfile.mkdtemp()
        self.addCleanup(lambda: shutil.rmtree(self._tmp, ignore_errors=True))
        self._settings_path = os.path.join(self._tmp, "guest_settings.json")
        self._env_patch = patch.dict(
            os.environ,
            {"ANGINEER_GUEST_ROUNDS": "30", "GUEST_SETTINGS_FILE": self._settings_path},
        )
        self._env_patch.start()
        self.addCleanup(self._env_patch.stop)
```

文件头 import 增加：`import json`、`import shutil`、`import tempfile`。

- [ ] **Step 2: 类内追加用例**（`test_rounds_limit_env_override` 之后、类结尾之前）

```python
    def _write_settings(self, **overrides):
        cfg = {"enabled": True, "rounds": 30, "library_ids": ["default"]}
        cfg.update(overrides)
        with open(self._settings_path, "w", encoding="utf-8") as fh:
            json.dump(cfg, fh, ensure_ascii=False)

    def test_disabled_blocks_guest_and_ip_not_users(self):
        """关闭游客（2026-10-17 游客设置）：g: 与 ip: 都拦；u:/k: 永远不受影响。"""
        self._write_settings(enabled=False)
        self.assertTrue(self.chat_auth.guest_gate_blocked("g:x", _FakeStore()))
        self.assertTrue(self.chat_auth.guest_gate_blocked("ip:abc", _FakeStore()))
        self.assertFalse(self.chat_auth.guest_gate_blocked("u:1", _FakeStore()))
        self.assertFalse(self.chat_auth.guest_gate_blocked("k:1", _FakeStore()))

    def test_disabled_gate_survives_store_none(self):
        """评审钉：存储降级 fail-open 只豁免轮数/claim，不得吞掉「关闭游客」闸。"""
        self._write_settings(enabled=False)
        self.assertTrue(self.chat_auth.guest_gate_blocked("g:x", None))
        self.assertTrue(self.chat_auth.guest_gate_blocked("ip:abc", None))

    def test_file_rounds_override_env(self):
        """文件 > env：文件写 5 时 env 30 失效。"""
        self._write_settings(rounds=5)
        with patch.dict(os.environ, {"ANGINEER_GUEST_ROUNDS": "30"}):
            self.assertEqual(self.chat_auth.guest_rounds_limit(), 5)
            self.assertTrue(self.chat_auth.guest_gate_blocked("g:x", _FakeStore(rounds=5)))
            self.assertFalse(self.chat_auth.guest_gate_blocked("g:x", _FakeStore(rounds=4)))

    def test_corrupt_file_fails_closed(self):
        with open(self._settings_path, "w", encoding="utf-8") as fh:
            fh.write("{ 半截")
        self.assertTrue(self.chat_auth.guest_gate_blocked("g:x", _FakeStore(rounds=0)))
        self.assertTrue(self.chat_auth.guest_gate_blocked("ip:abc", _FakeStore(rounds=0)))

    def test_state_cache_single_load_per_request(self):
        """单请求共读（设计稿 §3.2 评审补）：同 state 二次调用不重读文件。"""
        self._write_settings(rounds=5)
        state = SimpleNamespace()
        self.assertEqual(self.chat_auth.guest_rounds_limit(state), 5)
        self._write_settings(rounds=7)  # 文件变了，同 state 依旧拿缓存
        self.assertEqual(self.chat_auth.guest_rounds_limit(state), 5)
        self.assertEqual(self.chat_auth.guest_rounds_limit(SimpleNamespace()), 7)
```

- [ ] **Step 3: 跑红**

```powershell
python tests/aichat-api/test_chat_guest_gate.py -v
```

预期：新增 4 例红（enabled 闸未实现、文件轮数未生效）；既有无文件用例仍绿。

### Task 2.2: chat_auth.py 闸序改造 + main.py 传 state

**Files:**
- Modify: `services/aichat-api/chat_auth.py`
- Modify: `services/aichat-api/main.py`
- Test: `tests/aichat-api/test_chat_guest_gate.py`

- [ ] **Step 1: 新增单请求共读助手**（插在 `guest_rounds_limit` 之前）

```python
def _guest_settings(state=None) -> dict:
    """游客设置单请求共读（设计稿 §3.2 评审补）：state 有缓存就复用，否则读盘并挂回 state。

    state=None（测试直调/无请求上下文）每次直读；挂 state 的缓存让同请求内
    enforce_bound_libraries 与 guest_gate_blocked 共用一次文件加载。
    """
    if state is not None:
        cached = getattr(state, "_guest_settings_cache", None)
        if cached is not None:
            return cached
    from shared.guest_settings import load_guest_settings

    cfg = load_guest_settings()
    if state is not None:
        try:
            state._guest_settings_cache = cfg
        except Exception:  # noqa: BLE001
            pass
    return cfg
```

- [ ] **Step 2: `guest_rounds_limit` 换 shared 来源**

old：
```python
def guest_rounds_limit() -> int:
    """游客 30 轮闸阈值（策略注入，§3 硬约束 2）。"""
    try:
        return max(1, int(os.getenv("ANGINEER_GUEST_ROUNDS", "30") or 30))
    except ValueError:
        return 30
```

new：
```python
def guest_rounds_limit(state=None) -> int:
    """游客轮数阈值：游客设置文件 > env(ANGINEER_GUEST_ROUNDS) > 30。

    2026-10-17 游客设置（设计稿 §3.1）：文件一旦保存即钉死 rounds，改 .env 不再生效；
    文件缺失时退回 env 语义。state 传入则复用请求级缓存（见 _guest_settings）。
    """
    return int(_guest_settings(state).get("rounds") or 30)
```

- [ ] **Step 3: `guest_gate_blocked` 闸序改造**（评审修正后闸序，设计稿 §3.3）

old：
```python
def guest_gate_blocked(owner: str, store) -> bool:
    """游客闸（D2）：``g:`` 桶提问轮数 ≥ 阈值 → 拦；**已 claim 的身份直接拦**。

    轮数按 chat_runs 计（1 run = 提问 1 次；检索重试/steer 追加的 user 消息不重复计，
    2026-09-18 实踩：按 user 消息计会把 1 问答算成多轮）。claimed 即作废：claim 把 g:
    桶搬空后登出再聊会落到计数清零的空桶（无限对话实踩），登录过的游客身份须保持登录。
    存储降级（store=None）时 fail-open，行为同改造前；非游客桶永不拦。
    """
    if store is None or not owner.startswith("g:"):
        return False
    try:
        if store.guest_is_claimed(owner[2:]):
            return True
        return store.guest_rounds(owner) >= guest_rounds_limit()
    except Exception:  # noqa: BLE001
        return False
```

new：
```python
def guest_gate_blocked(owner: str, store, state=None) -> bool:
    """游客闸（D2 + 2026-10-17 游客设置，闸序见设计稿 §3.3）：

    ① enabled=false → g:/ip: 都拦（读设置文件，不依赖 store——存储降级不得吞掉关闭语义）；
    ② store=None 降级 fail-open 仅豁免轮数/claim（行为同改造前）；
    ③ 轮闸/claim 仍只对 g: 桶（ip: 桶永不进；claimed 即作废防「登出后空桶无限聊」实踩回归）；
    u:/k: 主体永远不受游客闸影响。轮数按 chat_runs 计（1 run = 提问 1 次）。
    state 可选：同请求复用设置缓存（见 _guest_settings），直调不传保持兼容。
    """
    if not owner.startswith(("u:", "k:")):
        if not _guest_settings(state).get("enabled", True):
            return True
    if store is None or not owner.startswith("g:"):
        return False
    try:
        if store.guest_is_claimed(owner[2:]):
            return True
        return store.guest_rounds(owner) >= guest_rounds_limit(state)
    except Exception:  # noqa: BLE001
        return False
```

- [ ] **Step 4: main.py 闸位传 state**（:479）

old：
```python
    if guest_gate_blocked(owner, store):
```

new：
```python
    if guest_gate_blocked(owner, store, raw_request.state):
```

（`enforce_bound_libraries(raw_request.state, ...)` :465 已同 state，缓存自动共用。）

- [ ] **Step 5: 跑绿**

```powershell
python tests/aichat-api/test_chat_guest_gate.py -v
```

预期：全绿。

### Task 2.3: 匿名允许集（库校验）改造（先红后绿）

**Files:**
- Modify: `tests/aichat-api/test_multi_library_auth.py`
- Modify: `tests/aichat-api/test_multi_library_v2.py`、`tests/aichat-api/test_multi_library_endpoint.py`（仅隔离）
- Modify: `services/aichat-api/chat_auth.py`

- [ ] **Step 1: test_multi_library_auth.py setUp 加文件隔离**（现 :48-55）

在 setUp 末尾（`os.environ.pop("ANGINEER_MAX_CHAT_LIBRARIES", None)` 之后）追加：

```python
        # 游客设置文件隔离（2026-10-17 游客设置）：匿名默认语义按「无文件」钉死，
        # 不受开发机 data/platform/guest_settings.json 真实状态影响
        self._guest_tmp = tempfile.mkdtemp()
        self.addCleanup(lambda: shutil.rmtree(self._guest_tmp, ignore_errors=True))
        self._guest_env = patch.dict(
            os.environ, {"GUEST_SETTINGS_FILE": os.path.join(self._guest_tmp, "guest_settings.json")}
        )
        self._guest_env.start()
        self.addCleanup(self._guest_env.stop)
```

文件头 import 增加：`import json`、`import shutil`、`import tempfile`。

- [ ] **Step 2: 追加允许集用例**（`test_anonymous_default_only` 之后）

```python
    def _write_guest_settings(self, library_ids):
        path = os.path.join(self._guest_tmp, "guest_settings.json")
        with open(path, "w", encoding="utf-8") as fh:
            json.dump({"enabled": True, "rounds": 30, "library_ids": library_ids}, fh, ensure_ascii=False)

    def test_anonymous_allowed_set_expansion(self):
        """游客设置允许集（2026-10-17）：隐式（空/default）展开为 S 全选、不截断。"""
        self._write_guest_settings(["default", "guifan"])
        state = self._state()
        self.assertEqual(self.chat_auth.enforce_bound_libraries(state, []), ["default", "guifan"])
        state2 = self._state()
        self.assertEqual(self.chat_auth.enforce_bound_libraries(state2, ["default"]), ["default", "guifan"])

    def test_anonymous_allowed_set_member_and_non_member(self):
        """显式 @：∈S 放行原样返回；∉S → 403 可见报错（不静默剔除）。"""
        from fastapi import HTTPException

        self._write_guest_settings(["default", "guifan"])
        state = self._state()
        self.assertEqual(self.chat_auth.enforce_bound_libraries(state, ["guifan"]), ["guifan"])
        state2 = self._state()
        with self.assertRaises(HTTPException) as ctx:
            self.chat_auth.enforce_bound_libraries(state2, ["libA"])
        self.assertEqual(ctx.exception.status_code, 403)
```

注意：同一 state 二次调用会吃缓存（设计如此），所以每断言用新 `_state()`。

- [ ] **Step 3: v2 / endpoint 测试隔离**（防开发机真实文件污染既有断言）

`test_multi_library_v2.py` setUp（:64 `os.environ.pop("ANGINEER_KB_SUBSCRIPTION_V2", None)` 之后）追加与上同款文件隔离块（tempfile + `GUEST_SETTINGS_FILE` patch.dict）。

`test_multi_library_endpoint.py` setUp（:134 `os.environ.pop("ANGINEER_CHAT_AUTH_REQUIRED", None)` 之后）追加同款隔离块；文件头按需补 `import shutil`、`import tempfile`（`os` 已有）。

- [ ] **Step 4: 跑红**

```powershell
python tests/aichat-api/test_multi_library_auth.py -v
```

预期：新增 2 例红（现实现恒 `["default"]`）。

- [ ] **Step 5: chat_auth.py 匿名分支改造**（:148-154）

old：
```python
    bound = getattr(state, "bound_library_id", "") or ""
    if not bound:
        # 匿名（无 API key 也无会话）：只允许默认库（2026-09-17 收紧语义的集合版）。
        libs = [str(x).strip() for x in requested if str(x).strip()]
        if not libs or libs == ["default"]:
            return ["default"]
        raise HTTPException(status_code=403, detail="未登录访问仅限默认知识库，请登录后选择其它知识库")
```

new：
```python
    bound = getattr(state, "bound_library_id", "") or ""
    if not bound:
        # 游客（无 API key 也无会话）：只可访问「游客设置」允许集 S（2026-10-17 设计稿 §3.3）。
        # 隐式（空/["default"]）= S 全选（与登录用户 V2 隐式语义一致，不截断）；
        # 显式非成员 → 403 可见报错；S>FANOUT_WARN_THRESHOLD 仅 warning（V2 观测口径）。
        allowed = [str(x) for x in (_guest_settings(state).get("library_ids") or ["default"])]
        if len(allowed) > FANOUT_WARN_THRESHOLD:
            logger.warning("游客允许集 %d 库（无上限，观测口径）: %s", len(allowed), allowed)
        libs = [str(x).strip() for x in requested if str(x).strip()]
        if not libs or libs == ["default"]:
            return list(allowed)
        for lib in libs:
            if lib not in allowed:
                raise HTTPException(
                    status_code=403,
                    detail="未登录仅可访问游客开放的知识库，请登录后选择其它知识库",
                )
        return libs
```

- [ ] **Step 6: 跑绿 + aichat 全目录回归**

```powershell
python tests/aichat-api/test_multi_library_auth.py -v
python tests/aichat-api/test_multi_library_v2.py -v
python tests/aichat-api/test_multi_library_endpoint.py -v
python -m unittest discover -s tests/aichat-api -p "test_*.py"
```

预期：全绿。兼容铁律核验点：`test_anonymous_default_only`（无文件时 `[]→["default"]`）、`test_anonymous_unbound_library_403`（`["default","lib-secret"]` 仍 403）不红。

---

## Stage 3：docs-api 端点（TDD）

### Task 3.1: 写失败测试

**Files:**
- Create: `services/docs-api/tests/test_guest_routes.py`

- [ ] **Step 1: 全文件写入**

```python
"""游客设置端点契约（docs/design-guest-settings.md §3.2/§3.6）：

- settings 读写必须管理员鉴权（无头 401）；PUT 校验失败一律 400（V1-V4）；
- config 公开；按允许集过滤分组清单；evals 组永不出现；读坏时 enabled=False。
服务层链路（文件读写）有真测（tests/unit/test_guest_settings.py），本文件 stub docs_service、
monkeypatch 设置文件路径，只钉 HTTP 边界。
"""
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import guest_routes
from admin_auth import resolve_admin_session


class _Lib:
    def __init__(self, group_name="system"):
        self.group_name = group_name


class _StubService:
    def __init__(self):
        self.libs = {"default": _Lib(), "guifan": _Lib(), "evals-demo": _Lib("evals")}

    def get_library(self, lid):
        return self.libs.get(lid)

    def list_grouped_libraries(self):
        return [
            {"group_name": "system", "display_name": "", "libraries": [
                {"id": "default", "name": "默认库"},
                {"id": "guifan", "name": "规范库"},
            ]},
            {"group_name": "evals", "display_name": "", "libraries": [
                {"id": "evals-demo", "name": "评测语料"},
            ]},
        ]


@pytest.fixture()
def client(monkeypatch, tmp_path):
    svc = _StubService()
    monkeypatch.setattr(guest_routes, "get_docs_service", lambda: svc)
    monkeypatch.setenv("GUEST_SETTINGS_FILE", str(tmp_path / "guest_settings.json"))
    app = FastAPI()
    app.include_router(guest_routes.router)
    return TestClient(app), svc


def _as_admin(c):
    c.app.dependency_overrides[resolve_admin_session] = lambda: None


_VALID = {"enabled": True, "rounds": 30, "library_ids": ["default"]}


def test_settings_requires_admin(client):
    c, _ = client
    assert c.get("/api/guest/settings").status_code == 401
    assert c.put("/api/guest/settings", json=_VALID).status_code == 401


def test_settings_route_has_admin_dependency(client):
    """防回归：settings 两方法的依赖必须挂在路由上（config 不需要）。"""
    by_path = {}
    for r in guest_routes.router.routes:
        by_path.setdefault(r.path, []).append(r)
    for r in by_path["/api/guest/settings"]:
        assert r.dependencies, r.methods


def test_settings_put_and_get_roundtrip(client):
    c, _ = client
    _as_admin(c)
    resp = c.put("/api/guest/settings", json={"enabled": True, "rounds": 5, "library_ids": ["guifan"]})
    assert resp.status_code == 200
    body = resp.json()
    assert body["enabled"] is True and body["rounds"] == 5 and body["library_ids"] == ["guifan"]
    got = c.get("/api/guest/settings").json()
    assert got["load_error"] == "" and got["library_ids"] == ["guifan"]


def test_settings_put_validation_400(client):
    c, _ = client
    _as_admin(c)
    for bad in (
        {"enabled": True, "rounds": 30, "library_ids": []},            # V1 至少 1 个
        {"enabled": True, "rounds": 30, "library_ids": ["nope"]},      # V2 不存在
        {"enabled": True, "rounds": 30, "library_ids": ["evals-demo"]},  # V3 evals 组
        {"enabled": True, "rounds": 0, "library_ids": ["default"]},    # V4 越界（明确 400）
        {"enabled": True, "rounds": 1001, "library_ids": ["default"]},
    ):
        resp = c.put("/api/guest/settings", json=bad)
        assert resp.status_code == 400, bad


def test_get_settings_exposes_load_error(client, tmp_path):
    path = tmp_path / "guest_settings.json"
    path.write_text("{ 半截", encoding="utf-8")
    c, _ = client
    _as_admin(c)
    body = c.get("/api/guest/settings").json()
    assert body["enabled"] is False
    assert body["load_error"]


def test_config_public_filtered_by_allowed_set(client):
    c, _ = client
    resp = c.get("/api/guest/config")
    assert resp.status_code == 200
    body = resp.json()
    assert body["enabled"] is True and body["rounds"] == 30
    # 默认设置（无文件）允许集 = ["default"] → 只回 default；evals 组永不出现
    assert [g["group_name"] for g in body["groups"]] == ["system"]
    assert [l["id"] for g in body["groups"] for l in g["libraries"]] == ["default"]


def test_config_respects_disabled_and_allowed_set(client):
    c, _ = client
    _as_admin(c)
    c.put("/api/guest/settings", json={"enabled": False, "rounds": 5, "library_ids": ["guifan"]})
    body = c.get("/api/guest/config").json()
    assert body["enabled"] is False and body["rounds"] == 5
    assert [l["id"] for g in body["groups"] for l in g["libraries"]] == ["guifan"]
```

- [ ] **Step 2: 跑红**

```powershell
python -m pytest services/docs-api/tests/test_guest_routes.py -q
```

预期：collection error（`No module named 'guest_routes'`）——红即对。

### Task 3.2: guest_routes.py + 挂载

**Files:**
- Create: `services/docs-api/guest_routes.py`
- Modify: `services/docs-api/main.py`
- Test: `services/docs-api/tests/test_guest_routes.py`

- [ ] **Step 1: 全文件写入 guest_routes.py**

```python
"""游客设置端点（docs/design-guest-settings.md §3.2）：

- GET/PUT /api/guest/settings：管理员读写（resolve_admin_session）；
- GET /api/guest/config：公开只读，游客端拉「是否开放 + 允许库（分组形状，同 /knowledge/libraries/groups）」。

存储与优先级在 shared.guest_settings；校验口径（V1-V4）见设计稿 §3.6，失败一律 400（不静默夹取）。
"""
from typing import List

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from admin_auth import resolve_admin_session
from docs_core.docs_service import get_docs_service
from shared.guest_settings import load_guest_settings, save_guest_settings
from shared.subscription import EVALS_GROUP

router = APIRouter(prefix="/api/guest", tags=["Guest"])


class GuestSettingsPayload(BaseModel):
    enabled: bool
    rounds: int = Field(default=30, description="游客轮数上限（1–1000，越界 400 见 handler）")
    library_ids: List[str] = Field(default_factory=list)


@router.get("/settings", dependencies=[Depends(resolve_admin_session)])
async def get_guest_settings():
    return load_guest_settings()


@router.put("/settings", dependencies=[Depends(resolve_admin_session)])
async def put_guest_settings(req: GuestSettingsPayload):
    if isinstance(req.rounds, bool) or not (1 <= req.rounds <= 1000):
        raise HTTPException(400, "轮数上限必须是 1–1000 的整数")
    libs = [str(x).strip() for x in req.library_ids if str(x).strip()]
    if not libs:
        raise HTTPException(400, "请至少选择 1 个游客可用知识库")
    ks = get_docs_service()
    for lid in libs:
        lib = ks.get_library(lid)
        if lib is None:
            raise HTTPException(400, f"知识库 {lid} 不存在，请先创建")
        if (getattr(lib, "group_name", "") or "") == EVALS_GROUP:
            raise HTTPException(400, f"评测语料库 {lid} 不可开放给游客")
    return save_guest_settings({"enabled": req.enabled, "rounds": req.rounds, "library_ids": libs})


@router.get("/config")
async def get_guest_config():
    """游客端公开配置：只含允许集库/组名（不扩大既有暴露面，设计稿 §6），evals 组永不出现。"""
    cfg = load_guest_settings()
    allowed = set(cfg["library_ids"])
    groups = []
    for g in get_docs_service().list_grouped_libraries():
        if g["group_name"] == EVALS_GROUP:
            continue
        libs = [{"id": l["id"], "name": l["name"]} for l in g["libraries"] if l["id"] in allowed]
        if libs:
            groups.append(
                {"group_name": g["group_name"], "display_name": g.get("display_name", ""), "libraries": libs}
            )
    return {"enabled": cfg["enabled"], "rounds": cfg["rounds"], "groups": groups}
```

- [ ] **Step 2: main.py 挂载**（import 区 :30 后、include 区 :135 后）

old：
```python
from users_routes import router as users_router
```
new：
```python
from users_routes import router as users_router
from guest_routes import router as guest_router
```

old：
```python
app.include_router(users_router)
```
new：
```python
app.include_router(users_router)
app.include_router(guest_router)
```

- [ ] **Step 3: 跑绿 + docs-api 全目录回归**

```powershell
python -m pytest services/docs-api/tests/test_guest_routes.py -q
python -m pytest services/docs-api/tests -q
```

预期：全绿。

---

## Stage 4：admin-web 游客虚拟行

### Task 4.1: guest.ts + UserManage.vue

**Files:**
- Create: `apps/admin-web/src/api/guest.ts`
- Modify: `apps/admin-web/src/views/UserManage.vue`

- [ ] **Step 1: 全文件写入 apps/admin-web/src/api/guest.ts**

```ts
/** 游客设置客户端（/api/guest/settings，管理员鉴权；公开 config 端点在 user-web 侧） */
import { docsApiClient } from '../../../shared/apiClient'

export interface GuestSettings {
  enabled: boolean
  rounds: number
  library_ids: string[]
  /** 非空 = 配置文件读坏（fail-closed 中）；后台醒目提示，保存一次即恢复 */
  load_error: string
}

export const guestApi = {
  getSettings: (): Promise<GuestSettings> => docsApiClient.get('/guest/settings'),
  saveSettings: (data: { enabled: boolean; rounds: number; library_ids: string[] }): Promise<GuestSettings> =>
    docsApiClient.put('/guest/settings', data),
}
```

- [ ] **Step 2: UserManage.vue script 区追加**（import 区追加 `import { guestApi, type GuestSettings } from '@/api/guest'`；以下块插在 `const libraryGroups = ref<LibraryGroupItem[]>([])` 之后、`columns` 之前）

```ts
// ---- 游客虚拟行（2026-10-17 游客设置，设计稿 §3.4）：非数据库记录，前端合成置顶 ----

const GUEST_ROW_ID = '__guest__'
const guestSettings = ref<GuestSettings | null>(null)

/** 游客选择器不展示评测语料组（V3：evals 不进游客允许集，服务端同口径 400 拒绝） */
const guestLibraryGroups = computed(() => libraryGroups.value.filter((g) => g.group_name !== 'evals'))
const evalsLibIds = computed(
  () => new Set(libraryGroups.value.filter((g) => g.group_name === 'evals').flatMap((g) => g.libraries.map((l) => l.id))),
)
const guestLooseLibraries = computed(() => looseLibraries.value.filter((l) => !evalsLibIds.value.has(l.id)))

/** 与真实用户同构的合成行：列分支复用（libraries 列走 accessUnitsOf → buildAccessUnits） */
const guestRow = computed(() => ({
  id: GUEST_ROW_ID,
  username: '游客',
  display_name: '免登录访客',
  is_admin: false,
  library_ids: guestSettings.value?.library_ids ?? [],
  accessible_libraries: guestSettings.value?.library_ids ?? [],
  is_active: guestSettings.value?.enabled ?? false,
  created_at: '',
  last_login_at: null as string | null,
}))
const tableRows = computed(() =>
  guestSettings.value ? [guestRow.value as unknown as AdminUserItem, ...users.value] : users.value,
)
function isGuestRow(record: any): boolean {
  return record?.id === GUEST_ROW_ID
}

async function loadGuestSettings(): Promise<void> {
  try {
    guestSettings.value = await guestApi.getSettings()
  } catch (e: any) {
    message.error('加载游客设置失败: ' + (e.message || e))
  }
}

/** 启用开关行内直切（PUT 三键恒全发——服务端按整份设置保存）；失败不动本地态=开关自动回滚 */
async function handleGuestToggle(checked: boolean): Promise<void> {
  if (!guestSettings.value) return
  try {
    guestSettings.value = await guestApi.saveSettings({
      enabled: checked,
      rounds: guestSettings.value.rounds,
      library_ids: guestSettings.value.library_ids,
    })
    message.success(checked ? '已开放游客访问' : '已关闭游客访问')
  } catch (e: any) {
    message.error('操作失败: ' + (e.message || e))
  }
}

// ---- 游客编辑弹框（复用 AccessScopeSelect 扁平勾选集 → library_ids，不走 V2 订阅序列化） ----

const guestEditVisible = ref(false)
const guestForm = reactive({ rounds: 30, accessChecked: [] as string[] })

function openGuestEdit(): void {
  void (async () => {
    await loadLibraries() // R5：无缓存——每次开弹框重拉库清单
    guestForm.rounds = guestSettings.value?.rounds ?? 30
    guestForm.accessChecked = [...(guestSettings.value?.library_ids ?? [])]
    guestEditVisible.value = true
  })()
}

async function handleGuestSave(): Promise<void> {
  if (!guestForm.accessChecked.length) {
    message.warning('请至少选择一个知识库')
    return
  }
  const rounds = Number(guestForm.rounds)
  if (!Number.isInteger(rounds) || rounds < 1 || rounds > 1000) {
    message.warning('轮数上限必须是 1–1000 的整数')
    return
  }
  saving.value = true
  try {
    guestSettings.value = await guestApi.saveSettings({
      enabled: guestSettings.value?.enabled ?? true,
      rounds,
      library_ids: guestForm.accessChecked,
    })
    message.success('已保存')
    guestEditVisible.value = false
  } catch (e: any) {
    message.error('保存失败: ' + (e.message || e))
  } finally {
    saving.value = false
  }
}
```

`onMounted` 内追加一行：

```ts
onMounted(() => {
  loadLibraries()
  loadUsers()
  loadGuestSettings()
})
```

- [ ] **Step 3: 模板改造**

页面头部之后加读坏告警（`</div>` of page-header 与 `.user-table-wrap` 之间）：

```html
    <a-alert
      v-if="guestSettings?.load_error"
      type="error"
      show-icon
      class="guest-load-error"
      message="游客设置文件读取失败（游客当前被临时关闭）"
      :description="`原因：${guestSettings.load_error}。点击游客行「编辑」保存一次即可恢复。`"
    />
```

Datatable 数据源改合成行：`:data-source="tableRows"`。

bodyCell 内加游客分支（`<template v-if="column.key === 'libraries'">` 之前插）：

```html
          <template v-if="column.key === 'username' && isGuestRow(record)">
            <span class="guest-name">游客</span>
            <a-tag color="gold">免登录</a-tag>
          </template>
```

is_admin 列开关加禁用（现 :28-32 分支）：

```html
            <a-switch
              :checked="record.is_admin"
              size="small"
              :disabled="isGuestRow(record)"
              @change="(checked: boolean) => handleAdminToggle(record, checked)"
            />
```

is_active 列开关分流（现 :34-40 分支）：

```html
            <a-switch
              :checked="record.is_active"
              size="small"
              @change="(checked: boolean) => (isGuestRow(record) ? handleGuestToggle(checked) : handleToggle(record, checked))"
            />
```

action 列分流（现 :41-49 分支整体替换）：

```html
          <template v-else-if="column.key === 'action'">
            <div class="action-cell">
              <template v-if="isGuestRow(record)">
                <AppButton variant="link" size="sm" @click="openGuestEdit">编辑</AppButton>
              </template>
              <template v-else>
                <AppButton variant="link" size="sm" @click="openEdit(record)">编辑</AppButton>
                <AppButton variant="link" size="sm" @click="openResetPassword(record)">重置密码</AppButton>
                <a-popconfirm title="确定删除该用户？此操作不可恢复" placement="left" @confirm="handleDelete(record)">
                  <AppButton variant="link" size="sm" danger>删除</AppButton>
                </a-popconfirm>
              </template>
            </div>
          </template>
```

游客编辑弹框（密码弹框之前插入）：

```html
    <a-modal v-model:open="guestEditVisible" title="编辑游客权限" @ok="handleGuestSave" :confirm-loading="saving">
      <a-form :model="guestForm" :label-col="{ span: 5 }" :wrapper-col="{ span: 18 }">
        <a-form-item label="可用知识库" required>
          <!-- 游客选择器：评测语料组不展示（V3 服务端同口径 400）；扁平勾选集直存 library_ids -->
          <AccessScopeSelect v-model="guestForm.accessChecked" :groups="guestLibraryGroups" :loose="guestLooseLibraries" />
        </a-form-item>
        <a-form-item label="轮数上限" required>
          <a-input-number v-model:value="guestForm.rounds" :min="1" :max="1000" :precision="0" style="width: 160px" />
        </a-form-item>
      </a-form>
    </a-modal>
```

样式区追加：

```less
.guest-load-error {
  max-width: 1100px;
  margin: 0 auto 12px;
}
.guest-name {
  margin-right: 6px;
}
```

- [ ] **Step 4: typecheck**

```powershell
pnpm --filter @angineer/admin-web exec vue-tsc -b
```

预期：0 错误。

### Task 4.2: 后台手工冒烟（可选，Stage 6 一并做）

- [ ] `pnpm dev:admin` + `pnpm dev:docs-api`（登录管理员）→ 用户管理页见置顶「游客」行；改轮数/勾库保存 → 刷新回显；开关键行内直切。

---

## Stage 5：user-web 游客选择器放开

### Task 5.1: guest.ts + auth.ts + ChatHome.vue

**Files:**
- Create: `apps/user-web/src/api/guest.ts`
- Modify: `apps/user-web/src/stores/auth.ts`
- Modify: `apps/user-web/src/views/ChatHome.vue`

- [ ] **Step 1: 全文件写入 apps/user-web/src/api/guest.ts**

```ts
/** 游客公开配置客户端（/api/guest/config，免鉴权；docs/design-guest-settings.md §3.2） */
import { docsApiClient } from '../../../shared/apiClient'

export interface GuestConfigGroup {
  group_name: string
  display_name?: string
  libraries: { id: string; name: string }[]
}

/** 公开配置：enabled（是否开放）/ rounds（轮数上限）/ 允许集分组库清单（evals 永不出现） */
export interface GuestConfig {
  enabled: boolean
  rounds: number
  groups: GuestConfigGroup[]
}

export const guestApi = {
  getConfig: (): Promise<GuestConfig> => docsApiClient.get('/guest/config'),
}

export default guestApi
```

- [ ] **Step 2: auth.ts 改造**

import 区追加：`import { guestApi, type GuestConfig } from '@/api/guest'`

state 增加（`guestMode: true` 之后）：

```ts
    /** 游客公开配置（2026-10-17 游客设置）：默认 null；拉取后提供游客库集合/分组 */
    guestConfig: null as GuestConfig | null,
```

getters 改两处：

old：
```ts
    /** 派生集 = 检索范围唯一真相源（R6 统一走派生）；消费点（ChatHome 选择器/setActiveLibraries 过滤）都读它 */
    libraries: (state) => state.user?.accessible_libraries ?? state.user?.libraries ?? [],
    /** 游客恒只能问默认库（服务端 v0.2.66 闸 + D2 双重约束） */
    effectiveLibraryId: (state) => (state.guestMode ? 'default' : state.activeLibraryId || state.user?.default_library || ''),
```

new：
```ts
    /** 派生集 = 检索范围唯一真相源（R6 统一走派生）；消费点（ChatHome 选择器/setActiveLibraries 过滤）都读它；
     *  游客态（2026-10-17 游客设置）= 公开配置的允许集（服务端闸门为最终裁定） */
    libraries: (state) =>
      state.guestMode
        ? (state.guestConfig?.groups ?? []).flatMap((g) => g.libraries.map((l) => l.id))
        : state.user?.accessible_libraries ?? state.user?.libraries ?? [],
    /** 游客态 = 勾选首项 || 允许集首项 || 'default'（服务端游客允许集闸兜底） */
    effectiveLibraryId: (state) => {
      if (!state.guestMode) return state.activeLibraryId || state.user?.default_library || ''
      const ids = state.activeLibraryIds.length
        ? state.activeLibraryIds
        : (state.guestConfig?.groups ?? []).flatMap((g) => g.libraries.map((l) => l.id))
      return ids[0] || 'default'
    },
```

actions 增加（`enterGuestMode` 之后）：

```ts
    /** 拉游客公开配置（2026-10-17 游客设置）：默认勾选 = 允许集全选；失败保持空集合
     *  （选择器降级为空、发送侧服务端仍按文件兜底裁定） */
    async loadGuestConfig() {
      if (!this.guestMode) return
      try {
        const cfg = await guestApi.getConfig()
        this.guestConfig = cfg
        const ids = cfg.groups.flatMap((g) => g.libraries.map((l) => l.id))
        this.activeLibraryIds = ids.length ? [...ids] : []
        this.activeLibraryId = this.activeLibraryIds[0] || 'default'
      } catch {
        this.guestConfig = null
        this.activeLibraryIds = []
        this.activeLibraryId = ''
      }
    },
```

- [ ] **Step 3: ChatHome.vue 改造**

template（:18-22）old：
```html
          :library-options="authStore.guestMode ? [] : libraryOptions"
          library-multi
          :library-values="authStore.activeLibraryIds"
          :library-sections="authStore.guestMode ? [] : librarySections"
```
new：
```html
          :library-options="effectiveLibraryOptions"
          library-multi
          :library-values="authStore.activeLibraryIds"
          :library-sections="effectiveLibrarySections"
```

script：

1）`librarySections` computed 之后追加：

```ts
/** 游客选择器数据源（2026-10-17 游客设置）：来自公开配置的分组库清单（服务端已按允许集过滤、已剔 evals） */
const guestLibraryOptions = computed(() =>
  (authStore.guestConfig?.groups ?? []).flatMap((g) =>
    g.libraries.map((l) => ({ value: l.id, label: l.name || l.id })),
  ),
)
const guestLibrarySections = computed<BaseChatLibrarySection[]>(() => {
  const sections: BaseChatLibrarySection[] = []
  for (const g of authStore.guestConfig?.groups ?? []) {
    if (!g.libraries.length) continue
    sections.push({
      key: g.group_name,
      label: GROUP_LABELS[g.group_name] || stripDomainPrefix(g.display_name || '') || g.group_name,
      libraries: g.libraries.map((l) => ({ id: l.id, name: l.name || l.id })),
    })
  }
  return sections
})
/** 选择器统一出口：游客走公开配置，登录态走授权派生集（模型选择仍只对登录态展示，维持现状） */
const effectiveLibraryOptions = computed(() =>
  authStore.guestMode ? guestLibraryOptions.value : libraryOptions.value,
)
const effectiveLibrarySections = computed(() =>
  authStore.guestMode ? guestLibrarySections.value : librarySections.value,
)
```

2）onMounted（:257-260）old：
```ts
  if (!authStore.isAuthed) void authStore.enterGuestMode()
  if (!authStore.guestMode) void loadLibraryNames()
```
new：
```ts
  if (!authStore.isAuthed) void authStore.enterGuestMode()
  // 游客态拉公开配置（默认全选在 store 里完成）；登录态拉授权库名/分组（既有逻辑）
  if (authStore.guestMode) void authStore.loadGuestConfig()
  else void loadLibraryNames()
```

3）isAuthed watch（:177-184）old：
```ts
watch(
  () => authStore.isAuthed,
  () => {
    loginPrompt.value = false
    void loadLibraryNames()
    void refreshSessions()
  }
)
```
new：
```ts
watch(
  () => authStore.isAuthed,
  () => {
    loginPrompt.value = false
    // 登录/登出切换重拉数据源（2026-10-17 游客设置）：登出回游客态必须重拉公开配置，
    // 否则选择器停在空集（自动登录清档后点发送会 403）
    if (authStore.guestMode) void authStore.loadGuestConfig()
    else void loadLibraryNames()
    void refreshSessions()
  }
)
```

> 关闭态（enabled=false）行为：config 照常返回（含 groups），选择器可浏览，发送 → 服务端 403 `login_required` → 既有 `onChatError` 弹 AuthGate（ChatHome.vue:168-172），零新增机制。

- [ ] **Step 4: typecheck**

```powershell
pnpm --filter @angineer/user-web exec vue-tsc -b
```

预期：0 错误。

---

## Stage 6：本地端到端验收（真服务，设计稿 §5.3 四场景）

### Task 6.1: 起服务 + API 冒烟

- [ ] **Step 1: 起后端**（另开两个终端）

```powershell
pnpm dev:docs-api
pnpm dev:aichat-api
```

- [ ] **Step 2: 取管理员 token 并切换设置**（Git Bash；`$TOKEN` = admin 登录返回）

```bash
# 登录（管理员账号）
TOKEN=$(curl -s -X POST http://127.0.0.1:8790/api/v1/auth/login \
  -H "Content-Type: application/json" \
  -d '{"username":"admin","password":"<管理员密码>"}' | python -c "import json,sys;print(json.load(sys.stdin)['token'])")

# 改设置：开放 + 3 轮 + 多库
curl -s -X PUT http://127.0.0.1:8790/api/guest/settings \
  -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -d '{"enabled":true,"rounds":3,"library_ids":["default","guifan"]}'

# 公开配置（游客端数据源）
curl -s http://127.0.0.1:8790/api/guest/config
```

预期：PUT 回显三键；config 的 groups 只含允许库、无 evals。

- [ ] **Step 3: 轮数闸（g: 桶，累计计数）**

```bash
rm -f /tmp/g.jar
curl -s -o /dev/null -X POST http://127.0.0.1:8791/api/chat/guest -c /tmp/g.jar   # 签发游客 cookie
for i in 1 2 3 4; do
  curl -s -o /dev/null -w "round$i: %{http_code}\n" -X POST http://127.0.0.1:8791/api/chat/agent \
    -b /tmp/g.jar -H "Content-Type: application/json" \
    -d '{"query":"你好","session_id":"guest-t1"}'
done
```

预期：`round1-3: 200`、`round4: 403`（轮数=3）。改回 30 后同一 cookie 继续可聊（V6 累计语义）。

- [ ] **Step 4: 关闭闸 + 读坏恢复**

```bash
# 关闭：ip: 与 g: 都 403（不带 cookie 即 ip: 桶）
curl -s -X PUT http://127.0.0.1:8790/api/guest/settings -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" -d '{"enabled":false,"rounds":30,"library_ids":["default"]}'
curl -s -o /dev/null -w "%{http_code}\n" -X POST http://127.0.0.1:8791/api/chat/agent \
  -H "Content-Type: application/json" -d '{"query":"hi","session_id":"ip-t1"}'   # 期望 403

# 读坏：手工写半截 JSON → 游客 403 + 后台 load_error 非空；DELETE 或再保存一次即恢复
```

- [ ] **Step 5: 浏览器四场景**（设计稿 §5.3）

1. 游客端：选择器出现「default+guifan」且默认全选；@ 非允许库（手工构造 `library_ids:["libA"]`）→ 403 文案（无选择器入口暴露，服务端语义可用 curl 复核）；模型选择仍隐藏。
2. 关闭态：进页可输入，发送弹登录浮层；登录用户（admin）不受影响。
3. 轮数=3：第 4 轮弹登录；改 30 后同桶续聊。
4. 读坏：后台顶部 alert、游客 403；保存一次恢复。

---

## Stage 7：回归与收尾

### Task 7.1: 全量回归

- [ ] **Step 1: 后端**

```powershell
python -m unittest discover -s tests/aichat-api -p "test_*.py"
python -m unittest discover -s tests/unit -p "test_*.py"
python -m pytest services/docs-api/tests -q
```

预期：全绿（重点红线：`test_chat_guest_gate`、`test_multi_library_auth/v2/endpoint`、`test_persist_baseline` 不红）。

- [ ] **Step 2: 前端两包 typecheck**

```powershell
pnpm --filter @angineer/admin-web exec vue-tsc -b
pnpm --filter @angineer/user-web exec vue-tsc -b
```

- [ ] **Step 3: 逐任务 commit（push 等用户明确指令）**

```
feat(guest): 游客设置 shared 模块（单测）
feat(guest): aichat 闸门接游客设置（关闭闸/文件轮数/允许集）
feat(guest): docs-api /api/guest 三端点
feat(guest): 后台游客虚拟行（开关+弹框）
feat(guest): 游客端库选择器放开
```

## 风险与回滚

- **回滚粒度**：删 `data/platform/guest_settings.json` 即回今天行为（开放/env 轮数/仅 default 库），代码层各文件独立回滚（无迁移、无破坏性 schema）。
- **已知取舍**（设计稿 §6 已登记）：scope_hash 换桶（管理员改库→进行中游客对话模型上下文断、本地消息在）；存量页面勾选滞后 403 刷新自愈。
- **服务器运维**：`.env` 里历史 `ANGINEER_GUEST_ROUNDS` 调试值在文件保存后自动退役（文件优先级更高），无需动 .env。
