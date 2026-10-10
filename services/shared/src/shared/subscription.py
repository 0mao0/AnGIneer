"""知识库访问范围两级授权（组订阅 → 组内库）——设计稿 docs/design-user-kb-access-scope.md（2026-10-09；该设计稿已完结清理、git 历史可查）。

V2 开关 = 环境变量 ``ANGINEER_KB_SUBSCRIPTION_V2``（默认关）：
- 关 = 逐位保留旧 ``user_libraries`` 平铺清单语义（含 5 库截断，回滚保险）；
- 开 = 每请求把订阅派生成实际检索集：组订阅（组内全部 active 库，含将来新增，
  减组内排除）∪ 散库直选；管理员 = 全部 active 库（无上限，业主 B1 口径）。

派生发生在请求时（读穿，不缓存——对齐 library_registry 头部「注册表只能显式初始化、
读穿不缓存」契约）：组内新入库自动进入已订阅用户的检索范围，属「整组开发」语义本意。
"""

import json
import logging
import os
import sqlite3
from typing import Any, Dict, List, Tuple

logger = logging.getLogger(__name__)

V2_ENV = "ANGINEER_KB_SUBSCRIPTION_V2"

# 单请求检索集超过该库数时记一条 warning（观测口径，不拦截、不截断——2026-10-09 B1 定版）
FANOUT_WARN_THRESHOLD = 20

# 非 active 状态（R4：派生源头排除，消费端不再二次猜）——
# 与 library_registry.list_libraries(include_retired=False) 及 kb_migrator 写门禁同口径
_NON_ACTIVE_STATUS = ("retired", "migrating")

# §8-B2（2026-10-09 定版）：评测语料不进对话检索——V2 开启时派生集在**源头**排除 evals 组
# （管理员/整组订阅含 evals 亦然）；用户端 ChatHome 展示层的 evals 过滤保留为第二层纸。
EVALS_GROUP = "evals"


def subscription_v2_enabled() -> bool:
    return (os.environ.get(V2_ENV, "") or "").strip().lower() in ("1", "true", "yes")


def _parse_excluded(raw: Any) -> List[str]:
    if isinstance(raw, str):
        try:
            raw = json.loads(raw or "[]")
        except (ValueError, TypeError):
            return []
    if not isinstance(raw, list):
        return []
    return [str(x).strip() for x in raw if str(x).strip()]


def load_subscriptions(conn: sqlite3.Connection, user_id: int) -> Tuple[List[Dict[str, Any]], List[str]]:
    """读取用户订阅（组订阅 + 散库直选）。表缺行返回 ([], [])——零订阅判定在调用方。"""
    subs = [
        {"group": r[0], "excluded_libraries": _parse_excluded(r[1])}
        for r in conn.execute(
            "SELECT group_name, excluded_libraries FROM user_group_subscriptions WHERE user_id = ?",
            (user_id,),
        ).fetchall()
    ]
    direct = [
        r[0]
        for r in conn.execute(
            "SELECT library_id FROM user_library_direct WHERE user_id = ? ORDER BY rowid", (user_id,)
        ).fetchall()
    ]
    return subs, direct


def active_libraries_snapshot() -> List[Tuple[str, str, str]]:
    """全部可检索库快照 [(library_id, group_name, status)]（读穿，不缓存）。

    主源 = ``docs_core.docs_service.list_libraries()``（knowledge_meta 主源 + 注册表补
    组归属/collection）；docs_core 不可导入的裸环境（独立包/独立测试）与读取失败
    一律按**空集**降级——派生范围只窄不宽（「查不到=没有」教训口径）。
    """
    try:
        from docs_core.docs_service import get_docs_service

        libs = get_docs_service().list_libraries()
        return [
            (lib.id, lib.group_name or "", lib.status or "")
            for lib in libs
            if (lib.status or "") not in _NON_ACTIVE_STATUS
        ]
    except ImportError:
        logger.debug("docs_core 不可导入：派生按空集降级")
        return []
    except Exception as exc:  # noqa: BLE001 — 读源失败按空集降级（宁可查不到，不可放宽）
        logger.warning("知识库清单读取失败（按空集降级）: %s", exc)
        return []


def _library_group_map() -> Dict[str, Tuple[str, str]]:
    return {lid: (group, status) for lid, group, status in active_libraries_snapshot()}


def derive_libraries_for_user(user: Any) -> List[str]:
    """把用户授权配置派生成实际检索集（顺序稳定：组订阅按订阅序、组内按清单序、直选殿后）。

    返回顺序稳定是刻意的：main.py 把派生集回填 ``request.library_id = library_ids[0]``
    并计入 scope_hash/会话池 key，顺序抖动会让同一勾选的跨请求 scope_hash 漂移。
    """
    if not subscription_v2_enabled():
        return list(user.library_ids or [])
    snapshot = active_libraries_snapshot()
    snapshot_ids = [lid for lid, _g, _s in snapshot]
    group_by_id = {lid: group for lid, group, _s in snapshot}
    if getattr(user, "is_admin", False):
        # §8-B2：管理员派生集同样不含 evals 组（管理员/整组订阅含 evals 时源头排除）
        return [lid for lid in snapshot_ids if group_by_id.get(lid, "") != EVALS_GROUP]
    subs = list(getattr(user, "group_subscriptions", None) or [])
    direct = list(getattr(user, "library_direct", None) or [])
    if not subs and not direct:
        # 零订阅（新建未勾选/回退层）：保留旧平铺清单语义，不锁死（设计稿 §8-4 口径）；
        # 但 V2 开启时照样源头排除 evals 组（§8-B2，评测语料不进对话检索）
        return [lid for lid in (user.library_ids or []) if group_by_id.get(lid, "") != EVALS_GROUP]
    derived: List[str] = []
    seen = set()
    for sub in subs:
        group = (sub.get("group") or "").strip()
        if group == EVALS_GROUP:
            continue  # §8-B2：整组订阅含 evals 组时不进派生集（前端展示层过滤只是第二层纸）
        excluded = set(_parse_excluded(sub.get("excluded_libraries")))
        for lid in snapshot_ids:
            if lid not in seen and group_by_id.get(lid, "") == group and lid not in excluded:
                seen.add(lid)
                derived.append(lid)
    # 散库直选只认「确有其库」：未登记 id 不进派生集（显式 @ 未登记库 → 403 的现行语义保留）；
    # evals 组内的库即使被直选也排除（§8-B2 源头排除，不留第二套口径）
    for lid in direct:
        if lid and lid not in seen and lid in group_by_id and group_by_id.get(lid, "") != EVALS_GROUP:
            seen.add(lid)
            derived.append(lid)
    return derived


def has_subscription_config(user: Any) -> bool:
    """是否配置过订阅（区分「订阅派生为空→403 候选」与「零订阅→保留 default 回退」）。"""
    return bool(getattr(user, "group_subscriptions", None) or getattr(user, "library_direct", None))
