"""
LLM 配置管理模块，提供 LLM 相关的配置加载与管理。
从 angineer_core.config 中提取，专注于 AI 推理层配置。
"""
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


def load_llm_models_from_env() -> List[LLMModelConfig]:
    """从环境变量加载 LLM 模型配置列表。"""
    models = []

    aliyun_private_key = _get_env_str("Private_ALIYUN_API_KEY")
    if aliyun_private_key:
        models.append(LLMModelConfig(
            name="Qwen3.6-35B-A3B (Private)",
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
        deepseek_url = _get_env_str("DEEPSEEK_API_URL")
        deepseek_model = _get_env_str("DEEPSEEK_MODEL")
        models.append(LLMModelConfig(
            name="DeepSeek-V4-Flash",
            api_key=deepseek_key,
            base_url=deepseek_url,
            model=deepseek_model,
            priority=7
        ))
        models.append(LLMModelConfig(
            name="DeepSeek-V4-Pro",
            api_key=deepseek_key,
            base_url=deepseek_url,
            model="deepseek-reasoner",
            priority=8
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

    for i, model in enumerate(models):
        if 'Qwen3.6-35B-A3B' in model.name or 'qwen3.6-35b-a3b' in model.name.lower():
            models.insert(0, models.pop(i))
            break

    return models


def load_llm_config_from_env() -> LLMClientConfig:
    """从环境变量加载 LLM 客户端配置。"""
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
