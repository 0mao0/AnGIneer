import os
import json
import glob
import subprocess
import asyncio
import time
import sys
import uuid
import tempfile
import threading
import logging
from typing import List, Dict, Any, Optional
from fastapi import FastAPI, HTTPException
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
from angineer_core.base_contracts import Step, SOP
from angineer_core import IntentClassifier, Dispatcher
from sop_core.sop_loader import SopLoader
from engtools.BaseTool import ToolRegistry, register_tool
# Import tools to ensure registration
from engtools import * 
import geo_core.GisTool
import engtools.KnowledgeTool
from knowledge_routes import knowledge_router, preview_router
from evals_routes import evals_router

app = FastAPI(title="AnGIneer API Bridge")

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
app.include_router(knowledge_router, prefix="/api/knowledge", tags=["Knowledge"])
app.include_router(preview_router, prefix="/api", tags=["Preview"])
app.include_router(evals_router, prefix="/api/evals", tags=["Evals"])

from sop_routes import sop_router
app.include_router(sop_router, prefix="/api/sops", tags=["SOPs"])

# Initialize SOP Loader (传入 SOP 根目录，包含 json/ 和 raw/)
SOP_BASE_DIR = os.path.join(ROOT_DIR, "data", "sops")
sop_loader = SopLoader(SOP_BASE_DIR)

# Enable CORS for Vue frontend
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# --- Static Files Handling ---
FRONTEND_DIR = os.path.join(ROOT_DIR, "apps", "web-console")

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


class SessionEntry(BaseModel):
    """服务端会话池条目，按 session_key 隔离对话上下文。"""
    session_key: str
    scene: str
    history: List[Dict[str, Any]] = Field(default_factory=list)
    last_active_at: float = 0.0


_SESSION_POOL: Dict[str, SessionEntry] = {}

_SESSION_POOL_MAX_SIZE = 200
_SESSION_POOL_TTL_SECONDS = 3600 * 2

_SESSION_LOCK = threading.RLock()


def _get_or_create_session(scene: str, session_id: Optional[str]) -> SessionEntry:
    with _SESSION_LOCK:
        key = f"{scene}:{session_id or 'default'}"
        entry = _SESSION_POOL.get(key)
        if entry:
            entry.last_active_at = time.time()
            return entry
        if len(_SESSION_POOL) >= _SESSION_POOL_MAX_SIZE:
            _evict_expired_sessions()
        entry = SessionEntry(session_key=key, scene=scene, last_active_at=time.time())
        _SESSION_POOL[key] = entry
        return entry


def _evict_expired_sessions() -> None:
    with _SESSION_LOCK:
        now = time.time()
        expired = [k for k, v in _SESSION_POOL.items() if now - v.last_active_at > _SESSION_POOL_TTL_SECONDS]
        for k in expired:
            del _SESSION_POOL[k]
        if len(_SESSION_POOL) >= _SESSION_POOL_MAX_SIZE:
            sorted_keys = sorted(_SESSION_POOL, key=lambda k: _SESSION_POOL[k].last_active_at)
            for k in sorted_keys[: len(sorted_keys) // 4]:
                del _SESSION_POOL[k]

class SOPUpdate(BaseModel):
    id: str
    description: str
    steps: List[Dict[str, Any]]

# AI Chat 对话相关模型
class ChatMessage(BaseModel):
    """聊天消息"""
    id: Optional[str] = None
    role: str  # 'user', 'assistant', 'system'
    content: str
    timestamp: Optional[int] = None
    images: Optional[List[str]] = None  # 多模态预留：base64 图片列表

class ChatContext(BaseModel):
    """扩展上下"""
    references: Optional[List[str]] = None  # 引用的规文档 ID

class ChatRequest(BaseModel):
    """AI 对话请求"""
    message: str  # 当前用户输入
    history: List[ChatMessage]  # 历史消息上下
    model: Optional[str] = None  # 使用的模
    mode: Optional[str] = 'chat'  # 对话模式: chat, reasoning, vision
    context: Optional[ChatContext] = None  # 扩展上下

class ChatStreamEvent(BaseModel):
    """流式响应事件"""
    type: str  # 'start', 'chunk', 'end', 'error'
    messageId: Optional[str] = None
    content: Optional[str] = None
    usage: Optional[Dict[str, int]] = None
    error: Optional[str] = None


# --- Global State for UI Tracking ---
# We'll use a simple global list to store execution logs for the frontend to poll
execution_trace = []


class TraceDispatcher(Dispatcher):
    """
    A specialized Dispatcher that records execution steps for the UI
    without modifying the original Dispatcher code.
    """
    def __init__(self, trace_list: list, config_name: str = None, mode: str = "instruct"):
        super().__init__(config_name=config_name, mode=mode)
        self.trace_list = trace_list

    def _execute_step(self, step: Step):
        step_trace = {
            "step_id": step.id,
            "step_name": step.name_zh or step.name, # Default to zh or legacy name
            "step_name_zh": step.name_zh or step.name,
            "step_name_en": step.name_en or step.name,
            "step_description_zh": step.description_zh or step.description,
            "step_description_en": step.description_en or step.description,
            "tool": step.tool,
            "status": "running",
            "inputs": {},
            "output": None,
            "error": None,
            "memory_snapshot": {}
        }
        self.trace_list.append(step_trace)
        
        # Resolve inputs (duplicated from original for trace capture)
        tool_inputs = {}
        for key, value in step.inputs.items():
            resolved_value = self.memory.resolve_value(value)
            tool_inputs[key] = resolved_value
        
        step_trace["inputs"] = tool_inputs
        
        try:
            # Determine Tool (Static or Auto)
            target_tool_name = step.tool
            if target_tool_name == "auto":
                detected_tool, detected_inputs = self._smart_select_tool(step, tool_inputs)
                if detected_tool:
                    target_tool_name = detected_tool
                    tool_inputs.update(detected_inputs)
                    step_trace["tool"] = f"auto -> {target_tool_name}" # Update trace
                    step_trace["inputs"] = tool_inputs # Update trace
                else:
                    raise ValueError("Auto-selection failed")

            # Call original logic but capture results
            # Note: We are re-implementing the execution part to capture trace
            # since the original doesn't have hooks.
            tool = ToolRegistry.get_tool(target_tool_name)
            if not tool:
                raise ValueError(f"Tool {target_tool_name} not found")
            
            run_kwargs = dict(tool_inputs)
            if self.config_name:
                run_kwargs["config_name"] = self.config_name
            if self.mode:
                run_kwargs["mode"] = self.mode
            result = tool.run(**run_kwargs)
            step_trace["output"] = result
            step_trace["status"] = "completed"
            
            # Record in original memory
            self._record_step(step, tool_inputs, result)
            step_trace["memory_snapshot"] = json.loads(json.dumps(self.memory.global_context, default=str))
            
        except Exception as e:
            step_trace["error"] = str(e)
            step_trace["status"] = "failed"
            self._record_step(step, tool_inputs, None, error=str(e))

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

@app.post("/chat")
def chat(request: QueryRequest):
    global execution_trace
    execution_trace = [] # Reset trace
    
    # 1. Load SOPs for Router (Dynamic from MD)
    sops = sop_loader.load_all()
    
    classifier = IntentClassifier(sops)
    route_result = classifier.route(request.query, config_name=request.config, mode=request.mode or "instruct")
    sop = route_result.sop
    args = route_result.args
    reason = route_result.reason
    
    if not sop:
        return {
            "sop_id": None,
            "response": None,
            "trace": [],
            "reason": reason
        }
    
    # 2. Execute with TraceDispatcher
    dispatcher = TraceDispatcher(execution_trace, config_name=request.config, mode=request.mode or "instruct")
    dispatcher.memory.add_chat_message("user", request.query)
    initial_context = {"user_query": request.query}
    initial_context.update(args)
    final_context = dispatcher.run_sop(sop, initial_context)
    
    return {
        "sop_id": sop.id,
        "sop_name_zh": sop.name_zh or sop.id,
        "sop_name_en": sop.name_en or sop.id,
        "args": args,
        "trace": execution_trace,
        "reason": reason,
        "final_context": final_context
    }

@app.post("/chat/stream")
def chat_stream(request: QueryRequest):
    def event_stream():
        try:
            yield json.dumps({"type": "routing"}) + "\n"

            # Load SOPs (Dynamic from MD)
            sops = sop_loader.load_all()

            classifier = IntentClassifier(sops)
            route_result = classifier.route(request.query, config_name=request.config, mode=request.mode or "instruct")
            sop = route_result.sop
            args = route_result.args
            reason = route_result.reason

            if not sop:
                yield json.dumps({"type": "nomatch"}) + "\n"
                return

            yield json.dumps({
                "type": "start",
                "sop_id": sop.id,
                "sop_name_zh": sop.name_zh or sop.id,
                "sop_name_en": sop.name_en or sop.id,
                "args": args,
                "reason": reason
            }) + "\n"

            trace_list: list = []
            dispatcher = TraceDispatcher(trace_list, config_name=request.config, mode=request.mode or "instruct")
            dispatcher.memory.add_chat_message("user", request.query)
            initial_context = {"user_query": request.query}
            initial_context.update(args)
            dispatcher.memory.update_context(initial_context)

            for step in sop.steps:
                dispatcher._execute_step(step)
                yield json.dumps({"type": "step", "step": trace_list[-1]}) + "\n"

            yield json.dumps({"type": "done", "final_context": dispatcher.memory.blackboard}) + "\n"
        except Exception as e:
            yield json.dumps({"type": "error", "error": str(e)}) + "\n"

    return StreamingResponse(event_stream(), media_type="application/x-ndjson")

@app.get("/api/llm_configs")
def list_llm_configs():
    """获取可用 LLM 模型配置列表"""
    try:
        client = LLMClient()
        # 仅返回名称和模型，不返回 API Key 等敏感信
        configs = [{"name": c["name"], "model": c["model"], "configured": bool(c["api_key"])} for c in client.configs]
        # 优先返回 Qwen3.6 私有模型作为默认模型
        qwen_index = next((i for i, c in enumerate(configs) if "Qwen3.6-35B-A3B" in c["name"]), None)
        if qwen_index is not None and qwen_index > 0:
            configs.insert(0, configs.pop(qwen_index))
        return configs
    except Exception as e:
        logger.error(f"获取 LLM 配置失败: {e}")
        raise HTTPException(status_code=500, detail=f"获取模型配置失败: {str(e)}")


@app.post("/api/chat")
async def chat_stream(request: ChatRequest):
    """
    AI 对话流式接口

    支持流式输出，前端通过 SSE 接收增量内容
    """
    async def event_stream():
        try:
            client = LLMClient()
            message_id = f"msg-{int(time.time() * 1000)}"

            # 发送开始事
            yield f"data: {json.dumps({'type': 'start', 'messageId': message_id}, ensure_ascii=False)}\n\n"

            # 构建消息列表
            messages = []

            # 添加历史消息
            for msg in request.history:
                if msg.role in ['user', 'assistant', 'system']:
                    messages.append({
                        "role": msg.role,
                        "content": msg.content
                    })

            # 添加当前用户消息
            messages.append({
                "role": "user",
                "content": request.message
            })

            # 调用流式对话
            full_content = ""
            prompt_tokens = 0
            completion_tokens = 0

            # 估算 prompt tokens
            for msg in messages:
                prompt_tokens += len(msg["content"]) // 2  # 简化估

            for token in client.chat_stream(
                messages=messages,
                model=request.model,
                mode=request.mode or "instruct"
            ):
                full_content += token
                completion_tokens += 1

                # 发送增量内
                yield f"data: {json.dumps({'type': 'chunk', 'content': token}, ensure_ascii=False)}\n\n"

            # 发送结束事
            yield f"data: {json.dumps({
                'type': 'end',
                'usage': {
                    'promptTokens': prompt_tokens,
                    'completionTokens': completion_tokens
                }
            }, ensure_ascii=False)}\n\n"

            yield "data: [DONE]\n\n"

        except Exception as e:
            logger.error(f"对话流错 {e}")
            yield f"data: {json.dumps({'type': 'error', 'error': str(e)}, ensure_ascii=False)}\n\n"

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no"  # 禁用 Nginx 缓冲
        }
    )

@app.get("/test_content/{test_id}")
def get_test_content(test_id: str):
    test_files = {
        "0": "test_00_llm_chat.py",
        "1": "test_01_tool_registration.py",
        "2": "test_02_intent_classifier.py",
        "3": "test_03_sop_analysis.py",
        "4": "test_04_tool_validity.py",
        "5": "test_05_full_execution_flow.py"
    }
    
    if test_id not in test_files:
        raise HTTPException(status_code=404, detail="Test not found")
    
    test_file = test_files[test_id]
    test_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "tests", test_file)
    
    try:
        with open(test_path, "r", encoding="utf-8") as f:
            return {"file": test_file, "content": f.read()}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/test_cases/{test_id}")
def get_test_cases(test_id: str):
    if test_id in ["0", "1", "2", "3", "4"]:
        try:
            import sys
            import importlib
            project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
            backend_dir = os.path.abspath(os.path.dirname(__file__))
            tests_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "tests"))
            for path_item in [project_root, backend_dir, tests_dir]:
                if path_item not in sys.path:
                    sys.path.append(path_item)
            
            module_map = {
                "0": "test_00_llm_chat",
                "1": "test_01_tool_registration",
                "2": "test_02_intent_classifier",
                "3": "test_03_sop_analysis",
                "4": "test_04_tool_validity"
            }
            
            module_name = module_map.get(test_id)
            if not module_name:
                return {"test_id": test_id, "cases": []}
                
            module = importlib.import_module(module_name)
            # Reload to ensure updates are reflected if using persistent process (optional but good for dev)
            importlib.reload(module)
            
            if hasattr(module, "SAMPLE_QUERIES"):
                return {"test_id": test_id, "cases": module.SAMPLE_QUERIES}
            else:
                return {"test_id": test_id, "cases": []}
                
        except ImportError as e:
            print(f"Import Error: {e}")
            return {"test_id": test_id, "cases": []}
        except Exception as e:
            print(f"Error loading test cases: {e}")
            return {"test_id": test_id, "cases": []}
            
    return {"test_id": test_id, "cases": []}

@app.get("/test/stream/02")
async def stream_test_02(query: str, config: str = None, mode: str = "instruct"):
    """
    Test 02 Streaming Execution Endpoint
    Provides real-time feedback on the Intent Classification process.
    """
    async def generate():
        try:
            # Step 1: SOP Check (Pre-loaded / Cache Check)
            yield json.dumps({"step": "sop_load", "status": "running", "msg": "正在检SOP 列表..."}) + "\n"
            await asyncio.sleep(0.3) # Visual pacing
            
            # Use the global sop_loader
            if not sop_loader.sops:
                sops = sop_loader.load_all()
            else:
                sops = sop_loader.sops
                
            yield json.dumps({"step": "sop_load", "status": "done", "msg": f"SOP 加载完成 ({len(sops)} 条)"}) + "\n"

            # Step 2: Validate SOPs (Quick sampling)
            yield json.dumps({"step": "sop_validate", "status": "running", "msg": "抽检 SOP 有效.."}) + "\n"
            await asyncio.sleep(0.2)
            required = ["math_sop", "code_review"]
            found_ids = [s.id for s in sops]
            missing = [r for r in required if r not in found_ids]
            if missing:
                 yield json.dumps({"step": "sop_validate", "status": "warning", "msg": f"缺少核心 SOP: {missing}"}) + "\n"
            else:
                 yield json.dumps({"step": "sop_validate", "status": "done", "msg": "核心 SOP 校验通过"}) + "\n"

            # Step 3: LLM Init
            yield json.dumps({"step": "llm_load", "status": "running", "msg": f"初始化意图分类器 (Model: {config or 'Default'}, Mode: {mode})..."}) + "\n"
            # Instantiate classifier
            classifier = IntentClassifier(sops)
            yield json.dumps({"step": "llm_load", "status": "done", "msg": "分类器就绪"}) + "\n"

            # Step 4: Inference
            yield json.dumps({"step": "inference", "status": "running", "msg": f"LLM 正在分析: {query[:20]}..."}) + "\n"
            
            # Run blocking route() in executor
            loop = asyncio.get_event_loop()
            start_time = asyncio.get_event_loop().time()
            
            # Use a wrapper to pass extra args
            def run_route():
                return classifier.route(query, config_name=config, mode=mode)
                
            route_result = await loop.run_in_executor(None, run_route)
            sop = route_result.sop
            args = route_result.args
            reason = route_result.reason
            duration = asyncio.get_event_loop().time() - start_time
            
            yield json.dumps({"step": "inference", "status": "done", "msg": f"推理完成 ({duration:.2f}s)"}) + "\n"

            # Step 5: Result
            sop_id = sop.id if sop else "None"
            result_data = {
                "sop_id": sop_id,
                "sop_name": sop.name_zh if sop else "Unknown",
                "args": args,
                "reason": reason,
                "raw_query": query,
                "inference_time_s": duration
            }
            yield json.dumps({"step": "result", "status": "done", "data": result_data}) + "\n"
            
        except Exception as e:
            yield json.dumps({"step": "error", "status": "failed", "msg": str(e)}) + "\n"

    return StreamingResponse(generate(), media_type="application/x-ndjson")

@app.get("/test/stream/03")
async def stream_test_03(query: str = None, config: str = None, mode: str = "instruct"):
    """返回测试接口占位流，避免无关测试代码阻塞后端启动。"""
    async def generate():
        yield json.dumps({
            "step": "disabled",
            "status": "done",
            "msg": "test/stream/03 暂时停用",
            "query": query,
            "config": config,
            "mode": mode,
        }) + "\n"

    return StreamingResponse(generate(), media_type="application/x-ndjson")

@app.get("/test/stream/04")
async def stream_test_04(query: str = None, config: str = None, mode: str = "instruct"):
    """返回测试接口占位流，避免无关测试代码阻塞后端启动。"""
    async def generate():
        yield json.dumps({
            "step": "disabled",
            "status": "done",
            "msg": "test/stream/04 暂时停用",
            "query": query,
            "config": config,
            "mode": mode,
        }) + "\n"

    return StreamingResponse(generate(), media_type="application/x-ndjson")

@app.get("/run_test/{test_id}")
def run_test(test_id: str, config: str = None, query: str = None, mode: str = "instruct"):
    # Map ID to filename
    test_files = {
        "0": "test_00_llm_chat.py",
        "1": "test_01_tool_registration.py",
        "2": "test_02_intent_classifier.py",
        "3": "test_03_sop_analysis.py",
        "4": "test_04_tool_validity.py",
        "5": "test_05_full_execution_flow.py"
    }
    
    filename = test_files.get(test_id)
    if not filename:
        return {"error": "Invalid Test ID"}
        
    fpath = os.path.join(os.path.dirname(__file__), "..", "tests", filename)
    
    # Environment variables for test
    env = os.environ.copy()
    env["PYTHONIOENCODING"] = "utf-8"
    if config:
        env["TEST_LLM_CONFIG"] = config
    if query:
        # Pass query as environment variable to the test script
        env["TEST_LLM_QUERY"] = query
    
    # Pass mode
    if mode:
        env["TEST_LLM_MODE"] = mode
    
    try:
        # Run unittest with python
        result = subprocess.run(
            ["python", fpath],
            capture_output=True,
            text=True,
            encoding="utf-8",
            env=env
        )
        return {
            "test_file": filename,
            "exit_code": result.returncode,
            "stdout": result.stdout,
            "stderr": result.stderr
        }
    except Exception as e:
        return {"error": str(e)}




# 将意图分类结果映射为检索器可识别的任务类型
@app.post("/api/query")
async def query(request: QueryRequest):
    """统一查询入口：委托 Dispatcher.dispatch() 执行完整链路。"""
    from angineer_core.dispatcher import Dispatcher

    started_at = time.time()
    query_id = f"q-{uuid.uuid4().hex[:12]}"

    try:
        session = _get_or_create_session(request.scene, request.session_id)
        session.history.append({"role": "user", "content": request.query})
    except Exception as e:
        logger.error(f"会话创建失败: {e}")
        session = None

    dispatcher = Dispatcher(
        config_name=request.config,
        mode=request.mode or "instruct",
    )
    result = dispatcher.dispatch(
        query=request.query,
        library_id=request.library_id,
        doc_ids=request.doc_ids or [],
        inline_citations=request.inline_citations or [],
        sop_loader=sop_loader,
    )

    result["query_id"] = query_id
    result["session_key"] = session.session_key if session else ""

    if session:
        session.history.append({"role": "assistant", "content": result.get("answer", "")})

    result["latency_ms"] = int((time.time() - started_at) * 1000)

    return result


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
    )
