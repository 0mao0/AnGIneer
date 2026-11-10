"""X-API-Key 单通道鉴权（静态键）——解析面包内中间件。

宿主的双通道（DB 键库 + 会话登录）留在主仓库 docs-api（models/api_key / admin_auth /
users_routes），不进包——外部消费方用静态 Key（DredgeAI docs-api 进包需求 R2）：

- env ``DOCS_API_STATIC_KEYS``（逗号分隔）配置静态键；命中即放行；
- 静态键视作**未绑定库**的键：不注入 ``library_id``、不限制查询参数里的 ``library_id``，
  消费方可显式传库（如 ``?library_id=bid-docs``），不传则路由层落 ``default``；
- 静态键未配置时行为与现状一致：无头 401、无效键 403。

principal 对象（``request.state.api_key_info``）与宿主 DB 键的 ApiKey 形状对齐
（``id`` / ``user_name`` / ``key_prefix`` / ``library_id`` 四属性），路由层代码无须分叉；
``id=None`` 即静态身份——需要按 key 归属判权的地方（如 resume）以 ``id`` 是否为 None 区分。
"""
import hmac
import os
from dataclasses import dataclass
from typing import List

from fastapi import Request
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware

STATIC_KEYS_ENV = "DOCS_API_STATIC_KEYS"


@dataclass
class StaticKeyInfo:
    """静态键 principal（形状对齐宿主 models.api_key.ApiKey 的消费面属性）。"""

    id: int | None = None
    user_name: str = "StaticAPI"
    key_prefix: str = ""
    library_id: str = ""  # 未绑定库：不注入也不限制


def static_keys() -> List[str]:
    """读静态键清单（每次请求现读 env，测试/运维改配置后无需重载进程）。"""
    raw = (os.getenv(STATIC_KEYS_ENV) or "").strip()
    if not raw:
        return []
    return [k.strip() for k in raw.split(",") if k.strip()]


class StaticAPIKeyMiddleware(BaseHTTPMiddleware):
    """``/api/v1/*`` 强制 X-API-Key 头（静态键单通道）。"""

    async def dispatch(self, request: Request, call_next):
        path = request.url.path
        if not path.startswith("/api/v1/"):
            return await call_next(request)

        supplied = (request.headers.get("X-API-Key") or "").strip()
        if not supplied:
            return JSONResponse(status_code=401, content={"detail": "Missing X-API-Key header"})
        for candidate in static_keys():
            if hmac.compare_digest(supplied, candidate):
                request.state.api_key_info = StaticKeyInfo(
                    key_prefix=f"****{candidate[-4:]}" if len(candidate) >= 4 else "****",
                )
                request.state.api_key_static = True
                return await call_next(request)
        return JSONResponse(status_code=403, content={"detail": "Invalid or inactive API key"})
