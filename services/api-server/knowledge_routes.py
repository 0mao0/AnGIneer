"""知识库路由与解析调度入口"""
import logging
import mimetypes
import os
import shutil
import tempfile
import threading
import traceback
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional
from urllib.parse import quote

from fastapi import APIRouter, HTTPException, UploadFile, File as FastAPIFile, Form
from fastapi.responses import FileResponse
from pydantic import BaseModel

from docs_core.knowledge_service import get_knowledge_service, KnowledgeNode
from docs_core.ingest.extract.mineru_parser import mineru_parser
from docs_core.ingest.store.assets_file_store import (
    build_structured_index_for_doc,
    get_doc_blocks_graph,
)
from docs_core.ingest.store.assets_file_store import file_storage
from docs_core.ingest.store.blocks_sql_store import resolve_repo_root

logger = logging.getLogger(__name__)


knowledge_router = APIRouter()
preview_router = APIRouter()


# --- Pydantic 请求模型 ---


class KnowledgeLibraryCreate(BaseModel):
    """创建知识库请求。"""
    library_id: str
    name: str
    description: Optional[str] = ''


class KnowledgeNodeCreate(BaseModel):
    """创建知识库节点请求。"""
    title: str
    node_type: str
    library_id: Optional[str] = 'default'
    parent_id: Optional[str] = None
    visible: Optional[bool] = True
    sort_order: Optional[int] = 0


class KnowledgeNodeUpdate(BaseModel):
    """更新知识库节点请求。"""
    title: Optional[str] = None
    parent_id: Optional[str] = None
    visible: Optional[bool] = None
    sort_order: Optional[int] = None


class KnowledgeStrategyUpdate(BaseModel):
    """更新文档策略请求。"""
    strategy: str


class KnowledgeStructuredIndexRequest(BaseModel):
    """结构化索引重建请求。"""
    library_id: str
    doc_id: str
    strategy: Optional[str] = "doc_blocks_graph_v1"


class KnowledgeDocumentUpdate(BaseModel):
    """更新文档内容请求。"""
    content: str


class KnowledgeReferenceSearchRequest(BaseModel):
    """知识引用搜索请求。"""
    library_id: str
    query: str
    limit: int = 10
    types: List[str] = ["content", "table", "formula", "figure"]
    current_doc_id: Optional[str] = None


class KnowledgeDocumentBlockUpdate(BaseModel):
    """更新文档结构节点内容请求。"""
    plain_text: Optional[str] = None
    math_content: Optional[str] = None
    table_html: Optional[str] = None
    title: Optional[str] = None
    caption: Optional[str] = None
    footnote: Optional[str] = None
    parent_block_uid: Optional[str] = None
    derived_title_level: Optional[int] = None
    merge_into_block_uid: Optional[str] = None


class KnowledgeDocumentBatchBlockOperation(BaseModel):
    """批量执行文档结构节点操作请求。"""
    operation: str
    blockIds: List[str]
    targetBlockId: Optional[str] = None
    splitSegments: Optional[List[Dict[str, Any]]] = None
    levelDelta: Optional[int] = None
    targetLevel: Optional[int] = None


class KnowledgeParseRequest(BaseModel):
    """文档解析请求。"""
    library_id: str
    doc_id: str
    file_path: Optional[str] = None
    parse_options: Optional["KnowledgeParseOptions"] = None


class KnowledgeParseOptions(BaseModel):
    """文档解析参数。"""
    use_llm: bool = True
    llm_model: Optional[str] = None


class DocBlocksGraphRequest(BaseModel):
    """文档块图谱请求。"""
    library_id: str
    doc_id: str


class DocBlocksGraphSummaryRequest(BaseModel):
    """文档块图谱摘要请求，仅返回树结构骨架不含 bbox/stats。"""
    library_id: str
    doc_id: str


# --- 解析编排器 ---


class ParseOrchestrator:
    """负责 API 层与解析主链之间的编排。"""

    def __init__(self) -> None:
        self._threads: Dict[str, threading.Thread] = {}

    def ensure_document(self, library_id: str, file_path: str, doc_id: Optional[str] = None) -> str:
        """注册或补全文档节点，确保解析主链使用统一文档标识。"""
        ks = get_knowledge_service()
        node = ks.register_document(library_id=library_id, file_path=file_path, doc_id=doc_id)
        return node.id

    def create_parse_task(
        self,
        library_id: str,
        doc_id: str,
        file_path: str,
        parse_options: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """创建解析任务并启动后台线程。"""
        ks = get_knowledge_service()
        task_id = f"parse-{uuid.uuid4().hex[:12]}"
        task = ks.create_parse_task(task_id, library_id, doc_id)
        ks.update_node(
            doc_id,
            status="processing",
            parse_progress=0,
            parse_stage="queued",
            parse_error=None,
            parse_task_id=task_id,
        )
        worker = threading.Thread(
            target=self._run_parse_task,
            args=(task_id, library_id, doc_id, file_path, parse_options or {}),
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

    def get_parse_task(self, task_id: str) -> Optional[Dict[str, Any]]:
        """返回当前任务状态。"""
        ks = get_knowledge_service()
        task = ks.get_parse_task(task_id)
        if not task:
            return None
        return task.model_dump(mode="json")

    def cancel_parse_task(self, task_id: str) -> bool:
        """取消正在运行的解析任务。"""
        if task_id not in self._threads:
            return False
        thread = self._threads[task_id]
        if not thread.is_alive():
            return False
        ks = get_knowledge_service()
        task = ks.get_parse_task(task_id)
        if task and task.status in ("queued", "processing"):
            ks.update_parse_task(
                task_id,
                status="cancelled",
                progress=task.progress,
                stage=task.stage,
                error="用户手动取消任务",
            )
            doc_id = task.doc_id
            ks.update_node(
                doc_id,
                status="failed",
                parse_progress=task.progress,
                parse_stage="cancelled",
                parse_error="用户手动取消任务",
                parse_task_id=task_id,
            )
        self._threads.pop(task_id, None)
        return True

    def retry_parse_task(self, doc_id: str) -> Optional[Dict[str, Any]]:
        """重试解析任务（支持已完成、失败、取消、待处理状态的文档重新解析）。"""
        ks = get_knowledge_service()
        node = ks.get_node(doc_id)
        if not node:
            return None
        if node.status == "processing":
            raise ValueError(f"节点 {doc_id} 正在解析中，请先取消当前任务")
        file_path = node.file_path
        if not file_path:
            raise ValueError(f"节点 {doc_id} 缺少文件路径信息")
        return self.create_parse_task(
            library_id=node.library_id,
            doc_id=doc_id,
            file_path=file_path,
        )

    def _run_parse_task(
        self,
        task_id: str,
        library_id: str,
        doc_id: str,
        file_path: str,
        parse_options: Dict[str, Any],
    ) -> None:
        """在后台执行文档解析并同步状态。"""
        ks = get_knowledge_service()
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

            self._update_progress(task_id, doc_id, progress=70, stage="indexing")
            use_llm = bool(parse_options.get("use_llm", True))
            llm_model = str(parse_options.get("llm_model") or "").strip() or None
            build_structured_index_for_doc(
                library_id=library_id,
                doc_id=doc_id,
                strategy="doc_blocks_graph_v1",
                options={
                    "use_llm": use_llm,
                    "llm_model": llm_model,
                },
            )

            self._update_progress(task_id, doc_id, progress=100, stage="completed", status="completed")
        except Exception as exc:
            error_message = f"{type(exc).__name__}: {exc}"
            error_detail = traceback.format_exc()
            logger.error(f"解析任务 {task_id} 失败: {error_message}\n{error_detail}")
            try:
                ks.update_parse_task(
                    task_id,
                    status="failed",
                    progress=100,
                    stage="failed",
                    error=error_message,
                )
                ks.update_node(
                    doc_id,
                    status="failed",
                    parse_progress=100,
                    parse_stage="failed",
                    parse_error=error_message,
                    parse_task_id=task_id,
                )
            except Exception as update_exc:
                logger.error(f"更新任务状态失败: {update_exc}")
        finally:
            self._threads.pop(task_id, None)
            shutil.rmtree(temp_output_dir, ignore_errors=True)

    def _update_progress(
        self,
        task_id: str,
        doc_id: str,
        progress: int,
        stage: str,
        status: str = "processing",
    ) -> None:
        """同步更新任务和节点的解析进度。"""
        ks = get_knowledge_service()
        ks.update_parse_task(task_id, status=status, progress=progress, stage=stage, error=None)
        ks.update_node(
            doc_id,
            status="completed" if status == "completed" else "processing",
            parse_progress=progress,
            parse_stage=stage,
            parse_error=None,
            parse_task_id=task_id,
        )


parse_orchestrator = ParseOrchestrator()


# --- 辅助函数 ---


def normalize_parse_options(options: Optional[KnowledgeParseOptions]) -> Dict[str, Any]:
    """归一化解析参数，确保前后端传参格式稳定。"""
    if options is None:
        return {"use_llm": True}
    llm_model = str(options.llm_model or "").strip() or None
    return {
        "use_llm": bool(options.use_llm),
        "llm_model": llm_model,
    }


def build_projection_for_doc(library_id: str, doc_id: str, strategy: str = "doc_blocks_graph_v1") -> Dict[str, Any]:
    """按策略分发文档投影构建。"""
    if strategy != "doc_blocks_graph_v1":
        raise ValueError(f"Unsupported strategy: {strategy}")
    return build_structured_index_for_doc(library_id, doc_id, strategy)


_allowed_roots_cache: Optional[list[str]] = None


def _allowed_roots() -> list[str]:
    """返回文件预览允许访问的根目录列表。"""
    global _allowed_roots_cache
    if _allowed_roots_cache is not None:
        return _allowed_roots_cache

    roots: list[str] = []

    env_dir = os.getenv("KNOWLEDGE_BASE_DIR", "").strip()
    if env_dir:
        env_root = os.path.abspath(env_dir)
        roots.append(env_root)
        logger.info("[Preview] KNOWLEDGE_BASE_DIR env override: %s", env_root)

    storage_root = os.path.abspath(str(file_storage.base_dir))
    if storage_root not in roots:
        roots.append(storage_root)

    try:
        repo_root = resolve_repo_root()
        knowledge_root = os.path.abspath(str(repo_root / "data" / "knowledge_base"))
        if knowledge_root not in roots:
            roots.append(knowledge_root)
    except Exception:
        logger.warning("[Preview] resolve_repo_root() failed, skipping repo-based root", exc_info=True)

    _allowed_roots_cache = roots
    logger.info("[Preview] Allowed roots: %s", roots)
    return roots


def _is_path_allowed(target_path: str, roots: list[str]) -> bool:
    """判断目标路径是否位于允许的根目录下。"""
    for root in roots:
        try:
            if os.path.commonpath([target_path, root]).lower() == root.lower():
                return True
        except ValueError:
            continue
    return False


def _normalize_parent_id(parent_id: Optional[str]) -> Optional[str]:
    """归一化父节点 ID，将空值统一转为 None。"""
    if not parent_id or parent_id in ['', 'undefined', '__root__', 'null', 'None']:
        return None
    return parent_id


# --- 知识库 CRUD 路由 ---


@knowledge_router.get("/libraries")
def list_knowledge_libraries():
    """获取知识库列表。"""
    ks = get_knowledge_service()
    return ks.list_libraries()


@knowledge_router.post("/libraries")
def create_knowledge_library(request: KnowledgeLibraryCreate):
    """创建知识库。"""
    ks = get_knowledge_service()
    library = ks.create_library(request.library_id, request.name, request.description)
    return library


@knowledge_router.get("/libraries/{library_id}")
def get_knowledge_library(library_id: str):
    """获取知识库详情。"""
    ks = get_knowledge_service()
    library = ks.get_library(library_id)
    if not library:
        raise HTTPException(status_code=404, detail="Library not found")
    return library


@knowledge_router.get("/nodes")
def list_knowledge_nodes(library_id: str = 'default', visible: bool = False):
    """获取知识库节点列表。"""
    ks = get_knowledge_service()
    return ks.list_nodes(library_id, visible)


@knowledge_router.post("/nodes")
def create_knowledge_node(request: KnowledgeNodeCreate):
    """创建知识库节点。"""
    ks = get_knowledge_service()
    normalized_parent_id = _normalize_parent_id(request.parent_id)

    if normalized_parent_id:
        parent_node = ks.get_node(normalized_parent_id)
        if not parent_node:
            raise HTTPException(status_code=400, detail=f"Parent node {normalized_parent_id} not found")
        if parent_node.type != 'folder':
            raise HTTPException(status_code=400, detail="Parent node must be a folder")

    node = KnowledgeNode(
        id=f'node-{uuid.uuid4().hex[:8]}',
        title=request.title,
        type=request.node_type,
        library_id=request.library_id or 'default',
        parent_id=normalized_parent_id,
        visible=request.visible if request.visible is not None else True,
        sort_order=request.sort_order if request.sort_order is not None else 0
    )
    return ks.create_node(node)


@knowledge_router.patch("/nodes/{node_id}")
def update_knowledge_node(node_id: str, request: KnowledgeNodeUpdate):
    """更新知识库节点。"""
    ks = get_knowledge_service()
    current_node = ks.get_node(node_id)
    if not current_node:
        raise HTTPException(status_code=404, detail=f"Node {node_id} not found")

    kwargs = {}
    if request.title is not None:
        kwargs['title'] = request.title

    if 'parent_id' in request.model_fields_set:
        normalized_parent_id = _normalize_parent_id(request.parent_id)

        if normalized_parent_id:
            parent_node = ks.get_node(normalized_parent_id)
            if not parent_node:
                raise HTTPException(status_code=400, detail=f"Parent node {normalized_parent_id} not found")
            if parent_node.type != 'folder':
                raise HTTPException(status_code=400, detail="Parent node must be a folder")
            if normalized_parent_id == node_id:
                raise HTTPException(status_code=400, detail="Node cannot be its own parent")

            parent_map = {node.id: node.parent_id for node in ks.nodes}
            curr = normalized_parent_id
            visited = {node_id}
            while curr:
                if curr in visited:
                    raise HTTPException(status_code=400, detail="Cannot move node into its own descendant (circular move)")
                visited.add(curr)
                curr = parent_map.get(curr)

        kwargs['parent_id'] = normalized_parent_id

    if request.visible is not None:
        kwargs['visible'] = request.visible

    if request.sort_order is not None:
        kwargs['sort_order'] = max(0, int(request.sort_order))

    try:
        node = ks.update_node(node_id, **kwargs)
        return node
    except Exception as e:
        import logging
        logging.error(f"Failed to update node {node_id}: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Database update failed: {str(e)}")


@knowledge_router.get("/nodes/{node_id}/delete-preview")
def get_knowledge_node_delete_preview(node_id: str):
    """获取删除节点前的影响范围预览。"""
    ks = get_knowledge_service()
    preview = ks.get_delete_preview(node_id)
    if not preview:
        raise HTTPException(status_code=404, detail="Node not found")
    return preview


@knowledge_router.delete("/nodes/{node_id}")
def delete_knowledge_node(node_id: str):
    """删除知识库节点。"""
    ks = get_knowledge_service()
    success = ks.delete_node(node_id)
    if not success:
        raise HTTPException(status_code=404, detail="Node not found")
    return {"status": "success"}


@knowledge_router.delete("/nodes/{node_id}/force")
def force_delete_knowledge_node(node_id: str):
    """强制删除知识库节点（跳过预览，用于处理异常状态节点）。"""
    ks = get_knowledge_service()
    node = ks.get_node(node_id)
    if not node:
        raise HTTPException(status_code=404, detail="Node not found")
    try:
        if node.parse_task_id:
            parse_orchestrator.cancel_parse_task(node.parse_task_id)
        success = ks.delete_node(node_id)
        if not success:
            raise HTTPException(status_code=500, detail="删除失败")
        return {"status": "success", "message": f"已强制删除节点 {node.title}"}
    except Exception as e:
        logger.error(f"强制删除节点 {node_id} 失败: {e}")
        raise HTTPException(status_code=500, detail=f"强制删除失败: {str(e)}")


@knowledge_router.post("/parse/{task_id}/cancel")
def cancel_parse_task(task_id: str):
    """取消正在运行的解析任务。"""
    success = parse_orchestrator.cancel_parse_task(task_id)
    if not success:
        raise HTTPException(status_code=400, detail="任务不存在、已完成或无法取消")
    return {"status": "success", "task_id": task_id, "message": "任务已取消"}


@knowledge_router.post("/parse/retry")
async def retry_parse_task(request: Dict[str, str]):
    """重试失败或被取消的解析任务。"""
    doc_id = request.get("doc_id")
    if not doc_id:
        raise HTTPException(status_code=400, detail="缺少 doc_id 参数")
    try:
        result = parse_orchestrator.retry_parse_task(doc_id)
        if not result:
            raise HTTPException(status_code=404, detail=f"文档 {doc_id} 不存在或无法重试")
        return {
            "status": "success",
            "task_id": result["task_id"],
            "doc_id": doc_id,
            "message": "已重新启动解析任务",
        }
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"重试解析任务失败: {e}")
        raise HTTPException(status_code=500, detail=f"重试失败: {str(e)}")


@knowledge_router.post("/upload")
async def upload_document(
    library_id: str = Form(...),
    file: UploadFile = FastAPIFile(...),
    parent_id: Optional[str] = Form(None)
):
    """上传文档到知识库。"""
    ks = get_knowledge_service()
    allowed_extensions = {'.pdf', '.doc', '.docx', '.md'}
    ext = os.path.splitext(file.filename or '')[1].lower()
    if ext not in allowed_extensions:
        raise HTTPException(status_code=400, detail=f"Unsupported file type: {ext or 'unknown'}")
    normalized_parent_id = _normalize_parent_id(parent_id)
    if normalized_parent_id:
        parent_node = ks.get_node(normalized_parent_id)
        if not parent_node:
            raise HTTPException(status_code=400, detail="Parent node not found")
        if parent_node.type != 'folder':
            raise HTTPException(status_code=400, detail="Parent node must be folder")

    doc_id = f"doc-{uuid.uuid4().hex[:8]}"
    content = await file.read()
    file_path = file_storage.save_source_file(library_id, doc_id, content, file.filename)

    node = KnowledgeNode(
        id=doc_id,
        title=file.filename,
        type='document',
        parent_id=normalized_parent_id,
        visible=True,
        library_id=library_id,
        file_path=file_path,
        status='pending',
        parse_progress=0,
        parse_stage='pending',
        parse_error=None,
        parse_task_id=None,
        created_at=datetime.now(),
        updated_at=datetime.now()
    )
    ks.create_node(node)

    return {
        "status": "success",
        "doc_id": doc_id,
        "file_path": file_path,
        "storage": file_storage.get_doc_manifest(library_id, doc_id),
        "node": node
    }


@knowledge_router.get("/parse/tasks/{task_id}")
def get_parse_task(task_id: str):
    """获取解析任务状态。"""
    ks = get_knowledge_service()
    task = ks.get_parse_task(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    return task


@knowledge_router.get("/strategies/{doc_id}")
def get_doc_strategy(doc_id: str):
    """获取文档策略。"""
    ks = get_knowledge_service()
    node = ks.get_node(doc_id)
    if not node:
        raise HTTPException(status_code=404, detail="Document not found")
    return {"doc_id": doc_id, "strategy": node.strategy}


@knowledge_router.put("/strategies/{doc_id}")
def set_doc_strategy(doc_id: str, request: KnowledgeStrategyUpdate):
    """设置文档策略。"""
    ks = get_knowledge_service()
    strategy = request.strategy
    allowed = {'doc_blocks_graph_v1'}
    if strategy not in allowed:
        raise HTTPException(status_code=400, detail="Unsupported strategy")
    node = ks.update_node(doc_id, strategy=strategy)
    if not node:
        raise HTTPException(status_code=404, detail="Document not found")
    return {"doc_id": doc_id, "strategy": strategy}


@knowledge_router.post("/structured/index")
def build_structured_index(request: KnowledgeStructuredIndexRequest):
    """构建结构化索引。"""
    ks = get_knowledge_service()
    doc_id = request.doc_id
    library_id = request.library_id
    strategy = request.strategy or 'doc_blocks_graph_v1'
    node = ks.get_node(doc_id)
    if not node:
        raise HTTPException(status_code=404, detail="Document not found")
    allowed = {'doc_blocks_graph_v1'}
    if strategy not in allowed:
        raise HTTPException(status_code=400, detail="Unsupported strategy")
    try:
        result = build_projection_for_doc(library_id, doc_id, strategy)
        ks.update_node(
            doc_id,
            strategy=strategy,
            parse_stage='structured_indexed',
            parse_error=None
        )
        return {"status": "success", "doc_id": doc_id, "strategy": strategy, **result}
    except Exception as error:
        ks.update_node(doc_id, parse_error=str(error))
        raise HTTPException(status_code=500, detail=f"Build structured index failed: {str(error)}")


@knowledge_router.get("/structured/{doc_id}")
def get_structured_index(
    doc_id: str,
    strategy: str = 'doc_blocks_graph_v1',
    item_type: Optional[str] = None,
    keyword: Optional[str] = None,
    limit: int = 200
):
    """查询结构化索引。"""
    ks = get_knowledge_service()
    node = ks.get_node(doc_id)
    if not node:
        raise HTTPException(status_code=404, detail="Document not found")
    items = ks.list_document_segments(
        doc_id=doc_id,
        strategy=strategy,
        item_type=item_type,
        keyword=keyword,
        limit=limit
    )
    return {"doc_id": doc_id, "strategy": strategy, "count": len(items), "items": items}


@knowledge_router.get("/structured/stats/{doc_id}")
def get_structured_stats(doc_id: str):
    """获取结构化索引统计。"""
    ks = get_knowledge_service()
    node = ks.get_node(doc_id)
    if not node:
        raise HTTPException(status_code=404, detail="Document not found")
    return ks.get_document_segment_stats(doc_id)


@knowledge_router.post("/references/search")
def search_knowledge_references(request: KnowledgeReferenceSearchRequest):
    """搜索知识引用候选，供前端 @ 提示面板使用。"""
    ks = get_knowledge_service()
    items = ks.search_references(
        library_id=request.library_id,
        query=request.query,
        limit=request.limit,
        types=request.types,
        current_doc_id=request.current_doc_id,
    )
    return {
        "library_id": request.library_id,
        "query": request.query,
        "count": len(items),
        "items": items,
    }


@knowledge_router.get("/document/{library_id}/{doc_id}")
def get_document(library_id: str, doc_id: str, include_graph: bool = False):
    """获取文档内容，默认不返回 graph_data 以提升大文档加载速度。"""
    content = file_storage.read_markdown(library_id, doc_id)
    if content is None:
        raise HTTPException(status_code=404, detail="Document not found")

    storage_manifest = file_storage.get_doc_manifest(library_id, doc_id)
    result: Dict[str, Any] = {
        "content": content,
        "storage": storage_manifest,
    }

    if include_graph:
        graph_data = get_doc_blocks_graph(library_id, doc_id)
        result["graph_data"] = graph_data

    return result


@knowledge_router.put("/document/{library_id}/{doc_id}")
def update_document(library_id: str, doc_id: str, request: KnowledgeDocumentUpdate):
    """更新文档内容。"""
    ks = get_knowledge_service()
    saved_path = file_storage.save_edited_markdown(library_id, doc_id, request.content)
    ks.update_node(doc_id, updated_at=datetime.now())
    return {"status": "success", "path": saved_path, "storage": file_storage.get_doc_manifest(library_id, doc_id)}


@knowledge_router.patch("/document/{library_id}/{doc_id}/blocks/{block_id}")
def update_document_block(
    library_id: str,
    doc_id: str,
    block_id: str,
    request: KnowledgeDocumentBlockUpdate,
):
    """更新文档结构节点内容。"""
    from docs_core.ingest.store.assets_file_store import update_doc_block_content

    changes = request.dict(exclude_unset=True)
    try:
        result = update_doc_block_content(library_id, doc_id, block_id, changes)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    return {
        "status": "success",
        "doc_id": doc_id,
        "block_id": result["block_id"],
        "updated_fields": result["updated_fields"],
        "node": result["node"],
        "storage": result["graph_path"],
    }


@knowledge_router.post("/document/{library_id}/{doc_id}/blocks/batch")
def batch_operate_document_blocks(
    library_id: str,
    doc_id: str,
    request: KnowledgeDocumentBatchBlockOperation,
):
    """批量执行文档结构节点操作。"""
    from docs_core.ingest.store.assets_file_store import batch_operate_doc_blocks

    payload = request.dict(exclude_unset=True)
    try:
        result = batch_operate_doc_blocks(library_id, doc_id, request.operation, payload)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    return {
        "status": "success",
        "doc_id": doc_id,
        "operation": result["operation"],
        "block_ids": result["block_ids"],
        "target_block_id": result.get("target_block_id"),
        "created_block_ids": result.get("created_block_ids") or [],
        "removed_block_ids": result.get("removed_block_ids") or [],
        "saved_segments": result["saved_segments"],
        "storage": result["graph_path"],
    }


@knowledge_router.post("/document/{library_id}/{doc_id}/blocks/undo")
def undo_document_block_operation(library_id: str, doc_id: str):
    """撤回当前文档最近一次可回滚的结构操作。"""
    from docs_core.ingest.store.assets_file_store import undo_last_doc_block_operation

    try:
        result = undo_last_doc_block_operation(library_id, doc_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    return {
        "status": "success",
        "doc_id": doc_id,
        "restored_block_ids": result["restored_block_ids"],
        "saved_segments": result["saved_segments"],
        "storage": result["graph_path"],
    }


@knowledge_router.post("/document/{library_id}/{doc_id}/blocks/merge/undo")
def undo_document_block_merge(library_id: str, doc_id: str):
    """兼容旧路由，撤回当前文档最近一次结构操作。"""
    return undo_document_block_operation(library_id, doc_id)


@knowledge_router.get("/storage/{library_id}/{doc_id}")
def get_document_storage(library_id: str, doc_id: str):
    """获取文档存储布局。"""
    ks = get_knowledge_service()
    node = ks.get_node(doc_id)
    if not node:
        raise HTTPException(status_code=404, detail="Document not found")
    return {"library_id": library_id, "doc_id": doc_id, "storage": file_storage.get_doc_manifest(library_id, doc_id)}


# --- 解析路由 ---


@knowledge_router.post("/parse")
async def create_parse_task(request: KnowledgeParseRequest) -> Dict[str, Any]:
    """创建解析任务并交给编排层执行。"""
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
        parse_options=normalize_parse_options(request.parse_options),
    )


@knowledge_router.get("/parse/{task_id}", include_in_schema=False)
async def get_parse_status(task_id: str) -> Dict[str, Any]:
    """查询解析任务状态。"""
    task = parse_orchestrator.get_parse_task(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    return task


@knowledge_router.post("/parse/structured-index")
async def build_structured_index_legacy(request: KnowledgeStructuredIndexRequest) -> Dict[str, Any]:
    """手动重建指定文档的策略投影。"""
    try:
        result = build_projection_for_doc(request.library_id, request.doc_id, request.strategy or "doc_blocks_graph_v1")
        return {"status": "success", "data": result}
    except Exception as error:
        raise HTTPException(status_code=500, detail=str(error))


@knowledge_router.post("/parse/doc-blocks-graph")
async def get_doc_blocks_graph_view(request: DocBlocksGraphRequest) -> Dict[str, Any]:
    """获取文档的块图谱视图。"""
    try:
        graph = get_doc_blocks_graph(request.library_id, request.doc_id)
        if not graph:
            raise HTTPException(status_code=404, detail="Graph data not found. Please run structured-index first.")
        return {"status": "success", "data": graph}
    except HTTPException:
        raise
    except Exception as error:
        raise HTTPException(status_code=500, detail=str(error))


@knowledge_router.post("/parse/doc-blocks-graph-summary")
async def get_doc_blocks_graph_summary(request: DocBlocksGraphSummaryRequest) -> Dict[str, Any]:
    """获取文档块图谱的轻量摘要，仅含树结构骨架。"""
    try:
        graph = get_doc_blocks_graph(request.library_id, request.doc_id)
        if not graph:
            raise HTTPException(status_code=404, detail="Graph data not found. Please run structured-index first.")
        light_nodes = []
        heavy_keys = {
            "bbox", "merged_bboxes", "caption_bboxes", "footnote_bboxes",
            "content_json", "rich_media_order", "image_paths",
            "table_html", "math_content",
        }
        for node in graph.get("nodes", []):
            light_node = {k: v for k, v in node.items() if k not in heavy_keys}
            light_nodes.append(light_node)
        summary = {
            "nodes": light_nodes,
            "edges": graph.get("edges", []),
        }
        stats = graph.get("stats")
        if stats:
            summary["stats"] = {
                "base_rows": [
                    {k: v for k, v in row.items() if k not in heavy_keys}
                    for row in stats.get("base_rows", [])
                ],
            }
        return {"status": "success", "data": summary}
    except HTTPException:
        raise
    except Exception as error:
        raise HTTPException(status_code=500, detail=str(error))


# --- 文件预览路由 ---


@preview_router.get("/files")
def get_file_for_preview(path: str):
    """按绝对路径预览文件。"""
    normalized_path = os.path.abspath(os.path.normpath(path))
    allowed_roots = _allowed_roots()
    if not _is_path_allowed(normalized_path, allowed_roots):
        logger.warning(
            "[Preview] Path not allowed: %s (allowed roots: %s)",
            normalized_path, allowed_roots,
        )
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
    "DocBlocksGraphSummaryRequest",
    "KnowledgeLibraryCreate",
    "KnowledgeNodeCreate",
    "KnowledgeNodeUpdate",
    "KnowledgeStrategyUpdate",
    "KnowledgeStructuredIndexRequest",
    "KnowledgeDocumentUpdate",
    "KnowledgeDocumentBlockUpdate",
    "KnowledgeDocumentBatchBlockOperation",
    "KnowledgeParseRequest",
    "KnowledgeParseOptions",
    "ParseOrchestrator",
    "build_projection_for_doc",
    "build_structured_index",
    "create_parse_task",
    "query_knowledge",
    "retrieve_knowledge",
    "get_doc_blocks_graph_view",
    "get_doc_blocks_graph_summary",
    "get_file_for_preview",
    "get_parse_status",
    "knowledge_router",
    "parse_orchestrator",
    "preview_router",
]
