import re
from typing import Any, Dict, List, Optional
from .BaseTool import BaseTool, register_tool

# LLM 客户端延迟导入
llm_client = None


def _get_llm_client():
    """延迟获取 LLM 客户端，避免循环导入。"""
    global llm_client
    if llm_client is None:
        try:
            from angineer_core.infra.llm_client import llm_client as client
            llm_client = client
        except ImportError:
            pass
    return llm_client


@register_tool
class ConditionalTool(BaseTool):
    """
    条件分支工具，根据条件变量的值选择不同的执行路径。
    支持精确匹配、语义匹配，以及返回固定值或调用其他工具。
    """
    name = "conditional"
    description_en = "Conditional branch tool. Based on condition variable value, select different execution path. Supports semantic matching. Inputs: condition_var, branches (list), default"
    description_zh = "条件分支工具。根据条件变量值选择不同执行路径，支持语义匹配。输入参数：condition_var, branches (分支列表), default"

    def run(
        self,
        condition_var: str = None,
        branches: List[Dict[str, Any]] = None,
        default: Any = None,
        context: Optional[Dict[str, Any]] = None,
        **kwargs
    ) -> Any:
        """
        执行条件分支逻辑。

        Args:
            condition_var: 条件变量的值（如船型 "油船"）
            branches: 分支列表，每个分支包含：
                - match: 匹配值或匹配列表（如 "杂货船" 或 ["杂货船", "集装箱船"]）
                - value: 固定返回值
                - 或者 table_lookup: 查表参数
            default: 默认返回值
            context: 上下文变量字典

        Returns:
            匹配分支的结果，或默认值
        """
        if condition_var is None:
            condition_var = kwargs.get("condition_var") or kwargs.get("condition")

        if not branches:
            branches = kwargs.get("branches")

        if condition_var is None:
            return {"error": "条件变量不能为空", "condition_var": condition_var}

        context = context or {}
        context.update(kwargs)

        # 1. 先尝试精确匹配
        for branch in (branches or []):
            match = branch.get("match")
            if self._is_exact_match(condition_var, match):
                return self._execute_branch(branch, match, context)

        # 2. 精确匹配失败，尝试排除法匹配兜底分支
        fallback_result = self._fallback_match(condition_var, branches, context)
        if fallback_result:
            branch, matched_category = fallback_result
            return self._execute_branch(branch, matched_category, context)

        # 3. 排除法失败，尝试 LLM 语义匹配
        semantic_result = self._semantic_match(condition_var, branches, context)
        if semantic_result:
            branch, matched_category = semantic_result
            return self._execute_branch(branch, matched_category, context)

        # 4. 使用默认值
        if default is not None:
            return {"result": default, "matched": "default", "semantic": True}

        return {
            "error": f"条件变量 '{condition_var}' 没有匹配的分支",
            "condition_var": condition_var,
            "available_branches": [str(b.get("match")) for b in (branches or [])]
        }

    def _fallback_match(
        self,
        condition_var: str,
        branches: List[Dict[str, Any]],
        context: Dict[str, Any]
    ) -> Optional[tuple]:
        """
        使用排除法匹配兜底分支。

        逻辑：如果输入不在任何明确分支中，且存在兜底分支，则归入兜底分支。

        Args:
            condition_var: 条件变量值（如 "油船"）
            branches: 分支列表
            context: 上下文

        Returns:
            (匹配的兜底分支, 匹配的分类名) 或 None
        """
        if not branches:
            return None
        
        # 收集所有明确的匹配值
        explicit_values = set()
        fallback_branch = None
        fallback_category = None
        
        for branch in branches:
            match = branch.get("match")
            
            if match is None:
                continue
            
            # 处理列表形式的 match
            if isinstance(match, list):
                # 检查列表中是否有兜底关键词
                fallback_item = None
                explicit_items = []
                
                for item in match:
                    if isinstance(item, str) and self._is_fallback_keyword(item):
                        fallback_item = item
                    elif isinstance(item, str):
                        explicit_items.append(item)
                
                if fallback_item:
                    # 这个分支包含兜底关键词
                    fallback_branch = branch
                    fallback_category = fallback_item
                    # 把列表中的其他值加入明确值
                    explicit_values.update(explicit_items)
                else:
                    # 没有兜底关键词，全部是明确值
                    explicit_values.update(match)
            
            elif isinstance(match, str):
                # 检查是否为兜底关键词
                if self._is_fallback_keyword(match):
                    fallback_branch = branch
                    fallback_category = match
                else:
                    explicit_values.add(match)
        
        # 如果存在兜底分支，且输入不在明确分支中
        if fallback_branch and condition_var not in explicit_values:
            return (fallback_branch, fallback_category)
        
        return None

    def _is_fallback_keyword(self, text: str) -> bool:
        """
        判断文本是否为兜底关键词。
        """
        fallback_keywords = [
            "其他", "其它", "其他类型", "其他船型", "其他情况",
            "default", "else", "otherwise", "其他类别"
        ]
        
        if not isinstance(text, str):
            return False
        
        text_lower = text.lower()
        return any(kw in text_lower for kw in fallback_keywords)

    def _is_exact_match(self, condition_var: str, match: Any) -> bool:
        """
        精确匹配判断。
        """
        if match is None:
            return False

        if isinstance(match, list):
            return condition_var in match

        if isinstance(match, str):
            return condition_var == match

        if isinstance(match, dict):
            op = match.get("op", "==")
            value = match.get("value")

            if op == "==":
                return condition_var == value
            elif op == "!=":
                return condition_var != value
            elif op == "in":
                return condition_var in (value or [])
            elif op == "contains":
                return value in condition_var

        return condition_var == str(match)

    def _semantic_match(
        self,
        condition_var: str,
        branches: List[Dict[str, Any]],
        context: Dict[str, Any]
    ) -> Optional[tuple]:
        """
        使用 LLM 进行语义匹配。

        Args:
            condition_var: 条件变量值（如 "油船"）
            branches: 分支列表
            context: 上下文

        Returns:
            (匹配的分支, 匹配的分类名) 或 None
        """
        client = _get_llm_client()
        if not client:
            return None

        # 构建分支描述
        branch_descriptions = []
        for i, branch in enumerate(branches or []):
            match = branch.get("match")
            if isinstance(match, list):
                branch_descriptions.append(f"分支{i+1}: {', '.join(match)}")
            elif isinstance(match, str):
                branch_descriptions.append(f"分支{i+1}: {match}")

        if not branch_descriptions:
            return None

        prompt = f"""你是一个分类专家。请判断 "{condition_var}" 属于以下哪个分类分支。

分类分支：
{chr(10).join(branch_descriptions)}

规则：
1. 如果 "{condition_var}" 明确属于某个分支中的类别，返回该分支编号
2. 如果 "{condition_var}" 是某个分类的同义词或子类，返回对应分支编号
3. 如果无法判断，返回 0

只返回分支编号（1, 2, 3... 或 0），不要返回其他内容。"""

        try:
            response = client.chat(
                [{"role": "user", "content": prompt}],
                mode="instruct",
                config_name=context.get("config_name")
            )
            response = response.strip()

            # 解析分支编号
            branch_idx = int(response) - 1
            if 0 <= branch_idx < len(branches):
                matched_branch = branches[branch_idx]
                matched_category = matched_branch.get("match")
                if isinstance(matched_category, list):
                    # 找到最匹配的具体分类
                    matched_category = matched_category[0] if matched_category else "semantic_match"
                return (matched_branch, matched_category)

        except (ValueError, IndexError, Exception):
            pass

        return None

    def _execute_branch(
        self,
        branch: Dict[str, Any],
        matched: Any,
        context: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        执行匹配到的分支动作。
        """
        if "value" in branch:
            return {"result": branch["value"], "matched": matched}

        if "table_lookup" in branch:
            table_info = branch["table_lookup"]
            return self._execute_table_lookup(
                table_info.get("table_name"),
                table_info.get("query_conditions", {}),
                table_info.get("file_name"),
                table_info.get("target_column"),
                context
            )

        if "calculator" in branch:
            calc_info = branch["calculator"]
            return self._execute_calculator(
                calc_info.get("expression"),
                context
            )

        return {"error": "分支没有定义执行动作", "branch": branch}

    def _execute_table_lookup(
        self,
        table_name: str,
        query_conditions: Dict[str, Any],
        file_name: str,
        target_column: str,
        context: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        执行查表操作。
        """
        from .TableTool import TableTool
        tool = TableTool()

        resolved_conditions = {}
        for key, value in query_conditions.items():
            resolved_value = self._resolve_value(value, context)
            resolved_conditions[key] = resolved_value

        result = tool.run(
            table_name=table_name,
            query_conditions=resolved_conditions,
            file_name=file_name,
            target_column=target_column
        )

        return {
            "result": result.get("result"),
            "matched_action": "table_lookup",
            "table_name": table_name,
            "query_conditions": resolved_conditions,
            "table_result": result
        }

    def _execute_calculator(self, expression: str, context: Dict[str, Any]) -> Dict[str, Any]:
        """
        执行计算操作。
        """
        from .CalculatorTool import Calculator
        tool = Calculator()

        resolved_expr = self._resolve_value(expression, context)

        result = tool.run(expression=resolved_expr, variables=context)

        return {
            "result": result.get("result"),
            "matched_action": "calculator",
            "expression": resolved_expr,
            "calculator_result": result
        }

    def _resolve_value(self, value: Any, context: Dict[str, Any]) -> Any:
        """
        解析值，支持变量引用 ${var}。
        """
        if not isinstance(value, str):
            return value

        if "${" in value:
            pattern = r"\$\{([^}]+)\}"
            matches = re.findall(pattern, value)

            if len(matches) == 1 and value == f"${{{matches[0]}}}":
                return context.get(matches[0], value)

            for var in matches:
                var_value = context.get(var, f"${{{var}}}")
                value = value.replace(f"${{{var}}}", str(var_value))

        return value
