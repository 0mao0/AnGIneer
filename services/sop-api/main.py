"""AnGIneer SOP 数据面服务：CRUD/导入/审核/审计/SOP 工厂。

自 aichat-api 平移（2026-10-12 解寄生，plan-sop-api-l4 阶段 1）；
路由实现见 sop_routes.py，数据目录 data/platform/sops/ 本服务独占写。
"""
import logging
import os
import sys
import time
from datetime import datetime
from pathlib import Path

# 本地源码直跑（容器内为 pip -e 安装，无需此段）
_SERVICES = Path(__file__).resolve().parent.parent
_REPO_ROOT = _SERVICES.parent
for _name in ("angineer-core", "sop-core"):
    _src = _SERVICES / _name / "src"
    if _src.is_dir() and str(_src) not in sys.path:
        sys.path.insert(0, str(_src))

logging.basicConfig(level=os.getenv("ANGINEER_LOG_LEVEL", "INFO"))

# 本机 dev：sops/ 在仓库树内；sop-api 是唯一写者（sop_path_generator 落盘读此变量）
os.environ.setdefault("DATA_DIR", str(_REPO_ROOT / "data"))

from fastapi import FastAPI  # noqa: E402

from sop_routes import sop_router  # noqa: E402

_PROCESS_STARTED_AT = datetime.now().astimezone().isoformat(timespec="seconds")

app = FastAPI(title="AnGIneer SOP API", version="0.1.0")


@app.get("/health")
def health():
    """started_at/pid 供 start.ps1 识别孤儿进程代答（8/13 事故防线，与 docs/aichat 同款）。"""
    return {
        "status": "ok",
        "service": "sop-api",
        "started_at": _PROCESS_STARTED_AT,
        "pid": os.getpid(),
    }


app.include_router(sop_router, prefix="/api/sops", tags=["SOPs"])


if __name__ == "__main__":
    import json
    import uvicorn

    with open(_REPO_ROOT / "apps" / "shared" / "ports.json", "r", encoding="utf-8") as pf:
        API_SERVER_PORT = int(json.load(pf)["sopApiPort"])
    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=API_SERVER_PORT,
        app_dir=str(Path(__file__).resolve().parent),
        reload=os.getenv("ANGINEER_NO_RELOAD", "0") != "1",
        reload_dirs=[
            str(Path(__file__).resolve().parent),
            str(_SERVICES / "sop-core" / "src"),
            str(_SERVICES / "angineer-core" / "src"),
        ],
        timeout_keep_alive=int(os.getenv("UVICORN_KEEP_ALIVE_TIMEOUT", "30")),
    )
