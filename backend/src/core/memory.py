from typing import Dict, Any, List, Optional
import re
from pydantic import BaseModel, Field

class StepRecord(BaseModel):
    step_id: str
    tool_name: str
    inputs: Dict[str, Any]
    outputs: Any
    status: str = "success" # success, failed
    error: Optional[str] = None

class Memory(BaseModel):
    # Global context shared across the session
    global_context: Dict[str, Any] = Field(default_factory=dict)
    # History of steps executed
    history: List[StepRecord] = Field(default_factory=list)
    
    def update_context(self, updates: Dict[str, Any]):
        self.global_context.update(updates)
        
    def add_history(self, record: StepRecord):
        self.history.append(record)
        
    def resolve_value(self, value: Any) -> Any:
        """
        Resolve variables like ${var_name} or ${step_id.output_key}
        """
        if not isinstance(value, str):
            return value
            
        # Check for ${variable} pattern
        pattern = r"\$\{(.+?)\}"
        matches = re.findall(pattern, value)
        
        if not matches:
            return value
            
        # If the entire string is just one variable, return the actual type
        if len(matches) == 1 and value.strip() == f"${{{matches[0]}}}":
            return self._get_value(matches[0])
            
        # Otherwise replace in string
        result = value
        for match in matches:
            val = self._get_value(match)
            result = result.replace(f"${{{match}}}", str(val))
        return result
        
    def _get_value(self, key: str) -> Any:
        # Support dot notation for nested access
        
        # 1. Check global context with dot notation support
        if "." in key:
            parts = key.split(".")
            val = self.global_context
            found = True
            for part in parts:
                if isinstance(val, dict) and part in val:
                    val = val[part]
                else:
                    found = False
                    break
            if found:
                return val
        elif key in self.global_context:
            return self.global_context[key]
            
        # 2. Check history (advanced: ${step_id.output})
        if "." in key:
            step_id, field = key.split(".", 1)
            for record in reversed(self.history):
                if record.step_id == step_id:
                    # Allow access to inputs or outputs
                    if field == "output" or field == "outputs":
                        return record.outputs
                    if field.startswith("outputs."):
                        sub_key = field.split(".", 1)[1]
                        if isinstance(record.outputs, dict):
                            return record.outputs.get(sub_key)
                    # More logic can be added here
                    
        return None
