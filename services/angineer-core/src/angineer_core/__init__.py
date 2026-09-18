"""
AnGIneer Core - AI Engineer Operating System Core Module.

LLM 相关功能请直接使用 ai_inference：
    from ai_inference.llm_client import LLMClient, get_llm_client
    from ai_inference.llm_response_parser import ParseError, extract_json_from_text

惰性导出（PEP 562，2026-09-18）：本包 __init__ 不再 import classifier/memory/
base_config/base_di 等重组件——此前 `import angineer_core.agent_messages` 也会
顺带拉起 ai_inference/docs-core 整条依赖树（importtime 实测 520ms+），独立包
（如 chat-history）只想用轻量数据类/协议却被迫背全家桶。现改为 __getattr__
按需加载并缓存到 globals()，`from angineer_core import IntentClassifier` 等
既有用法逐字兼容。
"""

import importlib
from typing import TYPE_CHECKING

if TYPE_CHECKING:  # 仅为类型检查器保留的静态视图，运行时不执行任何重导入
    from angineer_core.classifier import IntentClassifier
    from angineer_core.memory import Memory, StepRecord, UndefinedVariableError
    from angineer_core.base_contracts import (
        SOP, Step, AgentResponse,
        IntentResult, IntentLevel, ServiceMode,
        IntentResponse, ActionResponse, StepParseResponse, ArgsExtractResponse,
        ScopeContext, RouteDebug, RouteDecision, Evidence, EvidenceKind,
    )
    from angineer_core.base_logger import (
        get_logger,
        get_default_logger,
        set_default_logger,
    )
    from angineer_core.base_config import (
        AnGIneerConfig,
        get_config,
        set_config,
        reset_config,
    )
    from angineer_core.base_di import (
        setup_container,
        initialize_services,
    )

__version__ = "0.1.0"

# 导出名 → 所属子模块：__getattr__ 命中时才 importlib.import_module
_LAZY_EXPORTS = {
    "IntentClassifier": "classifier",
    "Memory": "memory",
    "StepRecord": "memory",
    "UndefinedVariableError": "memory",
    "SOP": "base_contracts",
    "Step": "base_contracts",
    "AgentResponse": "base_contracts",
    "IntentResult": "base_contracts",
    "IntentLevel": "base_contracts",
    "ServiceMode": "base_contracts",
    "IntentResponse": "base_contracts",
    "ActionResponse": "base_contracts",
    "StepParseResponse": "base_contracts",
    "ArgsExtractResponse": "base_contracts",
    "ScopeContext": "base_contracts",
    "RouteDebug": "base_contracts",
    "RouteDecision": "base_contracts",
    "Evidence": "base_contracts",
    "EvidenceKind": "base_contracts",
    "get_logger": "base_logger",
    "get_default_logger": "base_logger",
    "set_default_logger": "base_logger",
    "AnGIneerConfig": "base_config",
    "get_config": "base_config",
    "set_config": "base_config",
    "reset_config": "base_config",
    "setup_container": "base_di",
    "initialize_services": "base_di",
}

__all__ = sorted(_LAZY_EXPORTS)


def __getattr__(name: str):
    mod_name = _LAZY_EXPORTS.get(name)
    if mod_name is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    value = getattr(importlib.import_module(f"{__name__}.{mod_name}"), name)
    globals()[name] = value  # 缓存：后续访问不再走 __getattr__
    return value


def __dir__():
    return sorted(set(globals()) | set(_LAZY_EXPORTS))
