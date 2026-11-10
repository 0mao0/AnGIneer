"""docs-core [api]：解析面薄壳（上传 / 断点续跑 / 状态轮询 / 产物下载 + health）。

对外最小面（DredgeAI docs-api 进包需求 R1/R3，2026-11-11）：
- ``POST /api/v1/documents/parse?stages=...``     multipart 上传解析
- ``POST /api/v1/documents/{doc_id}/resume``      断点续跑（进行中 409）
- ``GET  /api/v1/documents/{doc_id}/status``      状态轮询
- ``GET  /api/v1/documents/{doc_id}/artifacts``   产物清单
- ``GET  /api/v1/documents/{doc_id}/artifacts/{name}``  产物字节流
- ``GET  /api/v1/documents/{doc_id}/pdf``         原始/转换后 PDF
- ``GET  /api/v1/documents/{doc_id}/blocks``      块清单（页面/类型过滤）
- ``GET  /api/v1/documents/{doc_id}/content``     markdown 全文
- ``DELETE /api/v1/documents/{doc_id}``           幂等软删（不存在 404）
- ``GET  /health``                                探活（含配置漂移 degraded）

数据面全参数化（``ANGINEER_DATA_ROOT`` / ``KB_STACK`` / ``KNOWLEDGE_PG_DSN`` /
``MINERU_CONFIGS`` 等），与检索壳 ``docs_core.server:app`` 同一套 env 口径：解析面写完
派生层，检索面/编排面读同一份存储，无需同步。

鉴权：``/api/v1/*`` 强制 ``X-API-Key``（静态键 env ``DOCS_API_STATIC_KEYS``，见 auth.py）；
``/health`` 不要求。

启动：``uvicorn docs_core.docs_api:app --host 127.0.0.1 --port 8312``（端口由 uvicorn
参数决定，不读 ports.json）；``python -m docs_core.docs_api`` 是带单实例守卫的可选入口
（env ``DOCS_API_SINGLE_INSTANCE_GUARD=1`` 开启守卫，默认关——进程唯一性由消费方启动器保证）。

宿主差异（服务名与启动事件保留宿主语义）：
- 去管理员引导/会话体系、去知识库管理面路由（见需求 3.2）；
- 配置校验内联（docs_api._config），不依赖 angineer-shared。
"""
import logging
import os
from datetime import datetime
from typing import Any, Dict, Optional

try:
    from dotenv import load_dotenv
    from fastapi import FastAPI
    from fastapi.middleware.cors import CORSMiddleware
    from fastapi.responses import JSONResponse
    from starlette.middleware.base import BaseHTTPMiddleware
except ImportError as exc:  # pragma: no cover - 安装提示
    raise ImportError(
        "docs_core.docs_api 需要 [api] extra（fastapi/uvicorn/python-multipart）。"
        "请安装：pip install 'angineer-docs-core[api]'"
    ) from exc

from docs_core import __version__ as _PKG_VERSION

# 允许 .env 兜底（本地裸跑），但绝不覆盖调用方已注入的环境变量（需求 3.3-f）；
# python-dotenv 默认 override=False，这里显式声明语义。无 .env 文件也能启动。
load_dotenv(override=False)

# root 日志兜底（同宿主 docs-api / 检索壳）：库代码普遍用 logging.getLogger(__name__)
# 且不设 handler，不配 root 会丢 INFO 级日志；basicConfig 幂等。
logging.basicConfig(
    level=os.getenv("ANGINEER_LOG_LEVEL", "INFO").upper(),
    format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)

logger = logging.getLogger("docs_core.docs_api")

_PROCESS_STARTED_AT = datetime.now().isoformat()


def create_app() -> FastAPI:
    from docs_core.docs_api import _config
    from docs_core.docs_api.auth import StaticAPIKeyMiddleware
    from docs_core.docs_api.documents import router as documents_router

    # 配置校验（等价宿主 ensure_env）：失败不退出，/health 报 degraded + config_errors
    _config.ensure_env()

    app = FastAPI(
        title="AnGIneer Docs API (standalone shell)",
        description="文档解析 API：上传 PDF/DOCX/PPTX，产出 content.md/images/jsonl 产物并落派生索引。",
        version=_PKG_VERSION,
        docs_url="/docs",
        redoc_url="/redoc",
    )

    # KB 迁移门禁：migrating 库上的写入统一 409（迁移管理面在宿主，错误面保持一致）
    from docs_core.kb_migrator import LibraryMigratingError

    @app.exception_handler(LibraryMigratingError)
    async def _library_migrating_handler(request, exc):  # noqa: ANN001
        return JSONResponse(status_code=409, content={"detail": str(exc)})

    _default_origins = (
        "http://localhost:3005,http://localhost:3002,http://127.0.0.1:3005,"
        "http://127.0.0.1:3002,http://localhost,http://127.0.0.1"
    )
    _allowed_origins = [
        o.strip() for o in os.getenv("ALLOWED_ORIGINS", _default_origins).split(",") if o.strip()
    ]
    app.add_middleware(
        CORSMiddleware,
        allow_origins=_allowed_origins,
        allow_methods=["*"],
        allow_headers=["*"],
        allow_credentials=False,
    )

    # /api/v1/* 强制 X-API-Key（静态键单通道，见 auth.py）
    app.add_middleware(StaticAPIKeyMiddleware)

    app.include_router(documents_router, prefix="/api/v1/documents", tags=["Documents"])

    _vector_guard_report: Optional[Dict[str, Any]] = None

    @app.on_event("startup")
    def _reconcile_stale_parse_tasks_on_startup() -> None:
        """启动自愈（宿主同款）：任务级 + 行级兜底，把重启遗留任务标 failed 可续跑。"""
        from docs_core.docs_api.orchestrator import parse_orchestrator
        from docs_core.docs_api.startup_recovery import (
            reconcile_stale_parse_tasks,
            reconcile_stale_records,
        )

        try:
            count = reconcile_stale_parse_tasks(parse_orchestrator)
            if count:
                logger.warning("启动自愈: 标记 %d 个中断解析任务为 failed", count)
            # 行级兜底必须在任务级清扫之后跑：任务级已把内存里能标的全标 failed，
            # 剩下的非终态行即任务悬空遗留（2026-10-04 取消 404 事故对账）。
            row_count = reconcile_stale_records(parse_orchestrator)
            if row_count:
                logger.warning("启动自愈: 标记 %d 条遗留解析记录为 failed", row_count)
        except Exception:
            logger.exception("启动自愈执行失败")

    @app.on_event("startup")
    def _split_graph_per_library_on_startup() -> None:
        """图谱一库一文件拆分（幂等）：旧数据根有全局 graph.sqlite 即拆；失败不阻断启动。"""
        try:
            from docs_core.step07_graph.graph_files import split_global_graph_if_present
            report = split_global_graph_if_present(log=logger)
            if report:
                logger.info("启动迁移: 图谱按库拆分完成 backup=%s", report.get("backup"))
        except Exception:
            logger.exception("启动迁移: 图谱按库拆分失败——继续用全局文件（回退生效）")

    @app.on_event("startup")
    def _run_vector_guard_on_startup() -> None:
        """启动向量守卫（宿主同款，非阻塞）：embedding 维度探针 + 向量库脏数据检查。"""
        nonlocal _vector_guard_report
        try:
            from docs_core.startup_guard import report_to_dict, run_vector_startup_guard
            report = run_vector_startup_guard()
            _vector_guard_report = report_to_dict(report)
        except Exception:
            logger.exception("启动向量库守卫执行失败")
            _vector_guard_report = {"ok": False, "errors": ["守卫自身异常"], "warnings": [], "details": {}}

    @app.get("/health")
    def health():
        cs = _config.config_status_response()
        body: Dict[str, Any] = {
            "service": "docs-api",
            "started_at": _PROCESS_STARTED_AT,
            "pid": os.getpid(),
        }
        if not cs["config_ok"]:
            body["status"] = "degraded"
            body["config_errors"] = cs["errors"]
        else:
            body["status"] = "ok"
        if _vector_guard_report is not None:
            body["vector_store"] = _vector_guard_report
            if not _vector_guard_report.get("ok", True):
                body["status"] = "degraded"
        return body

    return app


def assert_single_instance(port: int, service: str = "docs-api") -> None:
    """单实例守卫（可选，env DOCS_API_SINGLE_INSTANCE_GUARD=1 时由 __main__ 入口调用）。

    Windows SO_REUSEADDR 允许端口共绑——残留孤儿进程不报错、静默分流请求
    （2026-09-24/25 aichat-api 两次实踩）。启动前先探 /health：已有同服务在跑就拒绝启动。
    消费方进程唯一性由己方启动器保证时无须开启。
    """
    import json as _json
    import urllib.request

    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/health", timeout=2) as resp:
            body = _json.loads(resp.read().decode("utf-8", "ignore"))
    except Exception:
        return  # 端口无人应答 = 干净，正常启动
    if body.get("service") != service:
        return  # 端口上是别的服务，绑定时 uvicorn 会自行报端口占用
    raise SystemExit(
        f"{service} 端口 {port} 已有实例在跑（pid={body.get('pid')} "
        f"started_at={body.get('started_at')}），拒绝重复启动：端口共绑会静默分流请求。"
        "请先停掉旧实例。"
    )


app = create_app()
