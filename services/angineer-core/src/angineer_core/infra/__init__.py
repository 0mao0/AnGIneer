"""
AnGIneer 基础设施模块。

包含：
- LLMClient: LLM 客户端
- Logger: 日志系统
- ResponseParser: 响应解析器
- Timing: 时间度量
- DependencyInjection: 依赖注入
"""
from angineer_core.infra.llm_client import (
    LLMClient,
    llm_client,
    get_llm_client,
    set_llm_client,
    reset_llm_client,
    CircuitBreaker,
    CircuitState,
)
from angineer_core.infra.logger import (
    get_logger,
    get_default_logger,
    set_default_logger,
    log_execution,
    LoggerAdapter,
)
from angineer_core.infra.response_parser import (
    ParseError,
    extract_json_from_text,
    parse_and_validate,
    safe_extract_string,
    safe_extract_dict,
)
from angineer_core.infra.timing import (
    TimingRecord,
    TimingStats,
    TimingContext,
    measure_time,
    timed,
    PerformanceMonitor,
    get_monitor,
)
from angineer_core.infra.dependency_injection import (
    Container,
    ServiceLocator,
    inject,
    setup_container,
    initialize_services,
)

__all__ = [
    # LLM Client
    "LLMClient",
    "llm_client",
    "get_llm_client",
    "set_llm_client",
    "reset_llm_client",
    "CircuitBreaker",
    "CircuitState",
    # Logger
    "get_logger",
    "get_default_logger",
    "set_default_logger",
    "log_execution",
    "LoggerAdapter",
    # Response Parser
    "ParseError",
    "extract_json_from_text",
    "parse_and_validate",
    "safe_extract_string",
    "safe_extract_dict",
    # Timing
    "TimingRecord",
    "TimingStats",
    "TimingContext",
    "measure_time",
    "timed",
    "PerformanceMonitor",
    "get_monitor",
    # Dependency Injection
    "Container",
    "ServiceLocator",
    "inject",
    "setup_container",
    "initialize_services",
]
