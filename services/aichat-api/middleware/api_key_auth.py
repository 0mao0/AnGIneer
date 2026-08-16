"""API Key 验证 FastAPI 中间件。

- /api/v1/*：必须带 key（按服务 scope 校验）。
- /api/chat/*：带 key 则校验并注入 request.state（未绑定 key 拒绝；
  bound_library_id 供端点层强制）；不带 key 默认放行（管理端场景），
  ANGINEER_CHAT_AUTH_REQUIRED=true 时改为 401。
"""
import os

from fastapi import Request
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware

from models.api_key import lookup_key


class APIKeyAuthMiddleware(BaseHTTPMiddleware):
    def __init__(self, app, scope: str = "doc"):
        super().__init__(app)
        self.scope = scope

    async def dispatch(self, request: Request, call_next):
        path = request.url.path
        if path.startswith("/api/v1/"):
            api_key = request.headers.get("X-API-Key", "").strip()
            if not api_key:
                return JSONResponse(status_code=401, content={"detail": "Missing X-API-Key header"})

            key_info = lookup_key(api_key)
            if not key_info:
                return JSONResponse(status_code=403, content={"detail": "Invalid or inactive API key"})
            if key_info.scope not in (self.scope, "both"):
                return JSONResponse(status_code=403, content={"detail": f"API key has no {self.scope} scope"})
            if not str(getattr(key_info, "library_id", "") or "").strip():
                return JSONResponse(
                    status_code=403,
                    content={"detail": "API key 未绑定知识库，请联系管理员重新生成"},
                )

            request.state.api_key_info = key_info

        elif path.startswith("/api/chat/"):
            api_key = request.headers.get("X-API-Key", "").strip()
            if not api_key:
                if os.getenv("ANGINEER_CHAT_AUTH_REQUIRED", "").strip().lower() in ("1", "true", "yes"):
                    return JSONResponse(status_code=401, content={"detail": "Missing X-API-Key header"})
            else:
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
                request.state.api_key_info = key_info
                request.state.bound_library_id = bound_library

        response = await call_next(request)
        return response
