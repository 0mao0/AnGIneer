"""aichat 会话解析与库归属校验（供中间件与端点复用）。"""
from fastapi import Request

from models.user import get_session_user


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
        return (requested or "").strip() or "default"
    req = (requested or "").strip()
    if req and req != "default" and req != bound:
        from fastapi import HTTPException
        raise HTTPException(status_code=403, detail=f"API key 仅授权访问知识库 '{bound}'")
    return bound
