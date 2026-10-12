"""angineer-core [server]：chat-api 薄壳（agent 编排 SSE + health）。

对外最小面（DredgeAI 验收口径，2026-10-12）：
- ``POST /api/chat/agent``  Agent SSE（AgentEvent 帧，帧带 ``frame_version``；含
  ``route_debug`` 首帧）
- ``GET  /health``

内部依赖可关：SOP 发布面 / chat-history / admin 会话鉴权均不依赖，缺之照常启动。
检索经 HTTP（``ANGINEER_DOCS_API_URL`` → 检索服务 8310）；``ANGINEER_DISABLE_LOCAL_FALLBACK=1``
可禁止本地回退（独立部署推荐，避免静默降级为空结果）。

鉴权（可选）：设 ``ANGINEER_API_TOKEN``（或 ``API_TOKEN``）后，除 ``/health`` 外要求
``X-API-Key`` 头（或 ``Authorization: Bearer <token>``）；未设则不做校验（回环自部署默认）。

启动：``uvicorn angineer_core.server:app --host 127.0.0.1 --port 8311``
"""
import asyncio
import hmac
import json
import logging
import os
import time
from datetime import datetime
from typing import Any, Dict, List, Optional

try:
    from fastapi import Depends, FastAPI, Header, HTTPException, Request
    from fastapi.middleware.cors import CORSMiddleware
    from fastapi.responses import StreamingResponse
    from pydantic import BaseModel, Field
except ImportError as exc:  # pragma: no cover - 安装提示
    raise ImportError(
        "angineer_core.server 需要 [server] extra（fastapi/uvicorn）。"
        "请安装：pip install 'angineer-core[server]'"
    ) from exc

from angineer_core import __version__ as _PKG_VERSION
from angineer_core.base_contracts import ScopeContext, normalize_library_ids
from angineer_core.docs_retrieval_client import local_fallback_disabled
from angineer_core.route_pre import (
    decision_intent_result,
    fallback_note_event,
    fire_speculative_first_search,
    route_debug_event,
    route_parallel_enabled,
    route_pre_enabled,
    route_request,
)
from angineer_core.server.http_ports import register_http_ports
from angineer_core.server.session import (
    _classify_intent_blocking,
    get_agent_session,
    load_nodes_for,
    make_config_factory,
)

# root 日志兜底（同 aichat-api）：库代码普遍用 logging.getLogger(__name__) 且不设
# handler，不配 root 会让日志落 lastResort（stderr 裸格式）甚至静默丢失——2026-10-12
# DredgeAI 试用即因壳没配 logging 误判「警告没落日志」。basicConfig 幂等。
logging.basicConfig(
    level=os.getenv("ANGINEER_LOG_LEVEL", "INFO").upper(),
    format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)

logger = logging.getLogger("angineer_core.server")

_PROCESS_STARTED_AT = datetime.now().isoformat()


class ChatRequest(BaseModel):
    """统一查询请求（与内部服务 /api/chat/agent 请求体同构；inline_citations 等
    仅运营面消费的字段本壳不声明——pydantic 默认忽略多余键，客户端可原样发送）。"""

    query: str
    scene: str = "docs"
    session_id: Optional[str] = None
    library_id: str = "default"
    # 多库勾选：空=单库（library_id），非空=集合；服务端 normalize 后首项=主库
    library_ids: List[str] = Field(default_factory=list)
    doc_ids: List[str] = Field(default_factory=list)
    config: Optional[str] = None
    mode: Optional[str] = None


def _sse(obj: Dict[str, Any]) -> str:
    return f"data: {json.dumps(obj, ensure_ascii=False)}\n\n"


def _env_token() -> str:
    return (os.getenv("ANGINEER_API_TOKEN") or os.getenv("API_TOKEN") or "").strip()


def _token_guard(
    x_api_key: str = Header(default=""), authorization: str = Header(default="")
) -> None:
    """可选 API Token 门（env 未设则放行；/health 不挂本依赖）。"""
    token = _env_token()
    if not token:
        return
    supplied = (x_api_key or "").strip()
    if not supplied and (authorization or "").lower().startswith("bearer "):
        supplied = authorization[7:].strip()
    if not hmac.compare_digest(supplied, token):
        raise HTTPException(status_code=401, detail="invalid API token")


async def _classify_offloaded(query: str, config_name: Optional[str] = None, mode: str = "instruct"):
    """意图分类卸载到默认 executor，避免阻塞 SSE 事件循环；失败降级为 None。"""
    loop = asyncio.get_running_loop()
    try:
        return await loop.run_in_executor(
            None, _classify_intent_blocking, query, config_name, mode
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("Agent 意图分级失败，按 scene 默认路由: %s", exc)
        return None


def _empty_scope_warning(library_ids: List[str]) -> Optional[str]:
    """文档范围为空时显式提示（薄版：给库 id，不做库名映射）。

    否则检索恒为 0 条，模型会把「检索拿不到东西」说成「知识库里没有证据」
    （2026-09-11 内部服务排查结论，同语义保留）。同步函数——调用方须卸载到线程。
    """
    try:
        probe = load_nodes_for(library_ids, [])
        if probe:
            return None
        label = "、".join(f"「{x}」" for x in library_ids)
        return (
            f"知识库{label}当前没有可检索的文档（或检索服务尚未就绪），"
            "本次回答可能不准确，稍后重试通常可恢复。"
        )
    except Exception:  # noqa: BLE001
        return None


def create_app() -> FastAPI:
    app = FastAPI(
        title="AnGIneer Chat API (standalone shell)",
        description="独立宿主壳：agent 编排 SSE（angineer-core [server] extra）。",
        version=_PKG_VERSION,
    )

    @app.on_event("startup")
    def _register_http_ports_on_startup() -> None:
        """HTTP 端口适配器（六端口，见 http_ports.py）：启动时把进程内端口的 HTTP
        等价物注册进端口注册表——未配 ANGINEER_DOCS_API_URL 或 ANGINEER_HTTP_PORTS=0
        时自动跳过（保持原「端口未注册」降级语义）。幂等。放启动事件而非导入期：
        「导入壳模块」这种无请求场景不应产生全局副作用。"""
        register_http_ports()

    _allowed_origins = [
        o.strip()
        for o in os.getenv("ALLOWED_ORIGINS", "*").split(",")
        if o.strip()
    ]
    app.add_middleware(
        CORSMiddleware,
        allow_origins=_allowed_origins,
        allow_methods=["*"],
        allow_headers=["*"],
        allow_credentials=False,
    )

    @app.post("/api/chat/agent", dependencies=[Depends(_token_guard)])
    async def chat_agent_stream(request: ChatRequest, raw_request: Request):
        """Agent SSE：run/turn/tool 事件按 AgentEvent 帧输出。"""
        # 归一化（集合首项=主库；与内部服务同规则）——本壳无鉴权面，不做绑定/截断
        library_ids = normalize_library_ids(request.library_ids or None, request.library_id or "")
        request.library_id = library_ids[0]
        doc_ids = list(request.doc_ids or [])

        async def event_stream():
            try:
                session = get_agent_session(request.scene or "qa", request.session_id)
                loop = asyncio.get_running_loop()

                # 文档范围为空时显式提示（探针走 HTTP，卸载线程执行，勿阻塞事件循环）
                warning_msg = await loop.run_in_executor(
                    None, _empty_scope_warning, library_ids
                )
                if warning_msg:
                    yield _sse({"type": "warning", "message": warning_msg})

                queue: asyncio.Queue = asyncio.Queue()

                def emit(event):
                    queue.put_nowait(event)

                # 上一次 run 可能仍在收尾（客户端 abort 只断开连接）：等空闲而非把
                # 内部错误丢给用户（单飞保护 RuntimeError 语义同内部服务）
                if not await loop.run_in_executor(None, session.wait_for_idle, 30):
                    yield _sse({"type": "error", "error": "上一次生成尚未结束，请稍后重试"})
                    return

                # 阶段帧：分类自此开始（前端「意图理解」覆盖真实分类等待）；
                # ts=请求起点墙钟（前端折叠头「总耗时」锚点）
                yield _sse({"type": "stage", "stage": "classify", "ts": time.time()})

                # F3 共享 allocator：请求级创建、预检与主路共用同一实例
                shared_allocator = None
                if route_pre_enabled():
                    if route_parallel_enabled():
                        try:
                            from angineer_core.agent_tools import MarkerAllocator

                            shared_allocator = MarkerAllocator()
                            fire_speculative_first_search(
                                request.query,
                                request.library_id,
                                doc_ids,
                                load_nodes=lambda: load_nodes_for(library_ids, doc_ids),
                                has_history=bool(getattr(session, "history", None)),
                                marker_allocator=shared_allocator,
                                library_ids=library_ids,
                            )
                        except Exception:  # noqa: BLE001
                            logger.debug("赌博式预检未发起（忽略）", exc_info=True)
                    decision = await route_request(
                        query=request.query,
                        scene=request.scene or "qa",
                        library_id=request.library_id,
                        library_ids=library_ids,
                        doc_ids=doc_ids,
                        config_name=request.config,
                        mode=request.mode or "instruct",
                        classify=_classify_offloaded,
                    )
                    queue.put_nowait(route_debug_event(decision))
                    if decision.fallback:
                        queue.put_nowait(fallback_note_event())
                    intent_result = decision_intent_result(decision)
                    scope = decision.scope
                    route_debug = decision.route_debug
                else:
                    intent_result = await _classify_offloaded(
                        request.query,
                        config_name=request.config,
                        mode=request.mode or "instruct",
                    )
                    scope = ScopeContext(library_ids=list(library_ids), doc_ids=doc_ids)
                    route_debug = None

                config_factory = make_config_factory(
                    request.scene or "qa",
                    scope=scope,
                    intent_result=intent_result,
                    query=request.query,
                    route_debug=route_debug,
                    marker_allocator=shared_allocator,
                )
                run_future = loop.run_in_executor(
                    None, session.run, request.query, emit, config_factory
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
                    frame = json.loads(event.model_dump_json())
                    # 契约冻结：帧协议版本（客户端 transport 据此判兼容）
                    frame["frame_version"] = 1
                    yield _sse(frame)
                    if event.type in ("run_end", "error"):
                        break
                # worker 异常经此上浮（queue 未收到 run_end 时由外层 except 转 error 帧）
                await run_future

                yield "data: [DONE]\n\n"
            except Exception as e:  # noqa: BLE001
                logger.error("Agent 对话错误: %s", e)
                yield _sse({"type": "error", "error": str(e)})

        return StreamingResponse(
            event_stream(),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
                "X-Accel-Buffering": "no",
                "X-Chat-Frame-Version": "1",
            },
        )

    @app.get("/health")
    def health():
        docs_url = (os.getenv("ANGINEER_DOCS_API_URL") or "").strip()
        return {
            "service": "chat-api",
            "status": "ok",
            "version": _PKG_VERSION,
            "started_at": _PROCESS_STARTED_AT,
            "pid": os.getpid(),
            "retrieval": {
                "configured": bool(docs_url),
                "base_url": docs_url or None,
                "local_fallback_disabled": local_fallback_disabled(),
            },
            "auth": {"token_required": bool(_env_token())},
        }

    return app


app = create_app()
