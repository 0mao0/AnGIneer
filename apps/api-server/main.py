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
from datetime import datetime
from typing import List, Dict, Any, Optional
from fastapi import FastAPI, HTTPException, UploadFile, File as FastAPIFile, Form
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

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

# Import logic from packages
from angineer_core.infra.llm_client import LLMClient
from angineer_core.standard.context_models import Step, SOP
from angineer_core.core import IntentClassifier, Dispatcher
from sop_core.sop_loader import SopLoader
from engtools.BaseTool import ToolRegistry, register_tool
# Import tools to ensure registration
from engtools import * 
import geo_core.GisTool
import engtools.KnowledgeTool
from knowledge_routes import knowledge_router, preview_router

app = FastAPI(title="AnGIneer API Bridge")

# Mount sub-routers
app.include_router(knowledge_router, prefix="/api/knowledge", tags=["Knowledge"])
app.include_router(preview_router, prefix="/api", tags=["Preview"])

# Initialize SOP Loader
SOP_DIR = os.path.join(ROOT_DIR, "data", "sops", "raw")
sop_loader = SopLoader(SOP_DIR)

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
    query: str
    config: Optional[str] = None
    mode: Optional[str] = None

class SOPUpdate(BaseModel):
    id: str
    description: str
    steps: List[Dict[str, Any]]

class KnowledgeUpdate(BaseModel):
    data: Dict[str, Any]

class KnowledgeLibraryCreate(BaseModel):
    library_id: str
    name: str
    description: Optional[str] = ''

class KnowledgeNodeCreate(BaseModel):
    title: str
    node_type: str
    library_id: Optional[str] = 'default'
    parent_id: Optional[str] = None
    visible: Optional[bool] = True
    sort_order: Optional[int] = 0

class KnowledgeNodeUpdate(BaseModel):
    title: Optional[str] = None
    parent_id: Optional[str] = None
    visible: Optional[bool] = None
    sort_order: Optional[int] = None


class KnowledgeStrategyUpdate(BaseModel):
    strategy: str

class KnowledgeStructuredIndexRequest(BaseModel):
    library_id: str
    doc_id: str
    strategy: Optional[str] = 'doc_blocks_graph_v1'

class KnowledgeDocumentUpdate(BaseModel):
    content: str


class KnowledgeDocumentBlockUpdate(BaseModel):
    plain_text: Optional[str] = None
    math_content: Optional[str] = None
    table_html: Optional[str] = None
    title: Optional[str] = None
    caption: Optional[str] = None
    footnote: Optional[str] = None
    parent_block_uid: Optional[str] = None
    derived_title_level: Optional[int] = None
    merge_into_block_uid: Optional[str] = None


class KnowledgeDocumentBatchBlockOperation(BaseModel):
    operation: str
    blockIds: List[str]
    targetBlockId: Optional[str] = None
    splitSegments: Optional[List[Dict[str, Any]]] = None
    levelDelta: Optional[int] = None
    targetLevel: Optional[int] = None


# 读取知识库评测题集，并按需排除 SQL 题目
def _load_knowledge_eval_questions(include_sql: bool = False, dataset_id: Optional[str] = None) -> List[Dict[str, Any]]:
    from docs_core.evals.dataset_loader import load_eval_questions

    questions = load_eval_questions(dataset_id=dataset_id)
    if include_sql:
        return questions
    return [row for row in questions if str(row.get("task_type") or "") != "analytic_sql"]


# 返回前端可展示的评测题库列表
def _load_knowledge_eval_datasets() -> List[Dict[str, Any]]:
    from docs_core.evals.dataset_loader import list_eval_datasets

    datasets = list_eval_datasets()
    return [
        {
            "dataset_id": str(row.get("dataset_id") or ""),
            "title": str(row.get("title") or ""),
            "description": str(row.get("description") or ""),
            "schema_version": str(row.get("schema_version") or ""),
            "version": str(row.get("version") or ""),
            "library_id": str(row.get("library_id") or ""),
            "question_count": int(row.get("question_count") or 0),
            "visible_question_count": int(row.get("visible_question_count") or 0),
            "sql_question_count": int(row.get("sql_question_count") or 0),
        }
        for row in datasets
        if row.get("dataset_id")
    ]


# 组装知识库评测运行结果，便于前端直接展示逐题状态与汇总分数
def _build_knowledge_eval_payload(dataset_id: Optional[str] = None) -> Dict[str, Any]:
    from docs_core.evals.eval_reporter import build_eval_suite_report

    all_questions = _load_knowledge_eval_questions(include_sql=True, dataset_id=dataset_id)
    visible_questions = [row for row in all_questions if str(row.get("task_type") or "") != "analytic_sql"]
    question_map = {
        str(row.get("question_id") or ""): row
        for row in all_questions
        if row.get("question_id")
    }
    report = build_eval_suite_report(dataset_id=dataset_id)
    available_datasets = _load_knowledge_eval_datasets()
    selected_dataset = next(
        (item for item in available_datasets if str(item.get("dataset_id") or "") == str(dataset_id or "")),
        None,
    )

    answer_report = dict(report.get("answer") or {})
    answer_details = []
    for detail in list(answer_report.get("details") or []):
        question = question_map.get(str(detail.get("question_id") or ""), {})
        answer_details.append({
            **detail,
            "question": question.get("question", ""),
            "difficulty": question.get("difficulty", ""),
            "tags": list(question.get("tags") or []),
            "gold_answer": str((question.get("answer") or {}).get("gold_answer") or ""),
            "thought_process": str(question.get("thought_process") or ""),
        })
    answer_report["details"] = answer_details

    retrieval_report = dict(report.get("retrieval") or {})
    retrieval_details = []
    for detail in list(retrieval_report.get("details") or []):
        question = question_map.get(str(detail.get("question_id") or ""), {})
        retrieval_details.append({
            **detail,
            "question": question.get("question", ""),
            "difficulty": question.get("difficulty", ""),
            "tags": list(question.get("tags") or []),
        })
    retrieval_report["details"] = retrieval_details

    text2sql_report = dict(report.get("text2sql") or {})
    text2sql_details = []
    for detail in list(text2sql_report.get("details") or []):
        question = question_map.get(str(detail.get("question_id") or ""), {})
        text2sql_details.append({
            **detail,
            "question": question.get("question", ""),
            "difficulty": question.get("difficulty", ""),
            "tags": list(question.get("tags") or []),
        })
    text2sql_report["details"] = text2sql_details

    return {
        "generated_at": datetime.now().isoformat(),
        "available_datasets": available_datasets,
        "selected_dataset": selected_dataset,
        "questions": [
            {
                "question_id": str(row.get("question_id") or ""),
                "question": str(row.get("question") or ""),
                "task_type": str(row.get("task_type") or ""),
                "difficulty": str(row.get("difficulty") or ""),
                "tags": list(row.get("tags") or []),
                "dataset_id": str(row.get("dataset_id") or ""),
                "dataset_title": str(row.get("dataset_title") or ""),
                "gold_answer": str((row.get("answer") or {}).get("gold_answer") or ""),
                "thought_process": str(row.get("thought_process") or ""),
            }
            for row in visible_questions
            if row.get("question_id") and row.get("question")
        ],
        "report": {
            **report,
            "answer": answer_report,
            "retrieval": retrieval_report,
            "text2sql": text2sql_report,
        },
    }


class KnowledgeEvalRunRequest(BaseModel):
    dataset_id: Optional[str] = None

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


def _extract_structured_items_from_markdown(markdown_text: str) -> List[Dict[str, Any]]:
    from docs_core.ingest.store.assets_file_store import extract_structured_items_from_markdown
    return extract_structured_items_from_markdown(markdown_text)


def _build_structured_index_for_doc(library_id: str, doc_id: str, strategy: str = 'doc_blocks_graph_v1') -> Dict[str, Any]:
    if strategy != 'doc_blocks_graph_v1':
        raise ValueError(f'Unsupported strategy: {strategy}')
    from docs_core.ingest.store.assets_file_store import build_structured_index_for_doc
    return build_structured_index_for_doc(library_id, doc_id, strategy)

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

@app.get("/sops")
def list_sops():
    # Load dynamically from MD files
    sops = sop_loader.load_all()
    # Convert to dict for JSON response
    return [sop.dict() for sop in sops]

@app.post("/sops")
def save_sop(sop: SOPUpdate):
    # For now, we only support reading MD files in this new mode.
    # Editing MD files via this API would require mapping JSON structure back to MD text,
    # which is complex. For now, we return error or disable.
    raise HTTPException(status_code=501, detail="SOP modification via JSON API is not supported in Markdown-only mode.")

@app.delete("/sops/{sop_id}")
def delete_sop(sop_id: str):
    fpath = os.path.join(SOP_DIR, f"{sop_id}.md")
    if os.path.exists(fpath):
        os.remove(fpath)
        return {"status": "success"}
    raise HTTPException(status_code=404, detail="SOP not found")

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
    sop, args, reason = classifier.route(request.query, config_name=request.config, mode=request.mode or "instruct")
    
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
    final_context = dispatcher.run(sop, initial_context)
    
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
            sop, args, reason = classifier.route(request.query, config_name=request.config, mode=request.mode or "instruct")

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
                
            sop, args, reason = await loop.run_in_executor(None, run_route)
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

# --- Knowledge Base API Endpoints ---

@app.get("/api/knowledge/libraries")
def list_knowledge_libraries():
    """获取知识库列"""
    from docs_core.knowledge_service import knowledge_service
    return knowledge_service.list_libraries()

@app.post("/api/knowledge/libraries")
def create_knowledge_library(request: KnowledgeLibraryCreate):
    """创建知识"""
    from docs_core.knowledge_service import knowledge_service
    library = knowledge_service.create_library(request.library_id, request.name, request.description)
    return library

@app.get("/api/knowledge/libraries/{library_id}")
def get_knowledge_library(library_id: str):
    """获取知识"""
    from docs_core.knowledge_service import knowledge_service
    library = knowledge_service.get_library(library_id)
    if not library:
        raise HTTPException(status_code=404, detail="Library not found")
    return library

@app.get("/api/knowledge/nodes")
def list_knowledge_nodes(library_id: str = 'default', visible: bool = False):
    """获取知识库节点列"""
    from docs_core.knowledge_service import knowledge_service
    return knowledge_service.list_nodes(library_id, visible)

@app.post("/api/knowledge/nodes")
def create_knowledge_node(request: KnowledgeNodeCreate):
    """创建知识库节"""
    from docs_core.knowledge_service import KnowledgeNode, knowledge_service
    parent_id = request.parent_id
    # 统一处理根节点标
    if not parent_id or parent_id in ['', 'undefined', '__root__', 'null', 'None']:
        normalized_parent_id = None
    else:
        normalized_parent_id = parent_id

    if normalized_parent_id:
        parent_node = knowledge_service.get_node(normalized_parent_id)
        if not parent_node:
            raise HTTPException(status_code=400, detail=f"Parent node {normalized_parent_id} not found")
        if parent_node.type != 'folder':
            raise HTTPException(status_code=400, detail="Parent node must be a folder")
    
    node = KnowledgeNode(
        id=f'node-{uuid.uuid4().hex[:8]}',
        title=request.title,
        type=request.node_type,
        library_id=request.library_id or 'default',
        parent_id=normalized_parent_id,
        visible=request.visible if request.visible is not None else True,
        sort_order=request.sort_order if request.sort_order is not None else 0
    )
    return knowledge_service.create_node(node)

@app.patch("/api/knowledge/nodes/{node_id}")
def update_knowledge_node(node_id: str, request: KnowledgeNodeUpdate):
    """更新知识库节"""
    from docs_core.knowledge_service import knowledge_service
    import logging
    
    # 获取原始节点
    current_node = knowledge_service.get_node(node_id)
    if not current_node:
        raise HTTPException(status_code=404, detail=f"Node {node_id} not found")
        
    kwargs = {}
    if request.title is not None:
        kwargs['title'] = request.title
        
    if request.parent_id is not None:
        parent_id = request.parent_id
        # 统一处理根节点标
        # 前端可能'', 'undefined', '__root__', 'null' 
        if not parent_id or parent_id in ['', 'undefined', '__root__', 'null', 'None']:
            normalized_parent_id = None
        else:
            normalized_parent_id = parent_id
            
        # 校验新父节点
        if normalized_parent_id:
            parent_node = knowledge_service.get_node(normalized_parent_id)
            if not parent_node:
                raise HTTPException(status_code=400, detail=f"Parent node {normalized_parent_id} not found")
            if parent_node.type != 'folder':
                raise HTTPException(status_code=400, detail="Parent node must be a folder")
            if normalized_parent_id == node_id:
                raise HTTPException(status_code=400, detail="Node cannot be its own parent")
                
            # 循环移动校验
            parent_map = {node.id: node.parent_id for node in knowledge_service.nodes}
            curr = normalized_parent_id
            visited = {node_id}
            while curr:
                if curr in visited:
                    raise HTTPException(status_code=400, detail="Cannot move node into its own descendant (circular move)")
                visited.add(curr)
                curr = parent_map.get(curr)
        
        kwargs['parent_id'] = normalized_parent_id
        
    if request.visible is not None:
        kwargs['visible'] = request.visible
        
    if request.sort_order is not None:
        kwargs['sort_order'] = max(0, int(request.sort_order))
        
    try:
        node = knowledge_service.update_node(node_id, **kwargs)
        return node
    except Exception as e:
        logging.error(f"Failed to update node {node_id}: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Database update failed: {str(e)}")

@app.get("/api/knowledge/nodes/{node_id}/delete-preview")
def get_knowledge_node_delete_preview(node_id: str):
    """获取删除节点前的影响范围预览"""
    from docs_core.knowledge_service import knowledge_service
    preview = knowledge_service.get_delete_preview(node_id)
    if not preview:
        raise HTTPException(status_code=404, detail="Node not found")
    return preview

@app.delete("/api/knowledge/nodes/{node_id}")
def delete_knowledge_node(node_id: str):
    """删除知识库节"""
    from docs_core.knowledge_service import knowledge_service
    success = knowledge_service.delete_node(node_id)
    if not success:
        raise HTTPException(status_code=404, detail="Node not found")
    return {"status": "success"}

@app.post("/api/knowledge/upload")
async def upload_document(
    library_id: str = Form(...),
    file: UploadFile = FastAPIFile(...),
    parent_id: Optional[str] = Form(None)
):
    """上传文档到知识库"""
    from docs_core.knowledge_service import KnowledgeNode, knowledge_service
    from docs_core.ingest.store.assets_file_store import file_storage
    from datetime import datetime
    allowed_extensions = {'.pdf', '.doc', '.docx', '.md'}
    ext = os.path.splitext(file.filename or '')[1].lower()
    if ext not in allowed_extensions:
        raise HTTPException(status_code=400, detail=f"Unsupported file type: {ext or 'unknown'}")
    if parent_id:
        parent_node = knowledge_service.get_node(parent_id)
        if not parent_node:
            raise HTTPException(status_code=400, detail="Parent node not found")
        if parent_node.type != 'folder':
            raise HTTPException(status_code=400, detail="Parent node must be folder")

    # 生成文档ID
    doc_id = f"doc-{uuid.uuid4().hex[:8]}"

    # 读取文件内容
    content = await file.read()

    # 保存源文
    file_path = file_storage.save_source_file(library_id, doc_id, content, file.filename)

    # 创建知识库节
    node = KnowledgeNode(
        id=doc_id,
        title=file.filename,
        type='document',
        parent_id=parent_id,
        visible=True,
        library_id=library_id,
        file_path=file_path,
        status='pending',
        parse_progress=0,
        parse_stage='pending',
        parse_error=None,
        parse_task_id=None,
        created_at=datetime.now(),
        updated_at=datetime.now()
    )
    knowledge_service.create_node(node)

    return {
        "status": "success",
        "doc_id": doc_id,
        "file_path": file_path,
        "storage": file_storage.get_doc_manifest(library_id, doc_id),
        "node": node
    }


@app.get("/api/knowledge/parse/tasks/{task_id}")
def get_parse_task(task_id: str):
    """获取解析任务状"""
    from docs_core.knowledge_service import knowledge_service
    task = knowledge_service.get_parse_task(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    return task


@app.get("/api/knowledge/strategies/{doc_id}")
def get_doc_strategy(doc_id: str):
    """获取文档策略"""
    from docs_core.knowledge_service import knowledge_service
    node = knowledge_service.get_node(doc_id)
    if not node:
        raise HTTPException(status_code=404, detail="Document not found")
    return {"doc_id": doc_id, "strategy": node.strategy}


@app.put("/api/knowledge/strategies/{doc_id}")
def set_doc_strategy(doc_id: str, request: KnowledgeStrategyUpdate):
    """设置文档策略"""
    from docs_core.knowledge_service import knowledge_service
    strategy = request.strategy
    allowed = {'doc_blocks_graph_v1'}
    if strategy not in allowed:
        raise HTTPException(status_code=400, detail="Unsupported strategy")
    node = knowledge_service.update_node(doc_id, strategy=strategy)
    if not node:
        raise HTTPException(status_code=404, detail="Document not found")
    return {"doc_id": doc_id, "strategy": strategy}


@app.post("/api/knowledge/structured/index")
def build_structured_index(request: KnowledgeStructuredIndexRequest):
    """构建结构化索"""
    from docs_core.knowledge_service import knowledge_service
    doc_id = request.doc_id
    library_id = request.library_id
    strategy = request.strategy or 'doc_blocks_graph_v1'
    node = knowledge_service.get_node(doc_id)
    if not node:
        raise HTTPException(status_code=404, detail="Document not found")
    allowed = {'doc_blocks_graph_v1'}
    if strategy not in allowed:
        raise HTTPException(status_code=400, detail="Unsupported strategy")
    try:
        result = _build_structured_index_for_doc(library_id, doc_id, strategy)
        knowledge_service.update_node(
            doc_id,
            strategy=strategy,
            parse_stage='structured_indexed',
            parse_error=None
        )
        return {"status": "success", "doc_id": doc_id, "strategy": strategy, **result}
    except Exception as error:
        knowledge_service.update_node(doc_id, parse_error=str(error))
        raise HTTPException(status_code=500, detail=f"Build structured index failed: {str(error)}")


@app.get("/api/knowledge/evals/datasets")
def list_knowledge_eval_datasets():
    """获取知识库评测题库列表"""
    try:
        return {"datasets": _load_knowledge_eval_datasets()}
    except Exception as error:
        raise HTTPException(status_code=500, detail=f"Load eval datasets failed: {str(error)}")


@app.get("/api/knowledge/evals/questions")
def list_knowledge_eval_questions(dataset_id: Optional[str] = None):
    """获取知识库评测题目列表"""
    try:
        available_datasets = _load_knowledge_eval_datasets()
        return {
            "datasets": available_datasets,
            "selected_dataset": next(
                (item for item in available_datasets if str(item.get("dataset_id") or "") == str(dataset_id or "")),
                None,
            ),
            "questions": _load_knowledge_eval_questions(include_sql=False, dataset_id=dataset_id),
        }
    except Exception as error:
        raise HTTPException(status_code=500, detail=f"Load eval questions failed: {str(error)}")


@app.post("/api/knowledge/evals/run")
def run_knowledge_eval_suite(payload: Optional[KnowledgeEvalRunRequest] = None):
    """执行知识库评测并返回前端可展示的完整结果"""
    try:
        dataset_id = payload.dataset_id if payload else None
        return _build_knowledge_eval_payload(dataset_id=dataset_id)
    except Exception as error:
        raise HTTPException(status_code=500, detail=f"Run eval suite failed: {str(error)}")


@app.get("/api/knowledge/structured/{doc_id}")
def get_structured_index(
    doc_id: str,
    strategy: str = 'doc_blocks_graph_v1',
    item_type: Optional[str] = None,
    keyword: Optional[str] = None,
    limit: int = 200
):
    """查询结构化索"""
    from docs_core.knowledge_service import knowledge_service
    node = knowledge_service.get_node(doc_id)
    if not node:
        raise HTTPException(status_code=404, detail="Document not found")
    items = knowledge_service.list_document_segments(
        doc_id=doc_id,
        strategy=strategy,
        item_type=item_type,
        keyword=keyword,
        limit=limit
    )
    return {"doc_id": doc_id, "strategy": strategy, "count": len(items), "items": items}


@app.get("/api/knowledge/structured/stats/{doc_id}")
def get_structured_stats(doc_id: str):
    """获取结构化索引统"""
    from docs_core.knowledge_service import knowledge_service
    node = knowledge_service.get_node(doc_id)
    if not node:
        raise HTTPException(status_code=404, detail="Document not found")
    return knowledge_service.get_document_segment_stats(doc_id)


@app.get("/api/knowledge/document/{library_id}/{doc_id}")
def get_document(library_id: str, doc_id: str):
    """获取文档内容"""
    from docs_core.ingest.store.assets_file_store import file_storage
    from docs_core.ingest.store.assets_file_store import get_doc_blocks_graph

    content = file_storage.read_markdown(library_id, doc_id)
    if content is None:
        raise HTTPException(status_code=404, detail="Document not found")
    
    storage_manifest = file_storage.get_doc_manifest(library_id, doc_id)
    
    graph_data = get_doc_blocks_graph(library_id, doc_id)

    return {
        "content": content,
        "storage": storage_manifest,
        "graph_data": graph_data
    }

@app.put("/api/knowledge/document/{library_id}/{doc_id}")
def update_document(library_id: str, doc_id: str, request: KnowledgeDocumentUpdate):
    """更新文档内容"""
    from docs_core.knowledge_service import knowledge_service
    from docs_core.ingest.store.assets_file_store import file_storage
    content = request.content
    saved_path = file_storage.save_edited_markdown(library_id, doc_id, content)
    knowledge_service.update_node(doc_id, updated_at=datetime.now())
    return {"status": "success", "path": saved_path, "storage": file_storage.get_doc_manifest(library_id, doc_id)}


@app.patch("/api/knowledge/document/{library_id}/{doc_id}/blocks/{block_id}")
def update_document_block(
    library_id: str,
    doc_id: str,
    block_id: str,
    request: KnowledgeDocumentBlockUpdate,
):
    """更新文档结构节点内容"""
    from docs_core.ingest.store.assets_file_store import update_doc_block_content

    changes = request.dict(exclude_unset=True)
    try:
        result = update_doc_block_content(library_id, doc_id, block_id, changes)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    return {
        "status": "success",
        "doc_id": doc_id,
        "block_id": result["block_id"],
        "updated_fields": result["updated_fields"],
        "node": result["node"],
        "storage": result["graph_path"],
    }


@app.post("/api/knowledge/document/{library_id}/{doc_id}/blocks/batch")
def batch_operate_document_blocks(
    library_id: str,
    doc_id: str,
    request: KnowledgeDocumentBatchBlockOperation,
):
    """批量执行文档结构节点操作"""
    from docs_core.ingest.store.assets_file_store import batch_operate_doc_blocks

    payload = request.dict(exclude_unset=True)
    try:
        result = batch_operate_doc_blocks(library_id, doc_id, request.operation, payload)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    return {
        "status": "success",
        "doc_id": doc_id,
        "operation": result["operation"],
        "block_ids": result["block_ids"],
        "target_block_id": result.get("target_block_id"),
        "created_block_ids": result.get("created_block_ids") or [],
        "removed_block_ids": result.get("removed_block_ids") or [],
        "saved_segments": result["saved_segments"],
        "storage": result["graph_path"],
    }


@app.post("/api/knowledge/document/{library_id}/{doc_id}/blocks/undo")
def undo_document_block_operation(library_id: str, doc_id: str):
    """撤回当前文档最近一次可回滚的结构操"""
    from docs_core.ingest.store.assets_file_store import undo_last_doc_block_operation

    try:
        result = undo_last_doc_block_operation(library_id, doc_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    return {
        "status": "success",
        "doc_id": doc_id,
        "restored_block_ids": result["restored_block_ids"],
        "saved_segments": result["saved_segments"],
        "storage": result["graph_path"],
    }


@app.post("/api/knowledge/document/{library_id}/{doc_id}/blocks/merge/undo")
def undo_document_block_merge(library_id: str, doc_id: str):
    """兼容旧路由，撤回当前文档最近一次结构操"""
    return undo_document_block_operation(library_id, doc_id)


@app.get("/api/knowledge/storage/{library_id}/{doc_id}")
def get_document_storage(library_id: str, doc_id: str):
    """获取文档存储布局"""
    from docs_core.knowledge_service import knowledge_service
    from docs_core.ingest.store.assets_file_store import file_storage
    node = knowledge_service.get_node(doc_id)
    if not node:
        raise HTTPException(status_code=404, detail="Document not found")
    return {"library_id": library_id, "doc_id": doc_id, "storage": file_storage.get_doc_manifest(library_id, doc_id)}


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
        ],
    )
