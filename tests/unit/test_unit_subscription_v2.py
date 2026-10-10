"""V2 两级授权（组订阅→组内库）派生单元测试——设计稿 docs/design-user-kb-access-scope.md §9-2（设计稿已完结清理、git 历史可查）。

钉住开关两侧：V2 开=每请求派生实际检索集（组订阅减组内排除 ∪ 散库直选；管理员=全部
active 库减 evals；顺序稳定，scope_hash 依赖）；V2 关=旧 user_libraries 平铺语义逐位保留
（回滚保险）。库快照一律 patch 假清单，不依赖真实 knowledge_meta 注册表。
"""
import os
import sys
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import patch

_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "../.."))
for _p in (
    os.path.join(_ROOT, "services", "docs-api"),
    os.path.join(_ROOT, "services", "docs-core", "src"),
):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import models.user as user_model  # noqa: E402  —— 别名层=shared.user_model 本体（模块替换）
import shared.subscription as sub  # noqa: E402

# 假快照 (library_id, group_name, status)：road 组 4 员（1 个 retired）+ water 组 + evals 组 + 散库
SNAP = [
    ("default", "", "active"),
    ("road-1", "road", "active"),
    ("road-2", "road", "active"),
    ("road-3", "road", "active"),
    ("road-9", "road", "retired"),
    ("water-1", "water", "active"),
    ("evals-a", "evals", "active"),
]


def _user(**kw):
    base = dict(username="u", is_admin=False, library_ids=[], group_subscriptions=None, library_direct=None)
    base.update(kw)
    return SimpleNamespace(**base)


def _active(snap):
    """按生产端契约过滤（active_libraries_snapshot 只吐 active；替换桩必须同口径，
    否则 retired 假条目会绕过派生混进结果——过滤逻辑本身另有专测定住）。"""
    return [t for t in snap if t[2] not in sub._NON_ACTIVE_STATUS]


def _derive(user, snapshot=None, v2=True):
    """在受控快照/开关下跑一次派生（快照 patch 在定义处 shared.subscription）。"""
    snap = _active(SNAP if snapshot is None else list(snapshot))
    with patch.dict(os.environ, {"ANGINEER_KB_SUBSCRIPTION_V2": "1" if v2 else "0"}), patch.object(
        sub, "active_libraries_snapshot", lambda: snap
    ):
        return sub.derive_libraries_for_user(user)


class TestDeriveV2On(unittest.TestCase):
    def test_v2_off_keeps_flat_semantics(self):
        """关=回滚保险：平铺清单原样透传，连 evals 也不滤（旧语义逐位保留）。"""
        user = _user(library_ids=["road-1", "evals-a"])
        self.assertEqual(_derive(user, v2=False), ["road-1", "evals-a"])

    def test_snapshot_producer_excludes_non_active(self):
        """R4 源头排除在生产端：retired/migrating 到不了派生（此处不经 _derive 的过滤桩）。"""
        raw = [SimpleNamespace(id=l, group_name=g, status=s) for l, g, s in SNAP]
        service = SimpleNamespace(list_libraries=lambda: raw)
        with patch("docs_core.docs_service.get_docs_service", lambda: service):
            snap = sub.active_libraries_snapshot()
        self.assertEqual(
            [t[0] for t in snap], ["default", "road-1", "road-2", "road-3", "water-1", "evals-a"]
        )

    def test_group_sub_minus_excluded(self):
        """§9-1 主案：整组订阅减组内排除，顺序=订阅序+组内清单序。"""
        user = _user(
            group_subscriptions=[
                {"group": "road", "excluded_libraries": ["road-2"]},
                {"group": "water", "excluded_libraries": []},
            ]
        )
        self.assertEqual(_derive(user), ["road-1", "road-3", "water-1"])

    def test_order_stable_and_dedup(self):
        """顺序稳定+去重：同输入两次派生一致；重复组订阅不产生第二份。"""
        user = _user(
            group_subscriptions=[
                {"group": "road", "excluded_libraries": []},
                {"group": "road", "excluded_libraries": []},
            ]
        )
        first = _derive(user)
        self.assertEqual(first, ["road-1", "road-2", "road-3"])
        self.assertEqual(_derive(user), first)

    def test_direct_reselect_beats_group_exclusion(self):
        """直选点名可翻组排除：显式直选的库回到检索集且殿后（显式意图优先，顺序稳定）。"""
        user = _user(
            group_subscriptions=[{"group": "road", "excluded_libraries": ["road-2"]}],
            library_direct=["road-2", "default"],
        )
        self.assertEqual(_derive(user), ["road-1", "road-3", "road-2", "default"])

    def test_admin_gets_all_active_minus_evals(self):
        """管理员=全部 active 库−evals 组（§8-B2 源头排除；retired 按生产端契约已不在快照）。"""
        self.assertEqual(_derive(_user(is_admin=True)), ["default", "road-1", "road-2", "road-3", "water-1"])

    def test_zero_sub_flat_passthrough_excludes_evals(self):
        """§8-4：零订阅保留平铺透传不锁死；但 V2 开时源头排除 evals 组。"""
        self.assertEqual(_derive(_user(library_ids=["default", "evals-a"])), ["default"])

    def test_zero_sub_direct_only_passthrough(self):
        """零组订阅、纯散库直选：直选表照样进派生集。"""
        self.assertEqual(_derive(_user(library_direct=["default"])), ["default"])

    def test_unknown_direct_dropped(self):
        """未登记 id 不进派生集（显式 @未登记库→403 的现行语义保留）。"""
        user = _user(
            group_subscriptions=[{"group": "road", "excluded_libraries": []}],
            library_direct=["ghost"],
        )
        self.assertEqual(_derive(user), ["road-1", "road-2", "road-3"])

    def test_evals_group_subscription_skipped(self):
        """§8-B2：整组订阅含 evals 时整组跳过，不进对话检索。"""
        user = _user(
            group_subscriptions=[
                {"group": "evals", "excluded_libraries": []},
                {"group": "road", "excluded_libraries": []},
            ]
        )
        self.assertEqual(_derive(user), ["road-1", "road-2", "road-3"])

    def test_new_lib_enters_next_derive(self):
        """R2 核心特性：组内新入库自动进入已订阅用户的检索范围（读穿不缓存）。"""
        user = _user(group_subscriptions=[{"group": "road", "excluded_libraries": []}])
        before = _derive(user)
        self.assertEqual(before, ["road-1", "road-2", "road-3"])
        snap2 = SNAP + [("road-4", "road", "active")]
        self.assertEqual(_derive(user, snapshot=snap2), ["road-1", "road-2", "road-3", "road-4"])


class TestSetUserAccessDoubleWrite(unittest.TestCase):
    """§8-5/C-1 双写：保存订阅后 user_libraries 镜像=保存时刻派生结果（回滚 V2=0 不空窗）。"""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(lambda: __import__("shutil").rmtree(self.tmp, ignore_errors=True))
        db = os.path.join(self.tmp, "users.sqlite")
        env = patch.dict(os.environ, {"ANGINEER_KB_SUBSCRIPTION_V2": "1"})
        env.start()
        self.addCleanup(env.stop)

        def _snap():
            return _active(SNAP)

        for mod in (sub, user_model):
            p = patch.object(mod, "active_libraries_snapshot", _snap)
            p.start()
            self.addCleanup(p.stop)
        p = patch.object(user_model, "DB_PATH", db)
        p.start()
        self.addCleanup(p.stop)
        user_model.init_db()

    def _mirror(self, username):
        return user_model.get_user_by_username(username).library_ids

    def test_write_subscriptions_and_mirror(self):
        user = user_model.create_user("dave", "Dave", "secret123", ["road-1"])
        ok = user_model.set_user_access(
            user.id,
            [{"group": "road", "excluded_libraries": ["road-2"]}],
            ["default"],
        )
        self.assertTrue(ok)
        # 镜像=派生集（road 减排除 + 直选），不是入参直抄
        self.assertEqual(self._mirror("dave"), ["road-1", "road-3", "default"])
        import sqlite3

        conn = sqlite3.connect(os.path.join(self.tmp, "users.sqlite"))
        subs = conn.execute("SELECT group_name, excluded_libraries FROM user_group_subscriptions").fetchall()
        direct = conn.execute("SELECT library_id FROM user_library_direct").fetchall()
        conn.close()
        self.assertEqual(subs, [("road", '["road-2"]')])
        self.assertEqual(direct, [("default",)])

    def test_revoke_all_clears_mirror(self):
        user = user_model.create_user("erin", "Erin", "secret123", ["road-1", "water-1"])
        self.assertEqual(self._mirror("erin"), ["road-1", "water-1"])
        self.assertTrue(user_model.set_user_access(user.id, [], []))
        self.assertEqual(self._mirror("erin"), [])

    def test_v2_off_write_keeps_mirror(self):
        """开关关时 set_user_access 只写订阅表、不重写镜像（回滚层读镜像语义不变）。"""
        user = user_model.create_user("fred", "Fred", "secret123", ["road-1"])
        with patch.dict(os.environ, {"ANGINEER_KB_SUBSCRIPTION_V2": "0"}):
            self.assertTrue(
                user_model.set_user_access(
                    user.id,
                    [{"group": "road", "excluded_libraries": ["road-2"]}],
                    ["default"],
                )
            )
        # V2 关保存不碰镜像，也不派生读：user_libraries 原样
        self.assertEqual(self._mirror("fred"), ["road-1"])


if __name__ == "__main__":
    unittest.main()
