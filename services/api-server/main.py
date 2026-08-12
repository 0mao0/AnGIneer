import os
import json
import glob
import asyncio
import sys
import uuid
import logging
from typing import List, Dict, Any, Optional
from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

# 设置路径
ROOT_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "../.."))
SERVICES_DIR = os.path.join(ROOT_DIR, "services")
PORT_CONTRACT_PATH = os.path.join(ROOT_DIR, "apps", "shared", "ports.json")

with open(PORT_CONTRACT_PATH, "r", encoding="utf-8") as port_contract_file:
    PORT_CONTRACT = json.load(port_contract_file)

API_SERVER_PORT = int(PORT_CONTRACT["apiServerPort"])

# 添加路径sys.path 以支持本地包导入
sys.path.append(os.path.join(SERVICES_DIR, "angineer-core", "src"))
sys.path.append(os.path.join(SERVICES_DIR, "sop-core", "src"))
sys.path.append(os.path.join(SERVICES_DIR, "docs-core", "src"))
sys.path.append(os.path.join(SERVICES_DIR, "geo-core", "src"))
sys.path.append(os.path.join(SERVICES_DIR, "engtools", "src"))
sys.path.append(os.path.join(SERVICES_DIR, "evals-core", "src"))

# Import logic from packages
from ai_inference.llm_client import LLMClient
from angineer_core import IntentClassifier
from chat_agent import (
    find_session_by_run_id,
    get_agent_session,
    make_policy_config_factory,
    map_event_to_agent_frame,
)
from sop_core.sop_loader import SopLoader
# Import tools to ensure registration
from engtools import * 
import geo_core.GisTool
import engtools.KnowledgeTool
from docs_routes import docs_router, preview_router
from evals_routes import evals_router

app = FastAPI(
    title="AnGIneer API",
    description=(
        "AnGIneer 深度文档解析 API 服务。\n\n"
        "提供 PDF/DOCX/PPTX 等格式的文档结构化解析，"
        "返回带归一化 bbox 坐标的文本块，供前端做精准高亮渲染。\n\n"
        "**认证方式：** 所有 `/api/v1/*` 端点需在 Header 中携带 `X-API-Key`。"
    ),
    version="0.1.0",
    contact={
        "name": "AnGIneer Team",
    },
    docs_url="/docs",
    redoc_url="/redoc",
    openapi_tags=[
        {"name": "Documents", "description": "文档解析 — 上传、轮询、获取结构化结果"},
        {"name": "Auth", "description": "API Key 验证与状态查询"},
        {"name": "Knowledge", "description": "【内部】知识库管理"},
        {"name": "Preview", "description": "【内部】文件预览"},
        {"name": "Evals", "description": "【内部】评测集管理"},
        {"name": "SOPs", "description": "【内部】SOP 管理"},
        {"name": "Knowledge Graph", "description": "【内部】知识图谱管理"},
        {"name": "Dream Cycle", "description": "【内部】健康检查"},
    ],
)

@app.exception_handler(Exception)
async def global_exception_handler(request, exc):
    from angineer_core.base_utils import is_fatal_exception
    if is_fatal_exception(exc):
        raise
    import traceback as _tb
    _tb.print_exc()
    logger.error(f"未处理异常: {exc}", exc_info=True)
    from fastapi.responses import JSONResponse
    return JSONResponse(
        status_code=200,
        content={
            "query_id": f"q-{uuid.uuid4().hex[:12]}",
            "session_key": "",
            "intent": {},
            "answer": f"抱歉，服务处理出现异常：{type(exc).__name__}: {exc}",
            "citations": [],
            "retrieved_items": [],
            "sql": None,
            "fallback_used": False,
            "latency_ms": 0,
        },
    )

# Mount sub-routers
app.include_router(docs_router, prefix="/api/knowledge", tags=["Knowledge"])
app.include_router(preview_router, prefix="/api", tags=["Preview"])
app.include_router(evals_router, prefix="/api/evals", tags=["Evals"])

from sop_routes import sop_router
app.include_router(sop_router, prefix="/api/sops", tags=["SOPs"])

# sop_research_routes 已废弃 — 使用 /api/graph/* 替代

from graph_routes import graph_router
app.include_router(graph_router, prefix="/api/graph", tags=["Knowledge Graph"])

from dream_cycle_routes import dream_cycle_router
app.include_router(dream_cycle_router, prefix="/api/dream-cycle", tags=["Dream Cycle"])

from api_key_routes import router as api_key_router
app.include_router(api_key_router)

# v1 外部 API
from routes.v1 import router as v1_router
app.include_router(v1_router)

# Initialize SOP Loader (传入 SOP 根目录，包含 json/ 和 raw/)
SOP_BASE_DIR = os.path.join(ROOT_DIR, "data", "sops")
sop_loader = SopLoader(SOP_BASE_DIR)

# 允许的 CORS 来源（从环境变量读取，逗号分隔；默认仅允许本地前端）
_default_origins = "http://localhost:3005,http://localhost:3002,http://127.0.0.1:3005,http://127.0.0.1:3002,http://localhost,http://127.0.0.1,http://124.221.238.70"
_allowed_origins = [o.strip() for o in os.getenv("ALLOWED_ORIGINS", _default_origins).split(",") if o.strip()]

# Enable CORS for Vue frontend
app.add_middleware(
    CORSMiddleware,
    allow_origins=_allowed_origins,
    allow_methods=["*"],
    allow_headers=["*"],
    allow_credentials=False,
)

# v1 API Key 认证
from middleware.api_key_auth import APIKeyAuthMiddleware
app.add_middleware(APIKeyAuthMiddleware)

# --- Static Files Handling ---
FRONTEND_DIR = os.path.join(ROOT_DIR, "apps", "user-web")

@app.get("/")
async def read_index():
    """主页路由，返index.html"""
    index_path = os.path.join(FRONTEND_DIR, "index.html")
    if os.path.exists(index_path):
        return FileResponse(index_path)
    return {"error": "index.html not found"}

# 挂载静态文件目(例如 CSS/JS 等，如果有的
if os.path.exists(FRONTEND_DIR):
    app.mount("/frontend", StaticFiles(directory=FRONTEND_DIR), name="frontend")

# --- Data Models for API ---

class QueryRequest(BaseModel):
    """统一查询请求，支持 scene + id 会话池路由。"""
    query: str
    scene: str = "docs"
    session_id: Optional[str] = None
    library_id: str = "default"
    doc_ids: List[str] = Field(default_factory=list)
    inline_citations: List[Dict[str, Any]] = Field(default_factory=list)
    config: Optional[str] = None
    mode: Optional[str] = None
    history: List[Dict[str, Any]] = Field(default_factory=list)


# AI Chat 对话相关模型
class SteerRequest(BaseModel):
    """run 中途 steer 注入请求体。"""
    text: str


# --- API Endpoints ---

@app.get("/knowledge")
def list_knowledge():
    kb_data = {}
    for fpath in glob.glob("knowledge/*.json"):
        with open(fpath, "r", encoding="utf-8") as f:
            kb_data.update(json.load(f))
    return kb_data

@app.post("/knowledge/{file_name}")
def save_knowledge(file_name: str, data: Dict[str, Any]):
    # Ensure .json extension
    if not file_name.endswith(".json"):
        file_name += ".json"
    fpath = f"knowledge/{file_name}"
    with open(fpath, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    # Reload knowledge manager
    # knowledge_manager._load_knowledge()
    return {"status": "success"}

@app.get("/api/llm_configs")
def list_llm_configs():
    """获取可用 LLM 模型配置列表"""
    try:
        client = LLMClient()
        # 仅返回名称和模型，不返回 API Key 等敏感信
        configs = [{"name": c["name"], "model": c["model"], "configured": bool(c["api_key"])} for c in client.configs]
        # 将 ANGINEER_DEFAULT_MODEL 指定的默认模型排到最前面
        default_model = os.getenv("ANGINEER_DEFAULT_MODEL", "")
        if default_model:
            idx = next((i for i, c in enumerate(configs) if c["name"] == default_model), None)
            if idx is not None and idx > 0:
                configs.insert(0, configs.pop(idx))
        return configs
    except Exception as e:
        logger.error(f"获取 LLM 配置失败: {e}")
        raise HTTPException(status_code=500, detail=f"获取模型配置失败: {str(e)}")


@app.post("/api/chat/agent")
async def chat_agent_stream(request: QueryRequest, raw_request: Request):
    """Agent ????SSE??run/turn/tool ?? AgentEvent ?????

    ``scene`` ??? qa/complex ??``session_id`` ??????history/steer??
    """
    async def event_stream():
        try:
            session = get_agent_session(
                request.scene or "qa",
                request.session_id,
                library_id=request.library_id,
                doc_ids=request.doc_ids,
            )

            queue: asyncio.Queue = asyncio.Queue()

            def emit(event):
                queue.put_nowait(event)

            loop = asyncio.get_event_loop()
            intent_result = None
            try:
                sops = sop_loader.load_all() if sop_loader is not None else []
                intent_result = IntentClassifier(sops).classify_intent(
                    request.query,
                    config_name=request.config,
                    mode=request.mode or "instruct",
                )
            except Exception as exc:
                logger.warning("Agent 意图分级失败，按 scene 默认路由: %s", exc)
            config_factory = make_policy_config_factory(
                request.scene or "qa",
                request.library_id,
                request.doc_ids,
                intent_result=intent_result,
                sop_loader=sop_loader,
            )
            run_future = loop.run_in_executor(
                None,
                session.run,
                request.query,
                emit,
                config_factory,
            )

            while True:
                if await raw_request.is_disconnected():
                    session.cancel()
                    break
                try:
                    event = await asyncio.wait_for(queue.get(), timeout=0.2)
                except asyncio.TimeoutError:
                    if run_future.done():
                        break
                    continue
                yield f"data: {map_event_to_agent_frame(event)}\n\n"
                if event.type in ("run_end", "error"):
                    break
            await run_future

            yield "data: [DONE]\n\n"
        except Exception as e:
            logger.error(f"Agent ????? {e}")
            yield f"data: {json.dumps({'type': 'error', 'error': str(e)}, ensure_ascii=False)}\n\n"

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@app.post("/api/chat/agent/{run_id}/steer")
def steer_agent(run_id: str, request: SteerRequest):
    """run ???????steer ????? turn ?????"""
    session = find_session_by_run_id(run_id)
    if session is None:
        raise HTTPException(status_code=404, detail="run not found or already finished")
    session.steer(request.text)
    return {"status": "ok", "run_id": run_id}

if __name__ == "__main__":
    import uvicorn
    # 开发态启用热重载，确保新增路由和服务代码改动能被正在运行的后端拾取
    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=API_SERVER_PORT,
        app_dir=os.path.dirname(__file__),
        reload=True,
        reload_dirs=[
            os.path.dirname(__file__),
            os.path.join(SERVICES_DIR, "angineer-core", "src"),
            os.path.join(SERVICES_DIR, "sop-core", "src"),
            os.path.join(SERVICES_DIR, "docs-core", "src"),
            os.path.join(SERVICES_DIR, "geo-core", "src"),
            os.path.join(SERVICES_DIR, "engtools", "src"),
            os.path.join(SERVICES_DIR, "evals-core", "src"),
        ],
        # DredgeAI 以 5s 间隔轮询 /status，默认 keep-alive 超时（5s）会导致复用
        # 已被服务端关闭的连接而收到 RST（SocketException 10053），调大以规避。
        timeout_keep_alive=int(os.getenv("UVICORN_KEEP_ALIVE_TIMEOUT", "30")),
    )
