"""API Key / 账号会话认证与状态查询。"""
import asyncio
from fastapi import APIRouter, Request, HTTPException

from docs_core.docs_service import get_docs_service
from models.user import (
    create_session,
    delete_session,
    get_user_by_username,
    update_last_login,
    verify_password,
)
from models.v1_responses import LoginRequest, LoginResponse, MeResponse, SessionMeResponse

router = APIRouter()


@router.post("/login", response_model=LoginResponse)
async def auth_login(req: LoginRequest):
    user = get_user_by_username(req.username)
    if user is None or not user.is_active or not verify_password(req.password, user.password_hash):
        await asyncio.sleep(0.3)
        raise HTTPException(401, "用户名或密码错误")
    token = create_session(user.id)
    update_last_login(user.id)
    return LoginResponse(
        token=token,
        user={
            "username": user.username,
            "display_name": user.display_name,
            "libraries": user.library_ids,
        },
    )


@router.post("/logout")
async def auth_logout(request: Request):
    raw = getattr(request.state, "session_token_raw", "") or ""
    if raw:
        delete_session(raw)
    return {"status": "success"}


@router.get("/me")
async def auth_me(request: Request):
    session_user = getattr(request.state, "session_user", None)
    if session_user is not None and isinstance(getattr(session_user, "username", None), str):
        ks = get_docs_service()
        existing = [lid for lid in session_user.library_ids if ks.get_library(lid) is not None]
        return SessionMeResponse(
            username=session_user.username,
            display_name=session_user.display_name,
            libraries=existing,
            default_library=existing[0] if existing else "",
        )

    key_info = getattr(request.state, "api_key_info", None)
    if not key_info:
        raise HTTPException(401, "Not authenticated")
    library_id = str(getattr(key_info, "library_id", "") or "").strip()
    if not library_id:
        raise HTTPException(403, "API key 未绑定知识库，请联系管理员重新生成")
    # 租户首次登录自动建库（ensure）：库不存在则创建
    ks = get_docs_service()
    if ks.get_library(library_id) is None:
        user_name = key_info.user_name or library_id
        ks.create_library(library_id, f"{user_name}知识库")
    return MeResponse(
        key_prefix=key_info.key_prefix,
        user_name=key_info.user_name,
        email=key_info.email,
        rate_limit_per_minute=key_info.rate_limit_per_minute,
        created_at=key_info.created_at,
        library_id=library_id,
        library_exists=True,
    )
