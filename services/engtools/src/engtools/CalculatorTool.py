import math
import re
from typing import Any, Dict, Optional
from .BaseTool import BaseTool, register_tool
try:
    import sympy as sp
except Exception:
    sp = None


@register_tool
class Calculator(BaseTool):
    """
    工程计算器工具，支持基础运算、科学计算、变量替换和常用工程公式。
    """
    name = "calculator"
    description_en = "Engineering calculator with variables support. Inputs: expression (str), variables (dict, optional), solve_for (str, optional). Supports: +, -, *, /, **, sqrt, sin, cos, tan, log, ln, pi, e, abs, round, min, max, equation solving (requires sympy)"
    description_zh = "工程计算器，支持变量替换。输入参数：expression (str), variables (dict, optional), solve_for (str, optional)。支持运算符：+, -, *, /, **, sqrt, sin, cos, tan, log, ln, pi, e, abs, round, min, max，方程求解（需安装sympy）"

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

    def run(self, expression: str = None, variables: Optional[Dict[str, Any]] = None, solve_for: Optional[str] = None, **kwargs) -> Any:
        """
        执行工程计算表达式。

        Args:
            expression: 数学表达式字符串，如 "T + Z0 + Z1 + Z2 + Z3" 或 "sqrt(a**2 + b**2)"
            variables: 变量字典，如 {"T": 12.3, "Z0": 0.5, "Z1": 0.3}

        Returns:
            计算结果或错误信息
        """
        # 兼容 LLM 把 expression 放到 kwargs 的情况
        if expression is None:
            expression = kwargs.pop("expression", None)
        if not expression or not isinstance(expression, str):
            return {"error": "表达式不能为空", "expression": expression}
        if sp is None:
            return {"error": "计算需要安装 sympy", "expression": expression}

        try:
            # 清理表达式
            cleaned_expr = self._clean_expression(expression)

            # 验证表达式安全性
            if not self._is_safe_expression(cleaned_expr):
                return {
                    "error": "表达式包含不允许的字符或操作",
                    "expression": expression,
                    "cleaned": cleaned_expr
                }

            if "=" in cleaned_expr:
                return self._solve_equation(
                    cleaned_expr,
                    variables if variables else {},
                    solve_for
                )

            return self._evaluate_expression(
                cleaned_expr,
                variables if variables else {}
            )

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

        expr = re.sub(r"\$\{([^}]+)\}", r"\1", expr)

        # 处理工程表示法中的上标（如 m² → m2, m³ → m3）
        expr = expr.replace("²", "**2").replace("³", "**3")

        # 处理中文括号
        expr = expr.replace("（", "(").replace("）", ")")

        # 处理中文运算符
        expr = expr.replace("＋", "+").replace("－", "-")
        expr = expr.replace("×", "*").replace("÷", "/")
        expr = expr.replace("＝", "=")

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
        allowed_pattern = r'^[\w\s\+\-\*\/\%\(\)\,\.\*\^=]+$'
        if not re.match(allowed_pattern, expression):
            # 允许一些数学函数的调用
            allowed_funcs = ['sqrt', 'sin', 'cos', 'tan', 'log', 'ln', 'exp', 'abs', 'round', 'min', 'max', 'pow']
            for func in allowed_funcs:
                expression = expression.replace(func, '')
            # 再次检查
            if not re.match(allowed_pattern, expression):
                return False

        return True

    def _solve_equation(self, expression: str, variables: Dict[str, Any], solve_for: Optional[str]) -> Dict[str, Any]:
        """
        使用 sympy 求解方程。
        """
        parts = expression.split("=")
        if len(parts) != 2:
            return {
                "error": "方程格式错误，请使用单个等号",
                "expression": expression
            }

        exclude_vars = [solve_for] if solve_for else []
        sympy_locals = self._build_sympy_locals(variables, exclude_vars)

        left = sp.sympify(parts[0], locals=sympy_locals)
        right = sp.sympify(parts[1], locals=sympy_locals)
        equation = sp.Eq(left, right)

        target_symbol = None
        if solve_for:
            if not self._is_valid_variable_name(solve_for):
                return {
                    "error": "solve_for 变量名不合法",
                    "expression": expression
                }
            target_symbol = sp.Symbol(solve_for)
        else:
            free_symbols = list(equation.free_symbols)
            if not free_symbols:
                return {
                    "result": bool(equation),
                    "expression": expression,
                    "cleaned_expression": expression,
                    "variables_used": variables
                }
            if len(free_symbols) > 1:
                return {
                    "error": "方程包含多个未知量，请指定 solve_for",
                    "expression": expression,
                    "unknowns": [str(s) for s in free_symbols]
                }
            target_symbol = free_symbols[0]

        solutions = sp.solve(equation, target_symbol)
        formatted = []
        for item in solutions:
            formatted.append(self._format_sympy_value(item))

        return {
            "solutions": formatted,
            "solve_for": str(target_symbol),
            "expression": expression,
            "cleaned_expression": expression,
            "variables_used": variables
        }

    def _evaluate_expression(self, expression: str, variables: Dict[str, Any]) -> Dict[str, Any]:
        """
        使用 sympy 解析并计算表达式。
        """
        sympy_locals = self._build_sympy_locals(variables, [])
        expr = sp.sympify(expression, locals=sympy_locals)
        free_symbols = list(expr.free_symbols)
        if free_symbols:
            return {
                "error": "表达式包含未知量，请补充变量值",
                "expression": expression,
                "unknowns": [str(s) for s in free_symbols]
            }
        value = expr.evalf()
        return {
            "result": self._format_sympy_value(value),
            "expression": expression,
            "cleaned_expression": expression,
            "variables_used": variables
        }

    def _build_sympy_locals(self, variables: Dict[str, Any], exclude_vars: Optional[list]) -> Dict[str, Any]:
        """
        构建 sympy 解析所需的本地变量与函数映射。
        """
        sympy_locals = {
            "pi": sp.pi,
            "e": sp.E,
            "abs": sp.Abs,
            "round": sp.Function("round"),
            "min": sp.Min,
            "max": sp.Max,
            "pow": sp.Pow,
            "sqrt": sp.sqrt,
            "sin": sp.sin,
            "cos": sp.cos,
            "tan": sp.tan,
            "asin": sp.asin,
            "acos": sp.acos,
            "atan": sp.atan,
            "sinh": sp.sinh,
            "cosh": sp.cosh,
            "tanh": sp.tanh,
            "log": sp.log,
            "ln": sp.log,
            "log2": lambda x: sp.log(x, 2),
            "exp": sp.exp,
            "ceil": sp.ceiling,
            "floor": sp.floor,
            "degrees": lambda x: x * 180 / sp.pi,
            "radians": lambda x: x * sp.pi / 180
        }

        excluded = set(exclude_vars or [])
        for key, value in variables.items():
            if key in excluded:
                continue
            if self._is_valid_variable_name(key):
                numeric_value = self._to_number(value)
                if numeric_value is not None:
                    sympy_locals[key] = sp.Float(numeric_value)
        return sympy_locals

    def _format_sympy_value(self, value: Any) -> Any:
        """
        格式化 sympy 计算结果为可输出的数值或对象。
        """
        if isinstance(value, bool):
            return value
        if hasattr(value, "is_Boolean") and value.is_Boolean:
            return bool(value)
        if hasattr(value, "is_Number") and value.is_Number:
            try:
                return self._format_result(float(value))
            except Exception:
                return value
        if isinstance(value, (int, float)):
            return self._format_result(float(value))
        return value

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
