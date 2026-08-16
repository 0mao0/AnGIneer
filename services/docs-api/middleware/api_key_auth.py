"""API Key 验证 FastAPI 中间件。仅对 /api/v1/* 路径生效，按服务 scope 校验。

绑定了 library_id 的 key：query 缺失时自动注入绑定值；显式传不一致直接 403（防串库）。
未绑定 key（library_id=''）直接拒绝——开发期收紧，不再向后兼容旧 key。
"""
from urllib.parse import urlencode

from fastapi import Request
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware

from models.api_key import lookup_key


class APIKeyAuthMiddleware(BaseHTTPMiddleware):
    def __init__(self, app, scope: str = "doc"):
        super().__init__(app)
        self.scope = scope

    async def dispatch(self, request: Request, call_next):
        if request.url.path.startswith("/api/v1/"):
            api_key = request.headers.get("X-API-Key", "").strip()
            if not api_key:
                return JSONResponse(status_code=401, content={"detail": "Missing X-API-Key header"})

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

        response = await call_next(request)
        return response
