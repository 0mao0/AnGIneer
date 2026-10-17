"""游客设置端点（docs/design-guest-settings.md §3.2）：

- GET/PUT /api/guest/settings：管理员读写（resolve_admin_session）；
- GET /api/guest/config：公开只读，游客端拉「是否开放 + 允许库（分组形状，同 /knowledge/libraries/groups）」。

存储与优先级在 shared.guest_settings；校验口径（V1-V4）见设计稿 §3.6，失败一律 400（不静默夹取）。
"""
from typing import List

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from admin_auth import resolve_admin_session
from docs_core.docs_service import get_docs_service
from shared.guest_settings import load_guest_settings, save_guest_settings
from shared.subscription import EVALS_GROUP

router = APIRouter(prefix="/api/guest", tags=["Guest"])


class GuestSettingsPayload(BaseModel):
    enabled: bool
    rounds: int = Field(default=30, description="游客轮数上限（1–1000，越界 400 见 handler）")
    library_ids: List[str] = Field(default_factory=list)


@router.get("/settings", dependencies=[Depends(resolve_admin_session)])
async def get_guest_settings():
    return load_guest_settings()


@router.put("/settings", dependencies=[Depends(resolve_admin_session)])
async def put_guest_settings(req: GuestSettingsPayload):
    if isinstance(req.rounds, bool) or not (1 <= req.rounds <= 1000):
        raise HTTPException(400, "轮数上限必须是 1–1000 的整数")
    libs = [str(x).strip() for x in req.library_ids if str(x).strip()]
    if not libs:
        raise HTTPException(400, "请至少选择 1 个游客可用知识库")
    ks = get_docs_service()
    for lid in libs:
        lib = ks.get_library(lid)
        if lib is None:
            raise HTTPException(400, f"知识库 {lid} 不存在，请先创建")
        if (getattr(lib, "group_name", "") or "") == EVALS_GROUP:
            raise HTTPException(400, f"评测语料库 {lid} 不可开放给游客")
    return save_guest_settings({"enabled": req.enabled, "rounds": req.rounds, "library_ids": libs})


@router.get("/config")
async def get_guest_config():
    """游客端公开配置：只含允许集库/组名（不扩大既有暴露面，设计稿 §6），evals 组永不出现。"""
    cfg = load_guest_settings()
    allowed = set(cfg["library_ids"])
    groups = []
    for g in get_docs_service().list_grouped_libraries():
        if g["group_name"] == EVALS_GROUP:
            continue
        libs = [{"id": l["id"], "name": l["name"]} for l in g["libraries"] if l["id"] in allowed]
        if libs:
            groups.append(
                {"group_name": g["group_name"], "display_name": g.get("display_name", ""), "libraries": libs}
            )
    return {"enabled": cfg["enabled"], "rounds": cfg["rounds"], "groups": groups}
