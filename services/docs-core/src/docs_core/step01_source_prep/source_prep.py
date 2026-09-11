"""步骤一：源文件准备——确保源文件进入规范 source 目录。"""

import shutil
from pathlib import Path
from typing import Optional


def resolve_source_file(
    library_id: str,
    doc_id: str,
    base_dir: Optional[str] = None,
) -> Optional[str]:
    """只读解析规范 source 目录里已存在的源文件，返回其路径；目录为空/不存在返回 None。

    "取字典序第一个"与 :func:`_ensure_source_file` 同一口径，二者共用本函数以免漂移。
    不建目录、不复制，供 API 层在请求给的 file_path 失效时兜底（历史批量导入的
    ``nodes.file_path`` 写的是另一台机器的绝对路径，如 ``D:\\AI\\AnGIneer\\...``）。
    """
    from docs_core.paths import get_source_dir

    doc_source_dir = get_source_dir(library_id, doc_id, base_dir)
    if not doc_source_dir.is_dir():
        return None
    current_files = sorted([path for path in doc_source_dir.iterdir() if path.is_file()])
    return str(current_files[0]) if current_files else None


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
    existing = resolve_source_file(library_id, doc_id, base_dir)
    if existing:
        return existing
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


__all__ = ["prepare_source", "resolve_source_file"]
