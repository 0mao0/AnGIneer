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

    range_header = request.headers.get("range")
    if range_header:
        match = re.match(r"^bytes=(\d*)-(\d*)$", range_header.strip())
        if not match:
            raise HTTPException(status_code=416, detail="Invalid Range header")

        start_text, end_text = match.group(1), match.group(2)
        if not start_text and not end_text:
            raise HTTPException(status_code=416, detail="Invalid Range header")

        if start_text:
            start = int(start_text)
            end = int(end_text) if end_text else file_size - 1
        else:
            suffix_length = int(end_text)
            if suffix_length <= 0:
                raise HTTPException(status_code=416, detail="Invalid Range header")
            start = max(0, file_size - suffix_length)
            end = file_size - 1

        if file_size <= 0 or start < 0 or start >= file_size or end < start:
            raise HTTPException(
                status_code=416,
                detail="Range Not Satisfiable",
                headers={"Content-Range": f"bytes */{file_size}"}
            )

        end = min(end, file_size - 1)
        content_length = end - start + 1

        def iterfile():
            """按指定字节区间分块读取文件。"""
            with open(normalized_path, "rb") as file_obj:
                file_obj.seek(start)
                remaining = content_length
                chunk_size = 64 * 1024
                while remaining > 0:
                    read_size = min(chunk_size, remaining)
                    data = file_obj.read(read_size)
                    if not data:
                        break
                    remaining -= len(data)
                    yield data

        return StreamingResponse(
            iterfile(),
            status_code=206,
            media_type=mime_type,
            headers={
                **base_headers,
                "Content-Range": f"bytes {start}-{end}/{file_size}",
                "Content-Length": str(content_length)
            }
        )

    return FileResponse(
        normalized_path,
        filename=filename,
        media_type=mime_type,
        headers=base_headers
    )
