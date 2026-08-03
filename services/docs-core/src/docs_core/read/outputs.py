"""read 阶段产物落盘：源文件归位 + markdown/解析产物写入文档目录。

职责边界：本模块只做 read 阶段自己的输出 IO（基于 docs_core.paths 的
纯路径计算），不依赖 write 层存储实现，便于 read 阶段独立测试与将来替换。
"""
import os
import shutil
import uuid
from pathlib import Path
from typing import Any, Dict, Optional

import docs_core.paths as paths


def ensure_doc_source_file(
    library_id: str,
    doc_id: str,
    file_path: Optional[str] = None,
    base_dir: Optional[str] = None,
) -> Optional[str]:
    """确保文档源文件存在于一文档一目录并返回规范路径。"""
    doc_source_dir = paths.get_source_dir(library_id, doc_id, base_dir)
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


def save_markdown(
    library_id: str,
    doc_id: str,
    content: str,
    base_dir: Optional[str] = None,
) -> str:
    """保存 Markdown 文件（parsed + edited 孪生配对）。"""
    parsed_md_path = paths.get_parsed_markdown_path(library_id, doc_id, base_dir)
    parsed_md_path.parent.mkdir(parents=True, exist_ok=True)
    with open(parsed_md_path, "w", encoding="utf-8") as f:
        f.write(content)
    edited_md_path = paths.get_edited_markdown_path(library_id, doc_id, base_dir)
    edited_md_path.parent.mkdir(parents=True, exist_ok=True)
    if not edited_md_path.exists():
        with open(edited_md_path, "w", encoding="utf-8") as f:
            f.write(content)
    return str(parsed_md_path)


def save_parse_artifacts(
    library_id: str,
    doc_id: str,
    output_dir: str,
    base_dir: Optional[str] = None,
) -> Dict[str, Any]:
    """保存解析产物到文档目录（staging + mineru_raw 归一化 + 原子替换）。"""
    parsed_dir = paths.get_parsed_dir(library_id, doc_id, base_dir)
    parsed_dir.parent.mkdir(parents=True, exist_ok=True)
    staging_dir = parsed_dir.parent / f"{parsed_dir.name}.staging-{uuid.uuid4().hex[:8]}"
    if staging_dir.exists():
        shutil.rmtree(staging_dir, ignore_errors=True)
    shutil.copytree(output_dir, staging_dir)

    mineru_raw_dir = staging_dir / "mineru_raw"
    mineru_raw_dir.mkdir(parents=True, exist_ok=True)

    pdf_files = list(staging_dir.rglob("*.pdf"))
    if pdf_files:
        try:
            pdf_files[0].rename(staging_dir / "mineru_render.pdf")
        except Exception:
            pass
        for pdf_file in pdf_files[1:]:
            try:
                pdf_file.unlink()
            except Exception:
                pass

    artifact_map = {
        "origin.zip": "origin.zip",
        "*model.json": "model.json",
        "layout.json": "layout.json",
        "*content_list_v2.json": "content_list_v2.json",
        "content_list.json": "content_list.json",
        "*_content_list.json": "content_list.json",
        "middle.json": "middle.json",
    }

    final_files = {}
    for pattern, target_name in artifact_map.items():
        found_files = list(staging_dir.rglob(pattern))
        for artifact_file in found_files:
            if target_name == "content_list.json" and artifact_file.name == "content_list_v2.json":
                continue
            target = mineru_raw_dir / target_name
            try:
                if artifact_file.resolve() != target.resolve():
                    if target.exists():
                        target.unlink()
                    shutil.move(str(artifact_file), str(target))
                final_files[target_name] = str(target)
            except Exception:
                pass

    assets_path = staging_dir / "assets"
    images_path = staging_dir / "images"
    if assets_path.exists() and images_path.exists():
        try:
            shutil.rmtree(assets_path)
        except Exception:
            pass

    backup_dir = parsed_dir.parent / f"{parsed_dir.name}.backup-{uuid.uuid4().hex[:8]}"
    if parsed_dir.exists():
        parsed_dir.replace(backup_dir)
    staging_dir.replace(parsed_dir)
    if backup_dir.exists():
        shutil.rmtree(backup_dir, ignore_errors=True)

    return final_files
