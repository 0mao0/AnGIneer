"""管理端用户管理接口（受 nginx 白名单 + Basic Auth 保护）。"""
from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from admin_auth import resolve_admin_session
from docs_core.docs_service import get_docs_service
from models.user import (
    create_user,
    delete_user,
    derive_libraries_for_user,
    get_user_by_id,
    list_users,
    set_password,
    set_user_access,
    set_user_active,
    subscription_v2_enabled,
    update_user,
    User,
)

router = APIRouter(prefix="/api/users", tags=["Admin Users"], dependencies=[Depends(resolve_admin_session)])


class UserItem(BaseModel):
    id: int
    username: str
    display_name: str
    is_admin: bool = False
    library_ids: List[str] = Field(default_factory=list)
    # V2（2026-10-09 设计稿）：组订阅回显 + 实际可检索派生集（表格列/编辑回显数据源）
    group_subscriptions: List[dict] = Field(default_factory=list)
    accessible_libraries: List[str] = Field(default_factory=list)
    is_active: bool
    created_at: str
    last_login_at: Optional[str] = None


class CreateUserRequest(BaseModel):
    username: str = Field(..., min_length=1, max_length=100)
    display_name: str = Field(default="", max_length=100)
    password: str = Field(..., min_length=6, max_length=200)
    is_admin: bool = False
    library_ids: List[str] = Field(default_factory=list)
    # V2 写路径：整组订阅（含组内排除）与散库直选；缺省时按 library_ids 走直选语义
    group_subscriptions: List[dict] = Field(default_factory=list)
    direct_library_ids: List[str] = Field(default_factory=list)


class UpdateUserRequest(BaseModel):
    display_name: str = Field(default="", max_length=100)
    is_admin: bool = False
    library_ids: List[str] = Field(default_factory=list)
    group_subscriptions: List[dict] = Field(default_factory=list)
    direct_library_ids: List[str] = Field(default_factory=list)


class PasswordRequest(BaseModel):
    password: str = Field(..., min_length=6, max_length=200)


def _to_item(user: User) -> UserItem:
    return UserItem(
        id=user.id,
        username=user.username,
        display_name=user.display_name,
        is_admin=user.is_admin,
        library_ids=user.library_ids,
        group_subscriptions=list(user.group_subscriptions),
        accessible_libraries=derive_libraries_for_user(user) if subscription_v2_enabled() else list(user.library_ids),
        is_active=user.is_active,
        created_at=user.created_at,
        last_login_at=user.last_login_at,
    )


def _ensure_libraries_exist(library_ids: List[str]) -> None:
    ks = get_docs_service()
    for lid in library_ids:
        if ks.get_library(lid) is None:
            raise HTTPException(400, f"知识库 {lid} 不存在，请先创建")


def _write_access_v2(user: User, req) -> None:
    """V2 订阅保存（admin 两级勾选 → 存储）：组订阅+直选写两订阅表，同步回写回退层镜像。

    组校验口径 = 内置组 ∪ 已登记自定义组（`_known_group`，与建库入口同源）；
    订阅里的 excluded_libraries 是减法不做存在性校验（排除不存在的库无副作用）。
    """
    ks = get_docs_service()
    subs = [dict(s) for s in (req.group_subscriptions or [])]
    direct = [lid for lid in (req.direct_library_ids or req.library_ids or []) if str(lid or "").strip()]
    for sub in subs:
        group = (sub.get("group") or "").strip()
        if group and not ks._known_group(group):
            raise HTTPException(400, f"知识库组 {group} 不存在，请先创建组或改用库直选")
    _ensure_libraries_exist(direct)
    set_user_access(user.id, subs, direct)


@router.get("", response_model=List[UserItem])
async def list_users_route():
    return [_to_item(u) for u in list_users()]


@router.post("", response_model=UserItem)
async def create_user_route(req: CreateUserRequest):
    _ensure_libraries_exist(req.library_ids)
    try:
        user = create_user(req.username, req.display_name, req.password, req.library_ids, is_admin=req.is_admin)
    except ValueError as e:
        raise HTTPException(400, str(e))
    if subscription_v2_enabled():
        _write_access_v2(user, req)
        user = get_user_by_id(user.id) or user
    return _to_item(user)


@router.put("/{user_id}", response_model=dict)
async def update_user_route(user_id: int, req: UpdateUserRequest):
    if subscription_v2_enabled():
        # V2：不直写 library_ids（防回退层与订阅漂移）；镜像由 set_user_access 统一回写
        user = get_user_by_id(user_id)
        if user is None:
            raise HTTPException(404, "用户不存在")
        update_user(user_id, display_name=req.display_name, is_admin=req.is_admin)
        _write_access_v2(user, req)
        return {"status": "success"}
    _ensure_libraries_exist(req.library_ids)
    ok = update_user(user_id, display_name=req.display_name, library_ids=req.library_ids, is_admin=req.is_admin)
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
