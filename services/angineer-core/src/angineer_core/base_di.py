"""
依赖注入模块，提供服务初始化与组件注册。

提供：
- setup_container: 配置并返回默认容器
- initialize_services: 初始化服务定位器
"""
from typing import Any, Optional

from angineer_core.base_logger import get_logger

logger = get_logger(__name__)


def setup_container(config: Optional[Any] = None) -> dict:
    """
    配置并返回默认服务注册表。

    Args:
        config: 配置对象

    Returns:
        包含已注册服务的字典
    """
    from angineer_core.base_config import get_config, AnGIneerConfig
    from angineer_core.memory import Memory
    from ai_inference.llm_client import LLMClient, get_llm_client

    app_config = config or get_config()

    services = {
        AnGIneerConfig: app_config,
        LLMClient: get_llm_client(),
    }

    logger.info("Service container setup completed")
    return services


def initialize_services(config: Optional[Any] = None) -> dict:
    """初始化服务并返回服务注册表。"""
    return setup_container(config)
