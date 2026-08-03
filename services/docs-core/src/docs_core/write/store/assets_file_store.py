"""结构化结果文件与 JSON 存储"""
import json
import os
import re
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

    def save_assets(self, library_id: str, doc_id: str, source_dir: str) -> str:
        """保存解析产物中的资产文件目录"""
        assets_path = paths.get_parsed_dir(library_id, doc_id, self.base_dir) / "assets"
        assets_path.parent.mkdir(parents=True, exist_ok=True)
        if assets_path.exists():
            shutil.rmtree(assets_path)
        if os.path.isdir(source_dir):
            shutil.copytree(source_dir, assets_path)
        else:
            assets_path.mkdir(parents=True, exist_ok=True)
        return str(assets_path)

    def save_raw_artifacts(self, library_id: str, doc_id: str, source_dir: str) -> str:
        """保存解析流程中的原始返回文件目录"""
        raw_path = paths.get_raw_dir(library_id, doc_id, self.base_dir)
        raw_path.parent.mkdir(parents=True, exist_ok=True)
        if raw_path.exists():
            shutil.rmtree(raw_path)
        if os.path.isdir(source_dir):
            shutil.copytree(source_dir, raw_path)
        else:
            raw_path.mkdir(parents=True, exist_ok=True)
        return str(raw_path)

    def save_mineru_blocks(self, library_id: str, doc_id: str, blocks: List[Dict[str, Any]]) -> str:
        """保存 MinerU 块级结果"""
        blocks_path = paths.get_mineru_blocks_path(library_id, doc_id, self.base_dir)
        blocks_path.parent.mkdir(parents=True, exist_ok=True)
        with open(blocks_path, "w", encoding="utf-8") as f:
            json_blocks = blocks if isinstance(blocks, list) else []
            json.dump(json_blocks, f, ensure_ascii=False, indent=2)
        return str(blocks_path)

    def save_popo_results(self, library_id: str, doc_id: str, enriched_blocks: list, document_tree: dict) -> None:
        import json as _json
        eb_path = paths.get_popo_enriched_blocks_path(library_id, doc_id, self.base_dir)
        dt_path = paths.get_popo_document_tree_path(library_id, doc_id, self.base_dir)
        eb_path.parent.mkdir(parents=True, exist_ok=True)
        with open(eb_path, "w", encoding="utf-8") as f:
            _json.dump(enriched_blocks, f, ensure_ascii=False, indent=2)
        with open(dt_path, "w", encoding="utf-8") as f:
            _json.dump(document_tree, f, ensure_ascii=False, indent=2)

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

    def save_middle_json(self, library_id: str, doc_id: str, payload: Dict[str, Any]) -> str:
        """保存 middle.json 结构化中间数据"""
        middle_path = paths.get_middle_json_path(library_id, doc_id, self.base_dir)
        middle_path.parent.mkdir(parents=True, exist_ok=True)
        data = payload if isinstance(payload, dict) else {}
        with open(middle_path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        return str(middle_path)

    def read_middle_json(self, library_id: str, doc_id: str) -> Dict[str, Any]:
        """读取 middle.json 结构化中间数据"""
        middle_path = paths.get_middle_json_path(library_id, doc_id, self.base_dir)
        if not middle_path.exists():
            return {}
        try:
            with open(middle_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, dict):
                return data
        except Exception:
            return {}
        return {}

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

    def read_doc_blocks_graph(self, library_id: str, doc_id: str) -> Dict[str, Any]:
        """读取 doc_blocks_graph (jsonl + meta 新格式，回退 json 旧格式)"""
        jsonl_path = paths.get_graph_jsonl_path(library_id, doc_id, self.base_dir)
        meta_path = paths.get_graph_meta_path(library_id, doc_id, self.base_dir)
        if jsonl_path.exists():
            return _read_doc_blocks_graph_split(jsonl_path, meta_path)
        legacy_path = paths.get_graph_path(library_id, doc_id, self.base_dir)
        if not legacy_path.exists():
            return {}
        try:
            with open(legacy_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, dict):
                return data
        except Exception:
            return {}
        return {}

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
        source_file = self.get_latest_source_file(library_id, doc_id)
        parsed_path = paths.get_parsed_markdown_path(library_id, doc_id, self.base_dir)
        edited_path = paths.get_edited_markdown_path(library_id, doc_id, self.base_dir)
        assets_path = parsed_dir / "assets"
        raw_dir = parsed_dir / "raw"
        middle_json_path = paths.get_middle_json_path(library_id, doc_id, self.base_dir)
        mineru_blocks_path = paths.get_mineru_blocks_path(library_id, doc_id, self.base_dir)
        history_dir = paths.get_edited_dir(library_id, doc_id, self.base_dir) / "history"
        # 渲染底图 PDF：优先 source 目录（转换后 PDF 与上传文件同目录），兼容旧数据回退 parsed/mineru_render.pdf
        source_pdf = Path(source_file).with_suffix(".pdf") if source_file else None
        render_pdf_path = source_pdf if (source_pdf and source_pdf.exists()) else (parsed_dir / "mineru_render.pdf")
        return {
            "doc_root": str(doc_root),
            "source_file": source_file,
            "parsed_markdown": str(parsed_path) if parsed_path.exists() else None,
            "edited_markdown": str(edited_path) if edited_path.exists() else None,
            "assets_dir": str(assets_path) if assets_path.exists() else None,
            "raw_dir": str(raw_dir) if raw_dir.exists() else None,
            "middle_json": str(middle_json_path) if middle_json_path.exists() else None,
            "mineru_blocks": str(mineru_blocks_path) if mineru_blocks_path.exists() else None,
            "render_pdf": str(render_pdf_path) if render_pdf_path.exists() else None,
            "history_files": sorted([str(path) for path in history_dir.glob("*.md")], reverse=True) if history_dir.exists() else [],
        }

    def reorganize_storage(self) -> None:
        self._reorganize_once()

    def _reorganize_once(self) -> None:
        for library_root in self.libraries_dir.glob("*"):
            if not library_root.is_dir():
                continue
            documents_dir = library_root / "documents"
            documents_dir.mkdir(parents=True, exist_ok=True)
            for doc_root in documents_dir.iterdir():
                if not doc_root.is_dir():
                    continue
                self._normalize_doc_layout(doc_root)

    def _normalize_doc_layout(self, doc_root: Path) -> None:
        for child in ("source", "parsed", "edited", "structured"):
            (doc_root / child).mkdir(parents=True, exist_ok=True)


file_storage = FileStorage()


# 延迟获取 AnGIneer LLM 客户端，避免循环导入
def _get_llm_client():
    try:
        from ai_inference.llm_client import llm_client
        return llm_client
    except ImportError:
        return None


__all__ = [
    "FileStorage",
    "file_storage",
    "_get_llm_client",
]
