from abc import ABC, abstractmethod
from typing import Dict, Any, Type
from pydantic import BaseModel

class BaseTool(ABC):
    name: str = "base_tool"
    description: str = "Base tool description"
    
    @abstractmethod
    def run(self, **kwargs) -> Any:
        pass

class ToolRegistry:
    _registry: Dict[str, BaseTool] = {}
    
    @classmethod
    def register(cls, tool: BaseTool):
        cls._registry[tool.name] = tool
        
    @classmethod
    def get_tool(cls, name: str) -> BaseTool:
        return cls._registry.get(name)
        
    @classmethod
    def list_tools(cls) -> Dict[str, str]:
        return {name: tool.description for name, tool in cls._registry.items()}

# Decorator for easy registration
def register_tool(cls):
    instance = cls()
    ToolRegistry.register(instance)
    return cls
