"""docs-core [server]：retrieval-api 薄壳（检索 / 库册清单 / 原文回源 + health）。

对外最小面（DredgeAI 验收口径，2026-10-12；路径沿用内部服务，线契约逐位一致）：
- ``POST /api/knowledge/internal/retrieve``        五路召回融合检索（snake_case 线契约）
- ``POST /api/knowledge/internal/entity-search``   图谱实体检索
- ``GET  /api/knowledge/internal/doc-nodes``       文档节点清单（供对话壳 load_nodes）
- ``POST /api/knowledge/internal/normalize-query`` / ``/internal/rerank`` /
  ``/internal/relevant-citations`` / ``/internal/table-blocks`` / ``/internal/engtool-run``
  engine 端口 HTTP 面（见 ``engine_ports.py``；chat 壳 http_ports 适配器消费）
- ``GET  /api/knowledge/libraries``                库清单
- ``GET  /api/knowledge/stats``                    统计聚合（knowledge_stats 工具数据源）
- ``GET  /api/knowledge/documents/{doc_id}/download``  原文回源（``?kind=source|pdf``、
  ``?disposition=inline`` 支持内联呈示，按页定位由客户端 PDF 锚点或 Range 请求承担）
- ``GET  /health``                                 探活（含数据根/注册表挂载状态）

数据面全参数化：``ANGINEER_DATA_ROOT``（或 ``KNOWLEDGE_BASE_DIR``）定数据根；
``QDRANT_URL`` / ``DOCS_VECTORSTORE_PROVIDER`` / ``EMBEDDING_CONFIGS`` 等由 env 决定；
服务不内嵌数据、不读仓库工作树。

鉴权（可选）：设 ``ANGINEER_API_TOKEN``（或 ``API_TOKEN``）后，除 ``/health`` 外要求
``X-API-Key`` 头（或 ``Authorization: Bearer <token>``）；未设则不做校验。

启动：``uvicorn docs_core.server:app --host 127.0.0.1 --port 8310``
"""
import hmac
import logging
import mimetypes
import os
from datetime import datetime
from typing import Any, Dict, List, Optional

try:
    from fastapi import Depends, FastAPI, Header, HTTPException
    from fastapi.middleware.cors import CORSMiddleware
    from fastapi.responses import FileResponse
    from pydantic import BaseModel, Field
except ImportError as exc:  # pragma: no cover - 安装提示
    raise ImportError(
        "docs_core.server 需要 [server] extra（fastapi/uvicorn）。"
        "请安装：pip install 'angineer-docs-core[server]'"
    ) from exc

from docs_core import __version__ as _PKG_VERSION
from docs_core.docs_file_io import file_storage
from docs_core.docs_service import get_docs_service
from docs_core.knowledge_stats import compute_knowledge_stats
from docs_core.server.engine_ports import build_engine_ports_router
from docs_core.step09_query.retrieve_service import retrieve_knowledge

# root 日志兜底（同 docs-api/aichat-api）：库代码普遍用 logging.getLogger(__name__)
# 且不设 handler，不配 root 会让日志落 lastResort（stderr 裸格式）甚至静默丢失——
# 2026-10-12 DredgeAI 试用即因壳没配 logging 误判「警告没落日志」。basicConfig 幂等。
logging.basicConfig(
    level=os.getenv("ANGINEER_LOG_LEVEL", "INFO").upper(),
    format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)

logger = logging.getLogger("docs_core.server")

_PROCESS_STARTED_AT = datetime.now().isoformat()


def _env_token() -> str:
    return (os.getenv("ANGINEER_API_TOKEN") or os.getenv("API_TOKEN") or "").strip()


def _token_guard(
    x_api_key: str = Header(default=""), authorization: str = Header(default="")
) -> None:
    """可选 API Token 门（env 未设则放行；/health 不挂本依赖）。"""
    token = _env_token()
    if not token:
        return
    supplied = (x_api_key or "").strip()
    if not supplied and (authorization or "").lower().startswith("bearer "):
        supplied = authorization[7:].strip()
    if not hmac.compare_digest(supplied, token):
        raise HTTPException(status_code=401, detail="invalid API token")


class RetrieveInternalRequest(BaseModel):
    """检索请求（与内部服务 /api/knowledge/internal/retrieve 载荷逐位一致）。"""

    query: str
    library_id: str = "default"
    # 多库勾选：空=单库（library_id），非空=集合且 library_id 兼容=首项
    library_ids: List[str] = Field(default_factory=list)
    doc_ids: List[str] = Field(default_factory=list)
    top_k: int = 20
    task_type: str = "content_qa"
    filters: Optional[Dict[str, Any]] = None
    mode: str = "text"


class EntitySearchInternalRequest(BaseModel):
    query: str
    library_id: str = "default"
    limit: int = 20


def _serialize_entity(entity: Any) -> Dict[str, Any]:
    """GraphEntity dataclass → 可 JSON 序列化 dict（枚举取 value）。"""
    return {
        "entity_id": entity.entity_id,
        "name": entity.name,
        "layer": entity.layer.value,
        "aliases": list(entity.aliases or []),
        "description": entity.description or "",
        "source_doc": entity.source_doc or "",
        "source_clause": entity.source_clause or "",
        "library_id": entity.library_id,
        "status": entity.status.value,
        "proposed_doc_id": entity.proposed_doc_id or "",
        "proposed_by": entity.proposed_by or "",
        "reject_reason": entity.reject_reason or "",
        "reviewed_at": entity.reviewed_at or "",
        "reviewed_by": entity.reviewed_by or "",
        "created_at": entity.created_at or "",
        "updated_at": entity.updated_at or "",
    }


def create_app() -> FastAPI:
    app = FastAPI(
        title="AnGIneer Retrieval API (standalone shell)",
        description="独立宿主壳：检索 / 库册清单 / 原文回源（angineer-docs-core [server] extra）。",
        version=_PKG_VERSION,
    )

    _allowed_origins = [
        o.strip() for o in os.getenv("ALLOWED_ORIGINS", "*").split(",") if o.strip()
    ]
    app.add_middleware(
        CORSMiddleware,
        allow_origins=_allowed_origins,
        allow_methods=["*"],
        allow_headers=["*"],
        allow_credentials=False,
    )

    # engine 端口 HTTP 面（normalize-query / rerank / relevant-citations / table-blocks /
    # engtool-run）：供 chat 壳的 http_ports 适配器消费；与主仓库 docs-api 同批挂载保持镜像。
    app.include_router(
        build_engine_ports_router(),
        prefix="/api/knowledge",
        tags=["Engine Ports"],
        dependencies=[Depends(_token_guard)],
    )

    @app.post("/api/knowledge/internal/retrieve", dependencies=[Depends(_token_guard)])
    def retrieve_internal(request: RetrieveInternalRequest) -> Dict[str, Any]:
        return retrieve_knowledge(
            query=request.query,
            library_id=request.library_id,
            library_ids=request.library_ids or None,
            doc_ids=request.doc_ids,
            top_k=request.top_k,
            task_type=request.task_type,
            filters=request.filters,
            mode=request.mode,
        )

    @app.post("/api/knowledge/internal/entity-search", dependencies=[Depends(_token_guard)])
    def entity_search_internal(request: EntitySearchInternalRequest) -> Dict[str, Any]:
        from docs_core.step07_graph.graph_files import resolve_graph_db_for_library
        from docs_core.step07_graph.graph_store import GraphStore

        store = GraphStore(str(resolve_graph_db_for_library(request.library_id)))
        entities = store.search_entities(
            request.query, limit=request.limit, library_id=request.library_id
        )
        return {
            "entities": [_serialize_entity(entity) for entity in entities],
            "total": len(entities),
        }

    @app.get("/api/knowledge/internal/doc-nodes", dependencies=[Depends(_token_guard)])
    def list_doc_nodes_internal(library_id: str = "default") -> Dict[str, Any]:
        """返回指定库的 document 节点清单（KnowledgeNode 契约字段）。"""
        ks = get_docs_service()
        nodes = [
            node
            for node in ks.list_nodes(library_id)
            if getattr(node, "type", "") == "document"
        ]
        return {
            "nodes": [
                node.model_dump(mode="json") if hasattr(node, "model_dump") else dict(node)
                for node in nodes
            ],
            "total": len(nodes),
        }

    @app.get("/api/knowledge/libraries", dependencies=[Depends(_token_guard)])
    def list_knowledge_libraries():
        """库清单（含组/展示名；与内部服务同序列化）。"""
        return get_docs_service().list_libraries()

    @app.get("/api/knowledge/stats", dependencies=[Depends(_token_guard)])
    def get_knowledge_stats(library_id: Optional[str] = None):
        """知识库统计聚合（实现同 docs-api：docs_core.knowledge_stats 单一真相源）。"""
        return compute_knowledge_stats(library_id)

    @app.get(
        "/api/knowledge/documents/{doc_id}/download", dependencies=[Depends(_token_guard)]
    )
    def download_document_file(
        doc_id: str, kind: str = "source", disposition: str = "attachment"
    ):
        """按文档回源：kind=source 源文件 / kind=pdf PDF 转换文件。

        ``disposition=inline`` 供引用溯源内联呈示（PDF 可按页锚点定位）。
        """
        ks = get_docs_service()
        node = ks.get_node(doc_id)
        if not node:
            raise HTTPException(status_code=404, detail=f"文档不存在: {doc_id}")
        manifest = file_storage.get_doc_manifest(node.library_id, doc_id)
        path = manifest.get("render_pdf") if kind == "pdf" else manifest.get("source_file")
        if not path or not os.path.isfile(str(path)):
            raise HTTPException(status_code=404, detail="文件不存在或尚未生成")
        file_path = str(path)
        filename = os.path.basename(file_path)
        mime_type, _ = mimetypes.guess_type(file_path)
        inline = (disposition or "").strip().lower() == "inline"
        return FileResponse(
            file_path,
            filename=filename,
            media_type=mime_type or "application/octet-stream",
            content_disposition_type="inline" if inline else "attachment",
        )

    @app.get("/health")
    def health() -> Dict[str, Any]:
        """探活：引擎/数据根挂载状态 + 向量库配置形态（不触发网络请求）。"""
        report: Dict[str, Any] = {
            "service": "retrieval-api",
            "status": "ok",
            "version": _PKG_VERSION,
            "started_at": _PROCESS_STARTED_AT,
            "pid": os.getpid(),
        }
        errors: List[str] = []
        try:
            from docs_core.paths import resolve_knowledge_base_dir

            kb = resolve_knowledge_base_dir()
            exists = kb.exists()
            report["data_root"] = {"knowledge_base_dir": str(kb), "exists": exists}
            if not exists:
                errors.append(f"knowledge base dir not found: {kb}")
        except Exception as exc:  # noqa: BLE001
            report["data_root"] = {"error": str(exc)}
            errors.append(str(exc))
        try:
            from docs_core.library_registry import resolve_registry_db_path

            reg = resolve_registry_db_path()
            report["registry"] = {"path": str(reg), "exists": reg.exists()}
        except Exception as exc:  # noqa: BLE001
            report["registry"] = {"error": str(exc)}
        report["vectorstore"] = {
            "provider": (os.getenv("DOCS_VECTORSTORE_PROVIDER") or "").strip() or None,
            "qdrant_url": (os.getenv("QDRANT_URL") or "").strip() or None,
        }
        report["auth"] = {"token_required": bool(_env_token())}
        if errors:
            report["status"] = "degraded"
            report["errors"] = errors
        return report

    return app


app = create_app()
