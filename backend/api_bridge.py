import os
import json
import glob
import subprocess
import asyncio
import time
import sys
from typing import List, Dict, Any, Optional
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

ROOT_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
TESTS_DIR = os.path.join(ROOT_DIR, "tests")
if TESTS_DIR not in sys.path:
    sys.path.append(TESTS_DIR)

# Import existing logic
from src.core.llm import LLMClient
from src.core.contextStruct import Step
from src.agents import IntentClassifier, Dispatcher
from src.core.contextStruct import SOP
# from src.core.knowledge import knowledge_manager
from src.core.sop_loader import SopLoader
from src.tools import ToolRegistry, register_tool  # Ensure all tools are registered
from src.tools import *  # Import all tools for registration effect

app = FastAPI(title="PicoAgent API Bridge")

# Initialize SOP Loader
SOP_DIR = os.path.join(os.path.dirname(__file__), "sops")
sop_loader = SopLoader(SOP_DIR)

# Enable CORS for Vue frontend
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# --- Static Files Handling ---
FRONTEND_DIR = os.path.join(ROOT_DIR, "frontend")

@app.get("/")
async def read_index():
    """主页路由，返回 index.html"""
    index_path = os.path.join(FRONTEND_DIR, "index.html")
    if os.path.exists(index_path):
        return FileResponse(index_path)
    return {"error": "index.html not found"}

# 挂载静态文件目录 (例如 CSS/JS 等，如果有的话)
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
    final_context = dispatcher.run(sop, args)
    
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
            dispatcher.memory.update_context(args)

            for step in sop.steps:
                dispatcher._execute_step(step)
                yield json.dumps({"type": "step", "step": trace_list[-1]}) + "\n"

            yield json.dumps({"type": "done", "final_context": dispatcher.memory.global_context}) + "\n"
        except Exception as e:
            yield json.dumps({"type": "error", "error": str(e)}) + "\n"

    return StreamingResponse(event_stream(), media_type="application/x-ndjson")

@app.get("/llm_configs")
def list_llm_configs():
    client = LLMClient()
    # 仅返回名称和模型，不返回 API Key 等敏感信息
    return [{"name": c["name"], "model": c["model"], "configured": bool(c["api_key"])} for c in client.configs]

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
    if test_id in ["0", "1", "2", "3"]:
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
                "3": "test_03_sop_analysis"
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
            yield json.dumps({"step": "sop_load", "status": "running", "msg": "正在检查 SOP 列表..."}) + "\n"
            await asyncio.sleep(0.3) # Visual pacing
            
            # Use the global sop_loader
            if not sop_loader.sops:
                sops = sop_loader.load_all()
            else:
                sops = sop_loader.sops
                
            yield json.dumps({"step": "sop_load", "status": "done", "msg": f"SOP 加载完成 (共 {len(sops)} 个)"}) + "\n"

            # Step 2: Validate SOPs (Quick sampling)
            yield json.dumps({"step": "sop_validate", "status": "running", "msg": "抽检 SOP 有效性..."}) + "\n"
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
    """Test 03 Streaming Execution Endpoint."""
    async def generate():
        """逐步输出 SOP 解析流式结果。"""
        try:
            stream_padding = " " * 1024
            def pack(payload: Dict[str, Any]) -> str:
                """封装流式输出文本。"""
                return json.dumps(payload) + stream_padding + "\n"
            loop = asyncio.get_event_loop()
            start_time = time.time()
            yield pack({"step": "sop_load", "status": "running", "msg": "正在加载 SOP 列表..."})
            await asyncio.sleep(0.01)
            
            sops_task = loop.run_in_executor(None, sop_loader.load_all)
            while not sops_task.done():
                yield pack({"step": "sop_load", "status": "running", "msg": "SOP 加载中..."})
                await asyncio.sleep(0.1)
            sops = await sops_task
            sop_map = {s.id: s for s in sops}
            yield pack({"step": "sop_load", "status": "done", "msg": f"SOP 加载完成 (共 {len(sops)} 个)"})
            await asyncio.sleep(0.01)

            yield pack({"step": "classifier_init", "status": "running", "msg": "初始化意图分类器..."})
            await asyncio.sleep(0.01)
            
            classifier_task = loop.run_in_executor(None, lambda: IntentClassifier(sops))
            while not classifier_task.done():
                yield pack({"step": "classifier_init", "status": "running", "msg": "分类器构建中..."})
                await asyncio.sleep(0.1)
            classifier = await classifier_task
            yield pack({"step": "classifier_init", "status": "done", "msg": "分类器就绪"})
            await asyncio.sleep(0.01)

            import test_03_sop_analysis as t3
            cases = t3.select_cases(query) if query else list(t3.SAMPLE_QUERIES)
            results = []

            for case in cases:
                case_id = case.get("id")
                case_label = case.get("label")
                case_query = case.get("query")
                expected_sop = case.get("expected_sop")
                yield pack({
                    "step": "route",
                    "status": "running",
                    "msg": f"正在路由用例: {case_label}",
                    "case_id": case_id,
                    "case_label": case_label,
                    "case_query": case_query,
                    "expected_sop": expected_sop
                })
                await asyncio.sleep(0.01)

                # 强制执行 LLM 路由，以展示真实解析过程
                yield pack({
                    "step": "inference",
                    "status": "running",
                    "msg": f"LLM 正在分析意图: {case_query[:20]}...",
                    "case_id": case_id
                })
                await asyncio.sleep(0.01)
                
                route_task = loop.run_in_executor(
                    None,
                    lambda: classifier.route(case_query, config_name=config, mode=mode)
                )
                while not route_task.done():
                    yield pack({
                        "step": "inference",
                        "status": "running",
                        "msg": "LLM 匹配 SOP 中...",
                        "case_id": case_id
                    })
                    await asyncio.sleep(0.2)

                sop, args, reason = await route_task
                matched_sop = sop.id if sop else None
                
                # 如果有预期结果，进行比对（仅用于标注，不覆盖逻辑，除非完全没匹配到）
                route_note = reason
                if expected_sop:
                    if matched_sop == expected_sop:
                        route_note = f"{reason} (✅ 符合预期)"
                    else:
                        route_note = f"{reason} (❌ 预期: {expected_sop}, 实际: {matched_sop})"
                        # 可选：如果希望演示“修正”，可以在这里覆盖，但为了展示 LLM 能力，保留 LLM 结果更好
                        # 或者仅在 LLM 失败时兜底
                        if not matched_sop:
                            sop = sop_map.get(expected_sop)
                            matched_sop = expected_sop
                            route_note += " -> 启用兜底"

                yield pack({
                    "step": "route",
                    "status": "done",
                    "msg": f"已匹配 SOP: {matched_sop}",
                    "case_id": case_id,
                    "case_label": case_label,
                    "case_query": case_query,
                    "matched_sop": matched_sop,
                    "route_reason": route_note,
                    "args": args
                })
                await asyncio.sleep(0.01)

                yield pack({"step": "sop_analyze", "status": "running", "msg": f"解析 SOP: {matched_sop}", "case_id": case_id, "matched_sop": matched_sop})
                await asyncio.sleep(0.01)
                
                analyze_task = loop.run_in_executor(
                    None,
                    lambda: t3.analyze_sop_with_fallback(sop_loader, matched_sop, sop_map, config=config, mode=mode)
                )
                while not analyze_task.done():
                    yield pack({
                        "step": "sop_analyze",
                        "status": "running",
                        "msg": "LLM 提取步骤中...",
                        "case_id": case_id,
                        "matched_sop": matched_sop
                    })
                    await asyncio.sleep(0.2)

                analyzed_sop = await analyze_task
                yield pack({"step": "sop_analyze", "status": "done", "msg": f"SOP 解析完成: {matched_sop}", "case_id": case_id, "matched_sop": matched_sop})
                await asyncio.sleep(0.05)

                step_payloads = []
                for idx, step in enumerate(analyzed_sop.steps, start=1):
                    base_payload = {
                        "id": step.id,
                        "name": step.name or step.id,
                        "description": step.description or "",
                        "tool": step.tool or "auto",
                        "inputs": step.inputs or {},
                        "outputs": step.outputs or {},
                        "notes": step.notes or ""
                    }
                    yield pack({
                        "step": "step_analyze",
                        "status": "running",
                        "msg": f"分析步骤 {idx}: {step.name or step.id}",
                        "case_id": case_id,
                        "step_index": idx,
                        "step_name": step.name or step.id,
                        "payload": base_payload
                    })
                    await asyncio.sleep(0.05)

                    analysis_text = f"工具: {base_payload['tool']} | 输入: {list(base_payload['inputs'].keys()) or ['无']} | 输出: {list(base_payload['outputs'].keys()) or ['无']}"
                    yield pack({
                        "step": "step_analyze",
                        "status": "running",
                        "msg": f"结构分析完成 {idx}: {step.name or step.id}",
                        "case_id": case_id,
                        "step_index": idx,
                        "step_name": step.name or step.id,
                        "payload": {**base_payload, "analysis": analysis_text, "ai_note": "准备模拟执行"}
                    })
                    await asyncio.sleep(0.05)

                    ai_exec = t3.simulate_ai_output(step, case_query)
                    yield pack({
                        "step": "step_analyze",
                        "status": "running",
                        "msg": f"生成执行结果 {idx}: {step.name or step.id}",
                        "case_id": case_id,
                        "step_index": idx,
                        "step_name": step.name or step.id,
                        "payload": {
                            **base_payload,
                            "analysis": analysis_text,
                            "ai_result": ai_exec.get("result", ""),
                            "ai_note": ai_exec.get("note", "")
                        }
                    })
                    await asyncio.sleep(0.05)

                    payload = t3.analyze_step(step, case_query)
                    step_payloads.append(payload)
                    yield pack({
                        "step": "step_analyze",
                        "status": "done",
                        "msg": f"步骤完成 {idx}: {step.name or step.id}",
                        "case_id": case_id,
                        "step_index": idx,
                        "step_name": step.name or step.id,
                        "payload": payload
                    })
                    await asyncio.sleep(0.05)

                results.append({
                    "id": case_id,
                    "label": case_label,
                    "query": case_query,
                    "expected_sop": expected_sop,
                    "matched_sop": matched_sop,
                    "route_reason": reason,
                    "args": args,
                    "steps": step_payloads
                })

            duration = time.time() - start_time
            yield pack({"step": "result", "status": "done", "data": {"cases": results}, "duration_s": duration})
        except Exception as e:
            yield pack({"step": "error", "status": "failed", "msg": str(e)})

    return StreamingResponse(
        generate(),
        media_type="application/x-ndjson",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"}
    )

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

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8001)
