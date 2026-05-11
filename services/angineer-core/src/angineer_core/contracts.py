"""
模块解耦契约层，定义跨模块依赖的 Protocol 接口。
angineer-core 通过 Protocol 依赖 docs-core / sop-core 的能力，
避免直接 import 具体实现，实现模块解耦。
"""
from typing import Any, Dict, List, Optional, Protocol, runtime_checkable


@runtime_checkable
class KnowledgeProvider(Protocol):
    """知识库服务提供者协议。"""

    def list_nodes(self, library_id: str, visible: bool = False) -> List[Any]:
        """获取知识库节点列表。"""
        ...

    def get_node(self, node_id: str) -> Optional[Any]:
        """获取指定知识库节点。"""
        ...


@runtime_checkable
class SopProvider(Protocol):
    """SOP 加载服务提供者协议。"""

    def load_all(self) -> List[Any]:
        """加载所有 SOP。"""
        ...

    def analyze_sop(self, sop_id: str, **kwargs: Any) -> Any:
        """分析指定 SOP。"""
        ...


@runtime_checkable
class LLMProvider(Protocol):
    """LLM 客户端服务提供者协议。"""

    def chat(self, messages: List[Dict[str, Any]], **kwargs: Any) -> str:
        """发送对话请求并获取响应。"""
        ...

    def chat_stream(self, messages: List[Dict[str, Any]], **kwargs: Any) -> Any:
        """发送对话请求并以流式方式获取响应。"""
        ...
