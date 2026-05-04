"""
AnGIneer Core - AI Engineer Operating System Core Module.

This module provides the core functionality for the AnGIneer system,
including intent classification, SOP dispatching, and memory management.

LLM 相关功能请直接使用 ai_inference：
    from ai_inference.llm_client import LLMClient, get_llm_client
    from ai_inference.llm_response_parser import ParseError, extract_json_from_text
"""

from angineer_core.classifier import IntentClassifier
from angineer_core.dispatcher import Dispatcher
from angineer_core.memory import Memory, StepRecord, UndefinedVariableError
from angineer_core.base_contracts import (
    SOP, Step, AgentResponse,
    IntentResult, IntentLevel, ServiceMode,
    IntentResponse, ActionResponse, StepParseResponse, ArgsExtractResponse,
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

__all__ = [
    "IntentClassifier",
    "Dispatcher",
    "Memory",
    "StepRecord",
    "UndefinedVariableError",
    "SOP",
    "Step",
    "AgentResponse",
    "IntentResult",
    "IntentLevel",
    "ServiceMode",
    "IntentResponse",
    "ActionResponse",
    "StepParseResponse",
    "ArgsExtractResponse",
    "get_logger",
    "get_default_logger",
    "set_default_logger",
    "AnGIneerConfig",
    "get_config",
    "set_config",
    "reset_config",
    "setup_container",
    "initialize_services",
]
