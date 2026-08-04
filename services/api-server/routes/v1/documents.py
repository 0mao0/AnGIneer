"""文档解析 API v1 — 上传、状态轮询、产物下载。

内部统一走 parse_pipeline 8 阶段管线（默认只跑 structure，产出 jsonl+meta；
需要索引/向量/图谱时通过 stages 参数开启 fts/vectors/graph）。
"""
import os
import uuid
import json
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, UploadFile, File, HTTPException, Query, Request
from fastapi.responses import FileResponse
from starlette.background import BackgroundTask

import docs_core.paths as paths
from docs_core.assets_file_store import file_storage
from docs_core.step10_export.export_artifacts import (
    list_doc_artifacts,
    export_index_db,
    export_graph_db,
    remove_export_dir,
)
from docs_core.parse_pipeline import ParseOrchestrator

from models.v1_responses import (
    ParseResponse,
    ParseStatusResponse,
    BlocksResponse,
    ContentResponse,
    ArtifactsResponse,
    ArtifactListItem,
    Block,
    OutlineItem,
)
from models.parse_record import insert_record, ParseRecord, list_records, sync_record_for_task

router = APIRouter()

import logging
logger = logging.getLogger(__name__)

# 允许下载的产物名白名单
_ARTIFACT_NAMES = {
    "doc_blocks_graph.jsonl": "structure",
    "doc_blocks_graph_meta.json": "structure",
    "index.sqlite": "index",
    "graph.sqlite": "graph",
}

EXTERNAL_API_FOLDER_TITLE = "外部API"

# 编排器实例：创建解析任务并驱动 docs_core 阶段化管线（记录同步由 API 层钩子负责）
parse_orchestrator = ParseOrchestrator(record_updater=sync_record_for_task)


def _records_by_doc_id(doc_id: str) -> list:
    return [r for r in list_records() if r.get("doc_id") == doc_id]


def _ensure_external_api_folder(library_id: str) -> str:
    """找到或创建知识树根部的『外部API』文件夹，返回其 node_id。"""
    from docs_core.docs_service import get_docs_service, KnowledgeNode

    ks = get_docs_service()
    for node in ks.nodes:
        if (
            node.type == "folder"
            and node.library_id == library_id
            and not node.deleted
            and node.title == EXTERNAL_API_FOLDER_TITLE
        ):
            return node.id

    node = KnowledgeNode(
        id=f"node-{uuid.uuid4().hex[:8]}",
        title=EXTERNAL_API_FOLDER_TITLE,
        type="folder",
        library_id=library_id,
        parent_id=None,
        visible=True,
        sort_order=0,
    )
    return ks.create_node(node).id


@router.post("/parse")
async def parse_document_v1(
    request: Request,
    file: UploadFile = File(...),
    stages: str = Query(
        "structure",
        description="解析阶段，逗号分隔。默认 structure（jsonl+meta）；"
                    "需要索引/向量/图谱请传 structure,fts,vectors,graph 或 all",
    ),
):
    if not file.filename:
        raise HTTPException(400, "文件名不能为空")

    ext = Path(file.filename).suffix.lower()
    is_pdf = ext == ".pdf"
    library_id = "default"
    doc_id = f"v1-{uuid.uuid4().hex[:12]}"

    content = await file.read()
    source_path = file_storage.save_source_file(library_id, doc_id, content, file.filename)

    # 提取 API key 信息用于统计
    api_key_info = getattr(request.state, "api_key_info", None)
    uploaded_by = api_key_info.user_name if api_key_info else "未知"
    api_key_id = api_key_info.id if api_key_info else None

    # 注册知识库节点：挂在知识树根部的『外部API』文件夹下（parse_pipeline 依赖节点存在）
    from docs_core.docs_service import get_docs_service

    folder_id = _ensure_external_api_folder(library_id)
    get_docs_service().register_document(
        library_id,
        source_path,
        doc_id,
        title=file.filename,
        parent_id=folder_id,
    )

    # 插入统计记录（pending 占位，create_parse_task 会回填真实 task_id）
    insert_record(ParseRecord(
        doc_id=doc_id,
        task_id=f"pending-{doc_id}",
        uploaded_by=uploaded_by,
        api_key_id=api_key_id,
        file_name=file.filename,
        file_format=ext,
        file_size=len(content),
        status="pending",
    ))

    # 解析阶段校验
    if stages.strip().lower() == "all":
        stage_list = "all"
    else:
        stage_list = [s.strip() for s in stages.split(",") if s.strip()] or ["structure"]
    try:
        from docs_core.parse_pipeline import resolve_stage_order
        resolve_stage_order(stage_list)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    task = parse_orchestrator.create_parse_task(
        library_id=library_id,
        doc_id=doc_id,
        file_path=source_path,
        parse_options={"stages": stage_list, "use_llm": False},
    )

    return ParseResponse(
        doc_id=doc_id,
        task_id=task["task_id"],
        status=task.get("status", "queued"),
        is_pdf_input=is_pdf,
    )


@router.get("/{doc_id}/status", response_model=ParseStatusResponse)
async def get_parse_status(doc_id: str):
    library_id = "default"
    records = _records_by_doc_id(doc_id)
    record = records[0] if records else None
    task_id = record.get("task_id") if record else None

    task = None
    if task_id and not str(task_id).startswith("pending-"):
        task = parse_orchestrator.get_parse_task(task_id)

    is_pdf_input = bool(record and record.get("file_format") == ".pdf")
    pdf_ready = False
    if not is_pdf_input:
        try:
            manifest = file_storage.get_doc_manifest(library_id, doc_id)
            render_pdf = manifest.get("render_pdf")
            pdf_ready = bool(render_pdf and os.path.isfile(str(render_pdf)))
        except Exception:
            pdf_ready = False

    if task:
        return ParseStatusResponse(
            doc_id=doc_id,
            status=task.get("status", "queued"),
            progress=int(task.get("progress") or 0),
            stage=task.get("stage", "") or "",
            stage_message=task.get("stage_message") or "",
            pdf_ready=pdf_ready,
        )
    if record:
        status = record.get("status", "queued")
        return ParseStatusResponse(
            doc_id=doc_id,
            status=status,
            progress=100 if status in ("completed", "failed", "cancelled") else 0,
            stage=status,
            stage_message=record.get("error") or "",
            pdf_ready=pdf_ready,
        )
    raise HTTPException(404, f"未找到文档 {doc_id}")


@router.get("/{doc_id}/artifacts", response_model=ArtifactsResponse)
async def get_doc_artifacts(doc_id: str):
    """列出该文档可下载的产物（jsonl/meta/index.sqlite/graph.sqlite）。"""
    library_id = "default"
    items = [
        ArtifactListItem(
            name=item["name"],
            kind=item["kind"],
            size=item.get("size"),
            url=f"/api/v1/documents/{doc_id}/artifacts/{item['name']}",
        )
        for item in list_doc_artifacts(library_id, doc_id)
    ]
    if not items:
        raise HTTPException(404, f"文档 {doc_id} 暂无可下载产物，请先完成解析")
    return ArtifactsResponse(doc_id=doc_id, items=items)


@router.get("/{doc_id}/artifacts/{name}")
async def download_doc_artifact(doc_id: str, name: str):
    """按文件下载产物；index/graph 按本文档导出独立 sqlite，不泄漏其他文档数据。"""
    library_id = "default"
    if name not in _ARTIFACT_NAMES:
        raise HTTPException(400, f"不支持的产物: {name}")

    if name == "doc_blocks_graph.jsonl":
        path = paths.get_graph_jsonl_path(library_id, doc_id)
        if not path.exists():
            raise HTTPException(404, f"文档 {doc_id} 的解析结果尚未生成")
        return FileResponse(path, media_type="application/jsonl", filename=name)

    if name == "doc_blocks_graph_meta.json":
        path = paths.get_graph_meta_path(library_id, doc_id)
        if not path.exists():
            raise HTTPException(404, f"文档 {doc_id} 的解析结果尚未生成")
        return FileResponse(path, media_type="application/json", filename=name)

    try:
        if name == "index.sqlite":
            path = export_index_db(library_id, doc_id)
        else:
            path = export_graph_db(library_id, doc_id)
    except FileNotFoundError as exc:
        raise HTTPException(404, str(exc))
    return FileResponse(
        path,
        media_type="application/octet-stream",
        filename=name,
        background=BackgroundTask(remove_export_dir, path.parent),
    )


@router.get("/{doc_id}/blocks", response_model=BlocksResponse)
async def get_blocks(
    doc_id: str,
    page: Optional[int] = Query(None),
    block_type: Optional[str] = Query(None),
):
    library_id = "default"
    manifest = file_storage.get_doc_manifest(library_id, doc_id)
    if not manifest.get("doc_root"):
        raise HTTPException(404, f"文档 {doc_id} 不存在")

    jsonl_path = paths.get_graph_jsonl_path(library_id, doc_id)
    if not jsonl_path.exists():
        raise HTTPException(404, f"文档 {doc_id} 的解析结果尚未生成")

    nodes = []
    with open(jsonl_path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                nodes.append(json.loads(line))

    blocks = []
    for n in nodes:
        if page is not None and n.get("page_idx", 0) != page:
            continue
        if block_type and n.get("block_type") != block_type:
            continue
        blocks.append(Block(
            block_id=n.get("id", ""),
            block_type=n.get("block_type", ""),
            page_idx=n.get("page_idx", 0),
            block_seq=n.get("block_seq", 0),
            text=n.get("plain_text", ""),
            bbox=n.get("bbox"),
            heading_level=n.get("derived_level"),
            section_path=n.get("title_path"),
            parent_block_id=n.get("parent_uid"),
            image_url=n.get("image_path"),
            table_html=n.get("table_html"),
            math_latex=n.get("math_content"),
        ))

    outline_raw = []
    for n in nodes:
        lv = n.get("derived_level")
        tp = n.get("title_path", "")
        nid = n.get("id")
        if lv and tp:
            title = tp.split(">")[-1].strip()
            outline_raw.append((lv, title, n.get("page_idx", 0), nid))

    return BlocksResponse(
        doc_id=doc_id,
        filename=os.path.basename(manifest.get("source_file", "")),
        page_count=len({n.get("page_idx") for n in nodes}),
        blocks=blocks,
        outline=[OutlineItem(level=lv, title=t, page_idx=p, block_ids=[bid])
                 for lv, t, p, bid in outline_raw],
    )


@router.get("/{doc_id}/pdf")
async def get_pdf(doc_id: str):
    # 检查上传来源：原始文件为 PDF 时用户已有源文件，无需下载
    records = _records_by_doc_id(doc_id)
    if records and records[0].get("file_format") == ".pdf":
        raise HTTPException(404, "原始文件为 PDF，用户已有源文件，无需下载")

    library_id = "default"
    manifest = file_storage.get_doc_manifest(library_id, doc_id)
    pdf_path = manifest.get("render_pdf")
    if not pdf_path or not os.path.isfile(str(pdf_path)):
        raise HTTPException(404, "PDF 不可用")
    return FileResponse(str(pdf_path), media_type="application/pdf", filename=f"{doc_id}.pdf")


@router.delete("/{doc_id}")
async def delete_document_v1(request: Request, doc_id: str):
    """外部用户标记删除自己的文档。"""
    from models.parse_record import soft_delete_record
    api_key_info = getattr(request.state, "api_key_info", None)
    if not api_key_info:
        raise HTTPException(status_code=401, detail="需要认证")
    success = soft_delete_record(doc_id)
    if not success:
        raise HTTPException(status_code=404, detail="文档不存在或已删除")
    return {"status": "success", "message": "已标记为删除"}


@router.get("/{doc_id}/content", response_model=ContentResponse)
async def get_content(doc_id: str):
    library_id = "default"
    manifest = file_storage.get_doc_manifest(library_id, doc_id)
    if not manifest.get("doc_root"):
        raise HTTPException(404, f"文档 {doc_id} 不存在")
    md_path = manifest.get("parsed_markdown")
    if not md_path or not os.path.isfile(str(md_path)):
        raise HTTPException(404, f"文档 {doc_id} 的 Markdown 内容尚未生成")
    with open(str(md_path), "r", encoding="utf-8") as f:
        md = f.read()
    return ContentResponse(doc_id=doc_id, markdown=md)
