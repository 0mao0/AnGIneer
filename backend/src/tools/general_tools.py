import os
import re
import json
from typing import Any, Dict, List
from bs4 import BeautifulSoup
from src.tools.base import BaseTool, register_tool
from src.core.llm import llm_client

# 定义知识库目录路径
KNOWLEDGE_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "knowledge")

@register_tool
class TableLookupTool(BaseTool):
    name = "table_lookup"
    description_en = "Queries structured table data from specifications. Inputs: table_name (str), query_conditions (str/dict), target_column (str, optional)"
    description_zh = "查询规范表格数据。根据表格名称（或描述）和行查询条件，返回对应的数值。输入参数：table_name (str), query_conditions (str/dict), target_column (str, optional)"

    def run(self, table_name: str, query_conditions: Any, target_column: str = None, **kwargs) -> Any:
        print(f"  [表格查询] 正在查找表格 '{table_name}'，查询条件: {query_conditions}")
        
        # 1. 定位文件和表格
        # 原型阶段，我们扫描主要的规范文件。
        # 生产环境中，我们可能会有一个表格索引。
        knowledge_file = os.path.join(KNOWLEDGE_DIR, "《海港水文规范》.md")
        if not os.path.exists(knowledge_file):
            return {"error": "未找到知识库文件"}
            
        with open(knowledge_file, 'r', encoding='utf-8') as f:
            content = f.read()
            
        # 2. 使用 LLM 或启发式方法提取相关的表格 HTML
        # 启发式：找到包含 `table_name` 的章节并获取下一个 <table>
        # 但 `table_name` 可能是 "表A.0.1-1" 或 "杂货船设计船型尺度"
        # 使用 LLM 以增强鲁棒性（用户提到“工具可以是 AI 驱动的”）
        
        prompt = [
            {"role": "system", "content": "你是一个数据提取助手。你可以访问包含带有 HTML 表格的工程规范文档。"},
            {"role": "user", "content": f"""
文档内容 (部分/全部):
{content[:60000]}... (如果太长则截断)

任务: 找到匹配 '{table_name}' 的表格，并提取满足条件 {query_conditions} 的行/数值。
如果 'target_column' 是 '{target_column}'，则返回该特定值。否则以 JSON 格式返回整行。

仅返回 JSON: {{ "result": ... }} 或 {{ "error": ... }}
"""}
        ]
        
        try:
            response = llm_client.chat(prompt)
            # 解析 JSON
            if "```json" in response:
                response = response.split("```json")[1].split("```")[0]
            elif "```" in response:
                response = response.split("```")[1].split("```")[0]
            return json.loads(response.strip())
        except Exception as e:
            return {"error": f"查询失败: {str(e)}"}

@register_tool
class KnowledgeSearchTool(BaseTool):
    name = "knowledge_search"
    description_en = "Document/Report retrieval tool: search for relevant paragraphs in unstructured documents (e.g., regulations, design reports, research literature). Inputs: query (str)"
    description_zh = "文档/报告检索工具：根据查询关键词，在非结构化文档（如规范条文、设计报告、研究文献）中查找相关段落。输入参数：query (str)"

    def run(self, query: str, **kwargs) -> Dict[str, Any]:
        print(f"  [知识检索] 正在检索文档: {query}")
        
        # 1. 加载知识库 (示例：港口规范)
        knowledge_file = os.path.join(KNOWLEDGE_DIR, "《海港水文规范》.md")
        if not os.path.exists(knowledge_file):
            return {"error": "未找到知识库文件"}
            
        with open(knowledge_file, 'r', encoding='utf-8') as f:
            full_content = f.read()
            
        # 2. LLM 检索 (通过 LLM 阅读进行 RAG)
        # 专注于文本规程、逻辑、约束，而非结构化表格。
        
        # 如果内容太长则截断 (简单安全处理)
        if len(full_content) > 50000:
             content_snapshot = full_content[:50000] + "...(已截断)"
        else:
             content_snapshot = full_content
             
        prompt = [
            {"role": "system", "content": "你是一个专业的文档搜索代理。你的任务是从提供的文档中提取回答用户查询的相关文本章节、条款或规定。如果表格更适合由表格查询工具处理，请不要提取表格。仅返回相关文本。如果未找到，请说“未找到”。"},
            {"role": "user", "content": f"文档内容:\n{content_snapshot}\n\n查询关键词: {query}\n\n相关提取内容:"}
        ]
        
        try:
            extract = llm_client.chat(prompt)
            return {"result": extract, "source": "《海港水文规范》"}
        except Exception as e:
            return {"error": str(e)}

@register_tool
class Calculator(BaseTool):
    name = "calculator"
    description_en = "Performs basic arithmetic operations. Inputs: expression (str)"
    description_zh = "执行基础算术运算。输入参数：expression (str)"
    
    def run(self, expression: str, **kwargs) -> Any:
        try:
            # 生产环境中直接 eval 比较危险，但在 POC 阶段可以接受
            # 实际应用中应使用更安全的 eval 或特定库
            return eval(expression)
        except Exception as e:
            return f"错误: {e}"

@register_tool
class Echo(BaseTool):
    name = "echo"
    description_en = "Returns the input as is. Inputs: message (str)"
    description_zh = "原样返回输入内容。输入参数：message (str)"
    
    def run(self, message: str, **kwargs) -> Any:
        return message

@register_tool
class WeatherTool(BaseTool):
    name = "weather"
    description_en = "Mock weather tool. Inputs: city (str)"
    description_zh = "模拟天气查询工具。输入参数：city (str)"
    
    def run(self, city: str, **kwargs) -> Any:
        # 模拟数据
        return f"{city} 的天气是晴朗，25°C"

@register_tool
class WebSearchTool(BaseTool):
    name = "web_search"
    description_en = "Simulates a web search. Inputs: query (str)"
    description_zh = "模拟网页搜索工具。输入参数：query (str)"
    
    def run(self, query: str, **kwargs) -> Any:
        # 在实际场景中，这会调用 Google/Bing API
        # 目前我们根据关键词模拟一些响应
        query = query.lower()
        if "competitor" in query or "competitors" in query:
            return {
                "results": [
                    {"title": "竞品 A", "snippet": "AI 解决方案的领先提供商..."},
                    {"title": "竞品 B", "snippet": "专注于企业自动化..."},
                    {"title": "竞品 C", "snippet": "Agent AI 领域的新兴初创公司..."}
                ]
            }
        elif "market" in query or "trend" in query:
            return {
                "results": [
                    {"title": "2025 AI 市场报告", "snippet": "Agent 市场预计将增长 300%..."},
                    {"title": "LLM 发展趋势", "snippet": "向更小、更专业化的模型转变..."}
                ]
            }
        else:
            return {
                "results": [
                    {"title": f"{query} 的搜索结果", "snippet": "通用搜索结果内容..."}
                ]
            }

@register_tool
class ContentSummarizer(BaseTool):
    name = "summarizer"
    description_en = "Summarizes text content. Inputs: text (str), max_words (int)"
    description_zh = "文本内容摘要工具。输入参数：text (str), max_words (int)"
    
    def run(self, text: str, max_words: int = 50, **kwargs) -> Any:
        # 模拟摘要
        if isinstance(text, dict):
            text = str(text)
        return f"内容摘要 (长度 {len(text)}): {text[:100]}... [提取的关键点]"

@register_tool
class EmailSender(BaseTool):
    name = "email_sender"
    description_en = "Simulates sending an email. Inputs: recipient (str), subject (str), body (str)"
    description_zh = "模拟发送电子邮件。输入参数：recipient (str), subject (str), body (str)"
    
    def run(self, recipient: str, subject: str, body: str, **kwargs) -> Any:
        return f"邮件已发送至 {recipient}，主题为 '{subject}'"

@register_tool
class FileReader(BaseTool):
    name = "file_reader"
    description_en = "Reads a file. Inputs: file_path (str)"
    description_zh = "读取文件内容。输入参数：file_path (str)"
    
    def run(self, file_path: str, **kwargs) -> Any:
        try:
            # 为了演示，模拟读取特定文件
            if "code.py" in file_path:
                return "def hello():\n    print('Hello world')\n    x = 1/0 # 这里的 Bug"
            return f"{file_path} 的内容"
        except Exception as e:
            return f"读取文件时出错: {e}"

@register_tool
class CodeLinter(BaseTool):
    name = "code_linter"
    description_en = "Lints code and returns errors. Inputs: code (str)"
    description_zh = "代码检查工具，返回错误信息。输入参数：code (str)"
    
    def run(self, code: str, **kwargs) -> Any:
        issues = []
        if "1/0" in code:
            issues.append("第 3 行: 检测到除以零错误")
        if "print" in code and "(" not in code: # Python 2 风格
            issues.append("第 2 行: 调用 'print' 时缺少括号")
        
        if not issues:
            return "未发现问题。"
        return "\n".join(issues)

@register_tool
class ReportGenerator(BaseTool):
    name = "report_generator"
    description_en = "Generates a formatted report. Inputs: title (str), data (dict/str)"
    description_zh = "生成格式化报告。输入参数：title (str), data (dict/str)"
    
    def run(self, title: str, data: Any, **kwargs) -> Any:
        return f"# {title}\n\n## 生成的报告\n{str(data)}"
