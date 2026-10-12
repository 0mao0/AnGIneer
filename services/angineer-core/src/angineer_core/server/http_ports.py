"""chat 壳的 HTTP 端口适配器：无组装层时补齐进程内端口等价物。

2026-10-12 DredgeAI 试用反馈的修复（docs/angineer-shell-citations-fix-request-20261012.md）：

壳进程没有 aichat-api 那样的组装层去注册进程内端口，引擎六处端口消费点全部按
「端口未注册」降级——citations 恒空 / phrase rerank 跳过 / 条款号不归一化 /
canonical 查表找不到册 / 表格块读取不可用 / calculator 一调用即 LookupError。
本模块在壳启动时把 **HTTP 等价实现** 注册进端口注册表（指向 retrieval 壳 /
docs-api 的 engine_ports 路由，docs-core 侧同一份实现），行为与进程内装配对齐：

- 六端口：``normalize_query`` / ``local_rerank`` / ``relevant_citations`` /
  ``local_nodes_loader`` / ``table_blocks`` / ``engtool_registry``；
- **失败一律降级不抛错**（返回原值/空）——引擎对部分端口调用没有 try/except，
  把降级路径变成工具级异常会雪崩；`table_blocks` 例外（消费方自带 try/except，
  错误应显式上浮为「表格块读取失败」）；
- 仅当配置 ``ANGINEER_DOCS_API_URL``（client_from_env() 非 None）时注册；
  ``ANGINEER_HTTP_PORTS=0`` 可整体关闭（排障用）。
"""
import logging
import os
from typing import Any, Dict, List, Optional

from angineer_core import ports
from angineer_core.docs_retrieval_client import DocsRetrievalClient, client_from_env

logger = logging.getLogger(__name__)


def http_ports_enabled() -> bool:
    """注册开关：未配 ANGINEER_DOCS_API_URL 或显式 ANGINEER_HTTP_PORTS=0 时不注册。"""
    if os.getenv("ANGINEER_HTTP_PORTS", "1").strip().lower() in ("0", "false", "off", "no"):
        return False
    return client_from_env() is not None


# ---- 适配器（失败降级，绝不抛错——见模块 docstring）----


def _normalize_query(query: str) -> str:
    if not query:
        return query
    try:
        client = client_from_env()
        if client is None:
            return query
        return client.normalize_query(query) or query
    except Exception as exc:  # noqa: BLE001
        logger.warning("HTTP normalize_query 失败（按原样返回）: %s", exc)
        return query


def _local_rerank(normalized_query: str, task_type: str, candidates: list) -> list:
    if not candidates:
        return candidates
    try:
        client = client_from_env()
        if client is None:
            return candidates
        return client.rerank(normalized_query, task_type, candidates)
    except Exception as exc:  # noqa: BLE001
        logger.warning("HTTP rerank 失败（按原序返回）: %s", exc)
        return candidates


def _relevant_citations(query: str, items: list, limit: int = 5) -> List[Dict[str, Any]]:
    if not items:
        return []
    try:
        client = client_from_env()
        if client is None:
            return []
        return client.relevant_citations(query, items, limit)
    except Exception as exc:  # noqa: BLE001
        logger.warning("HTTP relevant_citations 失败（跳过引用挑选）: %s", exc)
        return []


def _local_nodes_loader(library_id: str, doc_ids: Optional[List[str]] = None) -> list:
    """节点清单：doc-nodes 端点全量拉取（doc_ids 收窄由引擎 _apply_doc_ids 统一做）。"""
    try:
        client = client_from_env()
        if client is None:
            return []
        return client.list_doc_nodes(library_id)
    except Exception as exc:  # noqa: BLE001
        logger.warning("HTTP doc-nodes 失败（节点清单为空）: %s", exc)
        return []


def _table_blocks(library_id: str, doc_ids: Optional[List[str]] = None) -> List[Dict[str, Any]]:
    """canonical 表格块：消费方（canonical_table_lookup）自带 try/except——按显式失败语义抛错。"""
    client = client_from_env()
    if client is None:
        raise RuntimeError("ANGINEER_DOCS_API_URL 未配置（HTTP table_blocks 不可用）")
    return client.table_blocks(library_id, doc_ids)


class _EngtoolToolShim:
    """单个外部工具的执行面：``run(**kwargs)`` → HTTP engtool-run。"""

    def __init__(self, name: str) -> None:
        self.name = name

    def run(self, **kwargs: Any) -> Any:
        client = client_from_env()
        if client is None:
            raise RuntimeError("ANGINEER_DOCS_API_URL 未配置（HTTP engtool 不可用）")
        return client.run_engtool(self.name, kwargs)


class _EngtoolRegistryShim:
    """注册表 duck-type（对齐 engtools ToolRegistry 的引擎消费面：get_tool(name)）。"""

    @staticmethod
    def get_tool(name: str) -> _EngtoolToolShim:
        # 不在此判存在性（校验在服务端）：404 时 run() 抛 LookupError("Tool not found: …")，
        # 与进程内 EngtoolAdapter 的 LookupError 语义对齐。
        return _EngtoolToolShim(name)


def _engtool_registry() -> Any:
    return _EngtoolRegistryShim()


def register_http_ports() -> bool:
    """注册六端口 HTTP 适配器；幂等，返回是否完成注册。"""
    if not http_ports_enabled():
        logger.info(
            "HTTP 端口适配器未注册（未配置 ANGINEER_DOCS_API_URL 或 ANGINEER_HTTP_PORTS=0）"
        )
        return False
    ports.register_agent_search(
        normalize_query=_normalize_query,
        relevant_citations=_relevant_citations,
        table_blocks=_table_blocks,
        engtool_registry=_engtool_registry,
    )
    ports.register_local_rerank(_local_rerank)
    ports.register_local_nodes_loader(_local_nodes_loader)
    url = os.getenv("ANGINEER_DOCS_API_URL", "").strip()
    logger.info(
        "HTTP 端口适配器已注册（→ %s）：normalize_query / relevant_citations / table_blocks / "
        "engtool_registry / local_rerank / local_nodes_loader",
        url,
    )
    return True
