"""文件存储管理"""
import os
import shutil
from typing import Optional, List
from pathlib import Path
from datetime import datetime


class FileStorage:
    """文件存储管理器"""

    def __init__(self, base_dir: str = None):
        if base_dir is None:
            base_dir = os.path.join(os.getcwd(), 'data', 'knowledge_base')
        
        self.base_dir = Path(base_dir)
        self.source_dir = self.base_dir / 'source'
        self.markdown_dir = self.base_dir / 'markdown'
        
        self._ensure_dirs()

    def _ensure_dirs(self):
        """确保目录存在"""
        self.source_dir.mkdir(parents=True, exist_ok=True)
        self.markdown_dir.mkdir(parents=True, exist_ok=True)

    def get_source_path(self, library_id: str, filename: str) -> Path:
        """获取源文件路径"""
        library_dir = self.source_dir / library_id
        library_dir.mkdir(parents=True, exist_ok=True)
        return library_dir / filename

    def get_markdown_path(self, library_id: str, doc_id: str) -> Path:
        """获取 Markdown 文件路径"""
        doc_dir = self.markdown_dir / library_id / doc_id
        doc_dir.mkdir(parents=True, exist_ok=True)
        return doc_dir / 'full.md'

    def save_source_file(self, library_id: str, doc_id: str, content: bytes) -> str:
        """保存源文件"""
        source_path = self.get_source_path(library_id, f'{doc_id}.pdf')
        with open(source_path, 'wb') as f:
            f.write(content)
        return str(source_path)

    def save_markdown(self, library_id: str, doc_id: str, content: str) -> str:
        """保存 Markdown 文件"""
        md_path = self.get_markdown_path(library_id, doc_id)
        with open(md_path, 'w', encoding='utf-8') as f:
            f.write(content)
        return str(md_path)

    def read_markdown(self, library_id: str, doc_id: str) -> Optional[str]:
        """读取 Markdown 文件"""
        md_path = self.get_markdown_path(library_id, doc_id)
        if md_path.exists():
            with open(md_path, 'r', encoding='utf-8') as f:
                return f.read()
        return None

    def delete_document(self, library_id: str, doc_id: str) -> bool:
        """删除文档"""
        source_path = self.source_dir / library_id / f'{doc_id}.pdf'
        md_path = self.markdown_dir / library_id / doc_id

        deleted = False
        if source_path.exists():
            source_path.unlink()
            deleted = True
        if md_path.exists():
            shutil.rmtree(md_path)
            deleted = True
        
        return deleted

    def list_documents(self, library_id: str) -> List[dict]:
        """列出知识库中的文档"""
        library_dir = self.source_dir / library_id
        if not library_dir.exists():
            return []

        documents = []
        for file in library_dir.glob('*.pdf'):
            doc_id = file.stem
            md_path = self.markdown_dir / library_id / doc_id / 'full.md'
            
            documents.append({
                'id': doc_id,
                'filename': file.name,
                'source_path': str(file),
                'has_markdown': md_path.exists(),
                'created_at': datetime.fromtimestamp(file.stat().st_ctime).isoformat()
            })
        
        return documents


file_storage = FileStorage()
