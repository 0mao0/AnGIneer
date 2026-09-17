"""aichat 会话解析与库归属校验（供中间件与端点复用）。"""
import hashlib
import os

from fastapi import Request

from models.user import get_session_user

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
    request.state.bound_library_id = user.library_ids[0] if user.library_ids else ""
    request.state.bound_library_ids = set(user.library_ids)
    return True


def enforce_bound_library(state, requested: str) -> str:
    """会话用户按库集合校验；Key 保持原单库逻辑。空/default → 默认库。"""
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


def guest_rounds_limit() -> int:
    """游客 30 轮闸阈值（策略注入，§3 硬约束 2）。"""
    try:
        return max(1, int(os.getenv("ANGINEER_GUEST_ROUNDS", "30") or 30))
    except ValueError:
        return 30


def guest_gate_blocked(owner: str, store) -> bool:
    """游客闸：``g:`` 桶 user 消息数 ≥ 阈值 → 拦（D2：满 30 轮硬拦，须登录）。

    存储降级（store=None）时 fail-open，行为同改造前；非游客桶永不拦。
    """
    if store is None or not owner.startswith("g:"):
        return False
    try:
        return store.count_user_messages(owner) >= guest_rounds_limit()
    except Exception:  # noqa: BLE001
        return False
