"""API Key 验证与状态查询。"""
from fastapi import APIRouter, Request, HTTPException

from models.v1_responses import MeResponse

router = APIRouter()


@router.get("/me", response_model=MeResponse)
async def auth_me(request: Request):
    key_info = getattr(request.state, "api_key_info", None)
    if not key_info:
        raise HTTPException(401, "Not authenticated")
    return MeResponse(
        key_prefix=key_info.key_prefix,
        user_name=key_info.user_name,
        email=key_info.email,
        rate_limit_per_minute=key_info.rate_limit_per_minute,
        created_at=key_info.created_at,
    )
