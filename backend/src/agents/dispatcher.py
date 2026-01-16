import time
from typing import Dict, Any
from src.core.models import SOP, Step
from src.core.memory import Memory, StepRecord
from src.tools.base import ToolRegistry
from src.core.llm import llm_client

class Dispatcher:
    def __init__(self):
        self.memory = Memory()
        
    def run(self, sop: SOP, initial_context: Dict[str, Any]):
        """
        Execute the SOP with the given initial context.
        """
        print(f"[{sop.id}] Starting execution: {sop.description}")
        self.memory.update_context(initial_context)
        
        # Simple linear execution for now
        # In a real FSM, we would follow next_step_id
        for step in sop.steps:
            self._execute_step(step)
            
        print(f"[{sop.id}] Execution finished.")
        return self.memory.global_context
        
    def _execute_step(self, step: Step):
        print(f"  -> Executing Step: {step.name} ({step.tool})")
        
        # 1. Resolve Inputs
        tool_inputs = {}
        for key, value in step.inputs.items():
            resolved_value = self.memory.resolve_value(value)
            tool_inputs[key] = resolved_value
            
        # 2. Get Tool
        tool = ToolRegistry.get_tool(step.tool)
        if not tool:
            error_msg = f"Tool '{step.tool}' not found"
            print(f"    Error: {error_msg}")
            self._record_step(step, tool_inputs, None, error=error_msg)
            return
            
        # 3. Execute Tool
        try:
            # Here we could insert an LLM call if inputs need formatting
            # But for now, trust the resolution
            result = tool.run(**tool_inputs)
            print(f"    Result: {result}")
            
            # 4. Process Outputs
            self._process_outputs(step, result)
            
            # 5. Record History
            self._record_step(step, tool_inputs, result)
            
        except Exception as e:
            print(f"    Error executing tool: {e}")
            self._record_step(step, tool_inputs, None, error=str(e))
            
    def _process_outputs(self, step: Step, result: Any):
        # Update global context based on output mapping
        if not step.outputs:
            return
            
        # If outputs is "*" map everything (if result is dict)
        if step.outputs == "*":
            if isinstance(result, dict):
                self.memory.update_context(result)
            else:
                self.memory.update_context({"last_result": result})
            return
            
        for context_key, result_path in step.outputs.items():
            # Simple extraction
            # If result_path is "result" or ".", use the whole result
            if result_path == "." or result_path == "result":
                val = result
            elif isinstance(result, dict) and result_path in result:
                val = result[result_path]
            else:
                val = None # Or keep existing?
                
            if val is not None:
                self.memory.update_context({context_key: val})
                
    def _record_step(self, step: Step, inputs: Any, outputs: Any, error: str = None):
        record = StepRecord(
            step_id=step.id,
            tool_name=step.tool,
            inputs=inputs,
            outputs=outputs,
            status="failed" if error else "success",
            error=error
        )
        self.memory.add_history(record)
