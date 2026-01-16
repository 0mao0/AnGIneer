from typing import Any
import requests
from src.tools.base import BaseTool, register_tool

@register_tool
class Calculator(BaseTool):
    name = "calculator"
    description = "Performs basic arithmetic operations. Inputs: expression (str)"
    
    def run(self, expression: str, **kwargs) -> Any:
        try:
            # Dangerous in production, but okay for POC
            # In real world, use a safe eval or specific library
            return eval(expression)
        except Exception as e:
            return f"Error: {e}"

@register_tool
class Echo(BaseTool):
    name = "echo"
    description = "Returns the input as is. Inputs: message (str)"
    
    def run(self, message: str, **kwargs) -> Any:
        return message

@register_tool
class WeatherTool(BaseTool):
    name = "weather"
    description = "Mock weather tool. Inputs: city (str)"
    
    def run(self, city: str, **kwargs) -> Any:
        # Mock data
        return f"The weather in {city} is Sunny, 25°C"

@register_tool
class WebSearchTool(BaseTool):
    name = "web_search"
    description = "Simulates a web search. Inputs: query (str)"
    
    def run(self, query: str, **kwargs) -> Any:
        # In a real scenario, this would call Google/Bing API
        # For now, we mock some responses based on keywords
        query = query.lower()
        if "competitor" in query or "competitors" in query:
            return {
                "results": [
                    {"title": "Competitor A", "snippet": "Leading provider of AI solutions..."},
                    {"title": "Competitor B", "snippet": "Focuses on enterprise automation..."},
                    {"title": "Competitor C", "snippet": "New startup in the agentic AI space..."}
                ]
            }
        elif "market" in query or "trend" in query:
            return {
                "results": [
                    {"title": "AI Market Report 2025", "snippet": "The agent market is expected to grow by 300%..."},
                    {"title": "Trends in LLM", "snippet": "Shift towards smaller, specialized models..."}
                ]
            }
        else:
            return {
                "results": [
                    {"title": f"Result for {query}", "snippet": "Generic search result content..."}
                ]
            }

@register_tool
class ContentSummarizer(BaseTool):
    name = "summarizer"
    description = "Summarizes text content. Inputs: text (str), max_words (int)"
    
    def run(self, text: str, max_words: int = 50, **kwargs) -> Any:
        # Mock summarization
        if isinstance(text, dict):
            text = str(text)
        return f"Summary of content (length {len(text)}): {text[:100]}... [Key points extracted]"

@register_tool
class EmailSender(BaseTool):
    name = "email_sender"
    description = "Simulates sending an email. Inputs: recipient (str), subject (str), body (str)"
    
    def run(self, recipient: str, subject: str, body: str, **kwargs) -> Any:
        return f"Email sent to {recipient} with subject '{subject}'"

@register_tool
class FileReader(BaseTool):
    name = "file_reader"
    description = "Reads a file. Inputs: file_path (str)"
    
    def run(self, file_path: str, **kwargs) -> Any:
        try:
            # Mock reading specific files for demo
            if "code.py" in file_path:
                return "def hello():\n    print('Hello world')\n    x = 1/0 # Bug here"
            return f"Content of {file_path}"
        except Exception as e:
            return f"Error reading file: {e}"

@register_tool
class CodeLinter(BaseTool):
    name = "code_linter"
    description = "Lints code and returns errors. Inputs: code (str)"
    
    def run(self, code: str, **kwargs) -> Any:
        issues = []
        if "1/0" in code:
            issues.append("Line 3: Division by zero detected")
        if "print" in code and "(" not in code: # Python 2 style
            issues.append("Line 2: Missing parentheses in call to 'print'")
        
        if not issues:
            return "No issues found."
        return "\n".join(issues)

@register_tool
class ReportGenerator(BaseTool):
    name = "report_generator"
    description = "Generates a formatted report. Inputs: title (str), data (dict/str)"
    
    def run(self, title: str, data: Any, **kwargs) -> Any:
        return f"# {title}\n\n## Generated Report\n{str(data)}"
