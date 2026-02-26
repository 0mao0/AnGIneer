"""
配置管理模块，提供统一的配置加载与管理。
"""
import os
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field
from dotenv import load_dotenv

load_dotenv()


class LLMModelConfig(BaseModel):
    """单个 LLM 模型配置。"""
    name: str
    api_key: Optional[str] = None
    base_url: Optional[str] = None
    model: Optional[str] = None
    enabled: bool = True
    priority: int = 0


class RetryConfig(BaseModel):
    """重试策略配置。"""
    max_retries: int = Field(default=3, ge=0, le=10)
    initial_delay: float = Field(default=1.0, ge=0.1)
    max_delay: float = Field(default=30.0, ge=1.0)
    exponential_base: float = Field(default=2.0, ge=1.0)


class CircuitBreakerConfig(BaseModel):
    """熔断器配置。"""
    failure_threshold: int = Field(default=5, ge=1)
    recovery_timeout: float = Field(default=60.0, ge=10.0)
    half_open_requests: int = Field(default=1, ge=1)


class TimeoutConfig(BaseModel):
    """超时配置。"""
    connect: float = Field(default=10.0, ge=1.0)
    read: float = Field(default=60.0, ge=1.0)
    total: float = Field(default=120.0, ge=1.0)


class LLMClientConfig(BaseModel):
    """LLM 客户端完整配置。"""
    models: List[LLMModelConfig] = Field(default_factory=list)
    default_model: Optional[str] = None
    timeout: TimeoutConfig = Field(default_factory=TimeoutConfig)
    retry: RetryConfig = Field(default_factory=RetryConfig)
    circuit_breaker: CircuitBreakerConfig = Field(default_factory=CircuitBreakerConfig)
    temperature: float = Field(default=0.1, ge=0.0, le=2.0)
    max_tokens: int = Field(default=16384, ge=1)


class MemoryConfig(BaseModel):
    """Memory 模块配置。"""
    strict_mode: bool = False
    none_replacement: str = ""  # 当变量值为 None 时的替换值
    max_context_length: int = Field(default=10000, ge=1000)


class DispatcherConfig(BaseModel):
    """Dispatcher 模块配置。"""
    result_md_path: Optional[str] = None
    mode: str = "instruct"
    config_name: Optional[str] = None
    enable_summary: bool = True
    summary_max_length: int = 80


class LoggingConfig(BaseModel):
    """日志配置。"""
    level: str = "INFO"
    format: str = "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s"
    date_format: str = "%Y-%m-%d %H:%M:%S"
    log_file: Optional[str] = None


class AnGIneerConfig(BaseModel):
    """AnGIneer 全局配置。"""
    llm: LLMClientConfig = Field(default_factory=LLMClientConfig)
    memory: MemoryConfig = Field(default_factory=MemoryConfig)
    dispatcher: DispatcherConfig = Field(default_factory=DispatcherConfig)
    logging: LoggingConfig = Field(default_factory=LoggingConfig)


def _get_env_str(key: str, default: str = "") -> str:
    """获取字符串类型的环境变量。"""
    return os.getenv(key, default)


def _get_env_int(key: str, default: int = 0) -> int:
    """获取整数类型的环境变量。"""
    try:
        return int(os.getenv(key, str(default)))
    except ValueError:
        return default


def _get_env_float(key: str, default: float = 0.0) -> float:
    """获取浮点类型的环境变量。"""
    try:
        return float(os.getenv(key, str(default)))
    except ValueError:
        return default


def _get_env_bool(key: str, default: bool = False) -> bool:
    """获取布尔类型的环境变量。"""
    val = os.getenv(key, "").lower()
    if val in ("true", "1", "yes", "on"):
        return True
    if val in ("false", "0", "no", "off"):
        return False
    return default


def load_llm_models_from_env() -> List[LLMModelConfig]:
    """
    从环境变量加载 LLM 模型配置列表。
    支持多个模型提供商的配置。
    """
    models = []
    
    aliyun_private_key = _get_env_str("Private_ALIYUN_API_KEY")
    if aliyun_private_key:
        models.append(LLMModelConfig(
            name="Qwen3VL-30B-A3B (Private)",
            api_key=aliyun_private_key,
            base_url=_get_env_str("Private_ALIYUN_API_URL"),
            model=_get_env_str("Private_ALIYUN_MODEL"),
            priority=10
        ))
    
    aliyun_free_key = _get_env_str("Free_ALIYUN_API_KEY")
    if aliyun_free_key:
        models.append(LLMModelConfig(
            name="Qwen2.5-7B (SiliconFlow)",
            api_key=aliyun_free_key,
            base_url=_get_env_str("Free_ALIYUN_API_BASE"),
            model=_get_env_str("Free_ALIYUN_MODEL"),
            priority=8
        ))
    
    aliyun_public_key = _get_env_str("Public_ALIYUN_API_KEY")
    if aliyun_public_key:
        models.append(LLMModelConfig(
            name="Qwen3-4B (Public)",
            api_key=aliyun_public_key,
            base_url=_get_env_str("Public_ALIYUN_API_URL"),
            model=_get_env_str("Public_ALIYUN_MODEL"),
            priority=6
        ))
        models.append(LLMModelConfig(
            name="Qwen3.5-397B (Public)",
            api_key=aliyun_public_key,
            base_url=_get_env_str("Public_ALIYUN_API_URL"),
            model=_get_env_str("Public_ALIYUN_MODEL2"),
            priority=5
        ))
    
    deepseek_key = _get_env_str("DEEPSEEK_API_KEY")
    if deepseek_key:
        models.append(LLMModelConfig(
            name="DeepSeek_V3.2",
            api_key=deepseek_key,
            base_url=_get_env_str("DEEPSEEK_API_URL"),
            model=_get_env_str("DEEPSEEK_MODEL"),
            priority=7
        ))
    
    zhipu_key = _get_env_str("ZHIPU_API_KEY")
    if zhipu_key:
        models.append(LLMModelConfig(
            name="GLM-4.7-Flash",
            api_key=zhipu_key,
            base_url=_get_env_str("ZHIPU_API_URL"),
            model=_get_env_str("ZHIPU_MODEL"),
            priority=5
        ))
    
    nvidia_key = _get_env_str("NVIDIA_API_KEY")
    if nvidia_key:
        nvidia_url = _get_env_str("NVIDIA_API_URL")
        models.append(LLMModelConfig(
            name="Nemotron30BA3B (NVIDIA)",
            api_key=nvidia_key,
            base_url=nvidia_url,
            model=_get_env_str("NVIDIA_MODEL_NEMOTRON"),
            priority=4
        ))
        models.append(LLMModelConfig(
            name="Kimi/Moonshot (NVIDIA源)",
            api_key=nvidia_key,
            base_url=nvidia_url,
            model=_get_env_str("NVIDIA_MODEL_KIMI"),
            priority=3
        ))
        models.append(LLMModelConfig(
            name="MiniMax (NVIDIA源)",
            api_key=nvidia_key,
            base_url=nvidia_url,
            model=_get_env_str("NVIDIA_MODEL_MINIMAX"),
            priority=2
        ))
    
    models.sort(key=lambda m: m.priority, reverse=True)
    
    return models


def load_config_from_env() -> AnGIneerConfig:
    """
    从环境变量加载完整配置。
    """
    models = load_llm_models_from_env()
    
    llm_config = LLMClientConfig(
        models=models,
        default_model=_get_env_str("ANGINEER_DEFAULT_MODEL"),
        timeout=TimeoutConfig(
            connect=_get_env_float("ANGINEER_TIMEOUT_CONNECT", 10.0),
            read=_get_env_float("ANGINEER_TIMEOUT_READ", 60.0),
            total=_get_env_float("ANGINEER_TIMEOUT_TOTAL", 120.0)
        ),
        retry=RetryConfig(
            max_retries=_get_env_int("ANGINEER_MAX_RETRIES", 3),
            initial_delay=_get_env_float("ANGINEER_RETRY_INITIAL_DELAY", 1.0),
            max_delay=_get_env_float("ANGINEER_RETRY_MAX_DELAY", 30.0),
            exponential_base=_get_env_float("ANGINEER_RETRY_EXPONENTIAL_BASE", 2.0)
        ),
        circuit_breaker=CircuitBreakerConfig(
            failure_threshold=_get_env_int("ANGINEER_CB_FAILURE_THRESHOLD", 5),
            recovery_timeout=_get_env_float("ANGINEER_CB_RECOVERY_TIMEOUT", 60.0),
            half_open_requests=_get_env_int("ANGINEER_CB_HALF_OPEN_REQUESTS", 1)
        ),
        temperature=_get_env_float("ANGINEER_TEMPERATURE", 0.1),
        max_tokens=_get_env_int("ANGINEER_MAX_TOKENS", 16384)
    )
    
    memory_config = MemoryConfig(
        strict_mode=_get_env_bool("ANGINEER_MEMORY_STRICT_MODE", False),
        none_replacement=_get_env_str("ANGINEER_MEMORY_NONE_REPLACEMENT", ""),
        max_context_length=_get_env_int("ANGINEER_MEMORY_MAX_CONTEXT_LENGTH", 10000)
    )
    
    logging_config = LoggingConfig(
        level=_get_env_str("ANGINEER_LOG_LEVEL", "INFO"),
        format=_get_env_str("ANGINEER_LOG_FORMAT", "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s"),
        date_format=_get_env_str("ANGINEER_LOG_DATE_FORMAT", "%Y-%m-%d %H:%M:%S"),
        log_file=_get_env_str("ANGINEER_LOG_FILE") or None
    )
    
    return AnGIneerConfig(
        llm=llm_config,
        memory=memory_config,
        logging=logging_config
    )


_config: Optional[AnGIneerConfig] = None


def get_config() -> AnGIneerConfig:
    """
    获取全局配置实例（单例模式）。
    """
    global _config
    if _config is None:
        _config = load_config_from_env()
    return _config


def set_config(config: AnGIneerConfig) -> None:
    """
    设置全局配置实例。
    """
    global _config
    _config = config


def reset_config() -> None:
    """
    重置全局配置（主要用于测试）。
    """
    global _config
    _config = None
