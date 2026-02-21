from abc import ABC, abstractmethod
from typing import Dict, Any, Type
from pydantic import BaseModel
    
class BaseTool(ABC):
    """
    工具基类。
    所有新工具都应继承此类并实现 run 方法。
    """
    name: str = "base_tool"
    description_en: str = "Base tool description"
    description_zh: str = "工具基类描述"
    
    @property
    def description(self) -> str:
        """
        为了向后兼容，默认返回中文描述。
        以后可以根据语言设置动态返回。
        """
        return self.description_zh

    @abstractmethod
    def run(self, **kwargs) -> Any:
        """
        执行工具的核心逻辑。
        """
        pass


class ToolRegistry:
    """
    工具注册表，负责管理和查找所有已注册的工具。
    """
    _registry: Dict[str, BaseTool] = {}
    
    @classmethod
    def register(cls, tool: BaseTool):
        """
        将工具实例注册到注册表中。
        """
        cls._registry[tool.name] = tool
        
    @classmethod
    def get_tool(cls, name: str) -> BaseTool:
        """
        根据名称获取工具实例。
        支持大小写不敏感查找。
        """
        if not name:
            return None
            
        # 1. 精确匹配
        if name in cls._registry:
            return cls._registry[name]
            
        # 2. 归一化匹配 (去除空白，转小写)
        normalized_name = name.strip().lower()
        if normalized_name in cls._registry:
            return cls._registry[normalized_name]
            
        # 3. 尝试匹配别名或由 LLM 产生的变体 (e.g. "Calculator" -> "calculator")
        # 遍历注册表查找
        for key, tool in cls._registry.items():
            if key.lower() == normalized_name:
                return tool
                
        return None
        
    @classmethod
    def list_tools(cls) -> Dict[str, Dict[str, str]]:
        """
        列出所有工具及其双语描述。
        """
        return {
            name: {
                "en": tool.description_en,
                "zh": tool.description_zh
            } for name, tool in cls._registry.items()
        }


# 用于简化工具注册的装饰器
def register_tool(cls):
    """
    类装饰器，用于自动实例化工具并注册到 ToolRegistry。
    """
    instance = cls()
    ToolRegistry.register(instance)
    return cls
