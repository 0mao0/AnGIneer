"""聊天历史 HTTP 路由（计划 §2）：会话列表/详情/删除/快照 PUT/claim。

组装方式（aichat-api）：
    app.include_router(
        build_chat_router(store, resolve_principal),
        prefix="/api/chat",
    )

解耦要点：
- 身份解析注入：``resolve_principal(request) -> (owner_key, user_id|None)``，
  路由层不认识 session token / API key / 游客 cookie 的解析细节；
- 策略注入：游客轮数阈值 / 保留天数 / 强制登录由参数或 env 决定（§3 硬约束 2）；
- 所有查询以 owner 桶为界（行级隔离由构造保证，D6）。
"""
import json
import os
from datetime import datetime
from typing import Any, Callable, Dict, List, Optional, Tuple

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from chat_history.store.sqlite_store import SqliteHistoryStore

# resolve_principal(request) -> (owner_key, user_id | None)
PrincipalResolver = Callable[[Request], Tuple[str, Optional[int]]]

MAX_SESSIONS_PER_LIBRARY = 50  # 与前端 chatHistory.MAX_SESSIONS_PER_LIBRARY 对齐


def _iso_to_ms(iso: str) -> int:
    try:
        return int(datetime.fromisoformat(iso).timestamp() * 1000)
    except (ValueError, TypeError):
        return 0


def _session_out(row: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "id": row["session_id"],
        "scene": row.get("scene") or "qa",
        "libraryId": row.get("library_id") or "default",
        "title": row.get("title") or "未命名对话",
        "createdAt": _iso_to_ms(row.get("created_at") or ""),
        "updatedAt": _iso_to_ms(row.get("updated_at") or ""),
    }


def _message_out(row: Dict[str, Any]) -> Dict[str, Any]:
    extra = json.loads(row.get("meta_json") or "{}")
    out: Dict[str, Any] = {
        "msgSeq": row["seq"],
        "role": row["role"],
        "content": row["content"] or "",
    }
    meta = extra.get("meta") or {}
    out.update(meta)  # citations / thinking_trace / strategy / timings 等展示字段
    return out


class MetaPatchItem(BaseModel):
    msg_seq: int
    meta_patch: Dict[str, Any] = {}


class MessagesPatchBody(BaseModel):
    patches: List[MetaPatchItem]


class ClaimBody(BaseModel):
    guest_id: Optional[str] = None  # 步 3 起以 cookie 为准；body 为兼容/测试入口


def build_chat_router(
    store: Optional[SqliteHistoryStore],
    resolve_principal: PrincipalResolver,
    *,
    guest_rounds: Optional[int] = None,
    guest_cookie: str = "ag_guest_id",
) -> APIRouter:
    """构建聊天历史路由；store 为 None 时全部端点 503（存储降级）。

    guest_rounds / 保留天数等策略读 env（§3 硬约束 2），参数仅作测试注入口。
    """
    router = APIRouter()

    def _store() -> SqliteHistoryStore:
        if store is None:
            raise HTTPException(status_code=503, detail="chat history store unavailable")
        return store

    def _rounds_limit() -> int:
        if guest_rounds is not None:
            return guest_rounds
        return int(os.getenv("ANGINEER_GUEST_ROUNDS", "30") or 30)

    @router.get("/sessions")
    def list_sessions(request: Request, library_id: Optional[str] = None):
        owner, _ = resolve_principal(request)
        rows = _store().list_sessions(owner, library_id, limit=MAX_SESSIONS_PER_LIBRARY)
        return {"sessions": [_session_out(r) for r in rows]}

    @router.get("/sessions/{session_id}")
    def get_session(request: Request, session_id: str):
        owner, _ = resolve_principal(request)
        st = _store()
        row = st.get_session(owner, session_id)
        if row is None:
            raise HTTPException(status_code=404, detail="session not found")
        messages = [_message_out(m) for m in st.get_messages(owner, session_id)]
        return {"session": _session_out(row), "messages": messages}

    @router.put("/sessions/{session_id}/messages")
    def patch_messages(request: Request, session_id: str, body: MessagesPatchBody):
        owner, _ = resolve_principal(request)
        try:
            n = _store().patch_meta(owner, session_id, [p.model_dump() for p in body.patches])
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc))
        return {"patched": n}

    @router.delete("/sessions/{session_id}")
    def delete_session(request: Request, session_id: str):
        owner, _ = resolve_principal(request)
        if not _store().delete_session(owner, session_id):
            raise HTTPException(status_code=404, detail="session not found")
        return {"deleted": session_id}

    @router.delete("/sessions")
    def delete_sessions_by_library(request: Request, library_id: str):
        owner, _ = resolve_principal(request)
        n = _store().delete_sessions_by_library(owner, library_id)
        return {"deleted": n}

    @router.post("/sessions/claim")
    def claim(request: Request, body: ClaimBody):
        owner, user_id = resolve_principal(request)
        if user_id is None:
            raise HTTPException(status_code=403, detail="claim requires login")
        guest_id = body.guest_id or request.cookies.get(guest_cookie) or ""
        if not guest_id:
            raise HTTPException(status_code=400, detail="guest_id required")
        n = _store().claim_guest(f"g:{guest_id}", f"u:{user_id}", user_id)
        return {"claimed": n, "already_claimed": n == 0}

    # ---- 步 3：游客端点与轮闸（在此工厂内一并构建，策略注入见 _rounds_limit） ----

    @router.post("/guest")
    def issue_guest(request: Request):
        import secrets

        gid = request.cookies.get(guest_cookie) or secrets.token_urlsafe(18)
        _store().touch_guest(gid)
        from fastapi.responses import JSONResponse

        resp = JSONResponse({"guest_id": gid})
        if request.cookies.get(guest_cookie) != gid:
            resp.set_cookie(guest_cookie, gid, max_age=180 * 24 * 3600, httponly=True, samesite="lax")
        return resp

    return router
