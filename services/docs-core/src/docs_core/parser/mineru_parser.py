"""MinerU 文档解析服务"""
import os
from typing import Optional, Dict, Any
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()


class MinerUParser:
    """MinerU 文档解析器"""

    def __init__(self):
        self.api_url = os.getenv('MINERU_API_URL', 'https://ai.bim-ace.com:50170')
        self.api_key = os.getenv('MINERU_API_KEY', '')
        self._client = None

    def _get_client(self):
        """获取 MinerU 客户端"""
        if self._client is None:
            try:
                from mineru_rag import MinerUClient
                self._client = MinerUClient(
                    api_token=self.api_key,
                    api_url=self.api_url
                )
            except ImportError:
                raise ImportError("请安装 mineru-rag: pip install mineru-rag[rag]")
        return self._client

    def parse_document(
        self,
        input_path: str,
        output_dir: str,
        **kwargs
    ) -> Dict[str, Any]:
        """
        解析文档

        Args:
            input_path: 输入文件路径
            output_dir: 输出目录
            **kwargs: 其他参数

        Returns:
            解析结果字典
        """
        client = self._get_client()

        result = client.process_file(
            input_path=input_path,
            output_path=output_dir,
            **kwargs
        )

        return {
            'success': result.get('success', False),
            'md_file': result.get('md_file'),
            'error': result.get('error'),
            'input_path': input_path,
            'output_dir': output_dir
        }

    def parse_documents_batch(
        self,
        file_paths: list,
        output_dir: str,
        **kwargs
    ) -> list:
        """
        批量解析文档

        Args:
            file_paths: 文件路径列表
            output_dir: 输出目录
            **kwargs: 其他参数

        Returns:
            解析结果列表
        """
        client = self._get_client()

        results = client.process_files_batch(
            file_paths=file_paths,
            output_dir=output_dir,
            **kwargs
        )

        return results


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
                from dotenv import load_dotenv
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


mineru_parser = MinerUParser()
mineru_rag = MinerURag()
