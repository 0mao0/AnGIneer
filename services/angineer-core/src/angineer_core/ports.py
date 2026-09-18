"""引擎端口注册表（C1 库化解耦，2026-09-18）。

引擎只定义 Protocol 与注册点，不认识任何具体实现：
- 组装层（aichat-api main.py）启动时调用 register_* 注入 docs-core 适配器
- 引擎内遇到未注册端口按既有降级语义处理（警告 + 空结果），不 import 具体包

当前端口：
- local_nodes_loader：policy_query 本地回退的节点加载（docs-core docs_service 适配器）
- local_rerank：retrieval_pipeline 降级链末端的 phrase rerank（docs-core reranker 适配器）
- agent_search 七件套（Seam 4，2026-09-19）：agent_tools 检索/图谱配方的 docs-core 侧实现
  （normalize_query / knowledge_local_search / table_local_search /
  entity_local_search / local_stats / engtool_registry / relevant_citations），
  适配器在 docs-core 侧 step09_query.agent_port，经 register_agent_search 一次性注入
"""
import logging
from typing import Any, Callable, Dict, List, Optional

logger = logging.getLogger(__name__)

# (library_id: str, doc_ids: Optional[List[str]]) -> List[document 节点]
LocalNodesLoader = Callable[[str, Optional[List[str]]], List[Any]]
# (normalized_query: str, task_type: str, candidates: list) -> list
LocalRerank = Callable[[str, str, list], list]

_local_nodes_loader: Optional[LocalNodesLoader] = None
_local_rerank: Optional[LocalRerank] = None


def register_local_nodes_loader(fn: LocalNodesLoader) -> None:
    """注入进程内节点加载实现（docs-core docs_service 适配），允许重复注册（后者覆盖）。"""
    global _local_nodes_loader
    _local_nodes_loader = fn


def get_local_nodes_loader() -> Optional[LocalNodesLoader]:
    return _local_nodes_loader


def register_local_rerank(fn: LocalRerank) -> None:
    """注入本地 phrase rerank 实现（docs-core reranker 适配）。"""
    global _local_rerank
    _local_rerank = fn


def get_local_rerank() -> Optional[LocalRerank]:
    return _local_rerank


# ---- Seam 4：agent_tools 检索/图谱配方端口（docs-core agent_port 适配） ----

# (query: str) -> str：中文数字条款号归一化（"第六十条"→"第60条"），HTTP 与本地两路共用
QueryNormalizerFn = Callable[[str], str]
# 知识库本地召回配方：dense/sparse/clause 三路 + 条件 formula/table 路 + fuse + 表格文本兜底。
# 返回 {"items": [...]}（已 fuse+兜底，未去重截断）或 {"error": ..., "detail": {...}}
KnowledgeLocalSearchFn = Callable[..., Dict[str, Any]]
# 表格/公式本地召回配方，返回语义同上（error 文案「表格检索全部失败」）
TableLocalSearchFn = Callable[..., Dict[str, Any]]
# 图谱本地直查：GraphStore 分支，返回实体列表（空列表=图谱无匹配，触发正文回退）
EntityLocalSearchFn = Callable[..., List[Any]]
# (library_id: Optional[str]) -> Dict：进程内直查 sqlite 的统计聚合
LocalStatsFn = Callable[[Optional[str]], Dict[str, Any]]
# () -> Any：返回外部工具注册表 ToolRegistry（惰性 import 在适配器内）
EngtoolRegistryFn = Callable[[], Any]
# (query: str, items: list, limit: int) -> List[Dict]：引用挑选（查询短语命中优先，
# 无命中按重排分取前 limit 条）；未注册降级为不返回 citations 字段
RelevantCitationsFn = Callable[..., List[Dict[str, Any]]]

_query_normalizer: Optional[QueryNormalizerFn] = None
_knowledge_local_search: Optional[KnowledgeLocalSearchFn] = None
_table_local_search: Optional[TableLocalSearchFn] = None
_entity_local_search: Optional[EntityLocalSearchFn] = None
_local_stats: Optional[LocalStatsFn] = None
_engtool_registry: Optional[EngtoolRegistryFn] = None
_relevant_citations: Optional[RelevantCitationsFn] = None

_UNSET = object()


def register_agent_search(
    *,
    normalize_query: Any = _UNSET,
    knowledge_local: Any = _UNSET,
    table_local: Any = _UNSET,
    entity_local: Any = _UNSET,
    local_stats: Any = _UNSET,
    engtool_registry: Any = _UNSET,
    relevant_citations: Any = _UNSET,
) -> None:
    """注入 agent_tools 七端口的 docs-core 侧实现（适配器 step09_query.agent_port）。

    省略参数 = 保持现状；显式传 None = 清除该项（测试需要）。
    """
    global _query_normalizer, _knowledge_local_search, _table_local_search
    global _entity_local_search, _local_stats, _engtool_registry, _relevant_citations
    if normalize_query is not _UNSET:
        _query_normalizer = normalize_query
    if knowledge_local is not _UNSET:
        _knowledge_local_search = knowledge_local
    if table_local is not _UNSET:
        _table_local_search = table_local
    if entity_local is not _UNSET:
        _entity_local_search = entity_local
    if local_stats is not _UNSET:
        _local_stats = local_stats
    if engtool_registry is not _UNSET:
        _engtool_registry = engtool_registry
    if relevant_citations is not _UNSET:
        _relevant_citations = relevant_citations


def get_query_normalizer() -> Optional[QueryNormalizerFn]:
    return _query_normalizer


def get_knowledge_local_search() -> Optional[KnowledgeLocalSearchFn]:
    return _knowledge_local_search


def get_table_local_search() -> Optional[TableLocalSearchFn]:
    return _table_local_search


def get_entity_local_search() -> Optional[EntityLocalSearchFn]:
    return _entity_local_search


def get_local_stats() -> Optional[LocalStatsFn]:
    return _local_stats


def get_engtool_registry() -> Optional[EngtoolRegistryFn]:
    return _engtool_registry


def get_relevant_citations() -> Optional[RelevantCitationsFn]:
    return _relevant_citations
