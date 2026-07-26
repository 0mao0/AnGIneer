"""内部 API Key 管理端点。"""
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from models.api_key import generate_key, list_keys, deactivate_key, reactivate_key
from models.v1_responses import CreateKeyRequest

router = APIRouter(prefix="/api")


class KeyItem(BaseModel):
    id: int
    key_prefix: str
    user_name: str
    email: str
    is_active: bool
    rate_limit_per_minute: int
    created_at: str
    last_used_at: str | None = None


class CreateKeyResponse(BaseModel):
    api_key: str = Field(..., description="完整 key，仅此时可见")
    key_prefix: str
    user_name: str
    email: str
    rate_limit_per_minute: int
    created_at: str
    message: str = "请妥善保管此 Key，离开此页面后将无法再次查看完整 Key。"


@router.get("/api-keys", response_model=list[KeyItem], tags=["Admin"])
async def list_api_keys():
    return list_keys()


@router.post("/api-keys", response_model=CreateKeyResponse, tags=["Admin"])
async def create_api_key(req: CreateKeyRequest):
    raw_key, api_key = generate_key(req.user_name, req.email, req.rate_limit_per_minute)
    return CreateKeyResponse(
        api_key=raw_key,
        key_prefix=api_key.key_prefix,
        user_name=api_key.user_name,
        email=api_key.email,
        rate_limit_per_minute=api_key.rate_limit_per_minute,
        created_at=api_key.created_at,
    )


@router.post("/api-keys/{key_id}/deactivate", tags=["Admin"])
async def deactivate_api_key(key_id: int):
    ok = deactivate_key(key_id)
    if not ok:
        raise HTTPException(404, "Key not found")
    return {"status": "deactivated"}


@router.post("/api-keys/{key_id}/reactivate", tags=["Admin"])
async def reactivate_api_key(key_id: int):
    ok = reactivate_key(key_id)
    if not ok:
        raise HTTPException(404, "Key not found")
    return {"status": "reactivated"}
