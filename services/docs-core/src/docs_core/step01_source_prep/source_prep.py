"""步骤一：源文件准备——确保源文件进入规范 source 目录。"""

import shutil
from pathlib import Path
from typing import Optional


def _ensure_source_file(
    library_id: str,
    doc_id: str,
    file_path: Optional[str] = None,
    base_dir: Optional[str] = None,
) -> Optional[str]:
    """确保源文件位于规范 source 目录并返回其路径（幂等：已有文件直接返回）。"""
    from docs_core.paths import get_source_dir

    doc_source_dir = get_source_dir(library_id, doc_id, base_dir)
    doc_source_dir.mkdir(parents=True, exist_ok=True)
    current_files = sorted([path for path in doc_source_dir.iterdir() if path.is_file()])
    if current_files:
        return str(current_files[0])
    source_candidate = Path(file_path) if file_path else None
    if source_candidate and source_candidate.exists() and source_candidate.is_file():
        target_path = doc_source_dir / source_candidate.name
        shutil.copy2(source_candidate, target_path)
        return str(target_path)
    return None


def prepare_source(library_id: str, doc_id: str, file_path: str) -> str:
    """确保源文件位于规范 source 目录，返回规范路径（docx 或 pdf）。

    供解析管线 source_prep 阶段调用；文件复制等物理操作由本模块负责。
    """
    source_path = _ensure_source_file(library_id, doc_id, file_path=file_path)
    if not source_path:
        raise RuntimeError("源文件不存在或无法复制到规范目录")
    return source_path


__all__ = ["prepare_source"]
