"""API Key / 会话双通道认证 FastAPI 中间件。
- /api/v1/*：必须带 key 或会话。
- /api/chat/*：带 key 或会话则校验并注入库归属；不带凭证默认放行（管理端场景），
  ANGINEER_CHAT_AUTH_REQUIRED=true 时改为 401。
"""
import os

from fastapi import Request
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware

from chat_auth import resolve_session_principal
from models.api_key import lookup_key


class APIKeyAuthMiddleware(BaseHTTPMiddleware):
    def __init__(self, app, scope: str = "doc"):
        super().__init__(app)
        self.scope = scope

    async def dispatch(self, request: Request, call_next):
        path = request.url.path
        if path.startswith("/api/v1/"):
            api_key = request.headers.get("X-API-Key", "").strip()
            if not api_key and not resolve_session_principal(request):
                return JSONResponse(status_code=401, content={"detail": "Missing X-API-Key or session token"})
            if api_key:
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
                request.state.api_key_info = key_info
                request.state.bound_library_id = bound_library
            elif not resolve_session_principal(request):
                if os.getenv("ANGINEER_CHAT_AUTH_REQUIRED", "").strip().lower() in ("1", "true", "yes"):
                    return JSONResponse(status_code=401, content={"detail": "Missing X-API-Key or session token"})

        response = await call_next(request)
        return response
