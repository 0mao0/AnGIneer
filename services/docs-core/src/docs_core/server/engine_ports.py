"""engine 端口 HTTP 面：进程内端口（agent_port 家族）的等价内部端点。

2026-10-12 独立壳修复（DredgeAI 试用反馈）：chat 壳无组装层注册进程内端口，
引擎多处按「端口未注册」降级——citations 恒空 / phrase rerank 跳过 / 条款号不
归一化 / canonical 查表找不到册 / calculator 一调用即 LookupError。本模块把
这些端口的 docs-core 实现以 HTTP 形态暴露，由壳侧 ``angineer_core.server.http_ports``
适配器消费——与进程内装配**同一份实现**，语义逐位一致。

挂载方：retrieval 壳（``docs_core.server:app``）与主仓库 docs-api 同批挂载
（prefix ``/api/knowledge``，路径 ``/internal/*``），两端面保持镜像。

端点清单：
- POST /internal/normalize-query      中文数字条款号归一化（agent_port.normalize_query）
- POST /internal/rerank               本地 phrase rerank（retrieval.reranker.rerank_candidates）
- POST /internal/relevant-citations   引用挑选（agent_port.relevant_citations）
- POST /internal/table-blocks         canonical 表格块批量取数（agent_port.table_blocks_provider）
- POST /internal/engtool-run          外部 engtool 执行（agent_port.engtool_registry）
"""
import logging
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from ..step09_query.protocols.contracts import RetrievedItem

logger = logging.getLogger(__name__)


class NormalizeQueryRequest(BaseModel):
    query: str


class RerankRequest(BaseModel):
    query: str
    task_type: str = "content_qa"
    candidates: List[RetrievedItem] = Field(default_factory=list)


class RelevantCitationsRequest(BaseModel):
    query: str
    items: List[RetrievedItem] = Field(default_factory=list)
    limit: Optional[int] = None  # None=全部（解析表覆盖所有 cite）；正整数=展示型截断


class TableBlocksRequest(BaseModel):
    library_id: str = "default"
    doc_ids: List[str] = Field(default_factory=list)


class EngtoolRunRequest(BaseModel):
    name: str
    kwargs: Dict[str, Any] = Field(default_factory=dict)


def build_engine_ports_router() -> APIRouter:
    """构造端口端点路由（不直接挂载；由调用方定前缀与鉴权依赖）。"""
    router = APIRouter()

    @router.post("/internal/normalize-query")
    def normalize_query_endpoint(request: NormalizeQueryRequest) -> Dict[str, Any]:
        from ..step09_query import agent_port

        return {"query": agent_port.normalize_query(request.query)}

    @router.post("/internal/rerank")
    def rerank_endpoint(request: RerankRequest) -> Dict[str, Any]:
        from ..step09_query.retrieval.reranker import rerank_candidates

        ranked = rerank_candidates(request.query, request.task_type, list(request.candidates))
        return {"candidates": ranked}

    @router.post("/internal/relevant-citations")
    def relevant_citations_endpoint(request: RelevantCitationsRequest) -> Dict[str, Any]:
        from ..step09_query import agent_port

        citations = agent_port.relevant_citations(
            request.query, list(request.items), request.limit
        )
        return {"citations": citations}

    @router.post("/internal/table-blocks")
    def table_blocks_endpoint(request: TableBlocksRequest) -> Dict[str, Any]:
        from ..step09_query import agent_port

        # doc_ids 空 = 全库找文件（与进程内端口调用语义一致）
        blocks = agent_port.table_blocks_provider(
            request.library_id, list(request.doc_ids) or None
        )
        return {"blocks": blocks}

    @router.post("/internal/engtool-run")
    def engtool_run_endpoint(request: EngtoolRunRequest) -> Dict[str, Any]:
        """外部工具执行：404=工具不存在（对齐进程内 LookupError("Tool not found")）、
        503=注册表不可用（engtools 包缺失等）、500=执行异常。"""
        from ..step09_query import agent_port

        try:
            registry = agent_port.engtool_registry()
            tool = registry.get_tool(request.name) if registry is not None else None
        except Exception as exc:  # noqa: BLE001 —— 适配器不可用按 503 上报
            raise HTTPException(status_code=503, detail=f"tool registry unavailable: {exc}")
        if tool is None:
            raise HTTPException(status_code=404, detail=f"Tool not found: {request.name}")
        try:
            result = tool.run(**request.kwargs)
        except Exception as exc:  # noqa: BLE001 —— 工具异常按 500 上报（引擎侧转工具错误）
            raise HTTPException(status_code=500, detail=f"tool {request.name} failed: {exc}")
        if result is None:
            result = {}
        if not isinstance(result, dict):
            result = {"result": result}
        return {"result": result}

    return router
