import os
from typing import Any, Dict
from src.tools.base import BaseTool, register_tool
from src.core.llm import llm_client
from src.config import KNOWLEDGE_DIR

@register_tool
class KnowledgeSearchTool(BaseTool):
    name = "knowledge_search"
    description_en = "Document/Report retrieval tool: search for relevant paragraphs in unstructured documents (e.g., regulations, design reports, research literature). Inputs: query (str), file_name (str, optional)"
    description_zh = "文档/报告检索工具：根据查询关键词，在非结构化文档（如规范条文、设计报告、研究文献）中查找相关段落。输入参数：query (str), file_name (str, optional)"

    def run(self, query: str, file_name: str = "《海港水文规范》.md", config_name: str = None, mode: str = "instruct", **kwargs) -> Dict[str, Any]:
        """在知识库文本中检索相关内容。"""
        print(f"  [知识检索] 正在检索文档: {query}，来源: {file_name}")
        knowledge_file = os.path.join(KNOWLEDGE_DIR, file_name)
        if not os.path.exists(knowledge_file):
            return {"error": f"未找到知识库文件: {file_name}"}
            
        with open(knowledge_file, 'r', encoding='utf-8') as f:
            full_content = f.read()
            
        if len(full_content) > 50000:
            content_snapshot = full_content[:50000] + "...(已截断)"
        else:
            content_snapshot = full_content
             
        prompt = [
            {"role": "system", "content": "你是一个专业的文档搜索代理。你的任务是从提供的文档中提取回答用户查询的相关文本章节、条款或规定。如果表格更适合由表格查询工具处理，请不要提取表格。仅返回相关文本。如果未找到，请说“未找到”。"},
            {"role": "user", "content": f"文档内容:\n{content_snapshot}\n\n查询关键词: {query}\n\n相关提取内容:"}
        ]
        
        try:
            extract = llm_client.chat(prompt, mode=mode, config_name=config_name)
            return {"result": extract, "source": "《海港水文规范》"}
        except Exception as e:
            return {"error": str(e)}

@register_tool
class ContentSummarizer(BaseTool):
    name = "summarizer"
    description_en = "Summarizes text content (Placeholder). Inputs: text (str), max_words (int)"
    description_zh = "文本内容摘要工具（占位符）。输入参数：text (str), max_words (int)"
    
    def run(self, text: str, max_words: int = 50, config_name: str = None, mode: str = "instruct", **kwargs) -> Any:
        """使用模型对文本进行摘要。"""
        prompt = [
            {"role": "system", "content": f"请将以下内容摘要为不超过 {max_words} 个字。"},
            {"role": "user", "content": text}
        ]
        try:
            return llm_client.chat(prompt, mode=mode, config_name=config_name)
        except Exception:
            return f"内容摘要: {text[:100]}..."
