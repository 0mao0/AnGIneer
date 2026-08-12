"""API Key 验证 FastAPI 中间件。仅对 /api/v1/* 路径生效，按服务 scope 校验。"""
from fastapi import Request, HTTPException
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
                raise HTTPException(status_code=401, detail="Missing X-API-Key header")

            key_info = lookup_key(api_key)
            if not key_info:
                raise HTTPException(status_code=403, detail="Invalid or inactive API key")
            if key_info.scope not in (self.scope, "both"):
                raise HTTPException(status_code=403, detail=f"API key has no {self.scope} scope")

            request.state.api_key_info = key_info

        response = await call_next(request)
        return response
