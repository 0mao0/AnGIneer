"""
AnGIneer AI Inference - AI 推理基础设施层。

包含：
- LLM 客户端（对话、流式输出、熔断、重试）
- LLM 配置管理
- LLM 响应解析

注：Embedding/Reranker 统一使用云端 API（见 .env 中 DOCS_EMBEDDING_* 与
ANGINEER_RERANKER_URL / DOCS_RERANKER_API_URL 配置），本项目不再内置本地推理服务。
"""
from ai_inference.llm_config import (
    LLMModelConfig,
    LLMClientConfig,
    RetryConfig,
    CircuitBreakerConfig,
    TimeoutConfig,
    load_llm_models_from_env,
    load_llm_config_from_env,
)
from ai_inference.llm_client import (
    LLMClient,
    CircuitBreaker,
    CircuitState,
    llm_client,
    get_llm_client,
    set_llm_client,
    reset_llm_client,
)
from ai_inference.llm_response_parser import (
    ParseError,
    extract_json_from_text,
    parse_and_validate,
    safe_extract_string,
    safe_extract_dict,
)

__all__ = [
    "LLMModelConfig",
    "LLMClientConfig",
    "RetryConfig",
    "CircuitBreakerConfig",
    "TimeoutConfig",
    "load_llm_models_from_env",
    "load_llm_config_from_env",
    "LLMClient",
    "CircuitBreaker",
    "CircuitState",
    "llm_client",
    "get_llm_client",
    "set_llm_client",
    "reset_llm_client",
    "ParseError",
    "extract_json_from_text",
    "parse_and_validate",
    "safe_extract_string",
    "safe_extract_dict",
]
