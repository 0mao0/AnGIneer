"""aichat 会话解析与库归属校验（供中间件与端点复用）。"""
import hashlib
import logging
import os

from fastapi import Request

from models.user import (
    FANOUT_WARN_THRESHOLD,
    derive_libraries_for_user,
    get_session_user,
    subscription_v2_enabled,
)

logger = logging.getLogger("aichat.auth")

# 游客身份 cookie（chat_history.routes 签发，HttpOnly）；步 3 起匿名桶由 ip: 升级为 g:
GUEST_COOKIE = "ag_guest_id"


def resolve_session_principal(request: Request) -> bool:
    auth_header = (request.headers.get("Authorization", "") or "").strip()
    if not auth_header.lower().startswith("bearer "):
        return False
    raw_token = auth_header[7:].strip()
    user = get_session_user(raw_token)
    if user is None or not user.is_active:
        return False
    request.state.session_user = user
    request.state.session_token_raw = raw_token
    if subscription_v2_enabled():
        # V2（2026-10-09 设计稿 §4 R1）：成员集 = 每请求派生（跟随注册表/新建库自动生效）；
        # 保序列表而非 set——scope_hash/会话池 key 依赖顺序，顺序抖动会拆桶历史并漂移主库标签。
        derived = derive_libraries_for_user(user)
        request.state.bound_library_id = derived[0] if derived else ""
        request.state.bound_library_ids = derived
    else:
        request.state.bound_library_id = user.library_ids[0] if user.library_ids else ""
        request.state.bound_library_ids = set(user.library_ids)
    return True


def enforce_bound_library(state, requested: str) -> str:
    """会话用户按库集合校验；Key 保持原单库逻辑。空/default → 默认库。

    零生产调用方（main 端点已走集合版 enforce_bound_libraries），仅作旧单值语义回归基准。
    """
    user = getattr(state, "session_user", None)
    if user is not None and getattr(user, "is_admin", False) is True:
        # 管理员跨库视野：允许访问任意知识库（与 admin-web 全局库选择一致）
        return (requested or "").strip() or "default"
    ids = getattr(state, "bound_library_ids", None)
    if ids is not None:
        req = (requested or "").strip()
        if not req or req == "default":
            return getattr(state, "bound_library_id", "") or "default"
        if req not in ids:
            from fastapi import HTTPException
            raise HTTPException(status_code=403, detail=f"用户无权访问知识库 '{req}'")
        return req
    bound = getattr(state, "bound_library_id", "") or ""
    if not bound:
        # 匿名（无 API key 也无会话）：只允许默认库。
        # 2026-09-17 之前这里原样透传 requested —— 无凭证即可检索任意知识库
        # （线上 POST /api/chat/agent 带 library_id 实测可达且未鉴权）。
        req = (requested or "").strip()
        if not req or req == "default":
            return "default"
        from fastapi import HTTPException
        raise HTTPException(status_code=403, detail="未登录访问仅限默认知识库，请登录后选择其它知识库")
    req = (requested or "").strip()
    if req and req != "default" and req != bound:
        from fastapi import HTTPException
        raise HTTPException(status_code=403, detail=f"API key 仅授权访问知识库 '{bound}'")
    return bound


def max_chat_libraries() -> int:
    """多库勾选上限（阶段三 D1）：默认 5，环境变量可调（夹 1..100；2026-10-13 业主放开，原夹 1..10）。"""
    try:
        return min(100, max(1, int(os.getenv("ANGINEER_MAX_CHAT_LIBRARIES", "5") or 5)))
    except ValueError:
        return 5


def _enforce_bound_v2(state, user, requested: "list[str]") -> "list[str]":
    """V2 订阅派生制成员校验（2026-10-09 设计稿 §4 R2/R3；开关默认关=永不进本函数）。

    - 隐式（空/["default"]）= 派生集全选（无上限、无截断；管理员同闸，派生集=全部 active 库）；
    - 显式 @ = 任一非成员（未订阅/未登记/retired）→ 403 可见报错，不静默剔除；
      全成员 → 整集返回（[:cap] 截断移除，「选 M 库 = M 库检索」业主口径）；
    - 派生集 >FANOUT_WARN_THRESHOLD → 仅 warning 日志（观测口径，不拦截）。
    成员集未经 principal 注入（旁路/单测 state）时现算派生——成员集单一真相源，不写第二套判定。
    """
    from fastapi import HTTPException

    derived = getattr(state, "bound_library_ids", None)
    if derived is None:
        derived = derive_libraries_for_user(user)
    else:
        derived = list(derived)
    libs = [str(x).strip() for x in requested if str(x).strip()]
    if len(derived) > FANOUT_WARN_THRESHOLD:
        logger.warning("单请求检索集 %d 库（无上限，V2 观测口径）: %s", len(derived), derived)
    if not libs or libs == ["default"]:
        if derived:
            return derived
        # 零订阅/派生为空（含管理员空快照）：保留旧空/default 回退，不锁死（§8-4 口径）
        return [getattr(state, "bound_library_id", "") or "default"]
    for lib in libs:
        if lib not in derived:
            raise HTTPException(status_code=403, detail=f"用户无权访问知识库 '{lib}'")
    return libs


def enforce_bound_libraries(state, requested: "list[str]") -> "list[str]":
    """集合版库归属校验：先整集鉴权（任一越权即 403），再按上限截断（spec §P1-5）。

    会话用户按 bound_library_ids 集合校验；管理员任意集合；Key 维持单库绑定
    （集合收敛为 [bound]，集合含非绑定库成员同样 403——与旧 enforce_bound_library
    的冲突拒绝逐位一致，不静默剔除）；匿名仅默认库。空集合回退默认库。

    V2=1（ANGINEER_KB_SUBSCRIPTION_V2，2026-10-09 设计稿）：会话用户改走
    _enforce_bound_v2（派生制，无截断无上限，403 保留）；以下主体 = V2=0 回滚语义。
    """
    from fastapi import HTTPException

    user = getattr(state, "session_user", None)
    if user is not None and subscription_v2_enabled():
        return _enforce_bound_v2(state, user, requested)
    if user is not None and getattr(user, "is_admin", False) is True:
        # 管理员跨库视野：允许访问任意知识库（与 admin-web 全局库选择一致）
        libs = [str(x).strip() for x in requested if str(x).strip()] or ["default"]
        return libs[: max_chat_libraries()]
    ids = getattr(state, "bound_library_ids", None)
    if ids is not None:
        libs = [str(x).strip() for x in requested if str(x).strip()]
        if not libs or libs == ["default"]:
            # 空/default 回退直返（不进成员校验）：零绑库登录用户（ids=set()、bound=""）
            # 旧 body 下 enforce_bound_library 放行 "default"，此处若仍过 ids 即 403，
            # 破兼容铁律 1（2026-10-04 评审 blocking 修正；bound 非空时该值恒 ∈ ids，
            # 跳过校验与有绑库用户的现行为等价）。
            return [getattr(state, "bound_library_id", "") or "default"][: max_chat_libraries()]
        for lib in libs:
            if lib not in ids:
                raise HTTPException(status_code=403, detail=f"用户无权访问知识库 '{lib}'")
        return libs[: max_chat_libraries()]
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
    # API key：单库绑定不变（spec：Key 仍单库），集合收敛为 [bound]；
    # 计划 v3 片段此处直接 return [bound] 会把旧 enforce_bound_library 的冲突 403 吞成静默收敛，
    # 破兼容铁律 1（2026-10-04 实施时修正：非绑定成员一律 403）。
    libs = [str(x).strip() for x in requested if str(x).strip()]
    if not libs or libs == ["default"]:
        return [bound]
    for lib in libs:
        if lib != bound:
            raise HTTPException(status_code=403, detail=f"API key 仅授权访问知识库 '{bound}'")
    return [bound]


def _client_ip_digest(request: Request) -> str:
    """匿名主体指纹：取最左 X-Forwarded-For（网关与前端层均已设），退化到直连 peer。"""
    xff = (request.headers.get("x-forwarded-for", "") or "").split(",")[0].strip()
    peer = request.client.host if request.client else ""
    material = xff or peer or "unknown"
    return hashlib.sha1(material.encode("utf-8")).hexdigest()[:12]


def resolve_pool_owner(request: Request) -> str:
    """会话池归属键：登录 ``u:<id>`` / API key ``k:<id>`` / 游客 cookie ``g:<id>`` / 匿名 ``ip:<hash>``。

    池 key 必须带身份：``session_id`` 由客户端生成（``chat-<毫秒时间戳>`` 形状可枚举），
    缺了 owner 时同 scene/库/文档范围的不同主体会命中同一份 history，
    后被问到的人会拿到前一个人的上下文（跨用户串话）。

    游客 cookie（2026-09-17，计划 D6）优先于 ip: 兜底：同 NAT 下不再共享匿名桶，
    30 轮闸与 claim 都按 ``g:<guest_id>`` 计数/搬迁。登录态与 API key 永远优先于 cookie。
    """
    user = getattr(request.state, "session_user", None)
    if user is not None:
        ident = getattr(user, "id", None) or getattr(user, "username", "")
        return f"u:{ident}"
    key_info = getattr(request.state, "api_key_info", None)
    if key_info is not None:
        ident = getattr(key_info, "id", None) or getattr(key_info, "user_name", "")
        return f"k:{ident}"
    guest_id = (request.cookies.get(GUEST_COOKIE) or "").strip()
    if guest_id:
        return f"g:{guest_id}"
    return f"ip:{_client_ip_digest(request)}"


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


def guest_rounds_limit(state=None) -> int:
    """游客轮数阈值：游客设置文件 > env(ANGINEER_GUEST_ROUNDS) > 30。

    2026-10-17 游客设置（设计稿 §3.1）：文件一旦保存即钉死 rounds，改 .env 不再生效；
    文件缺失时退回 env 语义。state 传入则复用请求级缓存（见 _guest_settings）。
    """
    return int(_guest_settings(state).get("rounds") or 30)


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
    except Exception as exc:  # noqa: BLE001
        # fail-open 仅对「store=None 存储降级」属设计豁免（§3.3）；运行期异常（DB 锁/IO）
        # 同样放行但必须留痕——否则游客轮闸静默失效无从排查（2026-10-17 排查实踩）。
        logger.warning(
            "游客闸判定异常，按 fail-open 放行（owner=%s）: %s", owner, exc,
        )
        return False
