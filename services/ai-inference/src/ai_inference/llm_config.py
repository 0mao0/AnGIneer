"""
LLM 配置管理模块。
所有模型配置统一从 .env 的 LLM_CONFIGS (JSON 格式) 读取，不再有硬编码。
"""
import json
import os
from typing import List, Optional

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
    max_retries: int = Field(default=3, ge=0, le=10)
    initial_delay: float = Field(default=1.0, ge=0.1)
    max_delay: float = Field(default=30.0, ge=1.0)
    exponential_base: float = Field(default=2.0, ge=1.0)


class CircuitBreakerConfig(BaseModel):
    failure_threshold: int = Field(default=5, ge=1)
    recovery_timeout: float = Field(default=60.0, ge=10.0)
    half_open_requests: int = Field(default=1, ge=1)


class TimeoutConfig(BaseModel):
    connect: float = Field(default=10.0, ge=1.0)
    read: float = Field(default=60.0, ge=1.0)
    total: float = Field(default=120.0, ge=1.0)


class LLMClientConfig(BaseModel):
    models: List[LLMModelConfig] = Field(default_factory=list)
    default_model: Optional[str] = None
    timeout: TimeoutConfig = Field(default_factory=TimeoutConfig)
    retry: RetryConfig = Field(default_factory=RetryConfig)
    circuit_breaker: CircuitBreakerConfig = Field(default_factory=CircuitBreakerConfig)
    temperature: float = Field(default=0.1, ge=0.0, le=2.0)
    max_tokens: int = Field(default=16384, ge=1)


def _get_env_str(key: str, default: str = "") -> str:
    return os.getenv(key, default)


def _get_env_int(key: str, default: int = 0) -> int:
    try:
        return int(os.getenv(key, str(default)))
    except ValueError:
        return default


def _get_env_float(key: str, default: float = 0.0) -> float:
    try:
        return float(os.getenv(key, str(default)))
    except ValueError:
        return default


def load_llm_models_from_env() -> List[LLMModelConfig]:
    """从 LLM_CONFIGS 环境变量 (JSON) 加载模型配置列表。"""
    raw = _get_env_str("LLM_CONFIGS")
    if not raw:
        return []

    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return []

    if not isinstance(data, list):
        return []

    models = []
    for item in data:
        if not isinstance(item, dict):
            continue
        models.append(LLMModelConfig(
            name=str(item.get("name", "")),
            model=str(item.get("model", "")),
            api_key=str(item.get("api_key", "")),
            base_url=str(item.get("base_url", "")),
            enabled=bool(item.get("enabled", True)),
            priority=int(item.get("priority", 0)),
        ))

    models.sort(key=lambda m: m.priority, reverse=True)
    return models


def load_llm_config_from_env() -> LLMClientConfig:
    models = load_llm_models_from_env()

    return LLMClientConfig(
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
