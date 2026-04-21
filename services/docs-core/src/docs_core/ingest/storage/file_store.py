"""结构化结果文件与 JSON 存储。"""
import json
import os
import re
import shutil
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Set

from docs_core.ingest.structured.formula_semantics import build_formula_representations
from docs_core.ingest.structured.structure_builder import (
    StructuredResult,
    build_structured_from_rawfiles,
    extract_media_bbox_list,
)
from docs_core.ingest.storage.db_store import persist_doc_blocks, resolve_knowledge_base_dir


class FileStorage:
    """文件存储管理器。"""

    def __init__(self, base_dir: str = None):
        if base_dir is None:
            base_dir = str(resolve_knowledge_base_dir())

        self.base_dir = Path(base_dir)
        self.libraries_dir = self.base_dir / "libraries"

        self._ensure_dirs()

    def _ensure_dirs(self):
        """确保目录存在。"""
        self.libraries_dir.mkdir(parents=True, exist_ok=True)

    def _library_root(self, library_id: str) -> Path:
        library_root = self.libraries_dir / library_id
        library_root.mkdir(parents=True, exist_ok=True)
        return library_root

    def get_doc_root(self, library_id: str, doc_id: str) -> Path:
        """获取一文档一目录根路径。"""
        doc_root = self._library_root(library_id) / "documents" / doc_id
        doc_root.mkdir(parents=True, exist_ok=True)
        return doc_root

    def get_source_dir(self, library_id: str, doc_id: str) -> Path:
        """获取源文件目录。"""
        source_dir = self.get_doc_root(library_id, doc_id) / "source"
        source_dir.mkdir(parents=True, exist_ok=True)
        return source_dir

    def get_parsed_dir(self, library_id: str, doc_id: str) -> Path:
        """获取解析结果目录。"""
        parsed_dir = self.get_doc_root(library_id, doc_id) / "parsed"
        parsed_dir.mkdir(parents=True, exist_ok=True)
        return parsed_dir

    def get_graph_path(self, library_id: str, doc_id: str) -> Path:
        """获取结构图谱文件路径。"""
        return self.get_parsed_dir(library_id, doc_id) / "doc_blocks_graph.json"

    def get_edited_dir(self, library_id: str, doc_id: str) -> Path:
        """获取编辑目录。"""
        edited_dir = self.get_doc_root(library_id, doc_id) / "edited"
        edited_dir.mkdir(parents=True, exist_ok=True)
        return edited_dir

    def get_raw_dir(self, library_id: str, doc_id: str) -> Path:
        """获取解析原始返回目录。"""
        raw_dir = self.get_parsed_dir(library_id, doc_id) / "raw"
        raw_dir.mkdir(parents=True, exist_ok=True)
        return raw_dir

    def get_mineru_raw_dir(self, library_id: str, doc_id: str) -> Path:
        """获取 MinerU 原始结构目录。"""
        raw_dir = self.get_parsed_dir(library_id, doc_id) / "mineru_raw"
        raw_dir.mkdir(parents=True, exist_ok=True)
        return raw_dir

    def get_parsed_markdown_path(self, library_id: str, doc_id: str) -> Path:
        """获取解析 Markdown 路径。"""
        return self.get_parsed_dir(library_id, doc_id) / "content.md"

    def get_middle_json_path(self, library_id: str, doc_id: str) -> Path:
        """获取中间语义数据文件路径。"""
        return self.get_parsed_dir(library_id, doc_id) / "middle.json"

    def get_edited_markdown_path(self, library_id: str, doc_id: str) -> Path:
        """获取新版编辑 Markdown 路径。"""
        return self.get_edited_dir(library_id, doc_id) / "current.md"

    def save_source_file(
        self,
        library_id: str,
        doc_id: str,
        content: bytes,
        original_filename: Optional[str] = None,
    ) -> str:
        """保存源文件。"""
        safe_name = Path(original_filename or f"{doc_id}.pdf").name
        source_path = self.get_source_dir(library_id, doc_id) / safe_name
        with open(source_path, "wb") as f:
            f.write(content)
        return str(source_path)

    def save_markdown(self, library_id: str, doc_id: str, content: str) -> str:
        """保存 Markdown 文件。"""
        parsed_md_path = self.get_parsed_markdown_path(library_id, doc_id)
        with open(parsed_md_path, "w", encoding="utf-8") as f:
            f.write(content)
        edited_md_path = self.get_edited_markdown_path(library_id, doc_id)
        if not edited_md_path.exists():
            with open(edited_md_path, "w", encoding="utf-8") as f:
                f.write(content)
        return str(parsed_md_path)

    def save_edited_markdown(self, library_id: str, doc_id: str, content: str) -> str:
        """保存编辑后的 Markdown 文件。"""
        edited_dir = self.get_edited_dir(library_id, doc_id)
        current_path = edited_dir / "current.md"
        with open(current_path, "w", encoding="utf-8") as f:
            f.write(content)
        revision_dir = edited_dir / "history"
        revision_dir.mkdir(parents=True, exist_ok=True)
        revision_path = revision_dir / f'{datetime.now().strftime("%Y%m%d%H%M%S")}.md'
        with open(revision_path, "w", encoding="utf-8") as f:
            f.write(content)
        return str(current_path)

    def save_parse_artifacts(self, library_id: str, doc_id: str, output_dir: str) -> Dict[str, Any]:
        """保存解析产物到文档目录。"""
        parsed_dir = self.get_parsed_dir(library_id, doc_id)
        if not parsed_dir.exists():
            parsed_dir.mkdir(parents=True, exist_ok=True)
        shutil.copytree(output_dir, parsed_dir, dirs_exist_ok=True)

        mineru_raw_dir = self.get_mineru_raw_dir(library_id, doc_id)

        for pdf_file in list(parsed_dir.rglob("*.pdf")):
            try:
                pdf_file.unlink()
            except Exception:
                pass

        artifact_map = {
            "origin.zip": "origin.zip",
            "*model.json": "model.json",
            "layout.json": "layout.json",
            "*content_list_v2.json": "content_list_v2.json",
            "*_content_list.json": "content_list.json",
        }

        final_files = {}
        for pattern, target_name in artifact_map.items():
            found_files = list(parsed_dir.rglob(pattern))
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

        assets_path = parsed_dir / "assets"
        images_path = parsed_dir / "images"
        if assets_path.exists() and images_path.exists():
            try:
                shutil.rmtree(assets_path)
            except Exception:
                pass

        return final_files

    def save_assets(self, library_id: str, doc_id: str, source_dir: str) -> str:
        """保存解析产物中的资产文件目录。"""
        assets_path = self.get_parsed_dir(library_id, doc_id) / "assets"
        if assets_path.exists():
            shutil.rmtree(assets_path)
        if os.path.isdir(source_dir):
            shutil.copytree(source_dir, assets_path)
        else:
            assets_path.mkdir(parents=True, exist_ok=True)
        return str(assets_path)

    def save_raw_artifacts(self, library_id: str, doc_id: str, source_dir: str) -> str:
        """保存解析流程中的原始返回文件目录。"""
        raw_path = self.get_raw_dir(library_id, doc_id)
        if raw_path.exists():
            shutil.rmtree(raw_path)
        if os.path.isdir(source_dir):
            shutil.copytree(source_dir, raw_path)
        else:
            raw_path.mkdir(parents=True, exist_ok=True)
        return str(raw_path)

    def resolve_canonical_raw_dir(self, library_id: str, doc_id: str) -> Path:
        """解析结构主链应优先读取的原始目录。"""
        mineru_raw_dir = self.get_parsed_dir(library_id, doc_id) / "mineru_raw"
        if mineru_raw_dir.exists():
            return mineru_raw_dir
        return self.get_parsed_dir(library_id, doc_id)

    def get_mineru_blocks_path(self, library_id: str, doc_id: str) -> Path:
        """获取 MinerU 块级结果路径。"""
        return self.get_parsed_dir(library_id, doc_id) / "mineru_blocks.json"

    def save_mineru_blocks(self, library_id: str, doc_id: str, blocks: List[Dict[str, Any]]) -> str:
        """保存 MinerU 块级结果。"""
        blocks_path = self.get_mineru_blocks_path(library_id, doc_id)
        with open(blocks_path, "w", encoding="utf-8") as f:
            json_blocks = blocks if isinstance(blocks, list) else []
            json.dump(json_blocks, f, ensure_ascii=False, indent=2)
        return str(blocks_path)

    def save_middle_json(self, library_id: str, doc_id: str, payload: Dict[str, Any]) -> str:
        """保存 middle.json 结构化中间数据。"""
        middle_path = self.get_middle_json_path(library_id, doc_id)
        data = payload if isinstance(payload, dict) else {}
        with open(middle_path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        return str(middle_path)

    def read_middle_json(self, library_id: str, doc_id: str) -> Dict[str, Any]:
        """读取 middle.json 结构化中间数据。"""
        middle_path = self.get_middle_json_path(library_id, doc_id)
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
        """读取 MinerU 块级结果。"""
        blocks_path = self.get_mineru_blocks_path(library_id, doc_id)
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
        """读取 doc_blocks_graph.json。"""
        graph_path = self.get_graph_path(library_id, doc_id)
        if not graph_path.exists():
            return {}
        try:
            with open(graph_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, dict):
                return data
        except Exception:
            return {}
        return {}

    def read_markdown(self, library_id: str, doc_id: str) -> Optional[str]:
        """读取 Markdown 文件。"""
        edited_path = self.get_edited_markdown_path(library_id, doc_id)
        parsed_path = self.get_parsed_markdown_path(library_id, doc_id)
        target_path = edited_path if edited_path.exists() else parsed_path
        if target_path.exists():
            with open(target_path, "r", encoding="utf-8") as f:
                return f.read()
        return None

    def get_latest_source_file(self, library_id: str, doc_id: str) -> Optional[str]:
        """获取源文件路径。"""
        source_dir = self.get_doc_root(library_id, doc_id) / "source"
        if source_dir.exists():
            files = sorted(
                [path for path in source_dir.iterdir() if path.is_file()],
                key=lambda path: path.stat().st_mtime,
                reverse=True,
            )
            if files:
                return str(files[0])
        return None

    def ensure_doc_source_file(self, library_id: str, doc_id: str, file_path: Optional[str] = None) -> Optional[str]:
        """确保文档源文件存在于一文档一目录并返回规范路径。"""
        doc_source_dir = self.get_source_dir(library_id, doc_id)
        current_files = sorted([path for path in doc_source_dir.iterdir() if path.is_file()])
        if current_files:
            return str(current_files[0])
        source_candidate = Path(file_path) if file_path else None
        if source_candidate and source_candidate.exists() and source_candidate.is_file():
            target_path = doc_source_dir / source_candidate.name
            shutil.copy2(source_candidate, target_path)
            return str(target_path)
        return None

    def delete_document(self, library_id: str, doc_id: str) -> bool:
        """删除文档。"""
        doc_root = self._library_root(library_id) / "documents" / doc_id
        deleted = False
        if doc_root.exists():
            shutil.rmtree(doc_root)
            deleted = True
        return deleted

    def list_documents(self, library_id: str) -> List[dict]:
        """列出知识库中的文档。"""
        documents = []
        documents_dir = self._library_root(library_id) / "documents"
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

    def get_doc_root_path(self, library_id: str, doc_id: str) -> str:
        """获取文档根目录字符串路径。"""
        return str(self.get_doc_root(library_id, doc_id))

    def get_doc_manifest(self, library_id: str, doc_id: str) -> Dict[str, Any]:
        """获取文档清单。"""
        doc_root = self.get_doc_root(library_id, doc_id)
        source_file = self.get_latest_source_file(library_id, doc_id)
        parsed_path = self.get_parsed_markdown_path(library_id, doc_id)
        edited_path = self.get_edited_markdown_path(library_id, doc_id)
        assets_path = self.get_parsed_dir(library_id, doc_id) / "assets"
        raw_dir = self.get_parsed_dir(library_id, doc_id) / "raw"
        middle_json_path = self.get_middle_json_path(library_id, doc_id)
        mineru_blocks_path = self.get_mineru_blocks_path(library_id, doc_id)
        history_dir = self.get_edited_dir(library_id, doc_id) / "history"
        return {
            "doc_root": str(doc_root),
            "source_file": source_file,
            "parsed_markdown": str(parsed_path) if parsed_path.exists() else None,
            "edited_markdown": str(edited_path) if edited_path.exists() else None,
            "assets_dir": str(assets_path) if assets_path.exists() else None,
            "raw_dir": str(raw_dir) if raw_dir.exists() else None,
            "middle_json": str(middle_json_path) if middle_json_path.exists() else None,
            "mineru_blocks": str(mineru_blocks_path) if mineru_blocks_path.exists() else None,
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


# 延迟获取 AnGIneer LLM 客户端，避免循环导入。
def _get_llm_client():
    try:
        from angineer_core.infra.llm_client import llm_client
        return llm_client
    except ImportError:
        return None


# 保存 doc_blocks_graph.json 文件。
def _save_doc_blocks_graph(
    library_id: str,
    doc_id: str,
    result: StructuredResult,
) -> str:
    graph_path = file_storage.get_graph_path(library_id, doc_id)

    payload = {
        "nodes": result.nodes,
        "edges": result.edges,
        "stats": result.stats,
        "generated_at": datetime.now().isoformat(),
    }

    with open(graph_path, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)

    return str(graph_path)


# 把 canonical structure 投影为统一的 document_segments。
def _persist_structured_segments(
    library_id: str,
    doc_id: str,
    strategy: str,
    result: StructuredResult,
    llm_client: Any = None,
    llm_model: Optional[str] = None,
    use_llm: bool = True,
) -> int:
    from docs_core.knowledge_service import knowledge_service

    structured_items = _build_a_structured_segment_items(
        result,
        llm_client=llm_client,
        llm_model=llm_model,
        use_llm=use_llm,
    )
    return knowledge_service.save_document_segments(doc_id, library_id, strategy, structured_items)


# 归一化文本以提升图表相关块匹配稳定性。
def _normalize_related_text(text: str) -> str:
    if not text:
        return ""
    compact = re.sub(r"\s+", "", text)
    compact = re.sub(r"[，。；：、“”‘’（）()\[\]【】<>《》,.;:!?！？·—\-~]", "", compact)
    return compact.strip().lower()


# 递归收集任意结构中的文本片段。
def _collect_texts_from_any(payload: Any) -> List[str]:
    fragments: List[str] = []

    def collect(node: Any) -> None:
        if isinstance(node, str):
            text = node.strip()
            if text:
                fragments.append(text)
            return
        if isinstance(node, list):
            for item in node:
                collect(item)
            return
        if isinstance(node, dict):
            for key in ("content", "text", "value"):
                value = node.get(key)
                if isinstance(value, str) and value.strip():
                    fragments.append(value.strip())
            for value in node.values():
                if isinstance(value, (list, dict, str)):
                    collect(value)

    collect(payload)
    return list(dict.fromkeys(fragments))


# 把文本片段转换为可用于跨块匹配的归一化候选。
def _build_related_text_needles(values: List[str]) -> List[str]:
    needles: List[str] = []
    for value in values:
        normalized = _normalize_related_text(value)
        if normalized:
            needles.append(normalized)
    filtered = [value for value in needles if len(value) >= 2]
    filtered.sort(key=len, reverse=True)
    return list(dict.fromkeys(filtered))


# 判断文本是否看起来像图表题注编号。
def _is_caption_like_text(value: str) -> bool:
    return bool(re.match(r"^(图|表|figure|table)\s*[0-9a-z\u4e00-\u9fa5]", value, re.IGNORECASE))


# 判断候选行文本是否命中图表 caption 或 footnote 文本。
def _matches_related_text(row_text: str, needles: List[str]) -> bool:
    if not row_text or not needles:
        return False
    return any(
        needle in row_text
        or (len(row_text) >= 10 and row_text in needle)
        or (isinstance(row_text, str) and _is_caption_like_text(row_text) and needle.startswith(row_text[: min(len(row_text), 32)]))
        for needle in needles
    )


# 为图表块收集同页 caption 与 footnote 的关联 block_uid。
def _collect_media_related_block_refs(
    row: Dict[str, Any],
    rows: List[Dict[str, Any]],
) -> Dict[str, List[str]]:
    block_type = str(row.get("block_type") or "").strip().lower()
    if block_type not in {"image", "table"}:
        return {}

    content_json = row.get("content_json") if isinstance(row.get("content_json"), dict) else {}
    caption_key = "table_caption" if block_type == "table" else "image_caption"
    footnote_key = "table_footnote" if block_type == "table" else "image_footnote"
    caption_needles = _build_related_text_needles(_collect_texts_from_any(content_json.get(caption_key)))
    footnote_needles = _build_related_text_needles(_collect_texts_from_any(content_json.get(footnote_key)))
    if not caption_needles and not footnote_needles:
        return {}

    block_uid = str(row.get("block_uid") or "").strip()
    page_idx = int(row.get("page_idx", -1) or -1)
    excluded_types = {"image", "table", "header", "footer", "page_header", "page_number"}
    caption_refs: List[str] = []
    footnote_refs: List[str] = []

    for candidate in rows:
        candidate_uid = str(candidate.get("block_uid") or candidate.get("id") or "").strip()
        if not candidate_uid or candidate_uid == block_uid:
            continue
        candidate_page_idx = int(candidate.get("page_idx", -1) or -1)
        if candidate_page_idx != page_idx:
            continue
        candidate_type = str(candidate.get("block_type") or candidate.get("type") or "").strip().lower()
        if candidate_type in excluded_types:
            continue
        candidate_text = _normalize_related_text(str(candidate.get("plain_text") or candidate.get("text") or "").strip())
        if not candidate_text:
            continue
        if caption_needles and _matches_related_text(candidate_text, caption_needles):
            caption_refs.append(candidate_uid)
        if footnote_needles and _matches_related_text(candidate_text, footnote_needles):
            footnote_refs.append(candidate_uid)

    result: Dict[str, List[str]] = {}
    if caption_refs:
        result["caption_block_uids"] = list(dict.fromkeys(caption_refs))
    if footnote_refs:
        result["footnote_block_uids"] = list(dict.fromkeys(footnote_refs))
    return result


# 从结构化结果构建 A_structured 片段投影。
def _build_a_structured_segment_items(
    result: StructuredResult,
    llm_client: Any = None,
    llm_model: Optional[str] = None,
    use_llm: bool = True,
) -> List[Dict[str, Any]]:
    node_map: Dict[str, Dict[str, Any]] = {}
    for node in result.nodes:
        node_id = str(node.get("block_uid") or node.get("id") or "").strip()
        if node_id:
            node_map[node_id] = node

    derived_map: Dict[str, Dict[str, Any]] = {}
    for row in result.stats.get("derived_rows", []) or []:
        block_uid = str(row.get("block_uid") or "").strip()
        if block_uid:
            derived_map[block_uid] = row

    base_row_map: Dict[str, Dict[str, Any]] = {}
    base_rows: List[Dict[str, Any]] = result.stats.get("base_rows", []) or []
    for row in base_rows:
        block_uid = str(row.get("block_uid") or "").strip()
        if block_uid:
            base_row_map[block_uid] = row

    child_nodes_by_parent: Dict[str, List[Dict[str, Any]]] = {}
    for node in result.nodes:
        parent_uid = str(node.get("parent_uid") or "").strip()
        if not parent_uid:
            continue
        child_nodes_by_parent.setdefault(parent_uid, []).append(node)
    for children in child_nodes_by_parent.values():
        children.sort(
            key=lambda item: (
                int(item.get("page_idx") or 0),
                int(item.get("block_seq") or 0),
                str(item.get("block_uid") or item.get("id") or ""),
            )
        )

    items: List[Dict[str, Any]] = []
    for row in result.index_rows:
        block_uid = str(row.get("block_uid") or "").strip()
        if not block_uid:
            continue

        node = node_map.get(block_uid, {})
        derived_row = derived_map.get(block_uid, {})
        base_row = base_row_map.get(block_uid, {})
        block_type = str(row.get("block_type") or node.get("block_type") or "segment").strip() or "segment"
        page_idx = int(row.get("page_idx", node.get("page_idx", 0)) or 0)
        page_seq = int(derived_row.get("page_seq") or (page_idx + 1))
        block_seq = int(row.get("block_seq", node.get("block_seq", 0)) or 0)
        derived_level = row.get("derived_level")
        parent_block_uid = row.get("parent_uid") or derived_row.get("parent_block_uid")
        plain_text = str(row.get("plain_text") or node.get("plain_text") or "").strip()
        title_path = row.get("title_path") or derived_row.get("title_path")
        fallback_title = f"{block_type}@P{page_seq}B{block_seq}" if block_seq > 0 else f"{block_type}@P{page_seq}"
        title = plain_text or str(title_path or "").strip() or fallback_title
        parser_caption_refs = row.get("caption_block_uids") or node.get("caption_block_uids") or derived_row.get("caption_block_uids") or []
        parser_footnote_refs = row.get("footnote_block_uids") or node.get("footnote_block_uids") or derived_row.get("footnote_block_uids") or []
        caption_block_uids = [str(value).strip() for value in parser_caption_refs if str(value).strip()]
        footnote_block_uids = [str(value).strip() for value in parser_footnote_refs if str(value).strip()]
        caption_bboxes = row.get("caption_bboxes") or node.get("caption_bboxes") or derived_row.get("caption_bboxes")
        footnote_bboxes = row.get("footnote_bboxes") or node.get("footnote_bboxes") or derived_row.get("footnote_bboxes")
        if not caption_block_uids and not footnote_block_uids and base_row:
            related_refs = _collect_media_related_block_refs(base_row, base_rows)
            caption_block_uids = related_refs.get("caption_block_uids", [])
            footnote_block_uids = related_refs.get("footnote_block_uids", [])

        meta = {
            "source": "a_structured_index",
            "block_uid": block_uid,
            "node_id": block_uid,
            "block_id": block_uid,
            "source_block_id": block_uid,
            "block_uids": [block_uid],
            "node_ids": [block_uid],
            "item_type": block_type,
            "page_idx": page_idx,
            "page_seq": page_seq,
            "page": page_seq,
            "block_seq": block_seq,
            "derived_level": derived_level,
            "heading_level": derived_level,
            "level": derived_level,
            "title_path": title_path,
            "parent_uid": parent_block_uid,
            "parent_block_uid": parent_block_uid,
            "caption_block_uid": caption_block_uids[0] if len(caption_block_uids) == 1 else None,
            "caption_block_uids": caption_block_uids or None,
            "caption_bboxes": caption_bboxes,
            "footnote_block_uid": footnote_block_uids[0] if len(footnote_block_uids) == 1 else None,
            "footnote_block_uids": footnote_block_uids or None,
            "footnote_bboxes": footnote_bboxes,
            "bbox": node.get("bbox"),
            "bbox_source": node.get("bbox_source"),
            "derived_by": node.get("derived_by"),
            "confidence": node.get("confidence"),
        }
        meta = {key: value for key, value in meta.items() if value is not None}

        if block_type == "equation_interline":
            explanation_lines = [
                str(child.get("plain_text") or "").strip()
                for child in child_nodes_by_parent.get(block_uid, [])
                if str(child.get("block_type") or "").strip() in {"paragraph", "list"}
                and str(child.get("plain_text") or "").strip()
            ]
            formula_semantics = build_formula_representations(
                formula_text=str(node.get("math_content") or plain_text or ""),
                explanation_lines=explanation_lines,
                llm_client=llm_client,
                llm_model=llm_model,
                use_llm=use_llm,
            )
            meta.update(
                {
                    "formula_number": formula_semantics.get("formula_number"),
                    "formula_param_count": len(formula_semantics.get("formula_params") or []),
                    "formula_params": formula_semantics.get("formula_params") or None,
                    "formula_summary": formula_semantics.get("formula_summary"),
                    "formula_llm_status": formula_semantics.get("llm_status"),
                }
            )
            meta = {key: value for key, value in meta.items() if value is not None}

        items.append(
            {
                "id": block_uid,
                "item_type": block_type,
                "title": title,
                "content": plain_text or title,
                "meta": meta,
                "order_index": len(items),
            }
        )

        if block_type != "equation_interline":
            continue

        formula_params = (meta.get("formula_params") or []) if isinstance(meta, dict) else []
        formula_summary = str(meta.get("formula_summary") or "").strip() if isinstance(meta, dict) else ""
        formula_number = str(meta.get("formula_number") or "").strip() if isinstance(meta, dict) else ""

        if formula_summary:
            items.append(
                {
                    "id": f"{block_uid}#summary",
                    "item_type": "formula_summary",
                    "title": f"公式摘要{f' ({formula_number})' if formula_number else ''}",
                    "content": formula_summary,
                    "meta": {
                        "block_uid": block_uid,
                        "block_id": block_uid,
                        "source_block_id": block_uid,
                        "formula_block_uid": block_uid,
                        "formula_number": formula_number or None,
                        "page_idx": page_idx,
                        "page_seq": page_seq,
                        "page": page_seq,
                        "block_seq": block_seq,
                        "item_type": "formula_summary",
                    },
                    "order_index": len(items),
                }
            )

        for param_index, param in enumerate(formula_params):
            symbol = str(param.get("symbol") or "").strip()
            description = str(param.get("description") or "").strip()
            if not symbol or not description:
                continue
            content_parts = [f"{symbol}: {description}"]
            unit = str(param.get("unit") or "").strip()
            reference_hint = str(param.get("reference_hint") or "").strip()
            if unit:
                content_parts.append(f"单位 {unit}")
            if reference_hint:
                content_parts.append(f"来源 {reference_hint}")
            items.append(
                {
                    "id": f"{block_uid}#param:{param_index + 1}",
                    "item_type": "formula_param",
                    "title": symbol,
                    "content": " | ".join(content_parts),
                    "meta": {
                        "block_uid": block_uid,
                        "block_id": block_uid,
                        "source_block_id": block_uid,
                        "formula_block_uid": block_uid,
                        "formula_number": formula_number or None,
                        "page_idx": page_idx,
                        "page_seq": page_seq,
                        "page": page_seq,
                        "block_seq": block_seq,
                        "parameter_index": param_index + 1,
                        "symbol": symbol,
                        "unit": unit or None,
                        "reference_hint": reference_hint or None,
                        "extracted_by": param.get("extracted_by"),
                        "confidence": param.get("confidence"),
                        "item_type": "formula_param",
                    },
                    "order_index": len(items),
                }
            )

    return items


# 为文档构建结构化索引。
def build_structured_index_for_doc(
    library_id: str,
    doc_id: str,
    strategy: str = "A_structured",
    options: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    opts = options or {}
    use_llm = opts.get("use_llm", True)
    llm_model = str(opts.get("llm_model") or "").strip() or None
    derive_version = opts.get("derive_version", "v1")

    parsed_dir = file_storage.get_parsed_dir(library_id, doc_id)
    raw_dir = file_storage.resolve_canonical_raw_dir(library_id, doc_id)

    content_list_path = raw_dir / "content_list_v2.json"
    if not content_list_path.exists():
        raise ValueError(f"文档尚无 MinerU 解析结果: {content_list_path}")

    llm_client = None
    if use_llm:
        llm_client = _get_llm_client()

    doc_name = ""
    doc_info = file_storage.get_doc_manifest(library_id, doc_id)
    if doc_info.get("source_file"):
        doc_name = Path(doc_info["source_file"]).name

    result = build_structured_from_rawfiles(
        parsed_dir=parsed_dir,
        doc_id=doc_id,
        doc_name=doc_name,
        llm_client=llm_client,
        options={
            "use_llm": use_llm,
            "llm_model": llm_model,
            "derive_version": derive_version,
        },
    )

    if result.stats.get("error"):
        raise ValueError(f"构建结构失败: {result.stats.get('error')}")

    graph_path = _save_doc_blocks_graph(library_id, doc_id, result)
    doc_block_write_stats = persist_doc_blocks(result)
    structured_saved_count = _persist_structured_segments(
        library_id,
        doc_id,
        strategy,
        result,
        llm_client=llm_client,
        llm_model=llm_model,
        use_llm=use_llm,
    )

    stats = {
        "nodes_count": len(result.nodes),
        "edges_count": len(result.edges),
        "index_rows_count": len(result.index_rows),
        "base_rows_count": doc_block_write_stats["inserted"],
        "derived_rows_count": doc_block_write_stats["updated"],
        "structured_items_saved_count": structured_saved_count,
        "llm_status": result.stats.get("llm_status", "disabled"),
        "llm_model": llm_model,
        "derive_version": derive_version,
        "graph_path": graph_path,
    }

    return {
        "saved_count": structured_saved_count,
        "stats": stats,
    }


# 获取文档的块图谱。
def get_doc_blocks_graph(library_id: str, doc_id: str) -> Optional[Dict[str, Any]]:
    graph_path = file_storage.get_graph_path(library_id, doc_id)

    if not graph_path.exists():
        return None

    with open(graph_path, "r", encoding="utf-8") as f:
        return json.load(f)


# 写回 doc_blocks_graph.json 文件。
def _write_doc_blocks_graph(library_id: str, doc_id: str, payload: Dict[str, Any]) -> str:
    graph_path = file_storage.get_graph_path(library_id, doc_id)
    with open(graph_path, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
    return str(graph_path)


# 判断节点引用是否命中指定 block_uid。
def _matches_block_ref(value: Any, block_uid: str) -> bool:
    if isinstance(value, list):
        return any(_matches_block_ref(item, block_uid) for item in value)
    return str(value or "").strip() == block_uid


# 规范化 block_uid，统一空值处理。
def _normalize_block_uid(value: Any) -> str:
    return str(value or "").strip()


# 仅返回图谱中当前仍然生效的节点集合。
def _get_active_graph_nodes(graph_data: Dict[str, Any]) -> List[Dict[str, Any]]:
    return [
        node
        for node in (graph_data.get("nodes") or [])
        if int(node.get("is_active", 1) or 0) != 0
    ]


# 构造 block_uid 到节点的快速索引。
def _build_active_node_map(graph_data: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
    node_map: Dict[str, Dict[str, Any]] = {}
    for node in _get_active_graph_nodes(graph_data):
        block_uid = _normalize_block_uid(node.get("block_uid") or node.get("id"))
        if block_uid:
            node_map[block_uid] = node
    return node_map


# 按页面与块序对节点做稳定排序，便于重建结构投影。
def _sort_graph_nodes(nodes: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    return sorted(
        nodes,
        key=lambda node: (
            int(node.get("page_idx") or 0),
            int(node.get("block_seq") or 0),
            _normalize_block_uid(node.get("block_uid") or node.get("id")),
        ),
    )


# 按稳定顺序回写图谱节点数组，避免前端树视图读取到旧顺序。
def _sort_graph_data_nodes(graph_data: Dict[str, Any]) -> None:
    graph_data["nodes"] = _sort_graph_nodes(_get_active_graph_nodes(graph_data))


# 获取指定节点及其规范化 block_uid。
def _get_graph_node_or_raise(graph_data: Dict[str, Any], block_id: str) -> Any:
    target_block_uid = _normalize_block_uid(block_id)
    for node in _get_active_graph_nodes(graph_data):
        candidate_ids = {
            _normalize_block_uid(node.get("id")),
            _normalize_block_uid(node.get("block_uid")),
        }
        if target_block_uid in candidate_ids:
            resolved_uid = _normalize_block_uid(node.get("block_uid") or node.get("id"))
            return node, resolved_uid
    raise KeyError(f"未找到块节点: {block_id}")


# 判断候选父节点是否会形成祖先环。
def _would_create_cycle(node_map: Dict[str, Dict[str, Any]], node_uid: str, candidate_parent_uid: Optional[str]) -> bool:
    cursor = _normalize_block_uid(candidate_parent_uid)
    visited = set()
    while cursor:
        if cursor == node_uid:
            return True
        if cursor in visited:
            return True
        visited.add(cursor)
        parent = node_map.get(cursor)
        if not parent:
            return False
        cursor = _normalize_block_uid(parent.get("parent_uid"))
    return False


# 解析节点到根节点的祖先路径。
def _resolve_parent_chain(node_map: Dict[str, Dict[str, Any]], parent_uid: Optional[str]) -> List[str]:
    chain: List[str] = []
    cursor = _normalize_block_uid(parent_uid)
    visited = set()
    while cursor and cursor not in visited:
        visited.add(cursor)
        parent = node_map.get(cursor)
        if not parent:
            break
        chain.append(cursor)
        cursor = _normalize_block_uid(parent.get("parent_uid"))
    chain.reverse()
    return chain


# 根据目标标题层级推断最近的上级结构节点。
def _infer_parent_uid_from_level(
    active_nodes: List[Dict[str, Any]],
    target_block_uid: str,
    target_level: Optional[int],
) -> Optional[str]:
    if target_level is None or target_level <= 1:
        return None
    latest_by_level: Dict[int, str] = {}
    for node in _sort_graph_nodes(active_nodes):
        block_uid = _normalize_block_uid(node.get("block_uid") or node.get("id"))
        if not block_uid:
            continue
        if block_uid == target_block_uid:
            break
        derived_level = node.get("derived_level")
        if derived_level is None or derived_level == "":
            continue
        try:
            normalized_level = int(derived_level)
        except (TypeError, ValueError):
            continue
        if normalized_level < 1:
            continue
        latest_by_level[normalized_level] = block_uid
        for stale_level in [level for level in latest_by_level.keys() if level > normalized_level]:
            latest_by_level.pop(stale_level, None)
    return latest_by_level.get(int(target_level) - 1)


# 把单值或数组中的 block 引用从旧 uid 替换为新 uid。
def _replace_block_ref(value: Any, source_uid: str, target_uid: str) -> Any:
    if isinstance(value, list):
        replaced = [_replace_block_ref(item, source_uid, target_uid) for item in value]
        return [item for item in replaced if _normalize_block_uid(item)]
    return target_uid if _matches_block_ref(value, source_uid) else value


# 合并两个文本字段，避免重复内容。
def _merge_text_value(primary: Any, secondary: Any) -> str:
    primary_text = str(primary or "").strip()
    secondary_text = str(secondary or "").strip()
    if not primary_text:
        return secondary_text
    if not secondary_text or secondary_text == primary_text:
        return primary_text
    return f"{primary_text}\n{secondary_text}"


# 归一化并去重节点合并产生的 bbox 列表。
def _normalize_graph_bbox_list(values: List[Any]) -> List[List[float]]:
    normalized: List[List[float]] = []
    seen = set()
    for bbox in extract_media_bbox_list(values):
        key = tuple(float(item) for item in bbox[:4])
        if key in seen:
            continue
        seen.add(key)
        normalized.append([float(item) for item in bbox[:4]])
    return normalized


# 提取节点当前应保留的所有 bbox 范围。
def _collect_node_bbox_list(node: Dict[str, Any]) -> List[List[float]]:
    values: List[Any] = []
    merged_bboxes = node.get("merged_bboxes")
    if isinstance(merged_bboxes, list):
        values.extend(merged_bboxes)
    bbox = node.get("bbox")
    if isinstance(bbox, (list, tuple)) and len(bbox) >= 4:
        values.append(list(bbox[:4]))
    return _normalize_graph_bbox_list(values)


# 归一化块引用字段，统一返回去重后的 block_uid 列表。
def _collect_block_ref_uids(value: Any) -> List[str]:
    if isinstance(value, list):
        return list(dict.fromkeys(
            uid
            for uid in (_normalize_block_uid(item) for item in value)
            if uid
        ))
    normalized = _normalize_block_uid(value)
    return [normalized] if normalized else []


# 收集节点关联的所有图片路径，兼容单图与多图合并结果。
def _collect_node_image_paths(node: Dict[str, Any]) -> List[str]:
    raw_values: List[Any] = []
    image_paths = node.get("image_paths")
    if isinstance(image_paths, list):
        raw_values.extend(image_paths)
    image_path = node.get("image_path")
    if image_path:
        raw_values.append(image_path)
    return list(dict.fromkeys(
        str(value).strip()
        for value in raw_values
        if str(value or "").strip()
    ))


# 深拷贝任意 JSON 兼容值，避免共享嵌套引用。
def _clone_json_compatible(value: Any) -> Any:
    return json.loads(json.dumps(value, ensure_ascii=False))


# 为 JSON 值生成稳定签名，用于去重合并。
def _build_json_signature(value: Any) -> str:
    try:
        return json.dumps(value, ensure_ascii=False, sort_keys=True)
    except TypeError:
        return json.dumps(str(value), ensure_ascii=False)


# 合并 content_json 里的富媒体载荷，尽量保留原始结构与顺序。
def _merge_content_json_value(primary: Any, secondary: Any) -> Any:
    if primary in (None, "", [], {}):
        return _clone_json_compatible(secondary)
    if secondary in (None, "", [], {}):
        return _clone_json_compatible(primary)
    if isinstance(primary, dict) and isinstance(secondary, dict):
        merged: Dict[str, Any] = {}
        for key in dict.fromkeys([*primary.keys(), *secondary.keys()]):
            if key in primary and key in secondary:
                merged[key] = _merge_content_json_value(primary[key], secondary[key])
            elif key in primary:
                merged[key] = _clone_json_compatible(primary[key])
            else:
                merged[key] = _clone_json_compatible(secondary[key])
        return merged
    if isinstance(primary, list) and isinstance(secondary, list):
        merged_list: List[Any] = []
        seen = set()
        for item in [*primary, *secondary]:
            signature = _build_json_signature(item)
            if signature in seen:
                continue
            seen.add(signature)
            merged_list.append(_clone_json_compatible(item))
        return merged_list
    return _clone_json_compatible(primary)


# 把多个节点的富媒体字段聚合到目标节点，避免合并后图片与注释信息丢失。
def _merge_rich_media_fields_into_target(target_node: Dict[str, Any], merged_nodes: List[Dict[str, Any]]) -> None:
    if not merged_nodes:
        return

    image_paths: List[str] = []
    caption_block_uids: List[str] = []
    footnote_block_uids: List[str] = []
    caption_bboxes: List[List[float]] = []
    footnote_bboxes: List[List[float]] = []
    merged_content_json: Dict[str, Any] = {}
    rich_media_order: List[Dict[str, Any]] = []

    for node in merged_nodes:
        node_content_json = node.get("content_json")
        if isinstance(node_content_json, dict):
            merged_content_json = _merge_content_json_value(merged_content_json, node_content_json)
        
        node_image_paths = _collect_node_image_paths(node)
        image_paths.extend(node_image_paths)
        
        for img_path in node_image_paths:
            rich_media_order.append({"type": "image", "path": img_path})
        
        if node.get("table_html") and str(node.get("table_html") or "").strip():
            rich_media_order.append({"type": "table"})
        
        if node.get("math_content") and str(node.get("math_content") or "").strip():
            rich_media_order.append({"type": "math"})
        
        caption_block_uids.extend(_collect_block_ref_uids(node.get("caption_block_uid")))
        caption_block_uids.extend(_collect_block_ref_uids(node.get("caption_block_uids")))
        footnote_block_uids.extend(_collect_block_ref_uids(node.get("footnote_block_uid")))
        footnote_block_uids.extend(_collect_block_ref_uids(node.get("footnote_block_uids")))
        caption_bboxes.extend(_normalize_graph_bbox_list(node.get("caption_bboxes")) or [])
        footnote_bboxes.extend(_normalize_graph_bbox_list(node.get("footnote_bboxes")) or [])

    target_node["content_json"] = merged_content_json or {}
    normalized_image_paths = list(dict.fromkeys(image_paths))
    target_node["image_path"] = normalized_image_paths[0] if normalized_image_paths else None
    target_node["image_paths"] = normalized_image_paths or None
    target_node["caption_block_uids"] = list(dict.fromkeys(caption_block_uids)) or None
    target_node["caption_block_uid"] = target_node["caption_block_uids"][0] if target_node.get("caption_block_uids") else None
    target_node["footnote_block_uids"] = list(dict.fromkeys(footnote_block_uids)) or None
    target_node["footnote_block_uid"] = target_node["footnote_block_uids"][0] if target_node.get("footnote_block_uids") else None
    target_node["caption_bboxes"] = _normalize_graph_bbox_list(caption_bboxes) or None
    target_node["footnote_bboxes"] = _normalize_graph_bbox_list(footnote_bboxes) or None
    target_node["rich_media_order"] = rich_media_order or None
    _sync_caption_bboxes_to_content_json(target_node, caption_bboxes, footnote_bboxes)


# 把合并后的 caption/footnote bbox 同步写入 content_json，确保前端联动能正确读取。
def _sync_caption_bboxes_to_content_json(
    target_node: Dict[str, Any],
    caption_bboxes: List[List[float]],
    footnote_bboxes: List[List[float]]
) -> None:
    block_type = str(target_node.get("block_type") or "").strip().lower()
    if block_type not in ("image", "table"):
        return
    content_json = target_node.get("content_json")
    if not isinstance(content_json, dict):
        content_json = {}
        target_node["content_json"] = content_json
    normalized_caption_bboxes = _normalize_graph_bbox_list(caption_bboxes)
    normalized_footnote_bboxes = _normalize_graph_bbox_list(footnote_bboxes)
    if block_type == "table":
        if normalized_caption_bboxes:
            content_json["table_caption_bboxes"] = normalized_caption_bboxes
        if normalized_footnote_bboxes:
            content_json["table_footnote_bboxes"] = normalized_footnote_bboxes
    else:
        if normalized_caption_bboxes:
            content_json["image_caption_bboxes"] = normalized_caption_bboxes
        if normalized_footnote_bboxes:
            content_json["image_footnote_bboxes"] = normalized_footnote_bboxes


# 提取节点当前应保留的合并来源 block_uid 列表。
def _collect_node_merge_block_uids(node: Dict[str, Any]) -> List[str]:
    ordered_uids: List[str] = []
    for value in node.get("merged_block_uids") or []:
        block_uid = _normalize_block_uid(value)
        if block_uid and block_uid not in ordered_uids:
            ordered_uids.append(block_uid)
    current_uid = _normalize_block_uid(node.get("block_uid") or node.get("id"))
    if current_uid and current_uid not in ordered_uids:
        ordered_uids.append(current_uid)
    return ordered_uids


# 同步引用当前节点的题注与脚注显示字段。
def _sync_related_graph_fields(nodes: List[Dict[str, Any]], target_block_uid: str, target_node: Dict[str, Any]) -> None:
    caption_text = str(target_node.get("plain_text") or target_node.get("caption") or "").strip()
    footnote_text = str(target_node.get("plain_text") or target_node.get("footnote") or "").strip()
    for node in nodes:
        if _matches_block_ref(node.get("caption_block_uid"), target_block_uid) or _matches_block_ref(node.get("caption_block_uids"), target_block_uid):
            node["caption"] = caption_text
        if _matches_block_ref(node.get("footnote_block_uid"), target_block_uid) or _matches_block_ref(node.get("footnote_block_uids"), target_block_uid):
            node["footnote"] = footnote_text


# 依据当前节点关系重建图谱边、前后关系与 title_path。
def _rebuild_graph_projection(graph_data: Dict[str, Any]) -> None:
    active_nodes = _sort_graph_nodes(_get_active_graph_nodes(graph_data))
    node_map = _build_active_node_map({"nodes": active_nodes})
    for node in active_nodes:
        block_uid = _normalize_block_uid(node.get("block_uid") or node.get("id"))
        node["block_uid"] = block_uid
        if not node.get("id"):
            node["id"] = block_uid
        parent_uid = _normalize_block_uid(node.get("parent_uid"))
        if not parent_uid or parent_uid not in node_map or parent_uid == block_uid or _would_create_cycle(node_map, block_uid, parent_uid):
            parent_uid = ""
        node["parent_uid"] = parent_uid or None
        derived_level = node.get("derived_level")
        if derived_level is not None and derived_level != "":
            try:
                node["derived_level"] = int(derived_level)
            except (TypeError, ValueError):
                node["derived_level"] = None
        else:
            node["derived_level"] = None
        parent_chain = _resolve_parent_chain(node_map, node.get("parent_uid"))
        if node.get("derived_level") is not None:
            node["title_path"] = ">".join(parent_chain + [block_uid]) if parent_chain else block_uid
        else:
            node["title_path"] = ">".join(parent_chain) if parent_chain else None

    for index, node in enumerate(active_nodes):
        node["prev_uid"] = _normalize_block_uid(active_nodes[index - 1].get("block_uid")) if index > 0 else None
        node["next_uid"] = _normalize_block_uid(active_nodes[index + 1].get("block_uid")) if index + 1 < len(active_nodes) else None

    edges: List[Dict[str, Any]] = []
    for node in active_nodes:
        block_uid = _normalize_block_uid(node.get("block_uid"))
        parent_uid = _normalize_block_uid(node.get("parent_uid"))
        if parent_uid and parent_uid in node_map:
            edges.append({
                "source": parent_uid,
                "target": block_uid,
                "relation": "contains",
                "strength": "strong",
            })
        prev_uid = _normalize_block_uid(node.get("prev_uid"))
        if prev_uid and prev_uid in node_map:
            edges.append({
                "source": prev_uid,
                "target": block_uid,
                "relation": "next",
                "strength": "weak",
            })
        explain_for_uid = _normalize_block_uid(node.get("explain_for_uid"))
        if explain_for_uid and explain_for_uid in node_map:
            edges.append({
                "source": explain_for_uid,
                "target": block_uid,
                "relation": "explain",
                "strength": "weak",
            })
    graph_data["edges"] = edges

    stats = graph_data.get("stats")
    if not isinstance(stats, dict):
        return
    active_uid_set = {
        _normalize_block_uid(node.get("block_uid"))
        for node in active_nodes
    }
    row_source_map = {uid: node for uid, node in node_map.items() if uid in active_uid_set}
    for row_key in ("base_rows", "derived_rows", "index_rows"):
        rows = stats.get(row_key)
        if not isinstance(rows, list):
            continue
        synced_rows: List[Dict[str, Any]] = []
        for row in rows:
            block_uid = _normalize_block_uid(row.get("block_uid") or row.get("id"))
            node = row_source_map.get(block_uid)
            if not node:
                continue
            row["plain_text"] = node.get("plain_text")
            row["table_html"] = node.get("table_html")
            row["math_content"] = node.get("math_content")
            row["title_path"] = node.get("title_path")
            row["caption"] = node.get("caption")
            row["footnote"] = node.get("footnote")
            row["content_json"] = node.get("content_json") if node.get("content_json") is not None else row.get("content_json")
            row["image_path"] = node.get("image_path")
            row["image_paths"] = node.get("image_paths")
            row["caption_block_uid"] = node.get("caption_block_uid")
            row["caption_block_uids"] = node.get("caption_block_uids")
            row["footnote_block_uid"] = node.get("footnote_block_uid")
            row["footnote_block_uids"] = node.get("footnote_block_uids")
            row["caption_bboxes"] = node.get("caption_bboxes")
            row["footnote_bboxes"] = node.get("footnote_bboxes")
            row["merged_bboxes"] = node.get("merged_bboxes")
            if row_key != "base_rows":
                row["parent_uid"] = node.get("parent_uid")
                row["parent_block_uid"] = node.get("parent_uid")
                row["derived_level"] = node.get("derived_level")
                row["derived_title_level"] = node.get("derived_level")
            synced_rows.append(row)
        stats[row_key] = synced_rows


# 从图谱节点重建结构化片段，确保合并和层级调整能实时投影。
def _build_structured_segment_items_from_graph(graph_data: Dict[str, Any]) -> List[Dict[str, Any]]:
    excluded_types = {"page_header", "page_footer", "page_number", "header", "footer"}
    items: List[Dict[str, Any]] = []
    for order_index, node in enumerate(_sort_graph_nodes(_get_active_graph_nodes(graph_data))):
        block_uid = _normalize_block_uid(node.get("block_uid") or node.get("id"))
        block_type = str(node.get("block_type") or "segment").strip() or "segment"
        if block_type in excluded_types:
            continue
        plain_text = str(node.get("plain_text") or "").strip()
        title_path = str(node.get("title_path") or "").strip()
        title = plain_text or title_path or block_uid
        meta = {
            "block_uid": block_uid,
            "block_type": block_type,
            "page_idx": node.get("page_idx"),
            "block_seq": node.get("block_seq"),
            "title_path": node.get("title_path"),
            "caption": node.get("caption"),
            "footnote": node.get("footnote"),
            "table_html": node.get("table_html"),
            "math_content": node.get("math_content"),
            "image_path": node.get("image_path"),
            "image_paths": node.get("image_paths"),
            "caption_bboxes": node.get("caption_bboxes"),
            "footnote_bboxes": node.get("footnote_bboxes"),
            "merged_bboxes": node.get("merged_bboxes"),
            "caption_block_uid": node.get("caption_block_uid"),
            "caption_block_uids": node.get("caption_block_uids"),
            "footnote_block_uid": node.get("footnote_block_uid"),
            "footnote_block_uids": node.get("footnote_block_uids"),
            "parent_uid": node.get("parent_uid"),
            "derived_level": node.get("derived_level"),
            "order_index": order_index,
        }
        items.append({
            "id": block_uid,
            "item_type": block_type,
            "title": title,
            "content": plain_text or title,
            "meta": {key: value for key, value in meta.items() if value is not None},
        })
    return items


# 基于最新图谱节点重写结构化片段的展示字段。
def _sync_structured_segments_after_node_update(
    library_id: str,
    doc_id: str,
    graph_data: Dict[str, Any],
) -> int:
    from docs_core.knowledge_service import knowledge_service

    updated_items = _build_structured_segment_items_from_graph(graph_data)
    return knowledge_service.save_document_segments(doc_id, library_id, "A_structured", updated_items)


# 将源节点内容并入目标节点，并移除源节点。
def _merge_graph_nodes(graph_data: Dict[str, Any], source_uid: str, target_uid: str) -> Dict[str, Any]:
    if source_uid == target_uid:
        raise ValueError("不能把 block 合并到自身")
    node_map = _build_active_node_map(graph_data)
    source_node = node_map.get(source_uid)
    target_node = node_map.get(target_uid)
    if not source_node or not target_node:
        raise KeyError("合并目标不存在")
    if _would_create_cycle(node_map, source_uid, target_uid):
        raise ValueError("不能把 block 合并到自己的子节点")

    target_node["plain_text"] = _merge_text_value(target_node.get("plain_text"), source_node.get("plain_text"))
    target_node["caption"] = _merge_text_value(target_node.get("caption"), source_node.get("caption"))
    target_node["footnote"] = _merge_text_value(target_node.get("footnote"), source_node.get("footnote"))
    if not str(target_node.get("math_content") or "").strip():
        target_node["math_content"] = source_node.get("math_content")
    if not str(target_node.get("table_html") or "").strip():
        target_node["table_html"] = source_node.get("table_html")
    _merge_rich_media_fields_into_target(target_node, [target_node, source_node])
    target_node["merged_bboxes"] = _normalize_graph_bbox_list([
        *_collect_node_bbox_list(target_node),
        *_collect_node_bbox_list(source_node),
    ]) or None
    target_node["merged_block_uids"] = list(dict.fromkeys([
        *_collect_node_merge_block_uids(target_node),
        *_collect_node_merge_block_uids(source_node),
    ])) or None

    updated_nodes: List[Dict[str, Any]] = []
    for node in graph_data.get("nodes") or []:
        block_uid = _normalize_block_uid(node.get("block_uid") or node.get("id"))
        if block_uid == source_uid:
            continue
        if _normalize_block_uid(node.get("parent_uid")) == source_uid:
            node["parent_uid"] = target_uid
        node["caption_block_uid"] = _replace_block_ref(node.get("caption_block_uid"), source_uid, target_uid)
        node["caption_block_uids"] = _replace_block_ref(node.get("caption_block_uids"), source_uid, target_uid)
        node["footnote_block_uid"] = _replace_block_ref(node.get("footnote_block_uid"), source_uid, target_uid)
        node["footnote_block_uids"] = _replace_block_ref(node.get("footnote_block_uids"), source_uid, target_uid)
        if _normalize_block_uid(node.get("explain_for_uid")) == source_uid:
            node["explain_for_uid"] = target_uid
        updated_nodes.append(node)
    graph_data["nodes"] = updated_nodes
    _sync_related_graph_fields(graph_data.get("nodes") or [], target_uid, target_node)
    return target_node


# 深拷贝图谱节点，避免直接复用嵌套引用。
def _clone_graph_node(node: Dict[str, Any]) -> Dict[str, Any]:
    return json.loads(json.dumps(node, ensure_ascii=False))


# 规范拆分后新文本节点的类型，避免继续挂着富媒体 block_type。
def _normalize_split_block_type(block_type: Any) -> str:
    normalized = str(block_type or "").strip()
    if normalized in {"title", "heading", "clause", "list", "paragraph"}:
        return normalized
    return "paragraph"


# 为拆分后的新节点生成稳定且唯一的 block_uid。
def _generate_manual_block_uid(doc_id: str) -> str:
    return f"{doc_id}:manual:{uuid.uuid4().hex[:12]}"


# 将当前活动节点按页码拆为可重排的顺序桶。
def _build_page_node_buckets(graph_data: Dict[str, Any]) -> Dict[int, List[Dict[str, Any]]]:
    buckets: Dict[int, List[Dict[str, Any]]] = {}
    for node in _sort_graph_nodes(_get_active_graph_nodes(graph_data)):
        page_idx = int(node.get("page_idx") or 0)
        buckets.setdefault(page_idx, []).append(node)
    return buckets


# 根据页面桶重写 page_idx 与 block_seq，保证跨页重组后的顺序稳定。
def _resequence_page_node_buckets(page_buckets: Dict[int, List[Dict[str, Any]]]) -> None:
    for page_idx in sorted(page_buckets.keys()):
        for block_seq, node in enumerate(page_buckets.get(page_idx) or [], start=1):
            node["page_idx"] = int(page_idx)
            node["block_seq"] = int(block_seq)
            node["page_seq"] = int(page_idx) + 1


# 过滤多值 block 引用，移除已删除节点。
def _filter_removed_block_refs(values: Any, removed_uids: Set[str]) -> Optional[List[str]]:
    normalized_values: List[str] = []
    for value in values or []:
        normalized_value = _normalize_block_uid(value)
        if normalized_value and normalized_value not in removed_uids:
            normalized_values.append(normalized_value)
    return normalized_values or None


# 校验并返回批量操作涉及的 block_uid 列表。
def _resolve_batch_block_uids(graph_data: Dict[str, Any], block_ids: List[str]) -> List[str]:
    normalized_uids: List[str] = []
    seen = set()
    for raw_block_id in block_ids or []:
        block_uid = _normalize_block_uid(raw_block_id)
        if not block_uid or block_uid in seen:
            continue
        _get_graph_node_or_raise(graph_data, block_uid)
        seen.add(block_uid)
        normalized_uids.append(block_uid)
    if not normalized_uids:
        raise ValueError("至少需要选择一个 block")
    return normalized_uids


# 把活动图谱节点重建为 doc_blocks 所需的基础行与派生行。
def _build_doc_block_projection_rows(doc_id: str, graph_data: Dict[str, Any]) -> Any:
    stats = graph_data.get("stats")
    if not isinstance(stats, dict):
        stats = {}
    base_row_map = {
        _normalize_block_uid(row.get("block_uid")): dict(row)
        for row in (stats.get("base_rows") or [])
        if _normalize_block_uid(row.get("block_uid"))
    }
    derived_row_map = {
        _normalize_block_uid(row.get("block_uid")): dict(row)
        for row in (stats.get("derived_rows") or [])
        if _normalize_block_uid(row.get("block_uid"))
    }
    now = datetime.now().isoformat()
    graph_doc_name = str(graph_data.get("doc_name") or doc_id)
    base_rows: List[Dict[str, Any]] = []
    derived_rows: List[Dict[str, Any]] = []
    for node in _sort_graph_nodes(_get_active_graph_nodes(graph_data)):
        block_uid = _normalize_block_uid(node.get("block_uid") or node.get("id"))
        bbox = node.get("bbox") or [0.0, 0.0, 0.0, 0.0]
        bbox_values = list(bbox)[:4] if isinstance(bbox, list) else [0.0, 0.0, 0.0, 0.0]
        while len(bbox_values) < 4:
            bbox_values.append(0.0)
        base_row = dict(base_row_map.get(block_uid) or {})
        base_row.update({
            "doc_id": doc_id,
            "doc_name": base_row.get("doc_name") or graph_doc_name,
            "page_idx": int(node.get("page_idx") or 0),
            "block_seq": int(node.get("block_seq") or 0),
            "block_uid": block_uid,
            "block_type": node.get("block_type"),
            "content_json": node.get("content_json") if node.get("content_json") is not None else (base_row.get("content_json") or {}),
            "plain_text": node.get("plain_text", ""),
            "bbox_abs_x1": bbox_values[0],
            "bbox_abs_y1": bbox_values[1],
            "bbox_abs_x2": bbox_values[2],
            "bbox_abs_y2": bbox_values[3],
            "created_at": base_row.get("created_at") or now,
            "updated_at": now,
        })
        derived_row = dict(derived_row_map.get(block_uid) or {})
        derived_row.update({
            "doc_id": doc_id,
            "block_uid": block_uid,
            "page_seq": int(node.get("page_idx") or 0) + 1,
            "bbox_source": node.get("bbox_source"),
            "derived_title_level": node.get("derived_level"),
            "title_path": node.get("title_path"),
            "parent_block_uid": node.get("parent_uid"),
            "prev_block_uid": node.get("prev_uid"),
            "next_block_uid": node.get("next_uid"),
            "explain_for_block_uid": node.get("explain_for_uid"),
            "table_html": node.get("table_html"),
            "math_content": node.get("math_content"),
            "image_path": node.get("image_path"),
            "derived_confidence": node.get("confidence"),
            "derived_by": node.get("derived_by"),
            "updated_at": now,
        })
        base_rows.append(base_row)
        derived_rows.append(derived_row)
    return base_rows, derived_rows


# 把最新图谱整体同步到 doc_blocks 索引表，覆盖单块与批量结构改动。
def _persist_graph_projection_to_index_store(doc_id: str, graph_data: Dict[str, Any]) -> None:
    from docs_core.knowledge_service import knowledge_service

    base_rows, derived_rows = _build_doc_block_projection_rows(doc_id, graph_data)
    knowledge_service.index_store.clear_doc_blocks(doc_id)
    if base_rows:
        knowledge_service.index_store.insert_doc_blocks_base_rows(base_rows)
    if derived_rows:
        knowledge_service.index_store.update_doc_blocks_derived_rows(derived_rows)


# 批量把多个节点内容并入目标节点，并移除其余源节点。
def _merge_multiple_graph_nodes(graph_data: Dict[str, Any], block_uids: List[str], target_uid: str) -> Dict[str, Any]:
    ordered_nodes = _sort_graph_nodes(_get_active_graph_nodes(graph_data))
    selected_set = set(block_uids)
    if target_uid not in selected_set:
        raise ValueError("目标 block 必须在选中集合内")
    node_map = _build_active_node_map(graph_data)
    target_node = node_map.get(target_uid)
    if not target_node:
        raise KeyError("未找到目标 block")
    merge_sources = [uid for uid in block_uids if uid != target_uid]
    for source_uid in merge_sources:
        if _would_create_cycle(node_map, source_uid, target_uid):
            raise ValueError("不能把祖先 block 合并到自己的子节点")
    merged_nodes = [
        node for node in ordered_nodes
        if _normalize_block_uid(node.get("block_uid") or node.get("id")) in selected_set
    ]
    merged_node_snapshots = [dict(node) for node in merged_nodes]
    target_node["plain_text"] = ""
    target_node["caption"] = ""
    target_node["footnote"] = ""
    target_node["math_content"] = None
    target_node["table_html"] = None
    for node in merged_node_snapshots:
        target_node["plain_text"] = _merge_text_value(target_node.get("plain_text"), node.get("plain_text"))
        target_node["caption"] = _merge_text_value(target_node.get("caption"), node.get("caption"))
        target_node["footnote"] = _merge_text_value(target_node.get("footnote"), node.get("footnote"))
        if not str(target_node.get("math_content") or "").strip() and str(node.get("math_content") or "").strip():
            target_node["math_content"] = node.get("math_content")
        if not str(target_node.get("table_html") or "").strip() and str(node.get("table_html") or "").strip():
            target_node["table_html"] = node.get("table_html")
    _merge_rich_media_fields_into_target(target_node, merged_node_snapshots)
    target_node["merged_bboxes"] = _normalize_graph_bbox_list([
        bbox
        for node in merged_node_snapshots
        for bbox in _collect_node_bbox_list(node)
    ]) or None
    target_node["merged_block_uids"] = list(dict.fromkeys([
        block_uid
        for node in merged_node_snapshots
        for block_uid in _collect_node_merge_block_uids(node)
    ])) or None

    updated_nodes: List[Dict[str, Any]] = []
    merge_source_set = set(merge_sources)
    for node in graph_data.get("nodes") or []:
        block_uid = _normalize_block_uid(node.get("block_uid") or node.get("id"))
        if block_uid in merge_source_set:
            continue
        if _normalize_block_uid(node.get("parent_uid")) in merge_source_set:
            node["parent_uid"] = target_uid
        for source_uid in merge_sources:
            node["caption_block_uid"] = _replace_block_ref(node.get("caption_block_uid"), source_uid, target_uid)
            node["caption_block_uids"] = _replace_block_ref(node.get("caption_block_uids"), source_uid, target_uid)
            node["footnote_block_uid"] = _replace_block_ref(node.get("footnote_block_uid"), source_uid, target_uid)
            node["footnote_block_uids"] = _replace_block_ref(node.get("footnote_block_uids"), source_uid, target_uid)
            if _normalize_block_uid(node.get("explain_for_uid")) == source_uid:
                node["explain_for_uid"] = target_uid
        updated_nodes.append(node)
    graph_data["nodes"] = updated_nodes
    _sync_related_graph_fields(graph_data.get("nodes") or [], target_uid, target_node)
    return target_node


# 按用户提供的片段把单个 block 拆成多个连续节点。
def _split_graph_node(
    graph_data: Dict[str, Any],
    doc_id: str,
    block_uid: str,
    split_segments: List[Dict[str, Any]],
) -> List[str]:
    normalized_segments = [
        {"plain_text": str((segment or {}).get("plain_text") or "").strip()}
        for segment in (split_segments or [])
    ]
    normalized_segments = [segment for segment in normalized_segments if segment.get("plain_text")]
    if len(normalized_segments) < 2:
        raise ValueError("拆分后至少需要两个非空片段")
    source_node, source_uid = _get_graph_node_or_raise(graph_data, block_uid)
    source_node["plain_text"] = normalized_segments[0]["plain_text"]
    split_block_type = _normalize_split_block_type(source_node.get("block_type"))
    page_buckets = _build_page_node_buckets(graph_data)
    source_page_idx = int(source_node.get("page_idx") or 0)
    page_nodes = page_buckets.get(source_page_idx) or []
    source_index = next(
        (index for index, node in enumerate(page_nodes) if _normalize_block_uid(node.get("block_uid") or node.get("id")) == source_uid),
        -1,
    )
    if source_index < 0:
        raise KeyError(f"未找到块节点: {block_uid}")
    created_nodes: List[Dict[str, Any]] = []
    created_block_ids: List[str] = []
    for segment in normalized_segments[1:]:
        new_node = _clone_graph_node(source_node)
        new_block_uid = _generate_manual_block_uid(doc_id)
        new_node["id"] = new_block_uid
        new_node["block_uid"] = new_block_uid
        new_node["block_type"] = split_block_type
        new_node["plain_text"] = segment["plain_text"]
        new_node["math_content"] = None
        new_node["table_html"] = None
        new_node["caption"] = None
        new_node["footnote"] = None
        new_node["image_path"] = None
        new_node["image_paths"] = None
        new_node["caption_block_uid"] = None
        new_node["caption_block_uids"] = None
        new_node["caption_bboxes"] = None
        new_node["footnote_block_uid"] = None
        new_node["footnote_block_uids"] = None
        new_node["footnote_bboxes"] = None
        new_node["merged_bboxes"] = None
        new_node["merged_block_uids"] = None
        new_node["content_json"] = {}
        new_node["prev_uid"] = None
        new_node["next_uid"] = None
        created_nodes.append(new_node)
        created_block_ids.append(new_block_uid)
    page_nodes[source_index + 1:source_index + 1] = created_nodes
    graph_data["nodes"].extend(created_nodes)
    _resequence_page_node_buckets(page_buckets)
    _sort_graph_data_nodes(graph_data)
    return created_block_ids


# 删除选中的 block，并把仍保留的子节点提升到最近的存活父级。
def _delete_graph_nodes(graph_data: Dict[str, Any], block_uids: List[str]) -> List[str]:
    delete_uid_set = set(block_uids)
    ordered_delete_uids = [
        _normalize_block_uid(node.get("block_uid") or node.get("id"))
        for node in _sort_graph_nodes(_get_active_graph_nodes(graph_data))
        if _normalize_block_uid(node.get("block_uid") or node.get("id")) in delete_uid_set
    ]
    delete_uids = set(ordered_delete_uids)
    if not delete_uids:
        raise ValueError("至少需要删除一个 block")

    node_map = _build_active_node_map(graph_data)
    parent_map = {
        block_uid: _normalize_block_uid(node.get("parent_uid")) or None
        for block_uid, node in node_map.items()
    }

    def resolve_surviving_parent(parent_uid: Any) -> Optional[str]:
        current_uid = _normalize_block_uid(parent_uid) or None
        visited: Set[str] = set()
        while current_uid and current_uid in delete_uids and current_uid not in visited:
            visited.add(current_uid)
            current_uid = parent_map.get(current_uid)
        return current_uid or None

    updated_nodes: List[Dict[str, Any]] = []
    for node in graph_data.get("nodes") or []:
        block_uid = _normalize_block_uid(node.get("block_uid") or node.get("id"))
        if block_uid in delete_uids:
            continue
        node["parent_uid"] = resolve_surviving_parent(node.get("parent_uid"))
        if _normalize_block_uid(node.get("caption_block_uid")) in delete_uids:
            node["caption_block_uid"] = None
        node["caption_block_uids"] = _filter_removed_block_refs(node.get("caption_block_uids"), delete_uids)
        if _normalize_block_uid(node.get("footnote_block_uid")) in delete_uids:
            node["footnote_block_uid"] = None
        node["footnote_block_uids"] = _filter_removed_block_refs(node.get("footnote_block_uids"), delete_uids)
        if _normalize_block_uid(node.get("explain_for_uid")) in delete_uids:
            node["explain_for_uid"] = None
        updated_nodes.append(node)
    graph_data["nodes"] = updated_nodes
    page_buckets = _build_page_node_buckets(graph_data)
    _resequence_page_node_buckets(page_buckets)
    _sort_graph_data_nodes(graph_data)
    return ordered_delete_uids


# 将选中的 block 跨页移动到目标页，并支持插入到指定锚点之后。
def _reorganize_graph_nodes(
    graph_data: Dict[str, Any],
    block_uids: List[str],
    target_page_idx: Optional[int],
    insert_after_block_uid: Optional[str],
    parent_block_uid: Optional[str],
    derived_title_level: Optional[int],
) -> List[str]:
    selected_set = set(block_uids)
    node_map = _build_active_node_map(graph_data)
    if parent_block_uid and parent_block_uid in selected_set:
        raise ValueError("目标父节点不能包含在移动集合内")
    page_buckets = _build_page_node_buckets(graph_data)
    moving_nodes: List[Dict[str, Any]] = []
    for page_idx, nodes in list(page_buckets.items()):
        retained_nodes: List[Dict[str, Any]] = []
        for node in nodes:
            block_uid = _normalize_block_uid(node.get("block_uid") or node.get("id"))
            if block_uid in selected_set:
                moving_nodes.append(node)
            else:
                retained_nodes.append(node)
        page_buckets[page_idx] = retained_nodes
    if not moving_nodes:
        raise ValueError("未找到可移动的 block")

    target_page_value = int(target_page_idx) if target_page_idx is not None else None
    insertion_index = None
    if insert_after_block_uid:
        insert_after_uid = _normalize_block_uid(insert_after_block_uid)
        if insert_after_uid in selected_set:
            raise ValueError("插入锚点不能位于当前移动集合内")
        anchor_node = node_map.get(insert_after_uid)
        if not anchor_node:
            raise KeyError(f"未找到插入锚点: {insert_after_uid}")
        target_page_value = int(anchor_node.get("page_idx") or 0)
        target_nodes = page_buckets.setdefault(target_page_value, [])
        insertion_index = next(
            (index for index, node in enumerate(target_nodes) if _normalize_block_uid(node.get("block_uid") or node.get("id")) == insert_after_uid),
            len(target_nodes) - 1,
        ) + 1
    if target_page_value is None:
        target_page_value = int(moving_nodes[0].get("page_idx") or 0)

    target_nodes = page_buckets.setdefault(target_page_value, [])
    if insertion_index is None:
        insertion_index = len(target_nodes)
    for node in moving_nodes:
        node["page_idx"] = target_page_value
        if parent_block_uid is not None:
            if parent_block_uid and _would_create_cycle(node_map, _normalize_block_uid(node.get("block_uid") or node.get("id")), parent_block_uid):
                raise ValueError("目标父节点不能设置为自身或子节点")
            node["parent_uid"] = _normalize_block_uid(parent_block_uid) or None
        if derived_title_level is not None:
            node["derived_level"] = int(derived_title_level)
    target_nodes[insertion_index:insertion_index] = moving_nodes
    _resequence_page_node_buckets(page_buckets)
    return [_normalize_block_uid(node.get("block_uid") or node.get("id")) for node in moving_nodes]


# 按批次统一应用多个标题节点的目标层级，并重算它们的父子关系。
def _apply_graph_node_levels(graph_data: Dict[str, Any], next_levels: Dict[str, int]) -> List[str]:
    ordered_nodes = _sort_graph_nodes(_get_active_graph_nodes(graph_data))
    node_map = _build_active_node_map(graph_data)
    selected_set = set(next_levels.keys())
    ordered_selected_uids = [
        _normalize_block_uid(node.get("block_uid") or node.get("id"))
        for node in ordered_nodes
        if _normalize_block_uid(node.get("block_uid") or node.get("id")) in selected_set
    ]
    if not ordered_selected_uids:
        raise ValueError("未找到可调整层级的 block")

    latest_by_level: Dict[int, str] = {}
    for node in ordered_nodes:
        block_uid = _normalize_block_uid(node.get("block_uid") or node.get("id"))
        if not block_uid:
            continue
        effective_level = next_levels.get(block_uid)
        if effective_level is not None:
            next_parent_uid = latest_by_level.get(effective_level - 1) if effective_level > 1 else None
            node["derived_level"] = effective_level
            node["parent_uid"] = next_parent_uid
            latest_by_level[effective_level] = block_uid
            for stale_level in [level for level in latest_by_level.keys() if level > effective_level]:
                latest_by_level.pop(stale_level, None)
            continue
        derived_level = node.get("derived_level")
        if derived_level is None or derived_level == "":
            continue
        try:
            normalized_level = int(derived_level)
        except (TypeError, ValueError):
            continue
        if normalized_level < 1:
            continue
        latest_by_level[normalized_level] = block_uid
        for stale_level in [level for level in latest_by_level.keys() if level > normalized_level]:
            latest_by_level.pop(stale_level, None)

    return ordered_selected_uids


# 按批次统一升降多个标题节点的层级，并重算它们的父子关系。
def _relevel_graph_nodes(graph_data: Dict[str, Any], block_uids: List[str], level_delta: int) -> List[str]:
    if level_delta == 0:
        raise ValueError("层级调整量不能为 0")
    ordered_nodes = _sort_graph_nodes(_get_active_graph_nodes(graph_data))
    selected_set = set(block_uids)
    next_levels: Dict[str, int] = {}
    for node in ordered_nodes:
        block_uid = _normalize_block_uid(node.get("block_uid") or node.get("id"))
        if block_uid not in selected_set:
            continue
        current_level = node.get("derived_level")
        if current_level is None or current_level == "":
            raise ValueError("批量升降级仅支持已识别为标题的节点")
        try:
            normalized_level = int(current_level)
        except (TypeError, ValueError) as exc:
            raise ValueError("批量升降级仅支持已识别为标题的节点") from exc
        target_level = normalized_level + int(level_delta)
        if target_level < 1:
            raise ValueError("L1 节点不能继续升一级")
        next_levels[block_uid] = target_level
    return _apply_graph_node_levels(graph_data, next_levels)


# 按批次把多个节点直接设置为指定层级，并重算它们的父子关系。
def _set_graph_nodes_level(graph_data: Dict[str, Any], block_uids: List[str], target_level: int) -> List[str]:
    normalized_target_level = int(target_level)
    if normalized_target_level < 1:
        raise ValueError("目标层级必须大于等于 L1")
    next_levels = {
        _normalize_block_uid(block_uid): normalized_target_level
        for block_uid in block_uids
        if _normalize_block_uid(block_uid)
    }
    if not next_levels:
        raise ValueError("未找到可调整层级的 block")
    return _apply_graph_node_levels(graph_data, next_levels)


# 执行批量结构操作，并同步图谱、索引库与结构化片段。
def batch_operate_doc_blocks(
    library_id: str,
    doc_id: str,
    operation: str,
    payload: Dict[str, Any],
) -> Dict[str, Any]:
    graph_data = get_doc_blocks_graph(library_id, doc_id)
    if not graph_data:
        raise FileNotFoundError("文档块图谱不存在")

    block_uids = _resolve_batch_block_uids(graph_data, payload.get("blockIds") or [])
    graph_snapshot_before = _clone_json_compatible(graph_data)
    result_payload = {
        "operation": operation,
        "block_ids": block_uids,
        "created_block_ids": [],
        "removed_block_ids": [],
        "target_block_id": None,
        "updated_block_ids": [],
    }
    if operation == "merge":
        if len(block_uids) < 2:
            raise ValueError("批量合并至少需要选择两个 block")
        target_block_uid = _normalize_block_uid(payload.get("targetBlockId"))
        if not target_block_uid:
            raise ValueError("批量合并必须指定目标 block")
        _merge_multiple_graph_nodes(graph_data, block_uids, target_block_uid)
        result_payload["removed_block_ids"] = [uid for uid in block_uids if uid != target_block_uid]
        result_payload["target_block_id"] = target_block_uid
    elif operation == "split":
        if len(block_uids) != 1:
            raise ValueError("拆分 block 只能选择一个源 block")
        result_payload["created_block_ids"] = _split_graph_node(
            graph_data,
            doc_id,
            block_uids[0],
            payload.get("splitSegments") or [],
        )
    elif operation == "delete":
        result_payload["removed_block_ids"] = _delete_graph_nodes(graph_data, block_uids)
    elif operation == "relevel":
        target_level = payload.get("targetLevel")
        if target_level is not None:
            try:
                normalized_target_level = int(target_level)
            except (TypeError, ValueError) as exc:
                raise ValueError("targetLevel 必须是整数") from exc
            result_payload["updated_block_ids"] = _set_graph_nodes_level(graph_data, block_uids, normalized_target_level)
        else:
            level_delta = payload.get("levelDelta")
            if level_delta is None:
                raise ValueError("批量层级调整必须提供 levelDelta 或 targetLevel")
            try:
                normalized_level_delta = int(level_delta)
            except (TypeError, ValueError) as exc:
                raise ValueError("levelDelta 必须是整数") from exc
            result_payload["updated_block_ids"] = _relevel_graph_nodes(graph_data, block_uids, normalized_level_delta)
    else:
        raise ValueError(f"不支持的批量操作: {operation}")

    _rebuild_graph_projection(graph_data)
    graph_data["updated_at"] = datetime.now().isoformat()
    graph_path = _write_doc_blocks_graph(library_id, doc_id, graph_data)

    from docs_core.knowledge_service import knowledge_service

    _persist_graph_projection_to_index_store(doc_id, graph_data)
    record_block_uid = _normalize_block_uid(payload.get("targetBlockId")) or block_uids[0]
    correction_payload = dict(payload)
    if operation in {"merge", "split", "delete", "relevel"}:
        correction_payload["undo_graph_snapshot"] = graph_snapshot_before
    knowledge_service.index_store.record_doc_block_correction(doc_id, record_block_uid, operation, correction_payload)
    saved_segments = _sync_structured_segments_after_node_update(library_id, doc_id, graph_data)
    knowledge_service.update_node(doc_id, updated_at=datetime.now())
    result_payload["graph_path"] = graph_path
    result_payload["saved_segments"] = saved_segments
    return result_payload


# 撤回当前文档最近一次可回滚的 block 结构操作，并恢复到操作前的图谱状态。
def undo_last_doc_block_operation(library_id: str, doc_id: str) -> Dict[str, Any]:
    from docs_core.knowledge_service import knowledge_service

    correction_record = knowledge_service.index_store.get_latest_doc_block_correction(doc_id)
    if not correction_record:
        raise ValueError("当前文档没有可撤回的结构操作")
    operation_type = str(correction_record.get("operation_type") or "").strip() or "unknown"
    payload = correction_record.get("payload") or {}
    snapshot = payload.get("undo_graph_snapshot")
    if not isinstance(snapshot, dict) or not isinstance(snapshot.get("nodes"), list):
        raise ValueError(f"最近一次 {operation_type} 操作不支持撤回")

    graph_data = _clone_json_compatible(snapshot)
    _rebuild_graph_projection(graph_data)
    _sort_graph_data_nodes(graph_data)
    graph_data["updated_at"] = datetime.now().isoformat()
    graph_path = _write_doc_blocks_graph(library_id, doc_id, graph_data)
    _persist_graph_projection_to_index_store(doc_id, graph_data)
    saved_segments = _sync_structured_segments_after_node_update(library_id, doc_id, graph_data)
    knowledge_service.index_store.delete_doc_block_correction(str(correction_record.get("id") or ""))
    knowledge_service.update_node(doc_id, updated_at=datetime.now())
    return {
        "graph_path": graph_path,
        "saved_segments": saved_segments,
        "restored_block_ids": [
            _normalize_block_uid(node.get("block_uid") or node.get("id"))
            for node in _sort_graph_nodes(_get_active_graph_nodes(graph_data))
            if _normalize_block_uid(node.get("block_uid") or node.get("id"))
        ],
    }


# 兼容旧调用名，统一走最近一次结构操作撤回。
def undo_last_doc_block_merge(library_id: str, doc_id: str) -> Dict[str, Any]:
    return undo_last_doc_block_operation(library_id, doc_id)


# 更新单个结构节点的纠错内容并同步索引投影。
def update_doc_block_content(
    library_id: str,
    doc_id: str,
    block_id: str,
    changes: Dict[str, Any],
) -> Dict[str, Any]:
    graph_data = get_doc_blocks_graph(library_id, doc_id)
    if not graph_data:
        raise FileNotFoundError("文档块图谱不存在")
    graph_snapshot_before = _clone_json_compatible(graph_data)

    editable_keys = {
        "plain_text",
        "math_content",
        "table_html",
        "title",
        "caption",
        "footnote",
        "parent_block_uid",
        "derived_title_level",
        "merge_into_block_uid",
    }
    normalized_changes = {key: value for key, value in changes.items() if key in editable_keys}
    if not normalized_changes:
        raise ValueError("未提供可更新字段")

    target_node, target_block_uid = _get_graph_node_or_raise(graph_data, block_id)
    source_block_uid = target_block_uid
    node_map = _build_active_node_map(graph_data)

    next_parent_uid = None
    if "parent_block_uid" in normalized_changes:
        next_parent_uid = _normalize_block_uid(normalized_changes.get("parent_block_uid")) or None
        if next_parent_uid and next_parent_uid not in node_map:
            raise KeyError(f"未找到父级节点: {next_parent_uid}")
        if _would_create_cycle(node_map, target_block_uid, next_parent_uid):
            raise ValueError("父级节点不能设置为自身或子节点")
        target_node["parent_uid"] = next_parent_uid

    if "derived_title_level" in normalized_changes:
        level_value = normalized_changes.get("derived_title_level")
        target_node["derived_level"] = int(level_value) if level_value is not None else None
        if "parent_block_uid" not in normalized_changes:
            next_parent_uid = _infer_parent_uid_from_level(
                _get_active_graph_nodes(graph_data),
                target_block_uid,
                target_node.get("derived_level"),
            )
            if next_parent_uid and _would_create_cycle(node_map, target_block_uid, next_parent_uid):
                raise ValueError("自动推断出的父级节点形成循环，请手动指定父级节点")
            target_node["parent_uid"] = next_parent_uid
    elif next_parent_uid and target_node.get("derived_level") is not None:
        parent_node = node_map.get(next_parent_uid)
        parent_level = parent_node.get("derived_level") if parent_node else None
        target_node["derived_level"] = int(parent_level) + 1 if parent_level is not None else 1

    for key in ("plain_text", "math_content", "table_html", "caption", "footnote"):
        if key in normalized_changes:
            target_node[key] = normalized_changes.get(key)
    if "title" in normalized_changes:
        target_node["title_path"] = normalized_changes.get("title")
        if not str(target_node.get("plain_text") or "").strip():
            target_node["plain_text"] = normalized_changes.get("title")

    merge_target_uid = _normalize_block_uid(normalized_changes.get("merge_into_block_uid"))
    if merge_target_uid:
        target_node = _merge_graph_nodes(graph_data, target_block_uid, merge_target_uid)
        target_block_uid = merge_target_uid

    _rebuild_graph_projection(graph_data)
    _sync_related_graph_fields(graph_data.get("nodes") or [], target_block_uid, target_node)
    graph_data["updated_at"] = datetime.now().isoformat()
    graph_path = _write_doc_blocks_graph(library_id, doc_id, graph_data)

    from docs_core.knowledge_service import knowledge_service

    _persist_graph_projection_to_index_store(doc_id, graph_data)
    operation_type = "merge" if merge_target_uid else "update"
    correction_payload = dict(normalized_changes)
    if merge_target_uid:
        correction_payload["undo_graph_snapshot"] = graph_snapshot_before
    knowledge_service.index_store.record_doc_block_correction(doc_id, target_block_uid, operation_type, correction_payload)
    saved_segments = _sync_structured_segments_after_node_update(library_id, doc_id, graph_data)
    knowledge_service.update_node(doc_id, updated_at=datetime.now())

    return {
        "graph_path": graph_path,
        "block_id": target_block_uid,
        "updated_fields": list(normalized_changes.keys()),
        "saved_segments": saved_segments,
        "node": target_node,
    }


# 从 Markdown 提取结构化项目。
def extract_structured_items_from_markdown(
    markdown_text: str,
    mineru_blocks: List[Dict[str, Any]] = None,
) -> List[Dict[str, Any]]:
    lines = markdown_text.splitlines()
    items: List[Dict[str, Any]] = []
    order_index = 0

    image_pattern = re.compile(r'!\[([^\]]*)\]\(([^)\s]+)(?:\s+"([^"]+)")?\)')
    heading_pattern = re.compile(r"^(#{1,6})\s+(.+?)\s*$")
    clause_pattern = re.compile(r"^\s*(\d+(?:\.\d+)*(?:[、.)])?)\s+(.+)$")

    # 清理文本，保留中文字符、字母和数字，用于模糊匹配。
    def clean_text(text: str) -> str:
        if not text:
            return ""
        return re.sub(r"[^\u4e00-\u9fa5a-zA-Z0-9]", "", text).lower()

    # 判断当前行是否属于 Markdown 表格行。
    def is_table_row(text: str) -> bool:
        stripped = text.strip()
        return stripped.startswith("|") and stripped.endswith("|") and stripped.count("|") >= 2

    # 判断当前行是否为 Markdown 表格分隔行。
    def is_table_separator(text: str) -> bool:
        stripped = text.strip().replace(" ", "")
        return bool(stripped) and set(stripped) <= {"|", "-", ":"}

    blocks_by_type: Dict[str, List[Dict[str, Any]]] = {}
    if mineru_blocks:
        for block in mineru_blocks:
            block_type = block.get("type", "paragraph")
            block["cleaned_text"] = clean_text(block.get("text", ""))
            if block_type not in blocks_by_type:
                blocks_by_type[block_type] = []
            blocks_by_type[block_type].append(block)

    stats = {
        "total_items": 0,
        "matched_items": 0,
        "types": {},
    }
    last_matched_idx: Dict[str, int] = {}

    # 在指定类型块中查找最佳匹配项。
    def find_best_match(text: str, block_type: str) -> Optional[Dict[str, Any]]:
        if not mineru_blocks or block_type not in blocks_by_type:
            return None

        cleaned = clean_text(text)
        if not cleaned:
            return None

        blocks = blocks_by_type[block_type]
        start_idx = last_matched_idx.get(block_type, 0)
        best_match = None
        best_score = 0.0

        for idx in range(start_idx, len(blocks)):
            block = blocks[idx]
            block_text = block.get("cleaned_text", "")
            if not block_text:
                continue

            if cleaned == block_text:
                last_matched_idx[block_type] = idx + 1
                return block

            if cleaned in block_text or block_text in cleaned:
                shorter = min(len(cleaned), len(block_text))
                longer = max(len(cleaned), len(block_text))
                score = shorter / longer if longer else 0.0
                if score > best_score and score >= 0.6:
                    best_score = score
                    best_match = block

        if best_match:
            try:
                match_idx = blocks.index(best_match)
                last_matched_idx[block_type] = match_idx + 1
            except ValueError:
                pass

        return best_match

    # 把匹配到的 MinerU 元信息写入 meta。
    def enrich_meta(meta: Dict[str, Any], match: Optional[Dict[str, Any]], block_type: str) -> None:
        stats["total_items"] += 1
        stats["types"].setdefault(block_type, {"total": 0, "matched": 0})
        stats["types"][block_type]["total"] += 1

        if not match:
            return

        stats["matched_items"] += 1
        stats["types"][block_type]["matched"] += 1
        meta["mineru_match"] = {
            "bbox": match.get("bbox"),
            "page_idx": match.get("page_idx"),
            "block_idx": match.get("block_idx"),
            "type": match.get("type"),
        }

    idx = 0
    while idx < len(lines):
        line = lines[idx]
        image_match = image_pattern.search(line)
        if image_match:
            alt_text = image_match.group(1) or ""
            src = image_match.group(2) or ""
            title = image_match.group(3) or alt_text or Path(src).name
            meta = {"line": idx + 1, "src": src}
            match = find_best_match(title, "image")
            enrich_meta(meta, match, "image")
            items.append(
                {
                    "item_type": "image",
                    "title": title,
                    "content": alt_text or title,
                    "meta": meta,
                    "order_index": order_index,
                }
            )
            order_index += 1
            idx += 1
            continue

        heading_match = heading_pattern.match(line)
        if heading_match:
            level = len(heading_match.group(1))
            title = heading_match.group(2).strip()
            meta = {"line": idx + 1, "level": level}
            match = find_best_match(title, "title")
            enrich_meta(meta, match, "title")
            items.append(
                {
                    "item_type": "heading",
                    "title": title,
                    "content": title,
                    "meta": meta,
                    "order_index": order_index,
                }
            )
            order_index += 1
            idx += 1
            continue

        clause_match = clause_pattern.match(line)
        if clause_match:
            marker = clause_match.group(1).strip()
            content = clause_match.group(2).strip()
            title = f"{marker} {content}".strip()
            meta = {"line": idx + 1, "clause_marker": marker}
            match = find_best_match(title, "paragraph")
            enrich_meta(meta, match, "paragraph")
            items.append(
                {
                    "item_type": "clause",
                    "title": marker,
                    "content": content,
                    "meta": meta,
                    "order_index": order_index,
                }
            )
            order_index += 1
            idx += 1
            continue

        if is_table_row(line):
            table_lines = [line]
            next_idx = idx + 1
            while next_idx < len(lines) and is_table_row(lines[next_idx]):
                table_lines.append(lines[next_idx])
                next_idx += 1
            content = "\n".join(table_lines)
            title = table_lines[0].strip()
            meta = {"line": idx + 1, "rows": len(table_lines)}
            match = find_best_match(content, "table")
            enrich_meta(meta, match, "table")
            items.append(
                {
                    "item_type": "table",
                    "title": title[:50],
                    "content": content,
                    "meta": meta,
                    "order_index": order_index,
                }
            )
            order_index += 1
            idx = next_idx
            continue

        if is_table_separator(line):
            idx += 1
            continue

        text = line.strip()
        if text:
            meta = {"line": idx + 1}
            match = find_best_match(text, "segment")
            enrich_meta(meta, match, "segment")
            items.append(
                {
                    "item_type": "segment",
                    "title": text[:50],
                    "content": text,
                    "meta": meta,
                    "order_index": order_index,
                }
            )
            order_index += 1

        idx += 1

    total_items = stats["total_items"]
    matched_items = stats["matched_items"]
    match_rate = matched_items / total_items if total_items else 0
    print(f"[StructuredStrategy] Match rate: {match_rate:.2%} ({matched_items}/{total_items})")

    return items


__all__ = [
    "FileStorage",
    "_build_a_structured_segment_items",
    "build_structured_index_for_doc",
    "extract_structured_items_from_markdown",
    "file_storage",
    "get_doc_blocks_graph",
]
