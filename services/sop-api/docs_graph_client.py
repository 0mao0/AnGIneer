"""docs-api 图谱只读适配器：generation-bundle 一次取全，内存物化 GraphReader。

plan-sop-api-l4 阶段 2（Task 2.4）。sop-core 的 SopPathGenerator 只认
sop_core.graph_port.GraphReader；本适配器用 docs-api 的
`GET /api/graphs/sop-generation-bundle` 快照在内存实现该协议，
sop-api 进程内不再出现 docs_core import。

快照语义：生成期间图谱以拉取时刻为准（生成是短事务，可接受）。
"""
import logging
import os
from types import SimpleNamespace
from typing import Any, List, Optional

import requests

logger = logging.getLogger(__name__)


def _default_docs_api_url() -> str:
    # 容器内走 compose 服务名；本机 dev 经 .env 覆盖为 http://127.0.0.1:8790
    return (os.getenv("DOCS_API_URL") or "").strip() or "http://docs-api:8790"


def _rec(**kwargs: Any) -> SimpleNamespace:
    return SimpleNamespace(**kwargs)


class HttpGraphReader:
    """sop_core.graph_port.GraphReader 的 docs-api HTTP 实现（只读、bundle 快照）。"""

    def __init__(self, bundle: dict, session: Optional[requests.Session] = None):
        self.session = session or requests.Session()
        self.session.trust_env = False  # 绕系统代理（httpx 同款教训 eec9438）
        self._library_id = bundle.get("library_id", "")
        self._doc_id = bundle.get("doc_id", "")
        self._entities = [_rec(**e) for e in bundle.get("entities", [])]
        self._entities_by_id = {e.entity_id: e for e in self._entities}
        self._relations = [_rec(**r) for r in bundle.get("relations", [])]
        self._frameworks = [_rec(**f) for f in bundle.get("frameworks", [])]
        raw = bundle.get("enrichments", {})
        self._principles = {eid: [_rec(**p) for p in v.get("principles", [])] for eid, v in raw.items()}
        self._warnings = {eid: [_rec(**w) for w in v.get("warnings", [])] for eid, v in raw.items()}
        self._examples = {eid: [_rec(**ex) for ex in v.get("examples", [])] for eid, v in raw.items()}

    @classmethod
    def from_bundle(
        cls,
        library_id: str,
        doc_id: str,
        base_url: Optional[str] = None,
        timeout: float = 20.0,
    ) -> Optional["HttpGraphReader"]:
        """拉取 bundle 构建适配器；失败返回 None（调用方降级为无图谱骨架生成）。"""
        url = f"{(base_url or _default_docs_api_url()).rstrip('/')}/api/graphs/sop-generation-bundle"
        session = requests.Session()
        session.trust_env = False
        try:
            resp = session.get(
                url, params={"library_id": library_id, "doc_id": doc_id}, timeout=timeout
            )
            resp.raise_for_status()
            return cls(resp.json(), session=session)
        except Exception as exc:  # noqa: BLE001
            logger.warning("图谱 bundle 拉取失败（%s）: %s", url, exc)
            return None

    # ---- GraphReader 协议 ----
    def get_entity_by_name(self, name: str, library_id: Optional[str] = None) -> Optional[Any]:
        for entity in self._entities:
            if entity.name == name:
                return entity
        return None

    def get_entity(self, entity_id: str) -> Optional[Any]:
        return self._entities_by_id.get(entity_id)

    def list_entities_by_doc(self, library_id: str, doc_id: str) -> List[Any]:
        if library_id and library_id != self._library_id:
            return []
        if doc_id and doc_id != self._doc_id:
            return []
        return list(self._entities)

    def get_frameworks_by_doc(self, library_id: str, doc_id: str) -> List[Any]:
        if library_id and library_id != self._library_id:
            return []
        if doc_id and doc_id != self._doc_id:
            return []
        return list(self._frameworks)

    def get_relations_by_entity(self, entity_id: str, direction: str = "both", **_: Any) -> List[Any]:
        if direction == "outgoing":
            return [r for r in self._relations if r.source_id == entity_id]
        if direction == "incoming":
            return [r for r in self._relations if r.target_id == entity_id]
        return [r for r in self._relations if entity_id in (r.source_id, r.target_id)]

    def get_principles_by_entity_ids(self, entity_ids: List[str]) -> List[Any]:
        return [p for eid in entity_ids for p in self._principles.get(eid, [])]

    def get_warnings_by_entity_ids(self, entity_ids: List[str]) -> List[Any]:
        return [w for eid in entity_ids for w in self._warnings.get(eid, [])]

    def get_examples_by_entity_ids(self, entity_ids: List[str]) -> List[Any]:
        return [ex for eid in entity_ids for ex in self._examples.get(eid, [])]
