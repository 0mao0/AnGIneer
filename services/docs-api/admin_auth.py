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
