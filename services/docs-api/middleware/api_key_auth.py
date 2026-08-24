"""API Key / 会话双通道认证 FastAPI 中间件。仅对 /api/v1/* 生效（/api/v1/auth/login 除外）。"""
from urllib.parse import urlencode

from fastapi import Request
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware

from models.api_key import lookup_key
from models.user import get_session_user


def resolve_session_principal(request: Request) -> bool:
    """从 Authorization: Bearer 解析会话用户；成功则写入 request.state。"""
    auth_header = (request.headers.get("Authorization", "") or "").strip()
    if not auth_header.lower().startswith("bearer "):
        return False
    raw_token = auth_header[7:].strip()
    user = get_session_user(raw_token)
    if user is None or not user.is_active:
        return False
    request.state.session_user = user
    request.state.session_token_raw = raw_token
    return True


def authorize_library(request: Request, requested: str) -> str | None:
    """校验会话用户请求的库；返回最终 library_id，越权返回 None。"""
    user = getattr(request.state, "session_user", None)
    if user is None or not user.library_ids:
        return None
    req = (requested or "").strip()
    if not req:
        return user.library_ids[0]
    if req in user.library_ids:
        return req
    return None


class APIKeyAuthMiddleware(BaseHTTPMiddleware):
    def __init__(self, app, scope: str = "doc"):
        super().__init__(app)
        self.scope = scope

    async def dispatch(self, request: Request, call_next):
        path = request.url.path
        if path == "/api/v1/auth/login":
            return await call_next(request)
        if path.startswith("/api/v1/"):
            api_key = request.headers.get("X-API-Key", "").strip()
            if api_key:
                key_info = lookup_key(api_key)
                if not key_info:
                    return JSONResponse(status_code=403, content={"detail": "Invalid or inactive API key"})
                if key_info.scope not in (self.scope, "both"):
                    return JSONResponse(status_code=403, content={"detail": f"API key has no {self.scope} scope"})
                bound_library = str(getattr(key_info, "library_id", "") or "").strip()
                if not bound_library:
                    return JSONResponse(
                        status_code=403,
                        content={"detail": "API key 未绑定知识库，请联系管理员重新生成"},
                    )
                params = dict(request.query_params)
                requested = str(params.get("library_id") or "").strip()
                if requested and requested != bound_library:
                    return JSONResponse(
                        status_code=403,
                        content={"detail": f"API key 仅授权访问知识库 '{bound_library}'"},
                    )
                if not requested:
                    params["library_id"] = bound_library
                    request.scope["query_string"] = urlencode(params).encode("utf-8")
                    request._query_params = None
                request.state.api_key_info = key_info
            elif resolve_session_principal(request):
                params = dict(request.query_params)
                requested = str(params.get("library_id") or "").strip()
                final_lib = authorize_library(request, requested)
                if final_lib is None:
                    return JSONResponse(status_code=403, content={"detail": "用户无权访问该知识库"})
                params["library_id"] = final_lib
                request.scope["query_string"] = urlencode(params).encode("utf-8")
                request._query_params = None
            else:
                return JSONResponse(status_code=401, content={"detail": "Missing X-API-Key or session token"})

        response = await call_next(request)
        return response
