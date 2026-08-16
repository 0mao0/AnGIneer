"""API Key 验证与状态查询。"""
from fastapi import APIRouter, Request, HTTPException

from docs_core.docs_service import get_docs_service
from models.v1_responses import MeResponse

router = APIRouter()


@router.get("/me", response_model=MeResponse)
async def auth_me(request: Request):
    key_info = getattr(request.state, "api_key_info", None)
    if not key_info:
        raise HTTPException(401, "Not authenticated")
    library_id = str(getattr(key_info, "library_id", "") or "").strip()
    library_exists = False
    if library_id:
        # 租户首次登录自动建库（ensure）：库不存在则创建
        ks = get_docs_service()
        if ks.get_library(library_id) is None:
            ks.create_library(library_id, key_info.user_name or library_id)
        library_exists = True
    return MeResponse(
        key_prefix=key_info.key_prefix,
        user_name=key_info.user_name,
        email=key_info.email,
        rate_limit_per_minute=key_info.rate_limit_per_minute,
        created_at=key_info.created_at,
        library_id=library_id,
        library_exists=library_exists,
    )
