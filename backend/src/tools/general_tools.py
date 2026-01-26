import os
import re
import json
import ast
import traceback
from typing import Any, Dict, List, Optional
from bs4 import BeautifulSoup
from src.tools.base import BaseTool, register_tool
from src.core.llm import llm_client

# 定义知识库目录路径
KNOWLEDGE_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "knowledge")

@register_tool
class TableLookupTool(BaseTool):
    name = "table_lookup"
    description_en = "Queries structured table data from specifications. Inputs: table_name (str), query_conditions (str/dict), file_name (str, optional), target_column (str, optional)"
    description_zh = "查询规范表格数据。根据表格名称（或描述）和行查询条件，返回对应的数值。输入参数：table_name (str), query_conditions (str/dict), file_name (str, optional), target_column (str, optional)"

    def run(self, table_name: str, query_conditions: Any, file_name: str = "《海港水文规范》.md", target_column: str = None, config_name: str = None, mode: str = "instruct", **kwargs) -> Any:
        print(f"  [表格查询] 正在查找表格 '{table_name}'，查询条件: {query_conditions}，来源: {file_name}")
        
        # 1. 定位文件
        knowledge_file = os.path.join(KNOWLEDGE_DIR, file_name)
        if not os.path.exists(knowledge_file):
            return {"error": f"未找到知识库文件: {file_name}"}
            
        try:
            with open(knowledge_file, 'r', encoding='utf-8') as f:
                content = f.read()
        except Exception as e:
            return {"error": f"无法读取文件: {str(e)}"}

        # 2. 提取表格 (Robust Extraction)
        # 使用 BeautifulSoup 提取所有表格，并保留上下文（前200字符）
        tables = []
        soup = BeautifulSoup(content, 'html.parser')
        html_tables = soup.find_all('table')
        
        candidates = []
        for idx, tbl in enumerate(html_tables):
            # 获取表格HTML
            table_html = str(tbl)
            
            # 获取上下文：尝试在原文本中定位表格位置 (简单反查可能不准确，改用 sibling 遍历)
            # 在 Markdown 转换的 HTML 中，表格前通常是标题 (h1-h6) 或段落 (p)
            # 这里为了简单有效，我们尝试找表格的前一个兄弟节点
            prev_node = tbl.find_previous_sibling()
            context_text = ""
            if prev_node:
                context_text = prev_node.get_text(strip=True)
            
            # 如果兄弟节点找不到，尝试在全文正则匹配定位 (为了获取 Markdown 原文中的上下文)
            # 但既然已经有了 HTML 结构，直接用 HTML 结构更稳健
            
            candidates.append({
                "html": table_html,
                "context": context_text,
                "index": idx
            })
            
        # 3. 筛选表格
        target_table = None
        # 优先全匹配
        for cand in candidates:
            if table_name in cand["context"]:
                target_table = cand
                break
        
        # 其次部分匹配
        if not target_table:
            for cand in candidates:
                if any(k in cand["context"] for k in table_name.split()):
                    target_table = cand
                    break
        
        # 如果还是找不到，尝试匹配表格内容（表头）
        if not target_table:
            for cand in candidates:
                if table_name in cand["html"]:
                    target_table = cand
                    break

        if target_table:
            llm_context = f"相关表格上下文: {target_table['context']}\n{target_table['html']}"
        else:
            # 没找到匹配的，截取前 3 个表格作为上下文 (避免全文)
            llm_context = "\n".join([f"表格{i+1}上下文: {c['context']}\n{c['html']}" for i, c in enumerate(candidates[:3])])
            if not llm_context:
                llm_context = content[:5000] # 实在没有表格，截取前 5000 字符

        # 4. LLM 查询与插值
        prompt = [
            {"role": "system", "content": "你是一个严谨的数据提取助手。用户提供了包含 HTML 表格的片段。"},
            {"role": "user", "content": f"""
片段内容:
{llm_context}

任务: 找到匹配 '{table_name}' 的表格，并提取满足条件 {query_conditions} 的行/数值。
如果 'target_column' 是 '{target_column}'，则返回该特定值。

**插值规则 (必须严格执行)**:
如果查询的数值在表格的两个档位之间（例如 DWT=40000 在 30000 和 50000 之间），请务必基于这两个相邻档位进行**线性插值 (Linear Interpolation)** 计算，保留一位小数。
公式: y = y1 + (x - x1) * (y2 - y1) / (x2 - x1)

仅返回 JSON 格式，不要包含 Markdown 格式标记:
{{ "result": <数值或对象>, "method": "interpolation" | "direct_lookup" }}
如果出错，返回 {{ "error": "错误原因" }}
"""}
        ]
        
        try:
            # 使用 instruct 模式以获得更确定性的结果，或者用户指定的 mode
            response = llm_client.chat(prompt, mode=mode, config_name=config_name)
            
            # 清理 JSON
            clean_response = response.strip()
            if "```json" in clean_response:
                clean_response = clean_response.split("```json")[1].split("```")[0].strip()
            elif "```" in clean_response:
                clean_response = clean_response.split("```")[1].split("```")[0].strip()
                
            result = json.loads(clean_response)
            
            # 注入源 HTML (如果存在)
            if target_table and "html" in target_table:
                result["_source_html"] = target_table["html"]
                
            return result
        except json.JSONDecodeError:
            return {"error": "LLM 返回了非 JSON 格式数据", "raw_response": response}
        except Exception as e:
            return {"error": f"查询失败: {str(e)}"}

@register_tool
class KnowledgeSearchTool(BaseTool):
    name = "knowledge_search"
    description_en = "Document/Report retrieval tool: search for relevant paragraphs in unstructured documents (e.g., regulations, design reports, research literature). Inputs: query (str), file_name (str, optional)"
    description_zh = "文档/报告检索工具：根据查询关键词，在非结构化文档（如规范条文、设计报告、研究文献）中查找相关段落。输入参数：query (str), file_name (str, optional)"

    def run(self, query: str, file_name: str = "《海港水文规范》.md", config_name: str = None, mode: str = "instruct", **kwargs) -> Dict[str, Any]:
        print(f"  [知识检索] 正在检索文档: {query}，来源: {file_name}")
        
        # 1. 加载知识库
        knowledge_file = os.path.join(KNOWLEDGE_DIR, file_name)
        if not os.path.exists(knowledge_file):
            return {"error": f"未找到知识库文件: {file_name}"}
            
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
            extract = llm_client.chat(prompt, mode=mode, config_name=config_name)
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
            # 使用 ast.literal_eval 进行安全求值，或者受限的 eval
            # 这里为了支持数学运算，使用 eval 但限制 globals
            allowed_names = {"abs": abs, "round": round, "min": min, "max": max, "pow": pow}
            return eval(expression, {"__builtins__": None}, allowed_names)
        except Exception as e:
            return f"计算错误: {e}"

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
    description_en = "Simulates weather query (Placeholder). Inputs: city (str)"
    description_zh = "模拟天气查询工具（占位符）。输入参数：city (str)"
    
    def run(self, city: str, **kwargs) -> Any:
        # 实际项目需要对接 OpenWeatherMap 等 API
        return f"{city} 的天气是晴朗，25°C (模拟数据)"

@register_tool
class WebSearchTool(BaseTool):
    name = "web_search"
    description_en = "Simulates a web search (Placeholder). Inputs: query (str)"
    description_zh = "模拟网页搜索工具（占位符）。输入参数：query (str)"
    
    def run(self, query: str, **kwargs) -> Any:
        # 实际项目需要对接 Google Custom Search API / Bing Search API
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
    description_en = "Summarizes text content (Placeholder). Inputs: text (str), max_words (int)"
    description_zh = "文本内容摘要工具（占位符）。输入参数：text (str), max_words (int)"
    
    def run(self, text: str, max_words: int = 50, config_name: str = None, mode: str = "instruct", **kwargs) -> Any:
        # 可以调用 LLM 进行摘要
        prompt = [
            {"role": "system", "content": f"请将以下内容摘要为不超过 {max_words} 个字。"},
            {"role": "user", "content": text}
        ]
        try:
            return llm_client.chat(prompt, mode=mode, config_name=config_name)
        except:
            return f"内容摘要: {text[:100]}..."

@register_tool
class EmailSender(BaseTool):
    name = "email_sender"
    description_en = "Simulates sending an email (Placeholder). Inputs: recipient (str), subject (str), body (str)"
    description_zh = "模拟发送电子邮件（占位符）。输入参数：recipient (str), subject (str), body (str)"
    
    def run(self, recipient: str, subject: str, body: str, **kwargs) -> Any:
        # 实际需对接 SMTP
        return f"邮件已发送至 {recipient}，主题为 '{subject}' (模拟)"

@register_tool
class FileReader(BaseTool):
    name = "file_reader"
    description_en = "Reads a file from the local system. Inputs: file_path (str)"
    description_zh = "读取本地文件内容。输入参数：file_path (str)"
    
    def run(self, file_path: str, **kwargs) -> Any:
        # 安全检查：限制读取目录 (可选，视部署环境而定)
        # 这里假设只允许读取项目目录下的文件
        base_dir = os.path.dirname(os.path.dirname(os.path.dirname(__file__))) # backend root
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
        # 暂时作为占位符
        return f"已启动子流程: {filename}，处理问题: {question}"

@register_tool
class CodeLinter(BaseTool):
    name = "code_linter"
    description_en = "Lints Python code using AST. Inputs: code (str)"
    description_zh = "使用 AST 检查 Python 代码语法。输入参数：code (str)"
    
    def run(self, code: str, **kwargs) -> Any:
        try:
            ast.parse(code)
            
            # 简单的自定义检查 (AST遍历)
            issues = []
            tree = ast.parse(code)
            for node in ast.walk(tree):
                if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Div):
                    if isinstance(node.right, ast.Constant) and node.right.value == 0:
                        issues.append(f"行 {node.lineno}: 检测到除以零错误")
                    if isinstance(node.right, ast.Num) and node.right.n == 0: # Python < 3.8
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
        return f"# {title}\n\n## 生成的报告\n{str(data)}"
