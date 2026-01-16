from typing import List, Dict, Any, Optional
from pydantic import BaseModel, Field

class Step(BaseModel):
    id: str
    name: Optional[str] = None # Legacy support
    name_zh: Optional[str] = None
    name_en: Optional[str] = None
    description: Optional[str] = None # Legacy support
    description_zh: Optional[str] = None
    description_en: Optional[str] = None
    tool: str
    # Map from tool argument name to value or context reference
    # e.g. {"location": "${user_query}", "days": 3}
    inputs: Dict[str, Any] = Field(default_factory=dict)
    # Define what keys to extract from tool output to update context
    # e.g. {"weather_info": "result"} -> context["weather_info"] = tool_output["result"]
    outputs: Dict[str, str] = Field(default_factory=dict)
    
    # Next step logic could be here, but for now simple linear or list index based
    next_step_id: Optional[str] = None
    on_failure: Optional[str] = None # Jump to this step id on failure

class SOP(BaseModel):
    id: str
    name_zh: Optional[str] = None
    name_en: Optional[str] = None
    description: Optional[str] = None # Legacy support
    description_zh: Optional[str] = None
    description_en: Optional[str] = None
    steps: List[Step]
    
    def get_step(self, step_id: str) -> Optional[Step]:
        for step in self.steps:
            if step.id == step_id:
                return step
        return None

class AgentResponse(BaseModel):
    """Standard response from Router or other agents"""
    content: str
    data: Optional[Dict[str, Any]] = None
