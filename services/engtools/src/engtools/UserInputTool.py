import os
import re
from typing import Any, Dict, Optional
from .BaseTool import BaseTool, register_tool

@register_tool
class UserInputTool(BaseTool):
    name = "user_input"
    description_en = "Asks the user for input. Inputs: question (str), default (any), variable (str)"
    description_zh = "向用户询问输入。输入参数：question (str), default (any), variable (str)"

    def run(self, question: str = None, default: Any = None, variable: str = None, **kwargs) -> Any:
        """
        模拟用户输入。
        策略：
        1. 检查 kwargs 中是否已经包含了需要的变量（通常来自 blackboard）。
        2. 如果没有，返回 default。
        3. 如果没有 default，返回模拟值。
        """
        # 尝试从 kwargs 中直接获取变量值（如果 SopRunner 已经注入）
        if variable and variable in kwargs:
             return kwargs[variable]
        
        # 检查是否有一些隐式的变量名匹配
        # 例如，如果 question 包含 "H_nav"，而 kwargs 里有 "H_nav"
        for key, val in kwargs.items():
            if key in (question or ""):
                return val

        if default is not None:
            result_val = default
        elif os.getenv("ANGINEER_USER_INPUT_MOCK", "0") == "1":
            # 仿真模式（显式开启）才允许占位串；生产路径默认禁——占位串会悄然污染黑板
            # （2026-10-12 实踩：Q1 的 user_input 步骤回填「Mock Input for None」毁掉整条受力路径）
            result_val = f"Mock Input for {variable or question}"
        else:
            name = variable or question or "输入"
            return {"error": f"需要用户提供「{name}」：当前会话不支持中途追问，请在题面补充该参数"}
        return {
            "result": result_val,
            "input": result_val,
            "value": result_val
        }