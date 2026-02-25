"""
LLM 客户端实现，负责读取统一配置并提供对话调用能力。
支持超时、重试、熔断机制。
"""
import os
import time
import json
import threading
from typing import Dict, List, Optional, Any
from datetime import datetime, timedelta
from enum import Enum
from functools import wraps
from dotenv import load_dotenv

from openai import OpenAI, APIError, APIConnectionError, APITimeoutError, RateLimitError

from .logger import get_logger
from .response_parser import extract_json_from_text, ParseError
from ..config import get_config, LLMModelConfig, RetryConfig, CircuitBreakerConfig, TimeoutConfig

load_dotenv()
logger = get_logger(__name__)


class CircuitState(Enum):
    """熔断器状态。"""
    CLOSED = "closed"       # 正常状态
    OPEN = "open"           # 熔断状态
    HALF_OPEN = "half_open" # 半开状态


class CircuitBreaker:
    """
    熔断器实现。
    当连续失败次数达到阈值时，熔断器打开，阻止后续请求。
    经过恢复时间后，进入半开状态，允许少量请求通过以测试服务是否恢复。
    """
    
    def __init__(self, config: CircuitBreakerConfig):
        self.config = config
        self.state = CircuitState.CLOSED
        self.failure_count = 0
        self.last_failure_time: Optional[datetime] = None
        self.half_open_success_count = 0
        self._lock = threading.Lock()
    
    def can_execute(self) -> bool:
        """检查是否允许执行请求。"""
        with self._lock:
            if self.state == CircuitState.CLOSED:
                return True
            
            if self.state == CircuitState.OPEN:
                if self.last_failure_time is None:
                    self.state = CircuitState.HALF_OPEN
                    return True
                
                elapsed = datetime.now() - self.last_failure_time
                if elapsed.total_seconds() >= self.config.recovery_timeout:
                    logger.info("熔断器进入半开状态，允许测试请求")
                    self.state = CircuitState.HALF_OPEN
                    self.half_open_success_count = 0
                    return True
                return False
            
            if self.state == CircuitState.HALF_OPEN:
                return self.half_open_success_count < self.config.half_open_requests
        
        return False
    
    def record_success(self):
        """记录成功请求。"""
        with self._lock:
            if self.state == CircuitState.HALF_OPEN:
                self.half_open_success_count += 1
                if self.half_open_success_count >= self.config.half_open_requests:
                    logger.info("熔断器恢复正常状态")
                    self.state = CircuitState.CLOSED
                    self.failure_count = 0
            elif self.state == CircuitState.CLOSED:
                self.failure_count = 0
    
    def record_failure(self):
        """记录失败请求。"""
        with self._lock:
            self.failure_count += 1
            self.last_failure_time = datetime.now()
            
            if self.state == CircuitState.HALF_OPEN:
                logger.warning("半开状态下请求失败，熔断器重新打开")
                self.state = CircuitState.OPEN
            elif self.failure_count >= self.config.failure_threshold:
                logger.warning(
                    f"连续失败 {self.failure_count} 次，熔断器打开，"
                    f"将在 {self.config.recovery_timeout} 秒后尝试恢复"
                )
                self.state = CircuitState.OPEN
    
    def get_status(self) -> Dict[str, Any]:
        """获取熔断器状态信息。"""
        with self._lock:
            return {
                "state": self.state.value,
                "failure_count": self.failure_count,
                "last_failure_time": self.last_failure_time.isoformat() if self.last_failure_time else None
            }


def retry_with_backoff(retry_config: RetryConfig):
    """
    重试装饰器，支持指数退避。
    
    Args:
        retry_config: 重试配置
    """
    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            last_error = None
            
            for attempt in range(retry_config.max_retries + 1):
                try:
                    return func(*args, **kwargs)
                except (APITimeoutError, APIConnectionError, RateLimitError) as e:
                    last_error = e
                    
                    if attempt < retry_config.max_retries:
                        delay = min(
                            retry_config.initial_delay * (retry_config.exponential_base ** attempt),
                            retry_config.max_delay
                        )
                        logger.warning(
                            f"请求失败 (尝试 {attempt + 1}/{retry_config.max_retries + 1})，"
                            f"{delay:.1f} 秒后重试: {e}"
                        )
                        time.sleep(delay)
                    else:
                        logger.error(f"重试次数耗尽: {e}")
                except Exception as e:
                    last_error = e
                    logger.error(f"请求发生不可重试的错误: {e}")
                    break
            
            raise last_error or Exception("重试失败")
        
        return wrapper
    return decorator


class LLMClient:
    """
    LLM 客户端类，负责管理多个 LLM 配置并处理对话请求。
    支持超时、重试、熔断机制。
    """
    
    def __init__(self, config=None):
        """
        初始化 LLM 客户端。
        
        Args:
            config: 可选的配置对象，默认从全局配置加载
        """
        self._config = config or get_config()
        self._circuit_breakers: Dict[str, CircuitBreaker] = {}
        self._init_circuit_breakers()
        logger.info(f"LLM 客户端初始化完成，加载了 {len(self._config.llm.models)} 个模型配置")
    
    def _init_circuit_breakers(self):
        """为每个模型配置初始化熔断器。"""
        for model_config in self._config.llm.models:
            self._circuit_breakers[model_config.name] = CircuitBreaker(
                self._config.llm.circuit_breaker
            )
    
    def _get_model_configs(self, config_name: Optional[str] = None) -> List[LLMModelConfig]:
        """
        获取可用的模型配置列表。
        
        Args:
            config_name: 可选的配置名称过滤
        
        Returns:
            可用的模型配置列表
        """
        configs = []
        for mc in self._config.llm.models:
            if not mc.enabled or not mc.api_key or not mc.base_url:
                continue
            if config_name and mc.name != config_name:
                continue
            configs.append(mc)
        
        configs.sort(key=lambda m: m.priority, reverse=True)
        return configs
    
    def _prepare_messages(self, messages: List[Dict], mode: str = "instruct") -> List[Dict]:
        """
        准备消息列表，根据模式添加系统提示。
        
        Args:
            messages: 原始消息列表
            mode: 运行模式
        
        Returns:
            处理后的消息列表
        """
        processed = list(messages)
        
        if mode == "thinking":
            thinking_prompt = "请在回答之前进行深度思考，并给出详细的思考过程（使用 <thought> 标签包裹）。"
            has_system = any(m.get("role") == "system" for m in processed)
            if has_system:
                for m in processed:
                    if m.get("role") == "system":
                        m["content"] = f"{m['content']}\n\n{thinking_prompt}"
            else:
                processed.insert(0, {"role": "system", "content": thinking_prompt})
        
        elif mode == "instruct":
            instruct_prompt = "请作为一个专业的助手，严格按照指令进行回答，保持简洁且专业。"
            has_system = any(m.get("role") == "system" for m in processed)
            if not has_system:
                processed.insert(0, {"role": "system", "content": instruct_prompt})
        
        return processed
    
    def _log_request(self, config_name: str, model: str, base_url: str, mode: str, messages: List[Dict]):
        """记录请求日志。"""
        logger.info("=" * 50)
        logger.info(f"[LLM 呼叫] 正在连接: {config_name} | 模式: {mode}")
        logger.info(f"   模型: {model}")
        logger.info(f"   地址: {base_url}")
        logger.debug("-" * 20)
        logger.debug("[输入消息]:")
        for msg in messages:
            role = msg.get('role', '未知')
            content = msg.get('content', '')
            truncated = content[:200] + "..." if len(content) > 200 else content
            logger.debug(f"   [{role.upper()}]: {truncated}")
        logger.debug("-" * 20)
    
    def _log_response(self, content: str, duration: float):
        """记录响应日志。"""
        logger.info(f"[输出响应] (耗时: {duration:.2f}秒):")
        try:
            if content.strip().startswith(("{", "[")):
                parsed = json.loads(content)
                logger.info(json.dumps(parsed, ensure_ascii=False, indent=2))
            else:
                truncated = content[:500] + "..." if len(content) > 500 else content
                logger.info(f"   {truncated}")
        except Exception:
            truncated = content[:500] + "..." if len(content) > 500 else content
            logger.info(f"   {truncated}")
        logger.info("=" * 50)
    
    def _log_error(self, error: Exception, duration: float):
        """记录错误日志。"""
        logger.error(f"[错误] (耗时: {duration:.2f}秒): {str(error)}")
        logger.error("=" * 50)
    
    def _call_openai(
        self,
        config: LLMModelConfig,
        messages: List[Dict],
        temperature: float,
        timeout_config: TimeoutConfig
    ) -> str:
        """
        调用 OpenAI 兼容的 API。
        
        Args:
            config: 模型配置
            messages: 消息列表
            temperature: 温度参数
            timeout_config: 超时配置
        
        Returns:
            模型响应内容
        """
        base_url = config.base_url
        if base_url.endswith("/chat/completions"):
            base_url = base_url.replace("/chat/completions", "")
        
        client = OpenAI(
            api_key=config.api_key,
            base_url=base_url,
            timeout=timeout_config.total
        )
        
        extra_body = {}
        if "dashscope" in config.base_url or "aliyun" in config.base_url:
            extra_body["enable_thinking"] = False
        
        response = client.chat.completions.create(
            model=config.model,
            messages=messages,
            temperature=temperature,
            max_tokens=self._config.llm.max_tokens,
            extra_body=extra_body if extra_body else None
        )
        
        return response.choices[0].message.content
    
    def chat(
        self,
        messages: List[Dict],
        temperature: Optional[float] = None,
        model: Optional[str] = None,
        mode: str = "instruct",
        config_name: Optional[str] = None
    ) -> str:
        """
        发送对话请求并获取响应。
        
        Args:
            messages: 消息列表
            temperature: 生成温度，默认使用配置值
            model: 可选，指定使用的模型 ID
            mode: 运行模式 ('thinking', 'instruct')，默认 'instruct'
            config_name: 可选，指定使用的配置名称
        
        Returns:
            模型生成的回答内容
        
        Raises:
            ValueError: 未找到有效的配置
            Exception: 所有配置都失败
        """
        env_mode = os.getenv("FORCE_LLM_MODE")
        if env_mode:
            mode = env_mode
        
        temp = temperature if temperature is not None else self._config.llm.temperature
        processed_messages = self._prepare_messages(messages, mode)
        
        model_configs = self._get_model_configs(config_name)
        
        if not model_configs:
            raise ValueError(f"未找到有效的 LLM 配置 (config_name={config_name})")
        
        last_error = None
        
        for config in model_configs:
            circuit_breaker = self._circuit_breakers.get(config.name)
            
            if circuit_breaker and not circuit_breaker.can_execute():
                logger.warning(f"熔断器已打开，跳过配置: {config.name}")
                continue
            
            self._log_request(config.name, config.model, config.base_url, mode, processed_messages)
            start_time = time.time()
            
            try:
                content = self._call_with_retry(
                    config, processed_messages, temp, self._config.llm.timeout
                )
                
                duration = time.time() - start_time
                self._log_response(content, duration)
                
                if circuit_breaker:
                    circuit_breaker.record_success()
                
                return content
                
            except Exception as e:
                duration = time.time() - start_time
                self._log_error(e, duration)
                
                if circuit_breaker:
                    circuit_breaker.record_failure()
                
                last_error = e
                continue
        
        raise last_error or ValueError("所有 LLM 配置均失败")
    
    def _call_with_retry(
        self,
        config: LLMModelConfig,
        messages: List[Dict],
        temperature: float,
        timeout_config: TimeoutConfig
    ) -> str:
        """
        带重试机制的 API 调用。
        """
        retry_config = self._config.llm.retry
        last_error = None
        
        for attempt in range(retry_config.max_retries + 1):
            try:
                return self._call_openai(config, messages, temperature, timeout_config)
            
            except (APITimeoutError, APIConnectionError, RateLimitError) as e:
                last_error = e
                
                if attempt < retry_config.max_retries:
                    delay = min(
                        retry_config.initial_delay * (retry_config.exponential_base ** attempt),
                        retry_config.max_delay
                    )
                    logger.warning(
                        f"请求失败 (尝试 {attempt + 1}/{retry_config.max_retries + 1})，"
                        f"{delay:.1f} 秒后重试: {e}"
                    )
                    time.sleep(delay)
                else:
                    logger.error(f"重试次数耗尽: {e}")
            
            except APIError as e:
                last_error = e
                logger.error(f"API 错误: {e}")
                break
            
            except Exception as e:
                last_error = e
                logger.error(f"未知错误: {e}")
                break
        
        raise last_error or Exception("重试失败")
    
    def get_circuit_breaker_status(self) -> Dict[str, Dict]:
        """获取所有熔断器状态。"""
        return {
            name: cb.get_status()
            for name, cb in self._circuit_breakers.items()
        }
    
    def reset_circuit_breaker(self, config_name: str):
        """重置指定配置的熔断器。"""
        if config_name in self._circuit_breakers:
            self._circuit_breakers[config_name] = CircuitBreaker(
                self._config.llm.circuit_breaker
            )
            logger.info(f"已重置熔断器: {config_name}")


llm_client: Optional[LLMClient] = None


def get_llm_client() -> LLMClient:
    """获取全局 LLM 客户端实例。"""
    global llm_client
    if llm_client is None:
        llm_client = LLMClient()
    return llm_client


def set_llm_client(client: LLMClient):
    """设置全局 LLM 客户端实例。"""
    global llm_client
    llm_client = client


def reset_llm_client():
    """重置全局 LLM 客户端（主要用于测试）。"""
    global llm_client
    llm_client = None


llm_client = get_llm_client()
