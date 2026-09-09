"""Docs 检索 HTTP client（3b）：angineer-core → docs-api 内部检索端点。

未配置 ANGINEER_DOCS_API_URL 时 client_from_env 返回 None，调用方回退本地进程内检索。
设 ANGINEER_DISABLE_LOCAL_FALLBACK=1 可禁用本地回退（服务化/多容器部署时强制全 HTTP，
避免跨进程直读 SQLite 的共享数据库反模式）。
"""
import logging
import os
from typing import Any, Dict, List, Optional

import requests

from docs_core.step09_query.protocols.contracts import KnowledgeNode, RetrievedItem

logger = logging.getLogger(__name__)


def local_fallback_disabled() -> bool:
    """ANGINEER_DISABLE_LOCAL_FALLBACK=1 时禁用进程内 SQLite 直读回退。"""
    return os.getenv("ANGINEER_DISABLE_LOCAL_FALLBACK", "").strip().lower() in ("1", "true", "yes", "on")


class DocsRetrievalClient:
    """调用 docs-api /api/knowledge/internal/retrieve，返回 RetrievedItem 列表。"""

    def __init__(self, base_url: str, timeout: float = 30.0) -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout

    def retrieve(
        self,
        *,
        mode: str,
        query: str,
        library_id: str,
        doc_ids: Optional[List[str]] = None,
        top_k: int = 20,
        task_type: str = "content_qa",
        filters: Any = None,
    ) -> List[RetrievedItem]:
        payload = {
            "query": query,
            "library_id": library_id,
            "doc_ids": list(doc_ids or []),
            "top_k": top_k,
            "task_type": task_type,
            "filters": filters,
            "mode": mode,
        }
        resp = requests.post(
            f"{self.base_url}/api/knowledge/internal/retrieve",
            json=payload,
            timeout=self.timeout,
        )
        if resp.status_code != 200:
            raise RuntimeError(f"docs-api retrieve status {resp.status_code}")
        data = resp.json()
        if data.get("error"):
            raise RuntimeError(str(data["error"]))
        return [RetrievedItem.model_validate(item) for item in data.get("items") or []]

    def entity_search(
        self,
        *,
        query: str,
        library_id: str,
        limit: int = 20,
    ) -> List[Dict[str, Any]]:
        """调用 docs-api /internal/entity-search，返回序列化实体 dict 列表。"""
        resp = requests.post(
            f"{self.base_url}/api/knowledge/internal/entity-search",
            json={"query": query, "library_id": library_id, "limit": limit},
            timeout=self.timeout,
        )
        if resp.status_code != 200:
            raise RuntimeError(f"docs-api entity-search status {resp.status_code}")
        data = resp.json()
        if data.get("error"):
            raise RuntimeError(str(data["error"]))
        return list(data.get("entities") or [])

    def list_doc_nodes(self, library_id: str) -> List[KnowledgeNode]:
        """调用 docs-api /internal/doc-nodes，返回 KnowledgeNode 列表。"""
        resp = requests.get(
            f"{self.base_url}/api/knowledge/internal/doc-nodes",
            params={"library_id": library_id},
            timeout=self.timeout,
        )
        if resp.status_code != 200:
            raise RuntimeError(f"docs-api doc-nodes status {resp.status_code}")
        data = resp.json()
        if data.get("error"):
            raise RuntimeError(str(data["error"]))
        return [KnowledgeNode.model_validate(item) for item in data.get("nodes") or []]

    def graph_append_note(self, *, entity_id: str, marker: str) -> None:
        """调用 docs-api /internal/graph-append-note，向实体描述追加标记。"""
        resp = requests.post(
            f"{self.base_url}/api/knowledge/internal/graph-append-note",
            json={"entity_id": entity_id, "marker": marker},
            timeout=self.timeout,
        )
        if resp.status_code != 200:
            raise RuntimeError(f"docs-api graph-append-note status {resp.status_code}")
        data = resp.json()
        if data.get("error"):
            raise RuntimeError(str(data["error"]))


def client_from_env() -> Optional[DocsRetrievalClient]:
    """配置 ANGINEER_DOCS_API_URL 时返回 client，否则 None（回退本地检索）。"""
    url = os.getenv("ANGINEER_DOCS_API_URL", "").strip()
    if not url:
        return None
    timeout = float(os.getenv("ANGINEER_DOCS_API_TIMEOUT", "30") or "30")
    return DocsRetrievalClient(url, timeout=timeout)
