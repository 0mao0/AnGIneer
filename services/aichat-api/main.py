"""aichat-api — AI 问答（AgentSession SSE）、模型配置、SOP、Evals 与 DreamCycle。"""
import os
import sys
import json
import asyncio
import uuid
import logging
from pathlib import Path
from typing import List, Dict, Any, Optional

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

ROOT_DIR = Path(__file__).resolve().parent.parent.parent
SERVICES_DIR = ROOT_DIR / "services"

for pkg in (
    "ai-inference", "angineer-core", "sop-core", "docs-core",
    "geo-core", "engtools", "evals-core", "tree-core",
):
    sys.path.insert(0, str(SERVICES_DIR / pkg / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from ai_inference.llm_client import LLMClient
from angineer_core import IntentClassifier
from chat_agent import (
    find_session_by_run_id,
    get_agent_session,
    make_policy_config_factory,
    map_event_to_agent_frame,
)
from sop_core.sop_loader import SopLoader
from engtools import *
import geo_core.GisTool
import engtools.KnowledgeTool
from sop_routes import sop_router
from evals_routes import evals_router
from dream_cycle_routes import dream_cycle_router
from middleware.api_key_auth import APIKeyAuthMiddleware

app = FastAPI(
    title="AnGIneer AIChat API",
    description="AI 问答 API：Agent 多轮会话、SSE 流式回答、引用与思考步骤。",
    version="0.1.0",
    docs_url="/docs",
    redoc_url="/redoc",
)


@app.exception_handler(Exception)
async def global_exception_handler(request, exc):
    """保留原 api-server 的全局异常处理，保持 chat 响应形状。"""
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


SOP_BASE_DIR = os.path.join(str(ROOT_DIR), "data", "sops")
sop_loader = SopLoader(SOP_BASE_DIR)

_default_origins = "http://localhost:3005,http://localhost:3002,http://127.0.0.1:3005,http://127.0.0.1:3002,http://localhost,http://127.0.0.1"
_allowed_origins = [o.strip() for o in os.getenv("ALLOWED_ORIGINS", _default_origins).split(",") if o.strip()]

app.add_middleware(
    CORSMiddleware,
    allow_origins=_allowed_origins,
    allow_methods=["*"],
    allow_headers=["*"],
    allow_credentials=False,
)

# 任务 2.4 后中间件带 scope；按决策仅校验 /api/v1/*（aichat-api 当前无 /api/v1 路由，中间件实际不拦截）
app.add_middleware(APIKeyAuthMiddleware, scope="chat")

app.include_router(sop_router, prefix="/api/sops", tags=["SOPs"])
app.include_router(evals_router, prefix="/api/evals", tags=["Evals"])
app.include_router(dream_cycle_router, prefix="/api/dream-cycle", tags=["Dream Cycle"])


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


class SteerRequest(BaseModel):
    """run 中途 steer 注入请求体。"""
    text: str


@app.get("/api/llm_configs")
def list_llm_configs():
    """获取可用 LLM 模型配置列表。"""
    try:
        client = LLMClient()
        configs = [{"name": c["name"], "model": c["model"], "configured": bool(c["api_key"])} for c in client.configs]
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
    """Agent SSE：run/turn/tool 事件按 AgentEvent 帧输出。"""
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
            logger.error(f"Agent 对话错误: {e}")
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
    """run 中途 steer 注入，下一 turn 生效。"""
    session = find_session_by_run_id(run_id)
    if session is None:
        raise HTTPException(status_code=404, detail="run not found or already finished")
    session.steer(request.text)
    return {"status": "ok", "run_id": run_id}


@app.get("/health")
def health():
    return {"service": "aichat-api", "status": "ok"}


if __name__ == "__main__":
    import uvicorn

    with open(ROOT_DIR / "apps" / "shared" / "ports.json", "r", encoding="utf-8") as pf:
        AICHAT_API_PORT = int(json.load(pf)["aichatApiPort"])
    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=AICHAT_API_PORT,
        app_dir=str(Path(__file__).resolve().parent),
        reload=True,
        reload_dirs=[
            str(Path(__file__).resolve().parent),
            str(SERVICES_DIR / "angineer-core" / "src"),
            str(SERVICES_DIR / "ai-inference" / "src"),
            str(SERVICES_DIR / "sop-core" / "src"),
            str(SERVICES_DIR / "evals-core" / "src"),
            str(SERVICES_DIR / "engtools" / "src"),
        ],
    )
