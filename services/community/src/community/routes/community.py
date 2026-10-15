"""FastAPI 路由工厂：`/api/community/*`（契约见设计 §10）。

挂载范式照 chat-history：`build_community_router(service, resolve_principal)`，
鉴权/游客归属由宿主注入——本包不认识 chat 会话体系，只消费
`resolve_principal(request) -> (owner_key, user_id, author_label)` 三元组。
读端点匿名可访问；写端点匿名可提交（nginx per-IP 频控在前，应用层日限兜底）。
"""
import logging
from typing import Any, Callable, Optional, Tuple

from fastapi import APIRouter, Query, Request
from fastapi.responses import JSONResponse

from community import models
from community.service import CommunityService, SubmissionError

logger = logging.getLogger(__name__)

PrincipalResolver = Callable[..., Tuple[str, Optional[int], str]]


def _error(status: int, detail: str) -> JSONResponse:
    return JSONResponse(status_code=status, content={"detail": detail})


def build_community_router(
    service: CommunityService,
    resolve_principal: Optional[PrincipalResolver] = None,
) -> APIRouter:
    router = APIRouter()

    def principal(request):
        if resolve_principal is None:
            return "", None, models.GUEST_LABEL
        owner_key, user_id, label = resolve_principal(request)
        return owner_key or "", user_id, (label or models.GUEST_LABEL)

    # ---- 读 ----

    @router.get("/tree")
    def get_tree(scope: str = Query("eval", pattern="^(eval|sop)$")):
        return service.get_tree(scope)

    @router.get("/datasets/{ref_id}")
    def get_dataset(ref_id: str, origin: str = Query("official", pattern="^(official|user)$")):
        card = service.dataset_card(ref_id, origin)
        if card is None:
            return _error(404, "测试集不存在或未公开。")
        return card

    @router.get("/datasets/{ref_id}/questions")
    def get_questions(
        ref_id: str,
        origin: str = Query("official", pattern="^(official|user)$"),
        offset: int = Query(0, ge=0),
        limit: int = Query(50, ge=1, le=200),
    ):
        items, total = service.list_questions(ref_id, origin, offset=offset, limit=limit)
        return {"items": items, "total": total, "offset": offset, "limit": limit}

    @router.get("/sops/{sop_id}")
    def get_sop(sop_id: str):
        sop = service.get_sop(sop_id)
        if sop is None:
            return _error(404, "SOP 不存在或未公开。")
        return sop

    @router.get("/sops/{sop_id}/comments")
    def get_sop_comments(sop_id: str):
        return {"comments": service.list_comments(sop_id)}

    # ---- 写（本版只收不审） ----

    @router.post("/submissions")
    async def create_submission(request: Request):
        try:
            body = await request.json()
        except Exception:  # noqa: BLE001
            return _error(400, "请求体不是合法 JSON。")
        if not isinstance(body, dict):
            return _error(400, "请求体须为 JSON 对象。")
        owner_key, user_id, label = principal(request)
        try:
            row = service.create_submission(
                scope=str(body.get("scope") or ""),
                kind=str(body.get("kind") or ""),
                payload=body.get("payload") or {},
                node_id=str(body.get("node_id") or ""),
                parent_ref=str(body.get("parent_ref") or ""),
                step_ref=str(body.get("step_ref") or ""),
                title=str(body.get("title") or ""),
                owner_key=owner_key,
                user_id=user_id,
                author_label=label,
            )
        except SubmissionError as exc:
            return _error(exc.status, exc.detail)
        except Exception as exc:  # noqa: BLE001
            logger.exception("community 投稿落库失败")
            return _error(500, "提交失败，请稍后重试。")
        return JSONResponse(
            status_code=201,
            content={
                "submission_id": row["submission_id"],
                "status": row["status"],
                "author_label": row["author_label"],
                "created_at": row["created_at"],
            },
        )

    return router


__all__ = ["build_community_router", "models"]
