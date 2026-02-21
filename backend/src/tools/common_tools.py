import os
import ast
import re
import math
from typing import Any, Dict, Optional
from src.tools.base import BaseTool, register_tool


@register_tool
class Calculator(BaseTool):
    """
    工程计算器工具，支持基础运算、科学计算、变量替换和常用工程公式。
    """
    name = "calculator"
    description_en = "Engineering calculator with variables support. Inputs: expression (str), variables (dict, optional). Supports: +, -, *, /, **, sqrt, sin, cos, tan, log, ln, pi, e, abs, round, min, max"
    description_zh = "工程计算器，支持变量替换。输入参数：expression (str), variables (dict, optional)。支持运算符：+, -, *, /, **, sqrt, sin, cos, tan, log, ln, pi, e, abs, round, min, max"

    # 定义允许的数学函数和常量
    ALLOWED_NAMES = {
        # 常量
        "pi": math.pi,
        "e": math.e,
        # 基础函数
        "abs": abs,
        "round": round,
        "min": min,
        "max": max,
        "pow": pow,
        # 数学函数
        "sqrt": math.sqrt,
        "sin": math.sin,
        "cos": math.cos,
        "tan": math.tan,
        "asin": math.asin,
        "acos": math.acos,
        "atan": math.atan,
        "sinh": math.sinh,
        "cosh": math.cosh,
        "tanh": math.tanh,
        "log": math.log10,  # log 默认以10为底
        "ln": math.log,     # ln 自然对数
        "log2": math.log2,
        "exp": math.exp,
        "ceil": math.ceil,
        "floor": math.floor,
        # 工程常用
        "degrees": math.degrees,
        "radians": math.radians,
    }

    def run(self, expression: str, variables: Optional[Dict[str, Any]] = None, **kwargs) -> Any:
        """
        执行工程计算表达式。

        Args:
            expression: 数学表达式字符串，如 "T + Z0 + Z1 + Z2 + Z3" 或 "sqrt(a**2 + b**2)"
            variables: 变量字典，如 {"T": 12.3, "Z0": 0.5, "Z1": 0.3}

        Returns:
            计算结果或错误信息
        """
        if not expression or not isinstance(expression, str):
            return {"error": "表达式不能为空", "expression": expression}

        try:
            # 清理表达式
            cleaned_expr = self._clean_expression(expression)

            # 准备变量环境
            eval_globals = {"__builtins__": None}
            eval_locals = dict(self.ALLOWED_NAMES)

            # 添加用户自定义变量
            if variables and isinstance(variables, dict):
                for key, value in variables.items():
                    # 验证变量名合法性
                    if self._is_valid_variable_name(key):
                        # 尝试转换为数值
                        numeric_value = self._to_number(value)
                        if numeric_value is not None:
                            eval_locals[key] = numeric_value

            # 验证表达式安全性
            if not self._is_safe_expression(cleaned_expr):
                return {
                    "error": "表达式包含不允许的字符或操作",
                    "expression": expression,
                    "cleaned": cleaned_expr
                }

            # 执行计算
            result = eval(cleaned_expr, eval_globals, eval_locals)

            # 格式化结果
            formatted_result = self._format_result(result)

            return {
                "result": formatted_result,
                "expression": expression,
                "cleaned_expression": cleaned_expr,
                "variables_used": variables if variables else {}
            }

        except ZeroDivisionError:
            return {"error": "除零错误", "expression": expression}
        except SyntaxError as e:
            return {"error": f"表达式语法错误: {str(e)}", "expression": expression}
        except NameError as e:
            return {"error": f"未定义变量: {str(e)}", "expression": expression}
        except OverflowError:
            return {"error": "数值溢出", "expression": expression}
        except Exception as e:
            return {"error": f"计算错误: {str(e)}", "expression": expression}

    def _clean_expression(self, expression: str) -> str:
        """
        清理表达式，处理常见的工程表示法。
        """
        # 去除首尾空白
        expr = expression.strip()

        # 处理工程表示法中的上标（如 m² → m2, m³ → m3）
        expr = expr.replace("²", "**2").replace("³", "**3")

        # 处理中文括号
        expr = expr.replace("（", "(").replace("）", ")")

        # 处理中文运算符
        expr = expr.replace("＋", "+").replace("－", "-")
        expr = expr.replace("×", "*").replace("÷", "/")

        # 处理数学函数的中文别名
        expr = expr.replace("平方根", "sqrt").replace("开方", "sqrt")
        expr = expr.replace("平方", "**2").replace("立方", "**3")

        # 去除多余空格
        expr = re.sub(r'\s+', ' ', expr)

        return expr

    def _is_valid_variable_name(self, name: str) -> bool:
        """
        验证变量名是否合法（不能以数字开头，只能包含字母、数字、下划线）。
        """
        if not name or not isinstance(name, str):
            return False
        # 变量名规则：字母或下划线开头，后跟字母、数字、下划线
        return bool(re.match(r'^[a-zA-Z_][a-zA-Z0-9_]*$', name))

    def _is_safe_expression(self, expression: str) -> bool:
        """
        验证表达式是否安全（不包含危险操作）。
        """
        # 黑名单：危险的关键字和函数
        dangerous_keywords = [
            'import', 'from', 'exec', 'eval', 'compile', '__',
            'open', 'file', 'os', 'sys', 'subprocess', 'class',
            'def', 'lambda', 'yield', 'return', 'assert'
        ]

        expr_lower = expression.lower()
        for keyword in dangerous_keywords:
            if keyword in expr_lower:
                return False

        # 检查是否包含非法字符（只允许数学相关字符）
        # 允许的字符：数字、字母、下划线、运算符、括号、空格、小数点、逗号
        allowed_pattern = r'^[\w\s\+\-\*\/\%\(\)\,\.\*\^]+$'
        if not re.match(allowed_pattern, expression):
            # 允许一些数学函数的调用
            allowed_funcs = ['sqrt', 'sin', 'cos', 'tan', 'log', 'ln', 'exp', 'abs', 'round', 'min', 'max', 'pow']
            for func in allowed_funcs:
                expression = expression.replace(func, '')
            # 再次检查
            if not re.match(allowed_pattern, expression):
                return False

        return True

    def _to_number(self, value: Any) -> Optional[float]:
        """
        将值转换为数值类型。
        """
        if value is None:
            return None
        if isinstance(value, (int, float)):
            return float(value)
        if isinstance(value, str):
            # 去除单位后缀（如 "12.3m", "5.0kg"）
            cleaned = re.sub(r'[a-zA-Z\s]+$', '', value.strip())
            try:
                return float(cleaned)
            except ValueError:
                return None
        return None

    def _format_result(self, result: Any) -> Any:
        """
        格式化计算结果。
        """
        if isinstance(result, float):
            # 如果是整数形式，转为整数
            if result == int(result):
                return int(result)
            # 保留合适的小数位数（最多6位）
            return round(result, 6)
        return result

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
                    if isinstance(node.right, ast.Num) and node.right.n == 0:
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
