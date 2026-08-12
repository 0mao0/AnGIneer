"""v1 外部 API 路由。"""
from fastapi import APIRouter
from .documents import router as documents_router
from .auth import router as auth_router

router = APIRouter(prefix="/api/v1")
router.include_router(documents_router, prefix="/documents", tags=["Documents"])
router.include_router(auth_router, prefix="/auth", tags=["Auth"])
