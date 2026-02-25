"""
LLM 响应解析模块，提供统一的 JSON 提取与 Schema 校验。
"""
import json
import re
from typing import Any, Dict, Optional, Type, TypeVar
from pydantic import ValidationError

from angineer_core.standard.response_models import (
    IntentResponse,
    ActionResponse,
    StepParseResponse,
    ArgsExtractResponse,
)
from .logger import get_logger

logger = get_logger(__name__)

T = TypeVar('T')


class ParseError(Exception):
    """LLM 响应解析错误。"""
    
    def __init__(self, message: str, raw_response: Optional[str] = None, details: Optional[str] = None):
        super().__init__(message)
        self.raw_response = raw_response
        self.details = details
    
    def __str__(self) -> str:
        parts = [super().__str__()]
        if self.details:
            parts.append(f"详情: {self.details}")
        if self.raw_response:
            truncated = self.raw_response[:200] + "..." if len(self.raw_response) > 200 else self.raw_response
            parts.append(f"原始响应: {truncated}")
        return " | ".join(parts)


def extract_json_from_text(text: str) -> Dict[str, Any]:
    """
    从文本中提取 JSON 对象。
    支持以下格式：
    1. ```json ... ``` 代码块
    2. ``` ... ``` 代码块
    3. 裸 JSON 对象
    
    Args:
        text: 包含 JSON 的文本
    
    Returns:
        解析后的字典
    
    Raises:
        ParseError: 无法提取或解析 JSON
    """
    if not text:
        raise ParseError("响应内容为空", raw_response=text)
    
    content = text.strip()
    
    if "```json" in content:
        parts = content.split("```json")
        if len(parts) >= 2:
            json_block = parts[1].split("```")[0]
            content = json_block.strip()
    elif "```" in content:
        parts = content.split("```")
        if len(parts) >= 2:
            content = parts[1].strip()
            if content.startswith("json"):
                content = content[4:].strip()
    
    if "{" in content and "}" in content:
        start = content.find("{")
        end = content.rfind("}") + 1
        if end > start:
            content = content[start:end]
    
    try:
        return json.loads(content)
    except json.JSONDecodeError as e:
        logger.debug(f"JSON 解析失败，尝试修复: {e}")
        fixed_content = _try_fix_json(content)
        if fixed_content:
            try:
                return json.loads(fixed_content)
            except json.JSONDecodeError:
                pass
        
        raise ParseError(
            "无法解析 JSON",
            raw_response=text,
            details=f"JSON 解析错误: {e}"
        )


def _try_fix_json(content: str) -> Optional[str]:
    """
    尝试修复常见的 JSON 格式问题。
    
    Args:
        content: 可能格式错误的 JSON 字符串
    
    Returns:
        修复后的 JSON 字符串，或 None 表示无法修复
    """
    if not content:
        return None
    
    content = re.sub(r',\s*}', '}', content)
    content = re.sub(r',\s*]', ']', content)
    content = re.sub(r'"\s*:\s*"', '": "', content)
    content = content.replace("'", '"')
    
    return content


def parse_and_validate(
    text: str,
    schema: Type[T],
    strict: bool = False
) -> T:
    """
    从文本中提取 JSON 并使用 Pydantic Schema 校验。
    
    Args:
        text: LLM 响应文本
        schema: Pydantic 模型类
        strict: 是否严格模式（校验失败时抛出异常）
    
    Returns:
        校验后的 Pydantic 模型实例
    
    Raises:
        ParseError: 解析或校验失败
    """
    try:
        data = extract_json_from_text(text)
    except ParseError:
        if strict:
            raise
        logger.warning(f"JSON 提取失败，使用空字典作为默认值")
        data = {}
    
    try:
        return schema.model_validate(data)
    except ValidationError as e:
        if strict:
            raise ParseError(
                f"Schema 校验失败: {schema.__name__}",
                raw_response=text,
                details=str(e)
            )
        logger.warning(f"Schema 校验失败，尝试使用默认值: {e}")
        return _create_with_defaults(schema, data)


def _create_with_defaults(schema: Type[T], partial_data: Dict[str, Any]) -> T:
    """
    使用默认值创建 Schema 实例，合并部分数据。
    
    Args:
        schema: Pydantic 模型类
        partial_data: 部分数据
    
    Returns:
        带默认值的模型实例
    """
    defaults = {}
    for field_name, field_info in schema.model_fields.items():
        if field_name in partial_data:
            defaults[field_name] = partial_data[field_name]
        elif field_info.default is not None:
            defaults[field_name] = field_info.default
        elif field_info.default_factory is not None:
            defaults[field_name] = field_info.default_factory()
        else:
            defaults[field_name] = None
    
    return schema(**defaults)


def safe_extract_string(text: str, key: str, default: str = "") -> str:
    """
    安全地从文本中提取特定键的字符串值。
    
    Args:
        text: 包含 JSON 的文本
        key: 要提取的键名
        default: 默认值
    
    Returns:
        提取的字符串值或默认值
    """
    try:
        data = extract_json_from_text(text)
        value = data.get(key)
        if value is None:
            return default
        return str(value)
    except ParseError:
        return default


def safe_extract_dict(text: str, key: str, default: Optional[Dict] = None) -> Dict[str, Any]:
    """
    安全地从文本中提取特定键的字典值。
    
    Args:
        text: 包含 JSON 的文本
        key: 要提取的键名
        default: 默认值
    
    Returns:
        提取的字典值或默认值
    """
    if default is None:
        default = {}
    
    try:
        data = extract_json_from_text(text)
        value = data.get(key)
        if isinstance(value, dict):
            return value
        return default
    except ParseError:
        return default
