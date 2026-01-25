import os
import json
import glob
import subprocess
import asyncio
from typing import List, Dict, Any, Optional
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

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

# --- Data Models for API ---

class QueryRequest(BaseModel):
    query: str

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
    def __init__(self, trace_list: list):
        super().__init__()
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
            
            result = tool.run(**tool_inputs)
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
    sop, args, reason = classifier.route(request.query)
    
    if not sop:
        return {
            "sop_id": None,
            "response": None,
            "trace": [],
            "reason": reason
        }
    
    # 2. Execute with TraceDispatcher
    dispatcher = TraceDispatcher(execution_trace)
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
            sop, args, reason = classifier.route(request.query)

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
            dispatcher = TraceDispatcher(trace_list)
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
    if test_id in ["0", "1", "2"]:
        try:
            # Dynamically import test module to get SAMPLE_QUERIES
            import sys
            import importlib
            tests_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "tests"))
            if tests_dir not in sys.path:
                sys.path.append(tests_dir)
            
            module_map = {
                "0": "test_00_llm_chat",
                "1": "test_01_tool_registration",
                "2": "test_02_intent_classifier"
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
    uvicorn.run(app, host="0.0.0.0", port=8000)
