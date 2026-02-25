"""
AnGIneer Core - AI Engineer Operating System Core Module.

This module provides the core functionality for the AnGIneer system,
including intent classification, SOP dispatching, and memory management.
"""

from angineer_core.core import IntentClassifier, Dispatcher, Memory, StepRecord, UndefinedVariableError
from angineer_core.standard import (
    SOP, Step, AgentResponse,
    IntentResponse, ActionResponse, StepParseResponse, ArgsExtractResponse,
)
from angineer_core.infra import (
    LLMClient,
    llm_client,
    get_llm_client,
    set_llm_client,
    reset_llm_client,
    get_logger,
    get_default_logger,
    set_default_logger,
    ParseError,
    extract_json_from_text,
    parse_and_validate,
)
from angineer_core.config import (
    AnGIneerConfig,
    get_config,
    set_config,
    reset_config,
)

__version__ = "0.1.0"

__all__ = [
    # Core components
    "IntentClassifier",
    "Dispatcher",
    "Memory",
    "StepRecord",
    "UndefinedVariableError",
    # Standard data structures
    "SOP",
    "Step",
    "AgentResponse",
    "IntentResponse",
    "ActionResponse",
    "StepParseResponse",
    "ArgsExtractResponse",
    # LLM client
    "LLMClient",
    "llm_client",
    "get_llm_client",
    "set_llm_client",
    "reset_llm_client",
    # Logging
    "get_logger",
    "get_default_logger",
    "set_default_logger",
    # Response parsing
    "ParseError",
    "extract_json_from_text",
    "parse_and_validate",
    # Configuration
    "AnGIneerConfig",
    "get_config",
    "set_config",
    "reset_config",
]
