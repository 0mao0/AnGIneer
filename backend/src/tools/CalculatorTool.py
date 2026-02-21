import math
import re
from typing import Any, Dict, Optional
from src.tools.BaseTool import BaseTool, register_tool


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
