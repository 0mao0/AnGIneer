"""管理端用户管理接口（受 nginx 白名单 + Basic Auth 保护）。"""
from typing import List, Optional
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from docs_core.docs_service import get_docs_service
from models.user import (
    create_user,
    delete_user,
    list_users,
    set_password,
    set_user_active,
    update_user,
    User,
)

router = APIRouter(prefix="/api/users", tags=["Admin Users"])


class UserItem(BaseModel):
    id: int
    username: str
    display_name: str
    library_ids: List[str] = Field(default_factory=list)
    is_active: bool
    created_at: str
    last_login_at: Optional[str] = None


class CreateUserRequest(BaseModel):
    username: str = Field(..., min_length=1, max_length=100)
    display_name: str = Field(default="", max_length=100)
    password: str = Field(..., min_length=6, max_length=200)
    library_ids: List[str] = Field(default_factory=list)


class UpdateUserRequest(BaseModel):
    display_name: str = Field(default="", max_length=100)
    library_ids: List[str] = Field(default_factory=list)


class PasswordRequest(BaseModel):
    password: str = Field(..., min_length=6, max_length=200)


def _to_item(user: User) -> UserItem:
    return UserItem(
        id=user.id,
        username=user.username,
        display_name=user.display_name,
        library_ids=user.library_ids,
        is_active=user.is_active,
        created_at=user.created_at,
        last_login_at=user.last_login_at,
    )


def _ensure_libraries_exist(library_ids: List[str]) -> None:
    ks = get_docs_service()
    for lid in library_ids:
        if ks.get_library(lid) is None:
            raise HTTPException(400, f"知识库 {lid} 不存在，请先创建")


@router.get("", response_model=List[UserItem])
async def list_users_route():
    return [_to_item(u) for u in list_users()]


@router.post("", response_model=UserItem)
async def create_user_route(req: CreateUserRequest):
    _ensure_libraries_exist(req.library_ids)
    try:
        user = create_user(req.username, req.display_name, req.password, req.library_ids)
    except ValueError as e:
        raise HTTPException(400, str(e))
    return _to_item(user)


@router.put("/{user_id}", response_model=dict)
async def update_user_route(user_id: int, req: UpdateUserRequest):
    _ensure_libraries_exist(req.library_ids)
    ok = update_user(user_id, display_name=req.display_name, library_ids=req.library_ids)
    if not ok:
        raise HTTPException(404, "用户不存在")
    return {"status": "success"}


@router.post("/{user_id}/password", response_model=dict)
async def reset_password_route(user_id: int, req: PasswordRequest):
    try:
        ok = set_password(user_id, req.password)
    except ValueError as e:
        raise HTTPException(400, str(e))
    if not ok:
        raise HTTPException(404, "用户不存在")
    return {"status": "success", "message": "密码已重置，该用户所有会话已失效"}


@router.post("/{user_id}/activate", response_model=dict)
async def activate_user_route(user_id: int):
    if not set_user_active(user_id, True):
        raise HTTPException(404, "用户不存在")
    return {"status": "success"}


@router.post("/{user_id}/deactivate", response_model=dict)
async def deactivate_user_route(user_id: int):
    if not set_user_active(user_id, False):
        raise HTTPException(404, "用户不存在")
    return {"status": "success"}


@router.delete("/{user_id}", response_model=dict)
async def delete_user_route(user_id: int):
    if not delete_user(user_id):
        raise HTTPException(404, "用户不存在")
    return {"status": "success", "message": "用户已删除"}
