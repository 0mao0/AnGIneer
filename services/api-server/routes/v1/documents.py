"""文档解析 API v1 — 上传、状态轮询、获取 blocks/PDF/内容。"""
import os
import uuid
import json
import shutil
import tempfile
import threading
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, UploadFile, File, HTTPException, Query, Request
from fastapi.responses import FileResponse

from docs_core.read.extract.mineru_parser import mineru_parser
from docs_core.write.store.assets_file_store import file_storage
from docs_core.read.convert.pdf_converter import convert_to_pdf
from docs_core.read import build_structured_index_for_doc

from models.v1_responses import (
    ParseResponse, ParseStatusResponse, BlocksResponse, ContentResponse,
    Block, OutlineItem,
)
from models.parse_record import insert_record, update_record_status, ParseRecord

router = APIRouter()

import logging
logger = logging.getLogger(__name__)

doc_registry: dict[str, dict] = {}


@router.post("/parse")
async def parse_document_v1(
    request: Request,
    file: UploadFile = File(...),
):
    if not file.filename:
        raise HTTPException(400, "文件名不能为空")

    ext = Path(file.filename).suffix.lower()
    is_pdf = ext == ".pdf"
    library_id = "default"
    doc_id = f"v1-{uuid.uuid4().hex[:12]}"
    task_id = f"task-{doc_id}"

    content = await file.read()

    source_path = file_storage.save_source_file(
        library_id, doc_id, content, file.filename,
    )

    # 提取 API key 信息用于统计
    api_key_info = getattr(request.state, "api_key_info", None)
    uploaded_by = api_key_info.user_name if api_key_info else "未知"
    api_key_id = api_key_info.id if api_key_info else None

    # 插入统计记录
    insert_record(ParseRecord(
        doc_id=doc_id,
        task_id=task_id,
        uploaded_by=uploaded_by,
        api_key_id=api_key_id,
        file_name=file.filename,
        file_format=ext,
        file_size=len(content),
        status="queued",
    ))

    doc_registry[task_id] = {
        "doc_id": doc_id,
        "status": "queued",
        "progress": 0,
        "stage": "queued",
        "stage_message": "等待解析",
        "pdf_ready": False,
        "is_pdf_input": is_pdf,
    }

    def _run():
        local = doc_registry
        try:
            if not is_pdf:
                local[task_id] = {
                    "doc_id": doc_id, "status": "processing", "progress": 10,
                    "stage": "converting", "stage_message": "LibreOffice 转换中",
                    "pdf_ready": False, "is_pdf_input": is_pdf,
                }
                update_record_status(task_id, "processing")

                lo_dir = tempfile.mkdtemp(prefix=f"lo-{doc_id}-")
                lo_pdf = convert_to_pdf(source_path, lo_dir)

                # LO 转换 PDF 落 source 目录（与上传文件同目录），前端渲染底图直接引用，无需 parsed 副本
                source_dir = file_storage.get_source_dir(library_id, doc_id)
                source_dir.mkdir(parents=True, exist_ok=True)
                lo_pdf_in_source = source_dir / Path(lo_pdf).name
                shutil.copy2(lo_pdf, str(lo_pdf_in_source))
                render_pdf = lo_pdf_in_source
                logger.info(f"LO PDF saved: {render_pdf}")

                local[task_id] = {
                    "doc_id": doc_id, "status": "processing", "progress": 30,
                    "stage": "mineru", "stage_message": "MinerU 解析中",
                    "pdf_ready": True, "is_pdf_input": is_pdf,
                }

                mineru_input = lo_pdf
            else:
                local[task_id] = {
                    "doc_id": doc_id, "status": "processing", "progress": 20,
                    "stage": "mineru", "stage_message": "MinerU 解析中",
                    "pdf_ready": False, "is_pdf_input": is_pdf,
                }
                update_record_status(task_id, "processing")
                mineru_input = source_path

            # MinerU 解析（慢的部分）：解析器自建临时目录并落盘（save_markdown + save_parse_artifacts）
            result = mineru_parser.parse_to_raw_artifacts(
                input_path=mineru_input,
                library_id=library_id,
                doc_id=doc_id,
            )
            if not result.get("success"):
                raise RuntimeError(result.get("error") or "MinerU 解析失败")

            build_structured_index_for_doc(
                library_id=library_id, doc_id=doc_id,
                strategy="doc_blocks_graph_v1", options={"use_llm": False},
            )

            local[task_id] = {
                "doc_id": doc_id, "status": "completed", "progress": 100,
                "stage": "completed", "stage_message": "解析完成",
                "pdf_ready": True if not is_pdf else False,
                "is_pdf_input": is_pdf,
            }
            update_record_status(task_id, "completed")
            logger.info(f"parse completed: task={task_id}")

        except Exception as e:
            import traceback
            traceback.print_exc()
            local[task_id] = {
                "doc_id": doc_id, "status": "failed", "progress": 100,
                "stage": "failed", "stage_message": str(e),
                "pdf_ready": local[task_id].get("pdf_ready", False),
                "is_pdf_input": is_pdf,
                "error": f"{type(e).__name__}: {e}",
            }
            update_record_status(task_id, "failed", f"{type(e).__name__}: {e}")

    t = threading.Thread(target=_run, daemon=True)
    t.start()

    return ParseResponse(
        doc_id=doc_id,
        task_id=task_id,
        status="queued",
        is_pdf_input=is_pdf,
    )


@router.get("/{doc_id}/status", response_model=ParseStatusResponse)
async def get_parse_status(doc_id: str):
    for task_info in doc_registry.values():
        if task_info.get("doc_id") == doc_id:
            return ParseStatusResponse(**task_info)
    raise HTTPException(404, f"未找到文档 {doc_id}")


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

    graph_file = os.path.join(manifest["doc_root"], "parsed", "doc_blocks_graph.json")
    if not os.path.isfile(graph_file):
        raise HTTPException(404, f"文档 {doc_id} 的解析结果尚未生成")

    with open(graph_file, "r", encoding="utf-8") as f:
        graph = json.load(f)

    nodes = graph.get("nodes", [])
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
    # 检查上传来源
    for task_info in doc_registry.values():
        if task_info.get("doc_id") == doc_id and task_info.get("is_pdf_input"):
            raise HTTPException(404, "原始文件为 PDF，用户已有源文件，无需下载")

    library_id = "default"
    manifest = file_storage.get_doc_manifest(library_id, doc_id)
    pdf_path = manifest.get("render_pdf")
    if not pdf_path or not os.path.isfile(pdf_path):
        raise HTTPException(404, "PDF 不可用")
    return FileResponse(pdf_path, media_type="application/pdf", filename=f"{doc_id}.pdf")


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
    if not md_path or not os.path.isfile(md_path):
        raise HTTPException(404, f"文档 {doc_id} 的 Markdown 内容尚未生成")
    with open(md_path, "r", encoding="utf-8") as f:
        md = f.read()
    return ContentResponse(doc_id=doc_id, markdown=md)
