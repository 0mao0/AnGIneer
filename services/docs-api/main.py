"""docs-api — 文档解析、知识库、图谱、产物下载与 API Key 管理。"""
import os
import sys
import logging
from datetime import datetime
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

_PROCESS_STARTED_AT = datetime.now().isoformat()

ROOT_DIR = Path(__file__).resolve().parent.parent.parent
SERVICES_DIR = ROOT_DIR / "services"

for pkg in ("docs-core", "angineer-core", "tree-core"):
    sys.path.insert(0, str(SERVICES_DIR / pkg / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from docs_routes import docs_router, preview_router
from graph_routes import graph_router
from retrieve_routes import retrieve_router
from api_key_routes import router as api_key_router
from users_routes import router as users_router
from routes.v1 import router as v1_router
from middleware.api_key_auth import APIKeyAuthMiddleware
from orchestrator import parse_orchestrator
from startup_recovery import reconcile_stale_parse_tasks
from models.user import ensure_admin_user

app = FastAPI(
    title="AnGIneer Docs API",
    description="文档解析 API：上传 PDF/DOCX/PPTX，产出 content.md/images/jsonl/sqlite 产物。",
    version="0.1.0",
    docs_url="/docs",
    redoc_url="/redoc",
)

# root 日志兜底：库代码普遍用 logging.getLogger(__name__) 且不设 handler，
# 不配 root 会导致 INFO 级日志（如解析阶段/检索分段计时）静默丢失；basicConfig 幂等。
logging.basicConfig(
    level=os.getenv("ANGINEER_LOG_LEVEL", "INFO").upper(),
    format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)

logger = logging.getLogger(__name__)


@app.on_event("startup")
def _reconcile_stale_parse_tasks_on_startup() -> None:
    try:
        count = reconcile_stale_parse_tasks(parse_orchestrator)
        if count:
            logger.warning("启动自愈: 标记 %d 个中断解析任务为 failed", count)
    except Exception:
        logger.exception("启动自愈执行失败")


@app.on_event("startup")
def _bootstrap_admin_on_startup() -> None:
    try:
        user = ensure_admin_user()
        if user is not None:
            logger.info("管理员引导完成: %s (is_admin=%s)", user.username, user.is_admin)
    except Exception:
        logger.exception("管理员引导执行失败")


_default_origins = "http://localhost:3005,http://localhost:3002,http://127.0.0.1:3005,http://127.0.0.1:3002,http://localhost,http://127.0.0.1"
_allowed_origins = [o.strip() for o in os.getenv("ALLOWED_ORIGINS", _default_origins).split(",") if o.strip()]

app.add_middleware(
    CORSMiddleware,
    allow_origins=_allowed_origins,
    allow_methods=["*"],
    allow_headers=["*"],
    allow_credentials=False,
)

# 任务 2.4 后中间件带 scope；按决策仅校验 /api/v1/*（详见 middleware/api_key_auth.py）
app.add_middleware(APIKeyAuthMiddleware, scope="doc")

app.include_router(docs_router, prefix="/api/knowledge", tags=["Knowledge"])
app.include_router(retrieve_router, prefix="/api/knowledge", tags=["Knowledge Internal"])
app.include_router(preview_router, prefix="/api", tags=["Preview"])
app.include_router(graph_router, prefix="/api/graph", tags=["Knowledge Graph"])
app.include_router(api_key_router)
app.include_router(users_router)
app.include_router(v1_router)


@app.get("/health")
def health():
    # started_at/pid 供启动脚本识别"端口被旧进程占用"（孤儿 worker 代答健康检查）
    return {
        "service": "docs-api",
        "status": "ok",
        "started_at": _PROCESS_STARTED_AT,
        "pid": os.getpid(),
    }


if __name__ == "__main__":
    import json
    import uvicorn

    with open(ROOT_DIR / "apps" / "shared" / "ports.json", "r", encoding="utf-8") as pf:
        API_SERVER_PORT = int(json.load(pf)["docsApiPort"])
    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=API_SERVER_PORT,
        app_dir=str(Path(__file__).resolve().parent),
        reload=True,
        reload_dirs=[
            str(Path(__file__).resolve().parent),
            str(SERVICES_DIR / "docs-core" / "src"),
            str(SERVICES_DIR / "angineer-core" / "src"),
        ],
        # DredgeAI 以 5s 间隔轮询 /status，默认 keep-alive 超时（5s）会导致复用
        # 已被服务端关闭的连接而收到 RST（SocketException 10053），调大以规避。
        timeout_keep_alive=int(os.getenv("UVICORN_KEEP_ALIVE_TIMEOUT", "30")),
    )
