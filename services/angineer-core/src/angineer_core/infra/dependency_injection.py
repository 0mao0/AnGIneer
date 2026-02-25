"""
依赖注入模块，提供组件注册与依赖解析。

包含：
- Container: 依赖注入容器
- ServiceLocator: 服务定位器
- inject: 注入装饰器
"""
from typing import Dict, Any, Type, TypeVar, Callable, Optional
from dataclasses import dataclass
from functools import wraps

from angineer_core.infra.logger import get_logger

logger = get_logger(__name__)

T = TypeVar('T')


@dataclass
class ServiceDescriptor:
    """服务描述符。"""
    service_type: Type
    factory: Optional[Callable] = None
    instance: Optional[Any] = None
    singleton: bool = True


class Container:
    """
    依赖注入容器。
    
    支持：
    - 单例模式
    - 工厂函数
    - 实例注册
    """
    
    def __init__(self):
        self._services: Dict[Type, ServiceDescriptor] = {}
        self._instances: Dict[Type, Any] = {}
    
    def register_singleton(
        self,
        service_type: Type[T],
        instance: T
    ) -> None:
        """
        注册单例实例。
        
        Args:
            service_type: 服务类型
            instance: 服务实例
        """
        self._services[service_type] = ServiceDescriptor(
            service_type=service_type,
            instance=instance,
            singleton=True
        )
        self._instances[service_type] = instance
        logger.debug(f"Registered singleton: {service_type.__name__}")
    
    def register_factory(
        self,
        service_type: Type[T],
        factory: Callable[[], T],
        singleton: bool = True
    ) -> None:
        """
        注册工厂函数。
        
        Args:
            service_type: 服务类型
            factory: 工厂函数
            singleton: 是否单例
        """
        self._services[service_type] = ServiceDescriptor(
            service_type=service_type,
            factory=factory,
            singleton=singleton
        )
        logger.debug(f"Registered factory: {service_type.__name__} (singleton={singleton})")
    
    def register_type(
        self,
        service_type: Type[T],
        implementation_type: Optional[Type[T]] = None,
        singleton: bool = True
    ) -> None:
        """
        注册类型。
        
        Args:
            service_type: 服务类型
            implementation_type: 实现类型（默认与 service_type 相同）
            singleton: 是否单例
        """
        impl = implementation_type or service_type
        self._services[service_type] = ServiceDescriptor(
            service_type=service_type,
            factory=lambda: impl(),
            singleton=singleton
        )
        logger.debug(f"Registered type: {service_type.__name__}")
    
    def resolve(self, service_type: Type[T]) -> T:
        """
        解析服务。
        
        Args:
            service_type: 服务类型
        
        Returns:
            服务实例
        
        Raises:
            KeyError: 服务未注册
        """
        if service_type not in self._services:
            raise KeyError(f"Service not registered: {service_type.__name__}")
        
        descriptor = self._services[service_type]
        
        if descriptor.singleton and service_type in self._instances:
            return self._instances[service_type]
        
        if descriptor.instance is not None:
            instance = descriptor.instance
        elif descriptor.factory is not None:
            instance = descriptor.factory()
        else:
            instance = descriptor.service_type()
        
        if descriptor.singleton:
            self._instances[service_type] = instance
        
        return instance
    
    def try_resolve(self, service_type: Type[T]) -> Optional[T]:
        """
        尝试解析服务，失败返回 None。
        
        Args:
            service_type: 服务类型
        
        Returns:
            服务实例或 None
        """
        try:
            return self.resolve(service_type)
        except KeyError:
            return None
    
    def is_registered(self, service_type: Type) -> bool:
        """检查服务是否已注册。"""
        return service_type in self._services
    
    def clear(self) -> None:
        """清空容器。"""
        self._services.clear()
        self._instances.clear()


class ServiceLocator:
    """
    服务定位器，提供全局服务访问。
    
    使用方式：
    ```python
    ServiceLocator.initialize(config)
    memory = ServiceLocator.get(Memory)
    ```
    """
    
    _container: Optional[Container] = None
    
    @classmethod
    def initialize(cls, container: Optional[Container] = None) -> None:
        """初始化服务定位器。"""
        cls._container = container or Container()
        logger.info("ServiceLocator initialized")
    
    @classmethod
    def get_container(cls) -> Container:
        """获取容器实例。"""
        if cls._container is None:
            cls.initialize()
        return cls._container
    
    @classmethod
    def get(cls, service_type: Type[T]) -> T:
        """获取服务实例。"""
        return cls.get_container().resolve(service_type)
    
    @classmethod
    def try_get(cls, service_type: Type[T]) -> Optional[T]:
        """尝试获取服务实例。"""
        return cls.get_container().try_resolve(service_type)
    
    @classmethod
    def register(cls, service_type: Type[T], instance: T) -> None:
        """注册服务实例。"""
        cls.get_container().register_singleton(service_type, instance)
    
    @classmethod
    def reset(cls) -> None:
        """重置服务定位器。"""
        if cls._container is not None:
            cls._container.clear()
        cls._container = None


def inject(*service_types: Type) -> Callable:
    """
    依赖注入装饰器，用于函数参数注入。
    
    使用方式：
    ```python
    @inject(Memory, LLMClient)
    def my_function(memory: Memory, llm: LLMClient):
        ...
    ```
    """
    def decorator(func: Callable) -> Callable:
        @wraps(func)
        def wrapper(*args, **kwargs):
            resolved = []
            for i, service_type in enumerate(service_types):
                if i < len(args):
                    resolved.append(args[i])
                else:
                    resolved.append(ServiceLocator.get(service_type))
            
            return func(*resolved, **kwargs)
        return wrapper
    return decorator


def setup_container(config: Optional[Any] = None) -> Container:
    """
    配置并返回默认容器。
    
    Args:
        config: 配置对象
    
    Returns:
        配置好的容器
    """
    from angineer_core.config import get_config, AnGIneerConfig
    from angineer_core.core.memory import Memory
    from angineer_core.infra.llm_client import LLMClient, get_llm_client
    
    container = Container()
    
    app_config = config or get_config()
    container.register_singleton(AnGIneerConfig, app_config)
    
    container.register_factory(
        Memory,
        lambda: Memory(),
        singleton=False
    )
    
    container.register_factory(
        LLMClient,
        get_llm_client,
        singleton=True
    )
    
    logger.info("Container setup completed")
    return container


def initialize_services(config: Optional[Any] = None) -> None:
    """初始化服务定位器。"""
    container = setup_container(config)
    ServiceLocator.initialize(container)
