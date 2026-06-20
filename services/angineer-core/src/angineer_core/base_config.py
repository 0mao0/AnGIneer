"""
配置管理模块，提供统一的配置加载与管理。

LLM 相关配置请直接使用 ai_inference.llm_config：
    from ai_inference.llm_config import LLMClientConfig, load_llm_config_from_env
"""
import os
from typing import Optional
from pydantic import BaseModel, Field
from dotenv import load_dotenv

from ai_inference.llm_config import LLMClientConfig, load_llm_config_from_env

load_dotenv()


class MemoryConfig(BaseModel):
    """Memory 模块配置。"""
    strict_mode: bool = False
    none_replacement: str = ""
    max_context_length: int = Field(default=10000, ge=1000)


class DispatcherConfig(BaseModel):
    """Dispatcher 模块配置。"""
    result_md_path: Optional[str] = None
    mode: str = "instruct"
    config_name: Optional[str] = None
    enable_summary: bool = True
    summary_max_length: int = 80
    reranker_url: Optional[str] = None
    reranker_timeout_sec: float = 10.0


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


def load_config_from_env() -> AnGIneerConfig:
    """从环境变量加载完整配置。"""
    llm_config = load_llm_config_from_env()

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

    dispatcher_config = DispatcherConfig(
        reranker_url=_get_env_str("ANGINEER_RERANKER_URL") or None,
        reranker_timeout_sec=_get_env_float("ANGINEER_RERANKER_TIMEOUT_SEC", 10.0),
    )

    return AnGIneerConfig(
        llm=llm_config,
        memory=memory_config,
        dispatcher=dispatcher_config,
        logging=logging_config
    )


_config: Optional[AnGIneerConfig] = None


def get_config() -> AnGIneerConfig:
    """获取全局配置实例（单例模式）。"""
    global _config
    if _config is None:
        _config = load_config_from_env()
    return _config


def set_config(config: AnGIneerConfig) -> None:
    """设置全局配置实例。"""
    global _config
    _config = config


def reset_config() -> None:
    """重置全局配置（主要用于测试）。"""
    global _config
    _config = None
