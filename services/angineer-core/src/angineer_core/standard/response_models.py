"""
LLM 响应数据结构定义。

定义 LLM 返回响应的标准数据格式，用于：
- 意图分类
- 步骤执行动作
- SOP 步骤解析
- 参数提取
"""
from typing import Any, Dict, Optional
from pydantic import BaseModel


class IntentResponse(BaseModel):
    """意图分类响应结构。"""
    sop_id: Optional[str] = None
    reason: Optional[str] = None


class ActionResponse(BaseModel):
    """步骤执行动作响应结构。"""
    action: str
    question: Optional[str] = None
    query: Optional[str] = None
    table_name: Optional[str] = None
    conditions: Optional[Dict[str, Any]] = None
    target_column: Optional[str] = None
    tool: Optional[str] = None
    inputs: Optional[Dict[str, Any]] = None
    value: Optional[Any] = None
    reason: Optional[str] = None


class StepParseResponse(BaseModel):
    """SOP 步骤解析响应结构。"""
    id: str
    name: Optional[str] = None
    description: Optional[str] = None
    tool: str
    inputs: Dict[str, Any] = {}
    outputs: Dict[str, str] = {}
    notes: Optional[str] = None


class ArgsExtractResponse(BaseModel):
    """参数提取响应结构。"""
    args: Dict[str, Any] = {}
