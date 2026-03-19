import os
import tempfile
import json
from typing import Any, Dict, List, Optional
from dotenv import load_dotenv
from pathlib import Path

from .structured_strategy import extract_structured_items_from_markdown

# -----------------------------------------------------------------------------
# MinerURag Service Class
# -----------------------------------------------------------------------------

class MinerURag:
    """MinerU RAG 服务"""

    def __init__(self):
        self._rag = None
        self._llm = None

    def _get_rag(self):
        """获取 RAG 构建器"""
        if self._rag is None:
            try:
                from mineru_rag import RAGBuilder
                self._rag = RAGBuilder()
            except ImportError:
                raise ImportError("请安装 mineru-rag: pip install mineru-rag[rag]")
        return self._rag

    def _get_llm(self):
        """获取 LLM 客户端"""
        if self._llm is None:
            try:
                from mineru_rag import LLMClient
                load_dotenv()

                api_key = os.getenv('Public_ALIYUN_API_KEY') or os.getenv('ALIYUN_API_KEY')
                base_url = os.getenv('Public_ALIYUN_API_URL') or os.getenv('ALIYUN_API_URL')
                model = os.getenv('Public_ALIYUN_MODEL2') or os.getenv('ALIYUN_MODEL', 'qwen3.5-397b-a17b')

                self._llm = LLMClient(
                    api_key=api_key,
                    base_url=base_url,
                    model=model
                )
            except ImportError:
                raise ImportError("请安装 mineru-rag: pip install mineru-rag[rag]")
        return self._llm

    def _ensure_vector_store_dir(self, library_id: str) -> Path:
        """确保 MinerU-RAG 的 Faiss 向量库目录存在。"""
        root_dir = Path.home() / '.mineru_rag' / 'vector_db'
        library_dir = root_dir / f'{library_id}_faiss'
        library_dir.mkdir(parents=True, exist_ok=True)
        return library_dir

    def build_knowledge_base(
        self,
        markdown_files: list,
        library_id: str,
        metadata: dict = None
    ) -> Dict[str, Any]:
        """
        构建知识库

        Args:
            markdown_files: Markdown 文件路径列表
            library_id: 知识库 ID
            metadata: 元数据

        Returns:
            构建结果
        """
        rag = self._get_rag()
        self._ensure_vector_store_dir(library_id)

        rag.build_from_files(
            file_paths=markdown_files,
            library_id=library_id,
            metadata=metadata or {}
        )

        return {
            'success': True,
            'library_id': library_id,
            'file_count': len(markdown_files)
        }

    def load_knowledge_base(self, library_id: str) -> None:
        """加载知识库"""
        rag = self._get_rag()
        rag.load_vector_store(library_id=library_id)

    def query(
        self,
        question: str,
        k: int = 4,
        library_id: str = 'default'
    ) -> Dict[str, Any]:
        """
        查询知识库（仅检索）

        Args:
            question: 问题
            k: 检索数量
            library_id: 知识库 ID

        Returns:
            检索结果
        """
        rag = self._get_rag()
        rag.load_vector_store(library_id=library_id)

        result = rag.query(question=question, k=k)

        return {
            'question': question,
            'num_sources': result.get('num_sources', 0),
            'sources': result.get('sources', [])
        }

    def query_with_llm(
        self,
        question: str,
        k: int = 4,
        library_id: str = 'default'
    ) -> Dict[str, Any]:
        """
        查询知识库并使用 LLM 生成答案

        Args:
            question: 问题
            k: 检索数量
            library_id: 知识库 ID

        Returns:
            问答结果
        """
        rag = self._get_rag()
        llm = self._get_llm()

        rag.load_vector_store(library_id=library_id)

        rag_result = rag.query(question=question, k=k)
        answer = llm.query_with_rag(rag_result)

        return {
            'question': question,
            'answer': answer.get('answer', ''),
            'num_sources': answer.get('num_sources', 0),
            'sources': answer.get('sources', [])
        }

# 全局实例
mineru_rag = MinerURag()


def build_mineru_rag_index_for_doc(library_id: str, doc_id: str, strategy: str = 'B_mineru_rag') -> Dict[str, Any]:
    from docs_core import file_storage, knowledge_service

    markdown_content = file_storage.read_markdown(library_id, doc_id)
    if markdown_content is None:
        raise ValueError('文档尚无可用 Markdown 内容')

    items = extract_structured_items_from_markdown(markdown_content)
    saved_count = knowledge_service.save_document_segments(doc_id, library_id, strategy, items)
    rag_result: Dict[str, Any] = {'success': False}

    with tempfile.NamedTemporaryFile(mode='w', suffix='.md', delete=False, encoding='utf-8') as handle:
        handle.write(markdown_content)
        temp_md = handle.name

    try:
        rag_result = mineru_rag.build_knowledge_base([temp_md], library_id)
    finally:
        try:
            import os
            if os.path.exists(temp_md):
                os.remove(temp_md)
        except Exception:
            pass

    stats = knowledge_service.get_document_segment_stats(doc_id)
    return {'saved_count': saved_count, 'stats': stats, 'rag_result': rag_result}
