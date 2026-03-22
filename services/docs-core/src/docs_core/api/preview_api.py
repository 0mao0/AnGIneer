import os
import re
import mimetypes
from pathlib import Path
from urllib.parse import quote

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse, FileResponse

from docs_core import file_storage

router = APIRouter()


def _allowed_roots() -> list[str]:
    """返回文件预览允许访问的根目录列表。"""
    storage_root = os.path.abspath(str(file_storage.base_dir))
    repo_root = Path(__file__).resolve().parents[5]
    knowledge_root = os.path.abspath(str(repo_root / "data" / "knowledge_base"))
    roots = [knowledge_root]
    if storage_root not in roots:
        roots.append(storage_root)
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


@router.get("/files")
def get_file_for_preview(path: str, request: Request):
    """按绝对路径预览文件并支持标准 Range 请求。"""
    normalized_path = os.path.abspath(os.path.normpath(path))
    allowed_roots = _allowed_roots()
    if not _is_path_allowed(normalized_path, allowed_roots):
        raise HTTPException(status_code=403, detail="Forbidden path")
    if not os.path.exists(normalized_path):
        raise HTTPException(status_code=404, detail="File not found")
    if not os.path.isfile(normalized_path):
        raise HTTPException(status_code=400, detail="Path is not a file")

    file_size = os.path.getsize(normalized_path)
    filename = os.path.basename(normalized_path)
    encoded_filename = quote(filename)
    mime_type, _ = mimetypes.guess_type(normalized_path)
    if not mime_type:
        mime_type = "application/octet-stream"

    base_headers = {
        "Accept-Ranges": "bytes",
        "Content-Disposition": f"inline; filename*=utf-8''{encoded_filename}",
        "Access-Control-Expose-Headers": "Accept-Ranges, Content-Range, Content-Length, Content-Disposition"
    }

    # 使用 FileResponse 处理文件预览。
    # FileResponse 内部已经实现了标准的 Range 请求处理逻辑（206 Partial Content），
    # 相比手动使用 StreamingResponse 处理分片，FileResponse 更加稳定且性能更好。
    return FileResponse(
        normalized_path,
        filename=filename,
        media_type=mime_type,
        headers=base_headers
    )
