"""全局文件 IO：结构化结果文件与 JSON 存储（不属于任何步骤，全局共用）。"""
import json
import shutil
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

import docs_core.paths as paths


class FileStorage:
    """文件存储管理器（目录布局见 docs_core.paths，本类只负责读写）。"""

    def __init__(self, base_dir: str = None):
        if base_dir is None:
            base_dir = str(paths.resolve_knowledge_base_dir())

        self.base_dir = Path(base_dir)
        self.libraries_dir = self.base_dir / "libraries"

    def save_source_file(
        self,
        library_id: str,
        doc_id: str,
        content: bytes,
        original_filename: Optional[str] = None,
    ) -> str:
        """保存源文件"""
        safe_name = Path(original_filename or f"{doc_id}.pdf").name
        source_dir = paths.get_source_dir(library_id, doc_id, self.base_dir)
        source_dir.mkdir(parents=True, exist_ok=True)
        source_path = source_dir / safe_name
        with open(source_path, "wb") as f:
            f.write(content)
        return str(source_path)

    def save_edited_markdown(self, library_id: str, doc_id: str, content: str) -> str:
        """保存编辑后的 Markdown 文件"""
        edited_dir = paths.get_edited_dir(library_id, doc_id, self.base_dir)
        edited_dir.mkdir(parents=True, exist_ok=True)
        current_path = edited_dir / "current.md"
        with open(current_path, "w", encoding="utf-8") as f:
            f.write(content)
        revision_dir = edited_dir / "history"
        revision_dir.mkdir(parents=True, exist_ok=True)
        revision_path = revision_dir / f'{datetime.now().strftime("%Y%m%d%H%M%S")}.md'
        with open(revision_path, "w", encoding="utf-8") as f:
            f.write(content)
        return str(current_path)

    def read_popo_enriched_blocks(self, library_id: str, doc_id: str) -> list:
        import json as _json
        path = paths.get_popo_enriched_blocks_path(library_id, doc_id, self.base_dir)
        if not path.exists():
            raise FileNotFoundError(f"PoPo enriched blocks not found: {path}")
        with open(path, "r", encoding="utf-8") as f:
            return _json.load(f)

    def read_popo_document_tree(self, library_id: str, doc_id: str) -> dict:
        import json as _json
        path = paths.get_popo_document_tree_path(library_id, doc_id, self.base_dir)
        if not path.exists():
            raise FileNotFoundError(f"PoPo document tree not found: {path}")
        with open(path, "r", encoding="utf-8") as f:
            return _json.load(f)

    def read_mineru_blocks(self, library_id: str, doc_id: str) -> List[Dict[str, Any]]:
        """读取 MinerU 块级结果"""
        blocks_path = paths.get_mineru_blocks_path(library_id, doc_id, self.base_dir)
        if not blocks_path.exists():
            return []
        try:
            with open(blocks_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, list):
                return [item for item in data if isinstance(item, dict)]
        except Exception:
            return []
        return []

    def read_markdown(self, library_id: str, doc_id: str) -> Optional[str]:
        """读取 Markdown 文件"""
        edited_path = paths.get_edited_markdown_path(library_id, doc_id, self.base_dir)
        parsed_path = paths.get_parsed_markdown_path(library_id, doc_id, self.base_dir)
        target_path = edited_path if edited_path.exists() else parsed_path
        if target_path.exists():
            with open(target_path, "r", encoding="utf-8") as f:
                return f.read()
        return None

    def get_latest_source_file(self, library_id: str, doc_id: str) -> Optional[str]:
        """获取源文件路径"""
        source_dir = paths.get_source_dir(library_id, doc_id, self.base_dir)
        if source_dir.exists():
            files = sorted(
                [path for path in source_dir.iterdir() if path.is_file()],
                key=lambda path: path.stat().st_mtime,
                reverse=True,
            )
            if files:
                return str(files[0])
        return None

    def _pick_original_source_file(self, source_dir: Path) -> Optional[str]:
        """优先返回上传的原始文件（非 PDF），避免转换产物把 source_file 顶成 PDF。"""
        if not source_dir.exists():
            return None
        files = sorted(
            [path for path in source_dir.iterdir() if path.is_file()],
            key=lambda path: path.stat().st_mtime,
            reverse=True,
        )
        if not files:
            return None
        non_pdf = [path for path in files if path.suffix.lower() != ".pdf"]
        return str(non_pdf[0] if non_pdf else files[0])

    def resolve_pdf_input(self, library_id: str, doc_id: str) -> str:
        """只读：返回 source 目录下最新 PDF（convert 产物或上传即 PDF）。

        供 raw_parse 输入核查使用；找不到时抛出带指引的 RuntimeError。
        """
        source_dir = paths.get_source_dir(library_id, doc_id, self.base_dir)
        if not source_dir.exists():
            raise RuntimeError(f"源文件目录不存在: {source_dir}")
        pdf_files = sorted(
            [p for p in source_dir.iterdir() if p.suffix.lower() == '.pdf' and p.is_file()],
            key=lambda p: p.stat().st_mtime, reverse=True,
        )
        if not pdf_files:
            raise RuntimeError(f"未找到 PDF 输入文件（请先运行格式转换）: {source_dir}")
        return str(pdf_files[0])

    def delete_document(self, library_id: str, doc_id: str) -> bool:
        """删除文档"""
        doc_root = paths.get_doc_root(library_id, doc_id, self.base_dir)
        deleted = False
        if doc_root.exists():
            shutil.rmtree(doc_root)
            deleted = True
        return deleted

    def list_documents(self, library_id: str) -> List[dict]:
        """列出知识库中的文档"""
        documents = []
        documents_dir = paths.library_root(library_id, self.base_dir) / "documents"
        if documents_dir.exists():
            for doc_root in documents_dir.iterdir():
                if not doc_root.is_dir():
                    continue
                source_dir = doc_root / "source"
                source_files = sorted([file for file in source_dir.glob("*") if file.is_file()])
                source_file = source_files[0] if source_files else None
                md_path = doc_root / "parsed" / "content.md"
                if source_file:
                    documents.append(
                        {
                            "id": doc_root.name,
                            "filename": source_file.name,
                            "source_path": str(source_file),
                            "has_markdown": md_path.exists(),
                            "created_at": datetime.fromtimestamp(source_file.stat().st_ctime).isoformat(),
                        }
                    )

        return documents

    def get_doc_manifest(self, library_id: str, doc_id: str) -> Dict[str, Any]:
        """获取文档清单"""
        parsed_dir = paths.get_parsed_dir(library_id, doc_id, self.base_dir)
        doc_root = parsed_dir.parent
        source_dir = paths.get_source_dir(library_id, doc_id, self.base_dir)
        source_file = self._pick_original_source_file(source_dir)
        parsed_path = paths.get_parsed_markdown_path(library_id, doc_id, self.base_dir)
        edited_path = paths.get_edited_markdown_path(library_id, doc_id, self.base_dir)
        assets_path = parsed_dir / "assets"
        raw_dir = parsed_dir / "raw"
        mineru_blocks_path = paths.get_mineru_blocks_path(library_id, doc_id, self.base_dir)
        history_dir = paths.get_edited_dir(library_id, doc_id, self.base_dir) / "history"
        # 渲染底图 PDF：转换产物或上传即 PDF（优先与原始文件名同名的 PDF）
        render_pdf_path = None
        if source_file:
            same_stem_pdf = Path(source_file).with_suffix(".pdf")
            if same_stem_pdf.exists():
                render_pdf_path = same_stem_pdf
            else:
                pdf_files = sorted(
                    [p for p in source_dir.iterdir() if p.suffix.lower() == ".pdf" and p.is_file()],
                    key=lambda p: p.stat().st_mtime,
                    reverse=True,
                )
                render_pdf_path = pdf_files[0] if pdf_files else None
        return {
            "doc_root": str(doc_root),
            "source_file": source_file,
            "parsed_markdown": str(parsed_path) if parsed_path.exists() else None,
            "edited_markdown": str(edited_path) if edited_path.exists() else None,
            "assets_dir": str(assets_path) if assets_path.exists() else None,
            "raw_dir": str(raw_dir) if raw_dir.exists() else None,
            "mineru_blocks": str(mineru_blocks_path) if mineru_blocks_path.exists() else None,
            "render_pdf": str(render_pdf_path) if render_pdf_path else None,
            "history_files": sorted([str(path) for path in history_dir.glob("*.md")], reverse=True) if history_dir.exists() else [],
        }

file_storage = FileStorage()


__all__ = [
    "FileStorage",
    "file_storage",
]
