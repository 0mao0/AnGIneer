"""引擎端口注册表（C1 库化解耦，2026-09-18）。

引擎只定义 Protocol 与注册点，不认识任何具体实现：
- 组装层（aichat-api main.py）启动时调用 register_* 注入 docs-core 适配器
- 引擎内遇到未注册端口按既有降级语义处理（警告 + 空结果），不 import 具体包

当前端口：
- local_nodes_loader：policy_query 本地回退的节点加载（docs-core docs_service 适配器）
- local_rerank：retrieval_pipeline 降级链末端的 phrase rerank（docs-core reranker 适配器）

将来的 RetrievalPort（知识/表格/公式/图谱检索工具）也在此注册，适配器落在
docs-core（检索实现的家），引擎 agent_tools 只消费端口。
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
