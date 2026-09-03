"""
配置管理模块，提供统一的配置加载与管理。

LLM 相关配置请直接使用 ai_inference.llm_config：
    from ai_inference.llm_config import LLMClientConfig, load_llm_config_from_env
"""
import json
import os
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field
from dotenv import load_dotenv

from ai_inference.llm_config import LLMClientConfig, load_llm_config_from_env

load_dotenv()

# SOP 路由置信度单一阈值（B3：收敛 classifier 拒绝阈值 0.45 与 dispatcher 执行门槛 0.6，
# 消除 0.45~0.6 区间的未定义语义）
# TODO(evals)：跑 evals 对比 0.45/0.5/0.6 三档后定值，当前先取 0.5
SOP_ROUTE_CONFIDENCE_THRESHOLD = 0.5


class MemoryConfig(BaseModel):
    """Memory 模块配置。"""
    strict_mode: bool = False
    none_replacement: str = ""
    max_context_length: int = Field(default=10000, ge=1000)


class RunnerConfig(BaseModel):
    """SOP 执行器（SopRunner）相关运行配置；reranker 配置历史挂载于此。"""
    result_md_path: Optional[str] = None
    mode: str = "instruct"
    config_name: Optional[str] = None
    enable_summary: bool = True
    summary_max_length: int = 80
    reranker_url: Optional[str] = None
    reranker_timeout_sec: float = 10.0
    reranker_configs: List[Dict[str, Any]] = Field(default_factory=list)


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
    runner: RunnerConfig = Field(default_factory=RunnerConfig)
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


def _load_reranker_configs() -> List[Dict[str, Any]]:
    """解析 reranker 端点列表：RERANKER_CONFIGS (JSON, 数组顺序=优先级, 第一项为默认)。

    每项: {name?, url, api_key?, timeout_sec?}；url 可写 base（retrieval_pipeline 自动补
    /v1/rerank 后缀）或完整 rerank 端点。未配置时返回空列表（调用方走降级链）。
    """
    raw = _get_env_str("RERANKER_CONFIGS", "").strip()
    if not raw:
        return []
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return []
    if not isinstance(data, list):
        return []
    entries: List[Dict[str, Any]] = []
    for idx, item in enumerate(data):
        if not isinstance(item, dict):
            continue
        url = str(item.get("url") or "").strip().rstrip("/")
        if not url:
            continue
        entry: Dict[str, Any] = {
            "name": str(item.get("name") or f"endpoint-{idx + 1}"),
            "url": url,
            "api_key": str(item.get("api_key") or item.get("key") or "").strip(),
        }
        timeout = item.get("timeout_sec")
        if timeout is not None:
            try:
                entry["timeout_sec"] = float(timeout)
            except (TypeError, ValueError):
                pass
        entries.append(entry)
    return entries


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

    reranker_configs = _load_reranker_configs()
    runner_config = RunnerConfig(
        reranker_url=reranker_configs[0]["url"] if reranker_configs else None,
        reranker_timeout_sec=_get_env_float("ANGINEER_RERANKER_TIMEOUT_SEC", 10.0),
        reranker_configs=reranker_configs,
    )

    return AnGIneerConfig(
        llm=llm_config,
        memory=memory_config,
        runner=runner_config,
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
