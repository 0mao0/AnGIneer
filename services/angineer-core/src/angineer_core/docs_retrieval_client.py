"""Docs 检索 HTTP client（3b）：angineer-core → docs-api 内部检索端点。

未配置 ANGINEER_DOCS_API_URL 时 client_from_env 返回 None，调用方回退本地进程内检索。
"""
import logging
import os
from typing import Any, List, Optional

import requests

from docs_core.step09_query.protocols.contracts import RetrievedItem

logger = logging.getLogger(__name__)


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


def client_from_env() -> Optional[DocsRetrievalClient]:
    """配置 ANGINEER_DOCS_API_URL 时返回 client，否则 None（回退本地检索）。"""
    url = os.getenv("ANGINEER_DOCS_API_URL", "").strip()
    if not url:
        return None
    timeout = float(os.getenv("ANGINEER_DOCS_API_TIMEOUT", "30") or "30")
    return DocsRetrievalClient(url, timeout=timeout)
