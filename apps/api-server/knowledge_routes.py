"""知识库路由与解析调度入口。"""
import mimetypes
import os
import shutil
import tempfile
import threading
import traceback
import uuid
from pathlib import Path
from typing import Any, Dict, Optional
from urllib.parse import quote

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel

from docs_core.canonical import build_canonical_document
from docs_core.knowledge_service import knowledge_service
from docs_core.parser.mineru_parser import mineru_parser
from docs_core.retrieval.contracts import KnowledgeQueryRequest, KnowledgeQueryResponse
from docs_core.retrieval.service import knowledge_query_service
from docs_core.structured.result_store_json import (
    build_structured_index_for_doc,
    get_doc_blocks_graph,
)
from docs_core.structured.result_store_json import file_storage


knowledge_router = APIRouter()
preview_router = APIRouter()


class KnowledgeParseRequest(BaseModel):
    """文档解析请求。"""

    library_id: str
    doc_id: str
    file_path: Optional[str] = None


class KnowledgeStructuredIndexRequest(BaseModel):
    """结构化索引重建请求。"""

    library_id: str
    doc_id: str
    strategy: Optional[str] = "A_structured"


class DocBlocksGraphRequest(BaseModel):
    """文档块图谱请求。"""

    library_id: str
    doc_id: str


class KnowledgeRetrieveRequest(BaseModel):
    """知识检索调试请求。"""

    query: str
    library_id: str = "default"
    doc_ids: list[str] = []
    top_k: int = 5


class ParseOrchestrator:
    """负责 API 层与解析主链之间的编排。"""

    def __init__(self) -> None:
        self._threads: Dict[str, threading.Thread] = {}

    # 注册或补全文档节点，确保解析主链使用统一文档标识。
    def ensure_document(self, library_id: str, file_path: str, doc_id: Optional[str] = None) -> str:
        node = knowledge_service.register_document(library_id=library_id, file_path=file_path, doc_id=doc_id)
        return node.id

    # 创建解析任务并启动后台线程。
    def create_parse_task(self, library_id: str, doc_id: str, file_path: str) -> Dict[str, Any]:
        task_id = f"parse-{uuid.uuid4().hex[:12]}"
        task = knowledge_service.create_parse_task(task_id, library_id, doc_id)
        knowledge_service.update_node(
            doc_id,
            status="processing",
            parse_progress=0,
            parse_stage="queued",
            parse_error=None,
            parse_task_id=task_id,
        )
        worker = threading.Thread(
            target=self._run_parse_task,
            args=(task_id, library_id, doc_id, file_path),
            daemon=True,
            name=f"parse-task-{task_id}",
        )
        self._threads[task_id] = worker
        worker.start()
        return {
            "task_id": task.id,
            "doc_id": doc_id,
            "status": task.status,
            "progress": task.progress,
            "stage": task.stage,
        }

    # 返回当前任务状态。
    def get_parse_task(self, task_id: str) -> Optional[Dict[str, Any]]:
        task = knowledge_service.get_parse_task(task_id)
        if not task:
            return None
        return task.model_dump(mode="json")

    # 在后台执行文档解析并同步状态。
    def _run_parse_task(self, task_id: str, library_id: str, doc_id: str, file_path: str) -> None:
        temp_output_dir = tempfile.mkdtemp(prefix=f"parse-{doc_id}-")
        try:
            self._update_progress(task_id, doc_id, status="processing", progress=5, stage="preparing")
            source_path = file_storage.ensure_doc_source_file(library_id, doc_id, file_path=file_path)
            if not source_path:
                raise RuntimeError("源文件不存在或无法复制到规范目录")

            self._update_progress(task_id, doc_id, progress=20, stage="parsing")
            parse_result = mineru_parser.parse_document(input_path=source_path, output_dir=temp_output_dir)
            if not parse_result.get("success"):
                raise RuntimeError(parse_result.get("error") or "MinerU 解析失败")

            markdown_path = parse_result.get("md_file")
            if markdown_path:
                with open(markdown_path, "r", encoding="utf-8") as handle:
                    file_storage.save_markdown(library_id, doc_id, handle.read())
            file_storage.save_parse_artifacts(library_id, doc_id, temp_output_dir)
            node = knowledge_service.get_node(doc_id)
            canonical_document = build_canonical_document(
                library_id=library_id,
                doc_id=doc_id,
                title=node.title if node else doc_id,
            )
            file_storage.save_middle_json(
                library_id,
                doc_id,
                canonical_document.model_dump(mode="json"),
            )

            self._update_progress(task_id, doc_id, progress=70, stage="indexing")
            build_structured_index_for_doc(
                library_id=library_id,
                doc_id=doc_id,
                strategy="A_structured",
                options={"use_llm": True},
            )

            self._update_progress(task_id, doc_id, progress=100, stage="completed", status="completed")
        except Exception as exc:
            error_message = f"{exc}\n{traceback.format_exc()}"
            knowledge_service.update_parse_task(
                task_id,
                status="failed",
                progress=100,
                stage="failed",
                error=error_message,
            )
            knowledge_service.update_node(
                doc_id,
                status="failed",
                parse_progress=100,
                parse_stage="failed",
                parse_error=error_message,
                parse_task_id=task_id,
            )
        finally:
            self._threads.pop(task_id, None)
            shutil.rmtree(temp_output_dir, ignore_errors=True)

    # 同步更新任务和节点的解析进度。
    def _update_progress(
        self,
        task_id: str,
        doc_id: str,
        progress: int,
        stage: str,
        status: str = "processing",
    ) -> None:
        knowledge_service.update_parse_task(task_id, status=status, progress=progress, stage=stage, error=None)
        knowledge_service.update_node(
            doc_id,
            status="completed" if status == "completed" else "processing",
            parse_progress=progress,
            parse_stage=stage,
            parse_error=None,
            parse_task_id=task_id,
        )


parse_orchestrator = ParseOrchestrator()


# 按策略分发文档投影构建。
def build_projection_for_doc(library_id: str, doc_id: str, strategy: str = "A_structured") -> Dict[str, Any]:
    if strategy != "A_structured":
        raise ValueError(f"Unsupported strategy: {strategy}")
    return build_structured_index_for_doc(library_id, doc_id, strategy)


# 返回文件预览允许访问的根目录列表。
def _allowed_roots() -> list[str]:
    storage_root = os.path.abspath(str(file_storage.base_dir))
    repo_root = Path(__file__).resolve().parents[2]
    knowledge_root = os.path.abspath(str(repo_root / "data" / "knowledge_base"))
    roots = [knowledge_root]
    if storage_root not in roots:
        roots.append(storage_root)
    return roots


# 判断目标路径是否位于允许的根目录下。
def _is_path_allowed(target_path: str, roots: list[str]) -> bool:
    for root in roots:
        try:
            if os.path.commonpath([target_path, root]).lower() == root.lower():
                return True
        except ValueError:
            continue
    return False


# 创建解析任务并交给编排层执行。
@knowledge_router.post("/parse")
async def create_parse_task(request: KnowledgeParseRequest) -> Dict[str, Any]:
    if not request.file_path:
        raise HTTPException(status_code=400, detail="缺少文档文件路径")
    source_path = Path(request.file_path)
    if not source_path.exists():
        raise HTTPException(status_code=404, detail="源文件不存在")

    doc_id = parse_orchestrator.ensure_document(
        library_id=request.library_id,
        file_path=str(source_path),
        doc_id=request.doc_id,
    )
    return parse_orchestrator.create_parse_task(
        library_id=request.library_id,
        doc_id=doc_id,
        file_path=str(source_path),
    )


# 查询解析任务状态。
@knowledge_router.get("/parse/tasks/{task_id}")
@knowledge_router.get("/parse/{task_id}", include_in_schema=False)
async def get_parse_status(task_id: str) -> Dict[str, Any]:
    task = parse_orchestrator.get_parse_task(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    return task


# 手动重建指定文档的策略投影。
@knowledge_router.post("/parse/structured-index")
async def build_structured_index(request: KnowledgeStructuredIndexRequest) -> Dict[str, Any]:
    try:
        result = build_projection_for_doc(request.library_id, request.doc_id, request.strategy or "A_structured")
        return {"status": "success", "data": result}
    except Exception as error:
        raise HTTPException(status_code=500, detail=str(error))


# 获取文档的块图谱视图。
@knowledge_router.post("/parse/doc-blocks-graph")
async def get_doc_blocks_graph_view(request: DocBlocksGraphRequest) -> Dict[str, Any]:
    try:
        graph = get_doc_blocks_graph(request.library_id, request.doc_id)
        if not graph:
            raise HTTPException(status_code=404, detail="Graph data not found. Please run structured-index first.")
        return {"status": "success", "data": graph}
    except HTTPException:
        raise
    except Exception as error:
        raise HTTPException(status_code=500, detail=str(error))


# 执行统一知识查询，按路由返回证据化答案。
@knowledge_router.post("/query", response_model=KnowledgeQueryResponse)
async def query_knowledge(request: KnowledgeQueryRequest) -> KnowledgeQueryResponse:
    try:
        return knowledge_query_service.query(request)
    except Exception as error:
        raise HTTPException(status_code=500, detail=str(error))


# 返回检索候选，便于前端调试和后续评测。
@knowledge_router.post("/retrieve")
async def retrieve_knowledge(request: KnowledgeRetrieveRequest) -> Dict[str, Any]:
    try:
        response = knowledge_query_service.query(
            KnowledgeQueryRequest(
                query=request.query,
                library_id=request.library_id,
                doc_ids=request.doc_ids,
                top_k=request.top_k,
                include_retrieved=True,
                include_debug=True,
            )
        )
        return {
            "query_id": response.query_id,
            "task_type": response.task_type,
            "strategy": response.strategy,
            "answer": response.answer,
            "citations": [item.model_dump(mode="json") for item in response.citations],
            "retrieved_items": [item.model_dump(mode="json") for item in response.retrieved_items],
            "confidence": response.confidence,
            "latency_ms": response.latency_ms,
            "debug": response.debug,
        }
    except Exception as error:
        raise HTTPException(status_code=500, detail=str(error))


# 按绝对路径预览文件。
@preview_router.get("/files")
def get_file_for_preview(path: str):
    normalized_path = os.path.abspath(os.path.normpath(path))
    allowed_roots = _allowed_roots()
    if not _is_path_allowed(normalized_path, allowed_roots):
        raise HTTPException(status_code=403, detail="Forbidden path")
    if not os.path.exists(normalized_path):
        raise HTTPException(status_code=404, detail="File not found")
    if not os.path.isfile(normalized_path):
        raise HTTPException(status_code=400, detail="Path is not a file")

    filename = os.path.basename(normalized_path)
    encoded_filename = quote(filename)
    mime_type, _ = mimetypes.guess_type(normalized_path)
    if not mime_type:
        mime_type = "application/octet-stream"

    base_headers = {
        "Accept-Ranges": "bytes",
        "Content-Disposition": f"inline; filename*=utf-8''{encoded_filename}",
        "Access-Control-Expose-Headers": "Accept-Ranges, Content-Range, Content-Length, Content-Disposition",
    }

    return FileResponse(
        normalized_path,
        filename=filename,
        media_type=mime_type,
        headers=base_headers,
    )


__all__ = [
    "DocBlocksGraphRequest",
    "KnowledgeParseRequest",
    "KnowledgeStructuredIndexRequest",
    "ParseOrchestrator",
    "build_projection_for_doc",
    "build_structured_index",
    "create_parse_task",
    "query_knowledge",
    "retrieve_knowledge",
    "get_doc_blocks_graph_view",
    "get_file_for_preview",
    "get_parse_status",
    "knowledge_router",
    "parse_orchestrator",
    "preview_router",
]
