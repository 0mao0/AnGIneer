"""知识库路由与解析调度入口"""
import logging
import mimetypes
import os
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional
from urllib.parse import quote

from fastapi import APIRouter, HTTPException, UploadFile, File as FastAPIFile, Form
from fastapi.responses import FileResponse
from pydantic import BaseModel

from docs_core.docs_service import get_docs_service, KnowledgeNode
from docs_core.step04_structure.shared.jsonl_store import (
    extract_build_id_from_markdown,
    extract_build_id_from_meta,
    get_doc_blocks_graph,
)
from docs_core.step04_structure.solo2json_pipeline import (
    build_structured_index_for_doc,
)
from docs_core.step05_sqlite_fts.sqlite_index import build_sqlite_index_from_graph
from docs_core.docs_file_io import file_storage
from docs_core.paths import resolve_repo_root
from models.parse_record import insert_record, ParseRecord, list_records, hard_delete_record, soft_delete_record, soft_delete_record_by_id, restore_record

logger = logging.getLogger(__name__)


docs_router = APIRouter()
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


from docs_core.parse_pipeline import ParseOrchestrator
from models.parse_record import sync_record_for_task

parse_orchestrator = ParseOrchestrator(record_updater=sync_record_for_task)


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


def _remap_path_for_container(raw_path: str) -> str:
    """将外部路径映射为容器内路径。

    Docker 部署时，数据库可能存储了宿主机格式的路径（如 D:\\AI\\data\\knowledge_base\\...），
    但容器内文件系统看到的路径是 /app/data/knowledge_base/...。
    此函数通过识别路径中的 knowledge_base 段，自动将路径重定向到容器内的知识库目录。
    """
    norm_raw = raw_path.replace("\\", "/")
    kb_segment = "/knowledge_base/"
    idx = norm_raw.lower().find(kb_segment)
    if idx < 0 and norm_raw.lower().endswith("/knowledge_base"):
        idx = norm_raw.lower().rfind("/knowledge_base")
    if idx < 0:
        return raw_path
    relative = norm_raw[idx + len(kb_segment) - 1:].lstrip("/")
    container_kb = os.path.abspath(str(file_storage.base_dir))
    remapped = os.path.join(container_kb, relative)
    if os.path.abspath(raw_path) == remapped:
        return raw_path
    logger.info(
        "[Preview] Remapped path %s -> %s",
        raw_path, remapped,
    )
    return remapped


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


@docs_router.get("/libraries")
def list_knowledge_libraries():
    """获取知识库列表。"""
    ks = get_docs_service()
    return ks.list_libraries()


@docs_router.post("/libraries")
def create_knowledge_library(request: KnowledgeLibraryCreate):
    """创建知识库。"""
    ks = get_docs_service()
    library = ks.create_library(request.library_id, request.name, request.description)
    return library


@docs_router.get("/libraries/{library_id}")
def get_knowledge_library(library_id: str):
    """获取知识库详情。"""
    ks = get_docs_service()
    library = ks.get_library(library_id)
    if not library:
        raise HTTPException(status_code=404, detail="Library not found")
    return library


@docs_router.get("/nodes")
def list_knowledge_nodes(library_id: str = 'default', visible: bool = False):
    """获取知识库节点列表。"""
    ks = get_docs_service()
    return ks.list_nodes(library_id, visible)


@docs_router.post("/nodes")
def create_knowledge_node(request: KnowledgeNodeCreate):
    """创建知识库节点。"""
    ks = get_docs_service()
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


@docs_router.patch("/nodes/{node_id}")
def update_knowledge_node(node_id: str, request: KnowledgeNodeUpdate):
    """更新知识库节点。"""
    ks = get_docs_service()
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


@docs_router.get("/nodes/{node_id}/delete-preview")
def get_knowledge_node_delete_preview(node_id: str):
    """获取删除节点前的影响范围预览。"""
    ks = get_docs_service()
    preview = ks.get_delete_preview(node_id)
    if not preview:
        raise HTTPException(status_code=404, detail="Node not found")
    return preview


@docs_router.delete("/nodes/{node_id}")
def delete_knowledge_node(node_id: str):
    """删除知识库节点。"""
    ks = get_docs_service()
    success = ks.delete_node(node_id)
    if not success:
        raise HTTPException(status_code=404, detail="Node not found")
    soft_delete_record(node_id)
    return {"status": "success"}


@docs_router.delete("/nodes/{node_id}/soft-delete")
def soft_delete_knowledge_node(node_id: str):
    """软删除：标记节点（含子树）为已删除并从树视图隐藏，节点与文件系统内容保持不变。"""
    ks = get_docs_service()
    success = ks.soft_delete_node(node_id)
    if not success:
        raise HTTPException(status_code=404, detail="Node not found")
    try:
        soft_delete_record(node_id)
    except Exception as e:
        logger.error(f"软删除节点 {node_id} 记录失败: {e}")
    return {
        "status": "success",
        "message": "已标记删除（数据保留，可在列表模式恢复或永久删除）",
    }


@docs_router.delete("/nodes/{node_id}/force")
def force_delete_knowledge_node(node_id: str):
    """强制删除知识库节点（跳过预览，用于处理异常状态节点）。"""
    ks = get_docs_service()
    node = ks.get_node(node_id)
    if not node:
        raise HTTPException(status_code=404, detail="Node not found")
    try:
        if node.parse_task_id:
            parse_orchestrator.cancel_parse_task(node.parse_task_id)
        success = ks.delete_node(node_id)
        if not success:
            raise HTTPException(status_code=500, detail="删除失败")
        soft_delete_record(node_id)
        return {"status": "success", "message": f"已强制删除节点 {node.title}"}
    except Exception as e:
        logger.error(f"强制删除节点 {node_id} 失败: {e}")
        raise HTTPException(status_code=500, detail=f"强制删除失败: {str(e)}")


@docs_router.get("/records")
def list_parse_records(
    status: Optional[str] = None,
    uploaded_by: Optional[str] = None,
    show_deleted: bool = False,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    limit: int = 500,
    offset: int = 0,
):
    """列出解析记录（知识库统计页面的表格数据源）。"""
    records = list_records(
        status_filter=status,
        uploaded_by_filter=uploaded_by,
        deleted_filter=show_deleted,
        start_date=start_date,
        end_date=end_date,
        limit=limit,
        offset=offset,
    )
    # 补充 file_status：已入库 / 用户已删 / 冗余
    ks = get_docs_service()
    existing_doc_ids = {n.id for n in ks.nodes}
    for r in records:
        if r.get("status") == "deleted":
            r["file_status"] = "用户已删"
        elif r.get("doc_id") in existing_doc_ids:
            r["file_status"] = "已入库"
        else:
            r["file_status"] = "冗余"
    return {"status": "success", "data": records, "total": len(records)}


@docs_router.put("/records/{record_id}/soft-delete")
def soft_delete_record_by_id(record_id: int):
    """标记单条解析记录为已删除（按 record_id）。"""
    success = soft_delete_record_by_id(record_id)
    if not success:
        raise HTTPException(status_code=404, detail="记录不存在或已删除")
    return {"status": "success", "message": f"记录 {record_id} 已标记为 deleted"}


@docs_router.post("/records/clean-orphaned")
def clean_orphaned_records():
    """清理孤立记录：将 doc_id 在知识库中已不存在的记录标记为 deleted。"""
    ks = get_docs_service()
    records = list_records()
    cleaned = 0
    for record in records:
        doc_id = record.get("doc_id", "")
        if not doc_id:
            continue
        if record.get("status") == "deleted":
            continue
        node = ks.get_node(doc_id)
        if node is None:
            soft_delete_record(doc_id)
            cleaned += 1
    return {"status": "success", "message": f"已清理 {cleaned} 条孤立记录"}


@docs_router.delete("/records/{record_id}/hard-delete")
def admin_hard_delete_record(record_id: int):
    """管理员永久删除（仅允许用户已标记删除的记录）。"""
    success = hard_delete_record(record_id)
    if not success:
        raise HTTPException(status_code=400, detail="仅允许删除用户已标记删除的记录")
    return {"status": "success", "message": "已永久删除"}


@docs_router.put("/records/{record_id}/restore")
def restore_deleted_record(record_id: int):
    """将已删除的解析记录恢复到待解析状态，并恢复对应节点的树显示。"""
    success = restore_record(record_id)
    if not success:
        raise HTTPException(status_code=404, detail="记录不存在或未被删除")
    # 恢复节点软删除标记（若节点仍存在）
    try:
        rec = None
        for r in list_records(limit=5000):
            if r.get("id") == record_id:
                rec = r
                break
        if rec and rec.get("doc_id"):
            ks = get_docs_service()
            if ks.get_node(rec["doc_id"]):
                ks.restore_soft_deleted_node(rec["doc_id"])
    except Exception as e:
        logger.error(f"恢复记录 {record_id} 时恢复节点失败: {e}")
    return {"status": "success", "message": "已恢复"}


@docs_router.post("/parse/{task_id}/cancel")
def cancel_parse_task(task_id: str):
    """取消正在运行的解析任务。"""
    ks = get_docs_service()
    task = ks.get_parse_task(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="任务不存在")
    if task.status in ("completed", "failed", "cancelled"):
        return {"status": "success", "task_id": task_id, "message": f"任务已处于「{task.status}」状态，无需停止"}
    success = parse_orchestrator.cancel_parse_task(task_id)
    if not success:
        raise HTTPException(status_code=400, detail="无法取消")
    return {"status": "success", "task_id": task_id, "message": "任务已取消"}


@docs_router.post("/parse/retry")
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


@docs_router.post("/upload")
async def upload_document(
    library_id: str = Form(...),
    file: UploadFile = FastAPIFile(...),
    parent_id: Optional[str] = Form(None)
):
    """上传文档到知识库。"""
    ks = get_docs_service()
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

    # 插入解析统计记录
    insert_record(ParseRecord(
        doc_id=doc_id,
        task_id=f"pending-{doc_id}",
        uploaded_by="管理员",
        api_key_id=None,
        file_name=file.filename or "未知文件",
        file_format=ext,
        file_size=len(content),
        status="pending",
    ))

    return {
        "status": "success",
        "doc_id": doc_id,
        "file_path": file_path,
        "storage": file_storage.get_doc_manifest(library_id, doc_id),
        "node": node
    }


@docs_router.get("/parse/tasks/{task_id}")
def get_parse_task(task_id: str):
    """获取解析任务状态。"""
    ks = get_docs_service()
    task = ks.get_parse_task(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    return task


@docs_router.get("/parse/tasks/{task_id}/steps")
def get_parse_task_steps(task_id: str):
    """获取解析任务步骤历史。"""
    ks = get_docs_service()
    steps = ks.get_parse_task_steps(task_id)
    return {"status": "success", "data": steps}


@docs_router.get("/strategies/{doc_id}")
def get_doc_strategy(doc_id: str):
    """获取文档策略。"""
    ks = get_docs_service()
    node = ks.get_node(doc_id)
    if not node:
        raise HTTPException(status_code=404, detail="Document not found")
    return {"doc_id": doc_id, "strategy": node.strategy}


@docs_router.put("/strategies/{doc_id}")
def set_doc_strategy(doc_id: str, request: KnowledgeStrategyUpdate):
    """设置文档策略。"""
    ks = get_docs_service()
    strategy = request.strategy
    allowed = {'doc_blocks_graph_v1'}
    if strategy not in allowed:
        raise HTTPException(status_code=400, detail="Unsupported strategy")
    node = ks.update_node(doc_id, strategy=strategy)
    if not node:
        raise HTTPException(status_code=404, detail="Document not found")
    return {"doc_id": doc_id, "strategy": strategy}


@docs_router.post("/structured/index")
def build_structured_index(request: KnowledgeStructuredIndexRequest):
    """构建结构化索引。"""
    ks = get_docs_service()
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
        sqlite_result = build_sqlite_index_from_graph(library_id, doc_id)
        result = {**result, "sqlite": sqlite_result}
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


@docs_router.get("/structured/{doc_id}")
def get_structured_index(
    doc_id: str,
    strategy: str = 'doc_blocks_graph_v1',
    item_type: Optional[str] = None,
    keyword: Optional[str] = None,
    limit: int = 200
):
    """查询结构化索引。"""
    ks = get_docs_service()
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


@docs_router.get("/structured/stats/{doc_id}")
def get_structured_stats(doc_id: str):
    """获取结构化索引统计。"""
    ks = get_docs_service()
    node = ks.get_node(doc_id)
    if not node:
        raise HTTPException(status_code=404, detail="Document not found")
    return ks.get_document_segment_stats(doc_id)


@docs_router.post("/references/search")
def search_knowledge_references(request: KnowledgeReferenceSearchRequest):
    """搜索知识引用候选，供前端 @ 提示面板使用。"""
    ks = get_docs_service()
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


@docs_router.get("/document/{library_id}/{doc_id}")
def get_document(library_id: str, doc_id: str, include_graph: bool = False):
    """获取文档内容，默认不返回 graph_data 以提升大文档加载速度。"""
    content = file_storage.read_markdown(library_id, doc_id)
    if content is None:
        raise HTTPException(status_code=404, detail="Document not found")

    storage_manifest = file_storage.get_doc_manifest(library_id, doc_id)
    result: Dict[str, Any] = {
        "content": content,
        "storage": storage_manifest,
        "build_id": extract_build_id_from_markdown(content),
    }

    if include_graph:
        graph_data = get_doc_blocks_graph(library_id, doc_id)
        result["graph_data"] = graph_data

    return result


@docs_router.patch("/document/{library_id}/{doc_id}/blocks/{block_id}")
def update_document_block(
    library_id: str,
    doc_id: str,
    block_id: str,
    request: KnowledgeDocumentBlockUpdate,
):
    """更新文档结构节点内容。"""
    from docs_core.step05_sqlite_fts.graph_editor import update_doc_block_content

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


@docs_router.post("/document/{library_id}/{doc_id}/blocks/batch")
def batch_operate_document_blocks(
    library_id: str,
    doc_id: str,
    request: KnowledgeDocumentBatchBlockOperation,
):
    """批量执行文档结构节点操作。"""
    from docs_core.step05_sqlite_fts.graph_editor import batch_operate_doc_blocks

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


@docs_router.post("/document/{library_id}/{doc_id}/blocks/undo")
def undo_document_block_operation(library_id: str, doc_id: str):
    """撤回当前文档最近一次可回滚的结构操作。"""
    from docs_core.step05_sqlite_fts.graph_editor import undo_last_doc_block_operation

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


@docs_router.post("/document/{library_id}/{doc_id}/blocks/merge/undo")
def undo_document_block_merge(library_id: str, doc_id: str):
    """兼容旧路由，撤回当前文档最近一次结构操作。"""
    return undo_document_block_operation(library_id, doc_id)


@docs_router.get("/storage/{library_id}/{doc_id}")
def get_document_storage(library_id: str, doc_id: str):
    """获取文档存储布局。"""
    ks = get_docs_service()
    node = ks.get_node(doc_id)
    if not node:
        raise HTTPException(status_code=404, detail="Document not found")
    return {"library_id": library_id, "doc_id": doc_id, "storage": file_storage.get_doc_manifest(library_id, doc_id)}


# --- 解析路由 ---


@docs_router.post("/parse")
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


@docs_router.post("/parse/doc-blocks-graph")
async def get_doc_blocks_graph_view(request: DocBlocksGraphRequest) -> Dict[str, Any]:
    """获取文档的块图谱视图。"""
    try:
        graph = get_doc_blocks_graph(request.library_id, request.doc_id)
        if not graph:
            raise HTTPException(status_code=404, detail="Graph data not found. Please run structured-index first.")
        import docs_core.paths as paths
        meta_path = paths.get_graph_meta_path(request.library_id, request.doc_id)
        meta_build_id = None
        if meta_path.exists():
            import json

            try:
                meta_build_id = extract_build_id_from_meta(json.loads(meta_path.read_text(encoding="utf-8")))
            except (OSError, json.JSONDecodeError):
                meta_build_id = None
        return {"status": "success", "data": graph, "build_id": meta_build_id}
    except HTTPException:
        raise
    except Exception as error:
        raise HTTPException(status_code=500, detail=str(error))


@docs_router.post("/parse/doc-blocks-graph-summary")
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
        import docs_core.paths as paths
        meta_path = paths.get_graph_meta_path(request.library_id, request.doc_id)
        meta_build_id = None
        if meta_path.exists():
            import json

            try:
                meta_build_id = extract_build_id_from_meta(json.loads(meta_path.read_text(encoding="utf-8")))
            except (OSError, json.JSONDecodeError):
                meta_build_id = None
        return {"status": "success", "data": summary, "build_id": meta_build_id}
    except HTTPException:
        raise
    except Exception as error:
        raise HTTPException(status_code=500, detail=str(error))


# --- 文件预览路由 ---


@preview_router.get("/files")
def get_file_for_preview(path: str):
    """按绝对路径预览文件。"""
    remapped = _remap_path_for_container(path)
    normalized_path = os.path.abspath(os.path.normpath(remapped))
    allowed_roots = _allowed_roots()
    if not _is_path_allowed(normalized_path, allowed_roots):
        logger.warning(
            "[Preview] Path not allowed: %s (raw: %s, allowed roots: %s)",
            normalized_path, path, allowed_roots,
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


# --- 阶段化解析端点 ---


_MINERU_TOP_OUTPUTS = ["content.md", "images", "mineru_raw"]
_MINERU_RAW_FILES = ["content_list.json", "content_list_v2.json", "model.json", "middle.json", "origin.zip"]
_POPO_OUTPUTS = ["enriched_blocks.json", "document_tree.json"]
_STRUCTURE_OUTPUTS = ["content.md", "doc_blocks_graph.jsonl", "doc_blocks_graph_meta.json"]


# 从结构化阶段消息识别实际后端："结构化完成（popo 后端）" / "结构化完成（solo 降级）"
def _structure_backend(message: str) -> str:
    if "popo" in (message or ""):
        return "popo"
    if "solo" in (message or ""):
        return "solo"
    return ""


# 固定清单 + 目录内「新增」文件（仅文件，目录不进新增清单，避免 images/mineru_raw/popo 噪音）
def _dir_file_items(directory: Path, expected: List[str]) -> List[Dict[str, Any]]:
    items: List[Dict[str, Any]] = []
    for name in expected:
        items.append({
            "name": name,
            "exists": (directory / name).exists(),
            "isDir": "." not in name,
            "isNew": False,
        })
    if directory.is_dir():
        seen = set(expected)
        for child in sorted(directory.iterdir(), key=lambda p: p.name.lower()):
            if child.name in seen or child.is_dir():
                continue
            items.append({"name": child.name, "exists": True, "isDir": False, "isNew": True})
    return items


# 真实文件系统核查：raw_parse / popo / structure 三个清单式阶段才有固定产物
def _stage_output_files(stage_key: str, node) -> Optional[Dict[str, Any]]:
    import docs_core.paths as paths

    library_id = node.library_id
    doc_id = node.id

    if stage_key == "raw_parse":
        parsed_dir = paths.get_parsed_dir(library_id, doc_id)
        raw_dir = parsed_dir / "mineru_raw"
        items: List[Dict[str, Any]] = []
        for name in _MINERU_TOP_OUTPUTS:
            items.append({
                "name": name,
                "exists": (parsed_dir / name).exists(),
                "isDir": "." not in name,
                "isNew": False,
                "childOfRaw": False,
            })
        for name in _MINERU_RAW_FILES:
            items.append({
                "name": name,
                "exists": (raw_dir / name).exists(),
                "isDir": False,
                "isNew": False,
                "childOfRaw": True,
            })
        if raw_dir.is_dir():
            raw_seen = set(_MINERU_RAW_FILES)
            for child in sorted(raw_dir.iterdir(), key=lambda p: p.name.lower()):
                if child.name not in raw_seen and not child.is_dir():
                    items.append({"name": child.name, "exists": True, "isDir": False, "isNew": True, "childOfRaw": True})
        if parsed_dir.is_dir():
            top_seen = set(_MINERU_TOP_OUTPUTS)
            for child in sorted(parsed_dir.iterdir(), key=lambda p: p.name.lower()):
                if child.name in top_seen or child.is_dir():
                    continue
                items.append({"name": child.name, "exists": True, "isDir": False, "isNew": True, "childOfRaw": False})
        return {"dir": str(parsed_dir), "raw_dir": str(raw_dir), "items": items}

    if stage_key == "popo":
        directory = paths.get_popo_dir(library_id, doc_id)
        return {"dir": str(directory), "items": _dir_file_items(directory, _POPO_OUTPUTS)}

    if stage_key == "structure":
        directory = paths.get_parsed_dir(library_id, doc_id)
        return {"dir": str(directory), "items": _dir_file_items(directory, _STRUCTURE_OUTPUTS)}

    return None


@docs_router.get("/documents/{doc_id}/stages")
def get_document_stages(doc_id: str):
    from docs_core.parse_pipeline import STAGE_REGISTRY, _PIPELINE_ORDER

    ks = get_docs_service()
    node = ks.get_node(doc_id)
    if not node:
        raise HTTPException(status_code=404, detail=f"文档不存在: {doc_id}")
    existing = {s["stage"]: s for s in ks.meta_store.list_parse_stages(doc_id)}
    rows = []
    for key in _PIPELINE_ORDER:
        stage = existing.get(key)
        step_num = STAGE_REGISTRY[key].step
        if stage is None:
            # 从未启动的阶段：补 pending 记录，输入提示按各阶段输入规则生成
            rows.append({
                "doc_id": doc_id, "stage": key, "status": "pending", "message": "",
                "error": "", "started_at": "", "finished_at": "", "updated_at": "",
                "input_summary": _stage_input_hint(key, node), "output_summary": "",
                "step": step_num,
            })
        else:
            row = {**stage, "step": step_num}
            if key == "structure":
                row["backend"] = _structure_backend(str(stage.get("message") or ""))
            if stage.get("status") in ("completed", "running", "failed"):
                row["outputs"] = _stage_output_files(key, node)
            rows.append(row)
    return {"doc_id": doc_id, "stages": rows}


def _stage_input_hint(stage_key: str, node) -> str:
    import docs_core.paths as paths

    if stage_key == "raw_parse":
        # MinerU 输入是 PDF（convert 产出或上传即 PDF），优先取 source_dir 内最新的 pdf
        source_dir = paths.get_source_dir(node.library_id, node.id)
        if source_dir.exists():
            pdf_files = sorted(
                [p for p in source_dir.iterdir() if p.suffix.lower() == '.pdf' and p.is_file()],
                key=lambda p: p.stat().st_mtime, reverse=True,
            )
            if pdf_files:
                return str(pdf_files[0])
        return ""
    if stage_key in ("source_prep", "convert"):
        return node.file_path or ""
    if stage_key in ("popo", "structure"):
        return str(paths.get_mineru_raw_dir(node.library_id, node.id))
    if stage_key in ("fts", "vectors"):
        return node.id
    if stage_key == "graph":
        return str(paths.get_graph_jsonl_path(node.library_id, node.id))
    return ""


@docs_router.post("/documents/{doc_id}/stages/{stage_key}/retry")
def retry_document_stage(doc_id: str, stage_key: str):
    from docs_core.parse_pipeline import validate_stage_retry, resolve_stage_order

    ks = get_docs_service()
    node = ks.get_node(doc_id)
    if not node:
        raise HTTPException(status_code=404, detail=f"文档不存在: {doc_id}")
    try:
        validate_stage_retry(node.status, stage_key)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    file_path = node.file_path
    if not file_path:
        raise HTTPException(status_code=400, detail="文档缺少文件路径信息")
    try:
        resolve_stage_order([stage_key])
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return parse_orchestrator.create_parse_task(
        library_id=node.library_id,
        doc_id=doc_id,
        file_path=file_path,
        parse_options={"stages": [stage_key], "use_llm": True},
    )


@docs_router.post("/documents/{doc_id}/parse")
def parse_document_stages(doc_id: str, stages: str = "all"):
    from docs_core.parse_pipeline import resolve_stage_order

    ks = get_docs_service()
    node = ks.get_node(doc_id)
    if not node:
        raise HTTPException(status_code=404, detail=f"文档不存在: {doc_id}")
    stage_list = "all" if stages == "all" else [s.strip() for s in stages.split(",") if s.strip()]
    try:
        resolve_stage_order(stage_list)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    file_path = node.file_path
    if not file_path:
        raise HTTPException(status_code=400, detail="文档缺少文件路径信息")
    return parse_orchestrator.create_parse_task(
        library_id=node.library_id,
        doc_id=doc_id,
        file_path=file_path,
        parse_options={"stages": stage_list, "use_llm": True},
    )


__all__ = [
    "DocBlocksGraphRequest",
    "DocBlocksGraphSummaryRequest",
    "KnowledgeLibraryCreate",
    "KnowledgeNodeCreate",
    "KnowledgeNodeUpdate",
    "KnowledgeStrategyUpdate",
    "KnowledgeStructuredIndexRequest",
    "KnowledgeDocumentBlockUpdate",
    "KnowledgeDocumentBatchBlockOperation",
    "KnowledgeParseRequest",
    "KnowledgeParseOptions",
    "ParseOrchestrator",
    "build_projection_for_doc",
    "build_structured_index",
    "create_parse_task",
    "get_doc_blocks_graph_view",
    "get_doc_blocks_graph_summary",
    "get_file_for_preview",
    "docs_router",
    "parse_orchestrator",
    "preview_router",
]
