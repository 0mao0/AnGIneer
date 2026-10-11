"""图谱只读端口：sop-core 不直接依赖 docs-core，宿主/接入层注入实现。

plan-sop-api-l4 阶段 2（Task 2.1/2.2）。生成器（SopPathGenerator）对图谱的全部
只读依赖收敛为本 Protocol；docs-api 的 HTTP 适配实现见 sop-api/docs_graph_client.py
（经 generation-bundle 端点一次取全后内存物化）。

layer 一律用字符串常量比较：docs-core 侧的 EntityLayer 是 (str, Enum)
（"concept"/"condition"/"action"），枚举实例与字符串相等比较天然成立，
两侧调用方传枚举或字符串均可。
"""
from typing import Any, List, Optional, Protocol

# 实体层字符串常量（与 docs_core.step07_graph.config.EntityLayer 值对齐）
LAYER_CONCEPT = "concept"
LAYER_CONDITION = "condition"
LAYER_ACTION = "action"

DEFAULT_LLM_CONFIG_NAME: Optional[str] = None


class GraphReader(Protocol):
    """SOP 生成所需的图谱只读面（与 docs_core GraphStore 相应方法同签名）。"""

    def get_entity_by_name(self, name: str, library_id: Optional[str] = None) -> Optional[Any]: ...

    def get_entity(self, entity_id: str) -> Optional[Any]: ...

    def list_entities_by_doc(self, library_id: str, doc_id: str) -> List[Any]: ...

    def get_frameworks_by_doc(self, library_id: str, doc_id: str) -> List[Any]: ...

    def get_relations_by_entity(
        self, entity_id: str, direction: str = "both", **kwargs: Any
    ) -> List[Any]: ...

    def get_principles_by_entity_ids(self, entity_ids: List[str]) -> List[Any]: ...

    def get_warnings_by_entity_ids(self, entity_ids: List[str]) -> List[Any]: ...

    def get_examples_by_entity_ids(self, entity_ids: List[str]) -> List[Any]: ...
