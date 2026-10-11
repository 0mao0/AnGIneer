"""AnGIneer SOP 数据面服务：CRUD/导入/审核/审计/SOP 工厂。

自 aichat-api 平移（2026-10-12 解寄生，plan-sop-api-l4 阶段 1）；
路由实现见 sop_routes.py，数据目录 data/platform/sops/ 本服务独占写。
"""
import logging
import os
import sys
from pathlib import Path

# 本地源码直跑（容器内为 pip -e 安装，无需此段）
_SERVICES = Path(__file__).resolve().parent.parent
for _name in ("angineer-core", "sop-core"):
    _src = _SERVICES / _name / "src"
    if _src.is_dir() and str(_src) not in sys.path:
        sys.path.insert(0, str(_src))

logging.basicConfig(level=os.getenv("ANGINEER_LOG_LEVEL", "INFO"))

from fastapi import FastAPI  # noqa: E402

from sop_routes import sop_router  # noqa: E402

app = FastAPI(title="AnGIneer SOP API", version="0.1.0")


@app.get("/health")
def health():
    return {"status": "ok", "service": "sop-api"}


app.include_router(sop_router, prefix="/api/sops", tags=["SOPs"])
