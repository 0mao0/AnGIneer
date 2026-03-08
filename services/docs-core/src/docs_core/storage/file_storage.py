"""文件存储管理"""
import os
import json
import shutil
from pathlib import Path
from datetime import datetime
from typing import Optional, List, Dict, Any


class FileStorage:
    """文件存储管理器"""

    def __init__(self, base_dir: str = None):
        if base_dir is None:
            root_dir = Path(__file__).resolve().parents[5]
            base_dir = str(root_dir / 'data' / 'knowledge_base')

        self.base_dir = Path(base_dir)
        self.libraries_dir = self.base_dir / 'libraries'

        self._ensure_dirs()

    def _ensure_dirs(self):
        """确保目录存在"""
        self.libraries_dir.mkdir(parents=True, exist_ok=True)
        self._reorganize_once()

    def _library_root(self, library_id: str) -> Path:
        library_root = self.libraries_dir / library_id
        library_root.mkdir(parents=True, exist_ok=True)
        return library_root

    def get_doc_root(self, library_id: str, doc_id: str) -> Path:
        """获取一文档一目录根路径"""
        doc_root = self._library_root(library_id) / 'documents' / doc_id
        doc_root.mkdir(parents=True, exist_ok=True)
        return doc_root

    def get_source_dir(self, library_id: str, doc_id: str) -> Path:
        """获取源文件目录"""
        source_dir = self.get_doc_root(library_id, doc_id) / 'source'
        source_dir.mkdir(parents=True, exist_ok=True)
        return source_dir

    def get_parsed_dir(self, library_id: str, doc_id: str) -> Path:
        """获取解析结果目录"""
        parsed_dir = self.get_doc_root(library_id, doc_id) / 'parsed'
        parsed_dir.mkdir(parents=True, exist_ok=True)
        return parsed_dir

    def get_edited_dir(self, library_id: str, doc_id: str) -> Path:
        """获取编辑目录"""
        edited_dir = self.get_doc_root(library_id, doc_id) / 'edited'
        edited_dir.mkdir(parents=True, exist_ok=True)
        return edited_dir

    def get_raw_dir(self, library_id: str, doc_id: str) -> Path:
        """获取解析原始返回目录。"""
        raw_dir = self.get_parsed_dir(library_id, doc_id) / 'raw'
        raw_dir.mkdir(parents=True, exist_ok=True)
        return raw_dir

    def get_parsed_markdown_path(self, library_id: str, doc_id: str) -> Path:
        """获取解析 Markdown 路径"""
        return self.get_parsed_dir(library_id, doc_id) / 'content.md'

    def get_middle_json_path(self, library_id: str, doc_id: str) -> Path:
        """获取中间语义数据文件路径。"""
        return self.get_parsed_dir(library_id, doc_id) / 'middle.json'

    def get_edited_markdown_path(self, library_id: str, doc_id: str) -> Path:
        """获取新版编辑 Markdown 路径"""
        return self.get_edited_dir(library_id, doc_id) / 'current.md'

    def save_source_file(
        self,
        library_id: str,
        doc_id: str,
        content: bytes,
        original_filename: Optional[str] = None
    ) -> str:
        """保存源文件"""
        safe_name = Path(original_filename or f'{doc_id}.pdf').name
        source_path = self.get_source_dir(library_id, doc_id) / safe_name
        with open(source_path, 'wb') as f:
            f.write(content)
        return str(source_path)

    def save_markdown(self, library_id: str, doc_id: str, content: str) -> str:
        """保存 Markdown 文件"""
        parsed_md_path = self.get_parsed_markdown_path(library_id, doc_id)
        with open(parsed_md_path, 'w', encoding='utf-8') as f:
            f.write(content)
        edited_md_path = self.get_edited_markdown_path(library_id, doc_id)
        if not edited_md_path.exists():
            with open(edited_md_path, 'w', encoding='utf-8') as f:
                f.write(content)
        return str(parsed_md_path)

    def save_edited_markdown(self, library_id: str, doc_id: str, content: str) -> str:
        """保存编辑后的 Markdown 文件"""
        edited_dir = self.get_edited_dir(library_id, doc_id)
        current_path = edited_dir / 'current.md'
        with open(current_path, 'w', encoding='utf-8') as f:
            f.write(content)
        revision_dir = edited_dir / 'history'
        revision_dir.mkdir(parents=True, exist_ok=True)
        revision_path = revision_dir / f'{datetime.now().strftime("%Y%m%d%H%M%S")}.md'
        with open(revision_path, 'w', encoding='utf-8') as f:
            f.write(content)
        return str(current_path)

    def save_assets(self, library_id: str, doc_id: str, source_dir: str) -> str:
        """保存解析产物中的资产文件目录"""
        assets_path = self.get_parsed_dir(library_id, doc_id) / 'assets'
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

    def get_mineru_blocks_path(self, library_id: str, doc_id: str) -> Path:
        """获取 MinerU 块级结果路径"""
        return self.get_parsed_dir(library_id, doc_id) / 'mineru_blocks.json'

    def _legacy_mineru_blocks_paths(self, library_id: str, doc_id: str) -> List[Path]:
        parsed_dir = self.get_parsed_dir(library_id, doc_id)
        return [
            parsed_dir / 'block_data.json',
            parsed_dir / 'blocks.json'
        ]

    def save_mineru_blocks(self, library_id: str, doc_id: str, blocks: List[Dict[str, Any]]) -> str:
        """保存 MinerU 块级结果"""
        blocks_path = self.get_mineru_blocks_path(library_id, doc_id)
        with open(blocks_path, 'w', encoding='utf-8') as f:
            json_blocks = blocks if isinstance(blocks, list) else []
            json.dump(json_blocks, f, ensure_ascii=False, indent=2)
        return str(blocks_path)

    def save_middle_json(self, library_id: str, doc_id: str, payload: Dict[str, Any]) -> str:
        """保存 middle.json 结构化中间数据。"""
        middle_path = self.get_middle_json_path(library_id, doc_id)
        data = payload if isinstance(payload, dict) else {}
        with open(middle_path, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        return str(middle_path)

    def read_mineru_blocks(self, library_id: str, doc_id: str) -> List[Dict[str, Any]]:
        """读取 MinerU 块级结果"""
        candidate_paths = [self.get_mineru_blocks_path(library_id, doc_id), *self._legacy_mineru_blocks_paths(library_id, doc_id)]
        for blocks_path in candidate_paths:
            if not blocks_path.exists():
                continue
            try:
                with open(blocks_path, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                if isinstance(data, list):
                    return [item for item in data if isinstance(item, dict)]
            except Exception:
                continue
        return []

    def read_markdown(self, library_id: str, doc_id: str) -> Optional[str]:
        """读取 Markdown 文件"""
        edited_path = self.get_edited_markdown_path(library_id, doc_id)
        parsed_path = self.get_parsed_markdown_path(library_id, doc_id)
        target_path = edited_path if edited_path.exists() else parsed_path
        if target_path.exists():
            with open(target_path, 'r', encoding='utf-8') as f:
                return f.read()
        return None

    def get_latest_source_file(self, library_id: str, doc_id: str) -> Optional[str]:
        """获取源文件路径"""
        source_dir = self.get_doc_root(library_id, doc_id) / 'source'
        if source_dir.exists():
            files = sorted(
                [p for p in source_dir.iterdir() if p.is_file()],
                key=lambda p: p.stat().st_mtime,
                reverse=True
            )
            if files:
                return str(files[0])
        return None

    def ensure_doc_source_file(self, library_id: str, doc_id: str, file_path: Optional[str] = None) -> Optional[str]:
        """确保文档源文件存在于一文档一目录并返回规范路径"""
        doc_source_dir = self.get_source_dir(library_id, doc_id)
        current_files = sorted([p for p in doc_source_dir.iterdir() if p.is_file()])
        if current_files:
            return str(current_files[0])
        source_candidate = Path(file_path) if file_path else None
        if source_candidate and source_candidate.exists() and source_candidate.is_file():
            target_path = doc_source_dir / source_candidate.name
            shutil.copy2(source_candidate, target_path)
            return str(target_path)
        return None

    def delete_document(self, library_id: str, doc_id: str) -> bool:
        """删除文档"""
        doc_root = self._library_root(library_id) / 'documents' / doc_id
        deleted = False
        if doc_root.exists():
            shutil.rmtree(doc_root)
            deleted = True
        return deleted

    def list_documents(self, library_id: str) -> List[dict]:
        """列出知识库中的文档"""
        documents = []
        documents_dir = self._library_root(library_id) / 'documents'
        if documents_dir.exists():
            for doc_root in documents_dir.iterdir():
                if not doc_root.is_dir():
                    continue
                source_dir = doc_root / 'source'
                source_files = sorted([f for f in source_dir.glob('*') if f.is_file()])
                source_file = source_files[0] if source_files else None
                md_path = doc_root / 'parsed' / 'content.md'
                if source_file:
                    documents.append({
                        'id': doc_root.name,
                        'filename': source_file.name,
                        'source_path': str(source_file),
                        'has_markdown': md_path.exists(),
                        'created_at': datetime.fromtimestamp(source_file.stat().st_ctime).isoformat()
                    })

        return documents

    def get_doc_root_path(self, library_id: str, doc_id: str) -> str:
        """获取文档根目录字符串路径"""
        return str(self.get_doc_root(library_id, doc_id))

    def get_doc_manifest(self, library_id: str, doc_id: str) -> Dict[str, Any]:
        """获取文档清单"""
        doc_root = self.get_doc_root(library_id, doc_id)
        source_file = self.get_latest_source_file(library_id, doc_id)
        parsed_path = self.get_parsed_markdown_path(library_id, doc_id)
        edited_path = self.get_edited_markdown_path(library_id, doc_id)
        assets_path = self.get_parsed_dir(library_id, doc_id) / 'assets'
        raw_dir = self.get_parsed_dir(library_id, doc_id) / 'raw'
        middle_json_path = self.get_middle_json_path(library_id, doc_id)
        mineru_blocks_path = self.get_mineru_blocks_path(library_id, doc_id)
        if not mineru_blocks_path.exists():
            for candidate in self._legacy_mineru_blocks_paths(library_id, doc_id):
                if candidate.exists():
                    mineru_blocks_path = candidate
                    break
        history_dir = self.get_edited_dir(library_id, doc_id) / 'history'
        return {
            'doc_root': str(doc_root),
            'source_file': source_file,
            'parsed_markdown': str(parsed_path) if parsed_path.exists() else None,
            'edited_markdown': str(edited_path) if edited_path.exists() else None,
            'assets_dir': str(assets_path) if assets_path.exists() else None,
            'raw_dir': str(raw_dir) if raw_dir.exists() else None,
            'middle_json': str(middle_json_path) if middle_json_path.exists() else None,
            'mineru_blocks': str(mineru_blocks_path) if mineru_blocks_path.exists() else None,
            'history_files': sorted([str(p) for p in history_dir.glob('*.md')], reverse=True) if history_dir.exists() else []
        }

    def reorganize_storage(self) -> None:
        self._reorganize_once()

    def _reorganize_once(self) -> None:
        for library_root in self.libraries_dir.glob('*'):
            if not library_root.is_dir():
                continue
            old_docs_dir = library_root / 'docs'
            documents_dir = library_root / 'documents'
            documents_dir.mkdir(parents=True, exist_ok=True)
            if old_docs_dir.exists() and old_docs_dir.is_dir():
                for old_doc_root in old_docs_dir.iterdir():
                    if not old_doc_root.is_dir():
                        continue
                    new_doc_root = documents_dir / old_doc_root.name
                    if not new_doc_root.exists():
                        shutil.move(str(old_doc_root), str(new_doc_root))
                    else:
                        self._merge_doc_dir(old_doc_root, new_doc_root)
                if not any(old_docs_dir.iterdir()):
                    old_docs_dir.rmdir()
            for doc_root in documents_dir.iterdir():
                if not doc_root.is_dir():
                    continue
                self._normalize_doc_layout(doc_root)
        self._cleanup_legacy_root_dirs()

    def _merge_doc_dir(self, source_dir: Path, target_dir: Path) -> None:
        for item in source_dir.iterdir():
            target = target_dir / item.name
            if target.exists():
                if item.is_dir():
                    self._merge_doc_dir(item, target)
                else:
                    item.unlink()
            else:
                shutil.move(str(item), str(target))
        if source_dir.exists() and not any(source_dir.iterdir()):
            source_dir.rmdir()

    def _normalize_doc_layout(self, doc_root: Path) -> None:
        parsed_dir = doc_root / 'parsed'
        if parsed_dir.exists():
            old_parsed = parsed_dir / 'full.md'
            new_parsed = parsed_dir / 'content.md'
            if old_parsed.exists() and not new_parsed.exists():
                shutil.move(str(old_parsed), str(new_parsed))
        edited_dir = doc_root / 'edited'
        if edited_dir.exists():
            old_revisions = edited_dir / 'revisions'
            new_history = edited_dir / 'history'
            if old_revisions.exists() and not new_history.exists():
                shutil.move(str(old_revisions), str(new_history))
            elif old_revisions.exists() and new_history.exists():
                self._merge_doc_dir(old_revisions, new_history)
        for child in ('source', 'parsed', 'edited'):
            (doc_root / child).mkdir(parents=True, exist_ok=True)

    def _cleanup_legacy_root_dirs(self) -> None:
        for legacy_name in ('source', 'markdown', 'pics'):
            legacy_dir = self.base_dir / legacy_name
            if legacy_dir.exists() and legacy_dir.is_dir() and not any(legacy_dir.iterdir()):
                legacy_dir.rmdir()


file_storage = FileStorage()
