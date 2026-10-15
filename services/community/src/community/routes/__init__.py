"""HTTP 路由层：`/api/community/*` 路由工厂（挂到 aichat-api）。"""
from community.routes.community import build_community_router  # noqa: F401
