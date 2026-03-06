"""文件存储管理"""
import os
import shutil
from pathlib import Path
from datetime import datetime
from typing import Optional, List


class FileStorage:
    """文件存储管理器"""

    def __init__(self, base_dir: str = None):
        if base_dir is None:
            root_dir = Path(__file__).resolve().parents[5]
            base_dir = str(root_dir / 'data' / 'knowledge_base')

        self.base_dir = Path(base_dir)
        self.libraries_dir = self.base_dir / 'libraries'
        self.legacy_source_dir = self.base_dir / 'source'
        self.legacy_markdown_dir = self.base_dir / 'markdown'

        self._ensure_dirs()

    def _ensure_dirs(self):
        """确保目录存在"""
        self.libraries_dir.mkdir(parents=True, exist_ok=True)
        self.legacy_source_dir.mkdir(parents=True, exist_ok=True)
        self.legacy_markdown_dir.mkdir(parents=True, exist_ok=True)

    def get_doc_root(self, library_id: str, doc_id: str) -> Path:
        """获取一文档一目录根路径"""
        doc_root = self.libraries_dir / library_id / 'docs' / doc_id
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

    def get_source_path(self, library_id: str, filename: str) -> Path:
        """获取旧版源文件路径"""
        library_dir = self.legacy_source_dir / library_id
        library_dir.mkdir(parents=True, exist_ok=True)
        return library_dir / filename

    def get_markdown_path(self, library_id: str, doc_id: str) -> Path:
        """获取旧版 Markdown 路径"""
        doc_dir = self.legacy_markdown_dir / library_id / doc_id
        doc_dir.mkdir(parents=True, exist_ok=True)
        return doc_dir / 'full.md'

    def get_parsed_markdown_path(self, library_id: str, doc_id: str) -> Path:
        """获取新版解析 Markdown 路径"""
        return self.get_parsed_dir(library_id, doc_id) / 'full.md'

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
        legacy_source_path = self.get_source_path(library_id, f'{doc_id}{Path(safe_name).suffix or ".pdf"}')
        with open(legacy_source_path, 'wb') as f:
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
        legacy_md_path = self.get_markdown_path(library_id, doc_id)
        with open(legacy_md_path, 'w', encoding='utf-8') as f:
            f.write(content)
        return str(parsed_md_path)

    def save_edited_markdown(self, library_id: str, doc_id: str, content: str) -> str:
        """保存编辑后的 Markdown 文件"""
        edited_dir = self.get_edited_dir(library_id, doc_id)
        current_path = edited_dir / 'current.md'
        with open(current_path, 'w', encoding='utf-8') as f:
            f.write(content)
        revision_dir = edited_dir / 'revisions'
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

    def read_markdown(self, library_id: str, doc_id: str) -> Optional[str]:
        """读取 Markdown 文件"""
        edited_path = self.get_edited_markdown_path(library_id, doc_id)
        parsed_path = self.get_parsed_markdown_path(library_id, doc_id)
        legacy_path = self.get_markdown_path(library_id, doc_id)
        target_path = edited_path if edited_path.exists() else parsed_path if parsed_path.exists() else legacy_path
        if target_path.exists():
            with open(target_path, 'r', encoding='utf-8') as f:
                return f.read()
        return None

    def get_latest_source_file(self, library_id: str, doc_id: str) -> Optional[str]:
        """获取源文件路径（优先新版）"""
        source_dir = self.get_doc_root(library_id, doc_id) / 'source'
        if source_dir.exists():
            files = sorted(
                [p for p in source_dir.iterdir() if p.is_file()],
                key=lambda p: p.stat().st_mtime,
                reverse=True
            )
            if files:
                return str(files[0])
        legacy_candidates = list((self.legacy_source_dir / library_id).glob(f'{doc_id}.*'))
        if legacy_candidates:
            return str(legacy_candidates[0])
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
        legacy_candidates = sorted((self.legacy_source_dir / library_id).glob(f'{doc_id}.*'))
        if legacy_candidates:
            legacy_source = legacy_candidates[0]
            target_path = doc_source_dir / legacy_source.name
            shutil.copy2(legacy_source, target_path)
            return str(target_path)
        return None

    def delete_document(self, library_id: str, doc_id: str) -> bool:
        """删除文档"""
        doc_root = self.libraries_dir / library_id / 'docs' / doc_id
        legacy_md_path = self.legacy_markdown_dir / library_id / doc_id

        deleted = False
        if doc_root.exists():
            shutil.rmtree(doc_root)
            deleted = True
        legacy_sources = list((self.legacy_source_dir / library_id).glob(f'{doc_id}.*'))
        for source_path in legacy_sources:
            source_path.unlink()
            deleted = True
        if legacy_md_path.exists():
            shutil.rmtree(legacy_md_path)
            deleted = True

        return deleted

    def list_documents(self, library_id: str) -> List[dict]:
        """列出知识库中的文档"""
        documents = []
        docs_dir = self.libraries_dir / library_id / 'docs'
        if docs_dir.exists():
            for doc_root in docs_dir.iterdir():
                if not doc_root.is_dir():
                    continue
                source_dir = doc_root / 'source'
                source_files = sorted([f for f in source_dir.glob('*') if f.is_file()])
                source_file = source_files[0] if source_files else None
                md_path = doc_root / 'parsed' / 'full.md'
                if source_file:
                    documents.append({
                        'id': doc_root.name,
                        'filename': source_file.name,
                        'source_path': str(source_file),
                        'has_markdown': md_path.exists(),
                        'created_at': datetime.fromtimestamp(source_file.stat().st_ctime).isoformat()
                    })
        legacy_library_dir = self.legacy_source_dir / library_id
        if legacy_library_dir.exists():
            existing_ids = {doc['id'] for doc in documents}
            for file in legacy_library_dir.glob('*.*'):
                doc_id = file.stem
                if doc_id in existing_ids:
                    continue
                md_path = self.legacy_markdown_dir / library_id / doc_id / 'full.md'
                documents.append({
                    'id': doc_id,
                    'filename': file.name,
                    'source_path': str(file),
                    'has_markdown': md_path.exists(),
                    'created_at': datetime.fromtimestamp(file.stat().st_ctime).isoformat()
                })

        return documents

    def get_doc_root_path(self, library_id: str, doc_id: str) -> str:
        """获取文档根目录字符串路径"""
        return str(self.get_doc_root(library_id, doc_id))

    def get_legacy_paths(self, library_id: str, doc_id: str) -> List[str]:
        """获取旧版兼容路径列表"""
        paths = []
        paths.extend(str(p) for p in (self.legacy_source_dir / library_id).glob(f'{doc_id}.*'))
        legacy_markdown = self.legacy_markdown_dir / library_id / doc_id / 'full.md'
        if legacy_markdown.exists():
            paths.append(str(legacy_markdown))
        return paths


file_storage = FileStorage()
