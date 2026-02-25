import ast
import os
from typing import Any
from .BaseTool import BaseTool, register_tool


@register_tool
class Echo(BaseTool):
    name = "echo"
    description_en = "Returns the input as is. Inputs: message (str)"
    description_zh = "原样返回输入内容。输入参数：message (str)"
    
    def run(self, message: str, **kwargs) -> Any:
        """返回输入内容。"""
        return message


@register_tool
class WeatherTool(BaseTool):
    name = "weather"
    description_en = "Simulates weather query (Placeholder). Inputs: city (str)"
    description_zh = "模拟天气查询工具（占位符）。输入参数：city (str)"
    
    def run(self, city: str, **kwargs) -> Any:
        """返回模拟天气结果。"""
        return f"{city} 的天气是晴朗，25°C (模拟数据)"


@register_tool
class WebSearchTool(BaseTool):
    name = "web_search"
    description_en = "Simulates a web search (Placeholder). Inputs: query (str)"
    description_zh = "模拟网页搜索工具（占位符）。输入参数：query (str)"
    
    def run(self, query: str, **kwargs) -> Any:
        """返回模拟网页搜索结果。"""
        query = query.lower()
        if "competitor" in query or "competitors" in query:
            return {
                "results": [
                    {"title": "竞品 A", "snippet": "AI 解决方案的领先提供商..."},
                    {"title": "竞品 B", "snippet": "专注于企业自动化..."},
                    {"title": "竞品 C", "snippet": "Agent AI 领域的新兴初创公司..."}
                ]
            }
        if "market" in query or "trend" in query:
            return {
                "results": [
                    {"title": "2025 AI 市场报告", "snippet": "Agent 市场预计将增长 300%..."},
                    {"title": "LLM 发展趋势", "snippet": "向更小、更专业化的模型转变..."}
                ]
            }
        return {
            "results": [
                {"title": f"{query} 的搜索结果", "snippet": "通用搜索结果内容..."}
            ]
        }


@register_tool
class EmailSender(BaseTool):
    name = "email_sender"
    description_en = "Simulates sending an email (Placeholder). Inputs: recipient (str), subject (str), body (str)"
    description_zh = "模拟发送电子邮件（占位符）。输入参数：recipient (str), subject (str), body (str)"
    
    def run(self, recipient: str, subject: str, body: str, **kwargs) -> Any:
        """返回模拟邮件发送结果。"""
        return f"邮件已发送至 {recipient}，主题为 '{subject}' (模拟)"


@register_tool
class FileReader(BaseTool):
    name = "file_reader"
    description_en = "Reads a file from the local system. Inputs: file_path (str)"
    description_zh = "读取本地文件内容。输入参数：file_path (str)"
    
    def run(self, file_path: str, **kwargs) -> Any:
        """读取本地文件内容。"""
        base_dir = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))
        abs_path = os.path.abspath(os.path.join(base_dir, file_path)) if not os.path.isabs(file_path) else file_path
        
        if not os.path.exists(abs_path):
             return f"错误: 文件不存在 {file_path}"
             
        try:
            with open(abs_path, 'r', encoding='utf-8') as f:
                return f.read()
        except Exception as e:
            return f"读取文件时出错: {e}"


@register_tool
class SopRunTool(BaseTool):
    name = "sop_run"
    description_en = "Runs a nested SOP. Inputs: filename (str), question (str)"
    description_zh = "执行嵌套的 SOP。输入参数：filename (str), question (str)"
    
    def run(self, filename: str, question: str, **kwargs) -> Any:
        """返回 SOP 启动结果。"""
        return f"已启动子流程: {filename}，处理问题: {question}"


@register_tool
class CodeLinter(BaseTool):
    name = "code_linter"
    description_en = "Lints Python code using AST. Inputs: code (str)"
    description_zh = "使用 AST 检查 Python 代码语法。输入参数：code (str)"
    
    def run(self, code: str, **kwargs) -> Any:
        """检查代码中的简单语法问题。"""
        try:
            ast.parse(code)
            issues = []
            tree = ast.parse(code)
            for node in ast.walk(tree):
                if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Div):
                    if isinstance(node.right, ast.Constant) and node.right.value == 0:
                        issues.append(f"行 {node.lineno}: 检测到除以零错误")
            if not issues:
                return "代码语法检查通过，未发现明显静态错误。"
            return "\n".join(issues)
        except SyntaxError as e:
            return f"语法错误: {e.msg} (行 {e.lineno})"
        except Exception as e:
            return f"检查时发生错误: {str(e)}"


@register_tool
class ReportGenerator(BaseTool):
    name = "report_generator"
    description_en = "Generates a formatted report. Inputs: title (str), data (dict/str)"
    description_zh = "生成格式化报告。输入参数：title (str), data (dict/str)"
    
    def run(self, title: str, data: Any, **kwargs) -> Any:
        """生成文本报告。"""
        return f"# {title}\n\n## 生成的报告\n{str(data)}"
