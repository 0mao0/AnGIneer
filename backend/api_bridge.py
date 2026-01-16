import os
import json
import glob
from typing import List, Dict, Any, Optional
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

# Import existing logic
from src.core.models import SOP, Step
from src.agents import IntentRouter, Dispatcher
from src.core.knowledge import knowledge_manager
from src.tools import ToolRegistry, register_tool  # Ensure all tools are registered
from src.tools import *  # Import all tools for registration effect

app = FastAPI(title="PicoAgent API Bridge")

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
            # Call original logic but capture results
            # Note: We are re-implementing the execution part to capture trace
            # since the original doesn't have hooks.
            tool = ToolRegistry.get_tool(step.tool)
            if not tool:
                raise ValueError(f"Tool {step.tool} not found")
            
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
    sops = []
    for fpath in glob.glob("sops/*.json"):
        with open(fpath, "r", encoding="utf-8") as f:
            sops.append(json.load(f))
    return sops

@app.post("/sops")
def save_sop(sop: SOPUpdate):
    fpath = f"sops/{sop.id}.json"
    with open(fpath, "w", encoding="utf-8") as f:
        json.dump(sop.dict(), f, indent=2, ensure_ascii=False)
    return {"status": "success"}

@app.delete("/sops/{sop_id}")
def delete_sop(sop_id: str):
    fpath = f"sops/{sop_id}.json"
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
    knowledge_manager._load_knowledge()
    return {"status": "success"}

@app.post("/chat")
def chat(request: QueryRequest):
    global execution_trace
    execution_trace = [] # Reset trace
    
    # 1. Load SOPs for Router
    sops = []
    for fpath in glob.glob("sops/*.json"):
        with open(fpath, "r", encoding="utf-8") as f:
            sops.append(SOP(**json.load(f)))
    
    router = IntentRouter(sops)
    sop, args = router.route(request.query)
    
    if not sop:
        return {
            "sop_id": None,
            "response": None,
            "trace": []
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
        "final_context": final_context
    }

@app.post("/chat/stream")
def chat_stream(request: QueryRequest):
    def event_stream():
        try:
            yield json.dumps({"type": "routing"}) + "\n"

            sops = []
            for fpath in glob.glob("sops/*.json"):
                with open(fpath, "r", encoding="utf-8") as f:
                    sops.append(SOP(**json.load(f)))

            router = IntentRouter(sops)
            sop, args = router.route(request.query)

            if not sop:
                yield json.dumps({"type": "nomatch"}) + "\n"
                return

            yield json.dumps({
                "type": "start",
                "sop_id": sop.id,
                "sop_name_zh": sop.name_zh or sop.id,
                "sop_name_en": sop.name_en or sop.id,
                "args": args
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

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
