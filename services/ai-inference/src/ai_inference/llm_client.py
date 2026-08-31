"""
LLM 客户端实现，负责读取统一配置并提供对话调用能力。支持超时、重试、熔断机制，支持流式输出。
从 angineer_core.infra.llm_client 迁移至 ai-inference 层。
"""
import asyncio
import json
import os
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Callable, Dict, Generator, List, Optional

import httpx
from dotenv import load_dotenv
from openai import (
    APIError,
    APIConnectionError,
    APITimeoutError,
    AsyncOpenAI,
    AuthenticationError,
    OpenAI,
    RateLimitError,
)
from pydantic import BaseModel, ConfigDict, ValidationError

from .errors import (
    AllProvidersFailedError,
    LLMError,
    LLMStreamError,
    LLMTruncatedError,
    ProviderAuthError,
    ProviderUnavailableError,
    RateLimitedError,
)
from .llm_config import (
    CircuitBreakerConfig,
    LLMClientConfig,
    LLMModelConfig,
    RetryConfig,
    TimeoutConfig,
    load_llm_config_from_env,
)
from .llm_logger import get_logger
from .llm_response_parser import ParseError, extract_json_from_text

load_dotenv()
logger = get_logger(__name__)


def _as_dict(value: Any) -> Any:
    """把 pydantic 对象 / 命名空间 / dict / list 递归转换成普通结构（用于 usage/tool_calls）。"""
    if value is None:
        return None
    if isinstance(value, dict):
        return {k: _as_dict(v) for k, v in value.items()}
    if hasattr(value, "model_dump"):
        return _as_dict(value.model_dump(mode="json"))
    if isinstance(value, (list, tuple)):
        return [_as_dict(v) for v in value]
    if hasattr(value, "__dict__"):
        return {k: _as_dict(v) for k, v in vars(value).items()}
    return value


def _format_missing_config_error(target_config_name: str, model_configs: List[LLMModelConfig]) -> ValueError:
    """生成带可用配置列表的缺省配置错误。"""
    available = [
        str(item.name or "").strip()
        for item in model_configs
        if str(item.name or "").strip()
    ]
    joined = ", ".join(sorted(set(available))) or "<none>"
    return ValueError(f"未找到有效的 LLM 配置 (config_name={target_config_name})；可用配置: {joined}")


def _normalize_model_identifier(value: Optional[str]) -> str:
    """归一化模型标识，兼容展示名、底层模型名和轻重后缀差异。"""
    normalized = str(value or "").strip().lower()
    if not normalized:
        return ""
    normalized = normalized.replace("_", "-").replace(" ", "")
    return normalized


def _match_config_alias(config_name: Optional[str], model_configs: List[LLMModelConfig]) -> str:
    """把配置名或底层模型别名解析为已注册的配置名。"""
    target = _normalize_model_identifier(config_name)
    if not target:
        return ""

    for item in model_configs:
        if _normalize_model_identifier(item.name) == target:
            return str(item.name or "").strip()

    alias_candidates: List[str] = []
    for item in model_configs:
        model_alias = _normalize_model_identifier(item.model)
        if not model_alias:
            continue
        if model_alias == target or model_alias.startswith(f"{target}-"):
            alias_candidates.append(str(item.name or "").strip())

    if len(alias_candidates) == 1:
        return alias_candidates[0]
    return str(config_name or "").strip()


def _resolve_target_config_name(
    model: Optional[str],
    config_name: Optional[str],
    default_model: Optional[str],
) -> tuple[str, bool]:
    """统一解析优先使用的配置名，并标记是否显式要求了配置解析。"""
    if model:
        return model, True
    if config_name is not None:
        return str(config_name or default_model or "").strip(), True
    return str(default_model or "").strip(), False


def _build_timeout(timeout_config: TimeoutConfig) -> httpx.Timeout:
    """把 TimeoutConfig 完整映射为 httpx.Timeout（connect/read/write/pool 均生效）。"""
    return httpx.Timeout(
        timeout_config.total,
        connect=timeout_config.connect,
        read=timeout_config.read,
        write=timeout_config.write,
        pool=timeout_config.pool,
    )


def _raise_mapped(error: Optional[Exception]) -> None:
    """把 OpenAI SDK 异常映射为 ai-inference 错误层级并抛出。"""
    if error is None:
        raise AllProvidersFailedError("所有 LLM 配置均失败")
    if isinstance(error, RateLimitError):
        raise RateLimitedError(f"Provider 限流: {error}") from error
    if isinstance(error, AuthenticationError):
        raise ProviderAuthError(f"Provider 鉴权失败: {error}") from error
    if isinstance(error, (APIConnectionError, APITimeoutError)):
        raise ProviderUnavailableError(f"Provider 不可用: {error}") from error
    if isinstance(error, APIError):
        status = getattr(error, "status_code", None)
        if status is None or status >= 500:
            raise ProviderUnavailableError(f"Provider 不可用: {error}") from error
    raise error


def _raise_final_error(
    last_error: Optional[Exception],
    errors: List[Exception],
    tried: int,
) -> None:
    """单 Provider 失败时抛出精确错误；多 Provider 全部失败时抛出聚合错误。"""
    if tried <= 1 and last_error is not None:
        raise last_error
    raise AllProvidersFailedError(
        f"所有 LLM 配置均失败: {last_error}",
        last_error=last_error,
        errors=errors,
    )


class CircuitState(Enum):
    """熔断器状态。"""
    CLOSED = "closed"
    OPEN = "open"
    HALF_OPEN = "half_open"


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
        self.success_count = 0
        self.total_calls = 0
        self.half_open_success_count = 0
        self.last_failure_time: Optional[datetime] = None
        self.last_success_time: Optional[datetime] = None
        self.last_error_message: Optional[str] = None
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
            self.total_calls += 1
            self.success_count += 1
            self.last_success_time = datetime.now()
            if self.state == CircuitState.HALF_OPEN:
                self.half_open_success_count += 1
                if self.half_open_success_count >= self.config.half_open_requests:
                    logger.info("熔断器恢复正常状态")
                    self.state = CircuitState.CLOSED
                    self.failure_count = 0
            elif self.state == CircuitState.CLOSED:
                self.failure_count = 0

    def record_failure(self, error: Optional[Exception] = None):
        """记录失败请求，可携带最近错误信息。"""
        with self._lock:
            self.total_calls += 1
            self.failure_count += 1
            self.success_count = 0
            self.last_failure_time = datetime.now()
            self.last_error_message = str(error) if error is not None else None

            if self.state == CircuitState.HALF_OPEN:
                logger.warning("半开状态下请求失败，熔断器重新打开")
                self.state = CircuitState.OPEN
            elif self.failure_count >= self.config.failure_threshold:
                logger.warning(
                    f"连续失败 {self.failure_count} 次，熔断器打开；"
                    f"将在 {self.config.recovery_timeout} 秒后尝试恢复"
                )
                self.state = CircuitState.OPEN

    def get_status(self) -> Dict[str, Any]:
        """获取熔断器状态信息。"""
        with self._lock:
            return {
                "state": self.state.value,
                "failure_count": self.failure_count,
                "success_count": self.success_count,
                "half_open_success_count": self.half_open_success_count,
                "total_calls": self.total_calls,
                "last_failure_time": self.last_failure_time.isoformat() if self.last_failure_time else None,
                "last_success_time": self.last_success_time.isoformat() if self.last_success_time else None,
                "last_error_message": self.last_error_message,
            }


@dataclass
class ChatResult:
    """LLM 对话完整结果（含 finish_reason/usage/tool_calls 与调用元数据）。"""
    text: str = ""
    finish_reason: Optional[str] = None
    usage: Optional[Dict[str, Any]] = None
    tool_calls: Optional[List[Dict[str, Any]]] = None
    latency_seconds: Optional[float] = None
    attempts: Optional[int] = None
    used_config: Optional[str] = None
    used_model: Optional[str] = None
    circuit_breaker_state: Optional[str] = None
    reasoning: Optional[str] = None


class _ChatMessage(BaseModel):
    """消息最小结构校验（保留未知字段，避免破坏 OpenAI 多模态/tool 消息）。"""
    model_config = ConfigDict(extra="allow")

    role: str
    content: Any = None
    name: Optional[str] = None
    tool_call_id: Optional[str] = None
    tool_calls: Optional[List[Any]] = None


class _ToolFunction(BaseModel):
    model_config = ConfigDict(extra="allow")

    name: str
    description: Optional[str] = None
    parameters: Optional[Dict[str, Any]] = None


class _ToolDef(BaseModel):
    model_config = ConfigDict(extra="allow")

    type: str = "function"
    function: _ToolFunction


class _CallCounter:
    """统计一次完整调用中实际发起的 provider 请求次数（含重试与 fallback）。"""

    def __init__(self):
        self.total = 0


class LLMClient:
    """
    LLM 客户端类，负责管理多个 LLM 配置并处理对话请求。
    支持超时、重试、熔断机制；提供同步与异步（achat_*）两套 API。
    """

    def __init__(
        self,
        config: Optional[LLMClientConfig] = None,
        usage_callback: Optional[Callable[[ChatResult], None]] = None,
    ):
        """
        初始化 LLM 客户端。

        Args:
            config: 可选的配置对象，默认从 ai_inference.llm_config 加载
            usage_callback: 可选用量回调（每次成功调用后触发），由调用方决定是否持久化；
                回调异常不会影响请求结果
        """
        if config is not None:
            self._config = config
        else:
            self._config = load_llm_config_from_env()
        self._usage_callback = usage_callback
        self._circuit_breakers: Dict[str, CircuitBreaker] = {}
        self._init_circuit_breakers()
        logger.info(f"LLM 客户端初始化完成，加载了 {len(self._config.models)} 个模型配置")

    def _init_circuit_breakers(self):
        """为每个模型配置初始化熔断器。"""
        for model_config in self._config.models:
            self._circuit_breakers[model_config.name] = CircuitBreaker(
                self._config.circuit_breaker
            )

    @property
    def configs(self) -> List[Dict[str, Any]]:
        """获取所有模型配置列表（用于 API 返回，api_key 脱敏）。"""
        return [
            {
                "name": mc.name,
                "model": mc.model,
                "api_key": "***" if mc.api_key else "",
                "base_url": mc.base_url,
                "enabled": mc.enabled,
                "priority": mc.priority
            }
            for mc in self._config.models
        ]

    def _get_model_configs(self, config_name: Optional[str] = None) -> List[LLMModelConfig]:
        """获取可用的模型配置列表。"""
        matched_config_name = _match_config_alias(config_name, self._config.models)
        configs = []
        for mc in self._config.models:
            if not mc.enabled or not mc.api_key or not mc.base_url:
                continue
            if matched_config_name and mc.name != matched_config_name:
                continue
            configs.append(mc)

        configs.sort(key=lambda m: m.priority, reverse=True)
        return configs

    def _resolve_model_configs(self, target_config_name: str, explicit_config: bool) -> List[LLMModelConfig]:
        """解析本轮可用的模型配置。

        - 显式指定 config_name/model：只使用该配置（严格过滤）；
        - 仅配置了 default_model：默认模型优先，但保留全部可用配置用于 fallback。
        """
        model_configs = self._get_model_configs(target_config_name if explicit_config else None)
        if not explicit_config and self._config.default_model:
            default_name = str(self._config.default_model)
            model_configs = sorted(
                model_configs,
                key=lambda m: (str(m.name) != default_name, -m.priority),
            )
        return model_configs

    @staticmethod
    def _validate_inputs(messages: Any, tools: Any) -> None:
        """尽早校验 messages / tools，暴露调用方错误（不改动原始数据）。"""
        if not isinstance(messages, list):
            raise ValueError("messages 必须是列表")
        for i, msg in enumerate(messages):
            if not isinstance(msg, dict):
                raise ValueError(f"messages[{i}] 必须是字典，实际为 {type(msg).__name__}")
            try:
                _ChatMessage.model_validate(msg)
            except ValidationError as e:
                raise ValueError(f"messages[{i}] 校验失败: {e}") from e

        if tools is None:
            return
        if not isinstance(tools, list):
            raise ValueError("tools 必须是列表")
        for i, tool in enumerate(tools):
            if not isinstance(tool, dict):
                raise ValueError(f"tools[{i}] 必须是字典，实际为 {type(tool).__name__}")
            try:
                _ToolDef.model_validate(tool)
            except ValidationError as e:
                raise ValueError(f"tools[{i}] 校验失败: {e}") from e

    def _prepare_messages(self, messages: List[Dict], mode: str = "instruct") -> List[Dict]:
        """准备消息列表，根据模式添加系统提示（不修改调用方传入的数据）。"""
        processed = [dict(m) for m in messages]

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
            instruct_prompt = "请作为一名专业的助手，严格按照指令进行回答，保持简洁且专业。"
            has_system = any(m.get("role") == "system" for m in processed)
            if not has_system:
                processed.insert(0, {"role": "system", "content": instruct_prompt})

        return processed

    def _log_request(self, config_name: str, model: str, base_url: str, mode: str, messages: List[Dict]):
        """记录请求日志。"""
        logger.info("=" * 50)
        logger.info(f"[LLM 调用] 正在连接: {config_name} | 模式: {mode}")
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

    @staticmethod
    def _normalize_base_url(base_url: str) -> str:
        """规范化 base_url，移除多余的路径后缀。"""
        if base_url.endswith("/chat/completions"):
            base_url = base_url.replace("/chat/completions", "")
        return base_url

    def _emit_usage_callback(self, result: ChatResult) -> None:
        """触发用量回调（异常只告警，不影响请求结果）。"""
        if self._usage_callback is None:
            return
        try:
            self._usage_callback(result)
        except Exception as e:
            logger.warning(f"usage_callback 执行失败（不影响请求结果）: {e}")

    def _call_openai(
        self,
        config: LLMModelConfig,
        messages: List[Dict],
        temperature: float,
        timeout_config: TimeoutConfig,
        max_tokens: Optional[int] = None,
        tools: Optional[List[Dict]] = None,
        counter: Optional[_CallCounter] = None
    ) -> ChatResult:
        """调用 OpenAI 兼容的 API（同步）。"""
        if counter is not None:
            counter.total += 1
        base_url = self._normalize_base_url(config.base_url)

        client = OpenAI(
            api_key=config.api_key,
            base_url=base_url,
            timeout=_build_timeout(timeout_config)
        )

        extra_body = {}
        _template_kwargs = json.loads(os.getenv("ANGINEER_CHAT_TEMPLATE_KWARGS", "null"))
        if _template_kwargs:
            extra_body["chat_template_kwargs"] = _template_kwargs
        elif "dashscope" in config.base_url or "aliyun" in config.base_url:
            extra_body["enable_thinking"] = False
        elif "124.221.238.70" in config.base_url or "qwen3.6" in config.model:
            extra_body["chat_template_kwargs"] = {"enable_thinking": False}

        effective_max_tokens = max_tokens if max_tokens is not None else self._config.max_tokens
        response = client.chat.completions.create(
            model=config.model,
            messages=messages,
            temperature=temperature,
            max_tokens=effective_max_tokens,
            tools=tools,
            extra_body=extra_body if extra_body else None
        )

        choice = response.choices[0]
        message = choice.message
        tool_calls = None
        raw_tool_calls = getattr(message, "tool_calls", None)
        if raw_tool_calls:
            tool_calls = [_as_dict(tc) for tc in raw_tool_calls]
        usage = None
        if getattr(response, "usage", None) is not None:
            usage = _as_dict(response.usage)
        return ChatResult(
            text=message.content or "",
            finish_reason=getattr(choice, "finish_reason", None),
            usage=usage,
            tool_calls=tool_calls,
            reasoning=getattr(message, "reasoning", None),
        )

    async def _call_openai_async(
        self,
        config: LLMModelConfig,
        messages: List[Dict],
        temperature: float,
        timeout_config: TimeoutConfig,
        max_tokens: Optional[int] = None,
        tools: Optional[List[Dict]] = None,
        counter: Optional[_CallCounter] = None
    ) -> ChatResult:
        """调用 OpenAI 兼容的 API（异步）。"""
        if counter is not None:
            counter.total += 1
        base_url = self._normalize_base_url(config.base_url)

        client = AsyncOpenAI(
            api_key=config.api_key,
            base_url=base_url,
            timeout=_build_timeout(timeout_config)
        )

        extra_body = {}
        _template_kwargs = json.loads(os.getenv("ANGINEER_CHAT_TEMPLATE_KWARGS", "null"))
        if _template_kwargs:
            extra_body["chat_template_kwargs"] = _template_kwargs
        elif "dashscope" in config.base_url or "aliyun" in config.base_url:
            extra_body["enable_thinking"] = False
        elif "124.221.238.70" in config.base_url or "qwen3.6" in config.model:
            extra_body["chat_template_kwargs"] = {"enable_thinking": False}

        effective_max_tokens = max_tokens if max_tokens is not None else self._config.max_tokens
        response = await client.chat.completions.create(
            model=config.model,
            messages=messages,
            temperature=temperature,
            max_tokens=effective_max_tokens,
            tools=tools,
            extra_body=extra_body if extra_body else None
        )

        choice = response.choices[0]
        message = choice.message
        tool_calls = None
        raw_tool_calls = getattr(message, "tool_calls", None)
        if raw_tool_calls:
            tool_calls = [_as_dict(tc) for tc in raw_tool_calls]
        usage = None
        if getattr(response, "usage", None) is not None:
            usage = _as_dict(response.usage)
        return ChatResult(
            text=message.content or "",
            finish_reason=getattr(choice, "finish_reason", None),
            usage=usage,
            tool_calls=tool_calls,
            reasoning=getattr(message, "reasoning", None),
        )

    def _call_openai_stream_events(
        self,
        config: LLMModelConfig,
        messages: List[Dict],
        temperature: float,
        timeout_config: TimeoutConfig,
        max_tokens: Optional[int] = None,
        tools: Optional[List[Dict]] = None,
        counter: Optional[_CallCounter] = None
    ) -> Generator[Dict[str, Any], None, None]:
        """调用 OpenAI 兼容的 API（同步流式），产出 delta/done 事件。"""
        if counter is not None:
            counter.total += 1
        base_url = self._normalize_base_url(config.base_url)

        client = OpenAI(
            api_key=config.api_key,
            base_url=base_url,
            timeout=_build_timeout(timeout_config)
        )

        extra_body = {}
        _template_kwargs = json.loads(os.getenv("ANGINEER_CHAT_TEMPLATE_KWARGS", "null"))
        if _template_kwargs:
            extra_body["chat_template_kwargs"] = _template_kwargs
        elif "dashscope" in config.base_url or "aliyun" in config.base_url:
            extra_body["enable_thinking"] = False
        elif "124.221.238.70" in config.base_url or "qwen3.6" in config.model:
            extra_body["chat_template_kwargs"] = {"enable_thinking": False}

        effective_max_tokens = max_tokens if max_tokens is not None else self._config.max_tokens
        response = client.chat.completions.create(
            model=config.model,
            messages=messages,
            temperature=temperature,
            max_tokens=effective_max_tokens,
            tools=tools,
            stream_options={"include_usage": True},
            extra_body=extra_body if extra_body else None,
            stream=True
        )

        finish_reason = None
        usage = None
        for chunk in response:
            if chunk.choices:
                choice = chunk.choices[0]
                delta = getattr(choice, "delta", None)
                content = getattr(delta, "content", None)
                if content:
                    yield {"type": "delta", "text": content}
                reasoning = getattr(delta, "reasoning", None)
                if reasoning:
                    yield {"type": "delta", "reasoning": reasoning}
                if getattr(choice, "finish_reason", None):
                    finish_reason = choice.finish_reason
            chunk_usage = getattr(chunk, "usage", None)
            if chunk_usage is not None:
                usage = _as_dict(chunk_usage)
        yield {"type": "done", "finish_reason": finish_reason, "usage": usage}

    async def _call_openai_stream_events_async(
        self,
        config: LLMModelConfig,
        messages: List[Dict],
        temperature: float,
        timeout_config: TimeoutConfig,
        max_tokens: Optional[int] = None,
        tools: Optional[List[Dict]] = None,
        counter: Optional[_CallCounter] = None
    ):
        """调用 OpenAI 兼容的 API（异步流式），产出 delta/done 事件。"""
        if counter is not None:
            counter.total += 1
        base_url = self._normalize_base_url(config.base_url)

        client = AsyncOpenAI(
            api_key=config.api_key,
            base_url=base_url,
            timeout=_build_timeout(timeout_config)
        )

        extra_body = {}
        _template_kwargs = json.loads(os.getenv("ANGINEER_CHAT_TEMPLATE_KWARGS", "null"))
        if _template_kwargs:
            extra_body["chat_template_kwargs"] = _template_kwargs
        elif "dashscope" in config.base_url or "aliyun" in config.base_url:
            extra_body["enable_thinking"] = False
        elif "124.221.238.70" in config.base_url or "qwen3.6" in config.model:
            extra_body["chat_template_kwargs"] = {"enable_thinking": False}

        effective_max_tokens = max_tokens if max_tokens is not None else self._config.max_tokens
        response = await client.chat.completions.create(
            model=config.model,
            messages=messages,
            temperature=temperature,
            max_tokens=effective_max_tokens,
            tools=tools,
            stream_options={"include_usage": True},
            extra_body=extra_body if extra_body else None,
            stream=True
        )

        finish_reason = None
        usage = None
        async for chunk in response:
            if chunk.choices:
                choice = chunk.choices[0]
                delta = getattr(choice, "delta", None)
                content = getattr(delta, "content", None)
                if content:
                    yield {"type": "delta", "text": content}
                reasoning = getattr(delta, "reasoning", None)
                if reasoning:
                    yield {"type": "delta", "reasoning": reasoning}
                if getattr(choice, "finish_reason", None):
                    finish_reason = choice.finish_reason
            chunk_usage = getattr(chunk, "usage", None)
            if chunk_usage is not None:
                usage = _as_dict(chunk_usage)
        yield {"type": "done", "finish_reason": finish_reason, "usage": usage}

    def chat(
        self,
        messages: List[Dict],
        temperature: Optional[float] = None,
        model: Optional[str] = None,
        mode: str = "instruct",
        config_name: Optional[str] = None,
        max_tokens: Optional[int] = None,
        tools: Optional[List[Dict]] = None
    ) -> str:
        """发送对话请求并获取响应（薄包装，返回纯文本；None 内容退化为空串）。"""
        return self.chat_result(
            messages,
            temperature=temperature,
            model=model,
            mode=mode,
            config_name=config_name,
            max_tokens=max_tokens,
            tools=tools,
        ).text or ""

    def chat_result(
        self,
        messages: List[Dict],
        temperature: Optional[float] = None,
        model: Optional[str] = None,
        mode: str = "instruct",
        config_name: Optional[str] = None,
        max_tokens: Optional[int] = None,
        tools: Optional[List[Dict]] = None
    ) -> ChatResult:
        """发送对话请求并返回完整结果（含 finish_reason/usage/tool_calls/元数据）。"""
        env_mode = os.getenv("FORCE_LLM_MODE")
        if env_mode:
            mode = env_mode

        self._validate_inputs(messages, tools)
        temp = temperature if temperature is not None else self._config.temperature
        effective_max_tokens = max_tokens if max_tokens is not None else self._config.max_tokens
        processed_messages = self._prepare_messages(messages, mode)

        target_config_name, explicit_config = _resolve_target_config_name(
            model,
            config_name,
            self._config.default_model,
        )
        if explicit_config and not target_config_name:
            raise _format_missing_config_error(target_config_name, self._config.models)
        model_configs = self._resolve_model_configs(target_config_name, explicit_config)

        if not model_configs:
            raise _format_missing_config_error(target_config_name, self._config.models)

        last_error = None
        errors: List[Exception] = []
        counter = _CallCounter()
        tried = 0

        for config in model_configs:
            circuit_breaker = self._circuit_breakers.get(config.name)

            if circuit_breaker and not circuit_breaker.can_execute():
                logger.warning(f"熔断器已打开，跳过配置 {config.name}")
                continue

            tried += 1
            self._log_request(config.name, config.model, config.base_url, mode, processed_messages)
            start_time = time.time()

            try:
                result = self._call_with_retry(
                    config, processed_messages, temp, self._config.timeout,
                    effective_max_tokens, tools, counter,
                )

                duration = time.time() - start_time
                result.latency_seconds = duration
                result.attempts = counter.total
                result.used_config = config.name
                result.used_model = config.model
                result.circuit_breaker_state = (
                    circuit_breaker.state.value if circuit_breaker else None
                )
                self._log_response(result.text, duration)

                if circuit_breaker:
                    circuit_breaker.record_success()

                self._emit_usage_callback(result)
                return result

            except Exception as e:
                duration = time.time() - start_time
                self._log_error(e, duration)

                if circuit_breaker:
                    circuit_breaker.record_failure(e)

                errors.append(e)
                last_error = e
                continue

        _raise_final_error(last_error, errors, tried)

    def chat_stream(
        self,
        messages: List[Dict],
        temperature: Optional[float] = None,
        model: Optional[str] = None,
        mode: str = "instruct",
        config_name: Optional[str] = None,
        max_tokens: Optional[int] = None,
        tools: Optional[List[Dict]] = None
    ) -> Generator[str, None, None]:
        """发送对话请求并以流式方式获取响应（保持纯文本 yield，兼容现有调用方）。

        流式语义：首个 delta 之前失败 → 重试/换模型；已经开始输出后失败 →
        抛出 LLMStreamError（携带 partial_text），由调用方决定保留或丢弃。
        """
        for event in self.chat_stream_events(
            messages,
            temperature=temperature,
            model=model,
            mode=mode,
            config_name=config_name,
            max_tokens=max_tokens,
            tools=tools,
        ):
            if event["type"] == "delta":
                yield event["text"]
            elif event["type"] == "stream_failed":
                raise LLMStreamError(
                    f"流式输出中途失败: {event['error']['message']}",
                    partial_text=event.get("text", ""),
                )

    def chat_stream_events(
        self,
        messages: List[Dict],
        temperature: Optional[float] = None,
        model: Optional[str] = None,
        mode: str = "instruct",
        config_name: Optional[str] = None,
        max_tokens: Optional[int] = None,
        tools: Optional[List[Dict]] = None
    ) -> Generator[Dict[str, Any], None, None]:
        """发送对话请求并以流式方式获取响应（yield delta/done/stream_failed 事件）。

        流式语义（已固化）：
        - 首个 delta 产出之前失败 → 按重试/熔断规则切换到下一个 Provider；
        - 已经产出 delta 之后失败 → 产出 ``stream_failed`` 事件（含 partial text 与错误信息）
          并立即停止，不再切换 Provider；
        - 正常结束 → 产出 ``done`` 事件（含 usage 与 used_config/attempts/latency 等元数据）。
        """
        env_mode = os.getenv("FORCE_LLM_MODE")
        if env_mode:
            mode = env_mode

        self._validate_inputs(messages, tools)
        temp = temperature if temperature is not None else self._config.temperature
        effective_max_tokens = max_tokens if max_tokens is not None else self._config.max_tokens
        processed_messages = self._prepare_messages(messages, mode)

        target_config_name, explicit_config = _resolve_target_config_name(
            model,
            config_name,
            self._config.default_model,
        )
        if explicit_config and not target_config_name:
            raise _format_missing_config_error(target_config_name, self._config.models)
        model_configs = self._resolve_model_configs(target_config_name, explicit_config)

        if not model_configs:
            raise _format_missing_config_error(target_config_name, self._config.models)

        last_error = None
        errors: List[Exception] = []
        counter = _CallCounter()
        tried = 0
        started = False
        partial_parts: List[str] = []

        for config in model_configs:
            circuit_breaker = self._circuit_breakers.get(config.name)

            if circuit_breaker and not circuit_breaker.can_execute():
                logger.warning(f"熔断器已打开，跳过配置 {config.name}")
                continue

            tried += 1
            self._log_request(config.name, config.model, config.base_url, mode, processed_messages)
            start_time = time.time()

            try:
                for event in self._call_openai_stream_events(
                    config, processed_messages, temp, self._config.timeout,
                    effective_max_tokens, tools, counter,
                ):
                    if event["type"] == "delta":
                        started = True
                        partial_parts.append(event["text"])
                        yield event
                        continue

                    if event["type"] == "done":
                        duration = time.time() - start_time
                        if circuit_breaker:
                            circuit_breaker.record_success()

                        metadata = {
                            "used_config": config.name,
                            "used_model": config.model,
                            "attempts": counter.total,
                            "latency_seconds": duration,
                            "circuit_breaker_state": (
                                circuit_breaker.state.value if circuit_breaker else None
                            ),
                        }
                        enriched = dict(event)
                        enriched.update(metadata)

                        self._emit_usage_callback(
                            ChatResult(
                                text="".join(partial_parts),
                                finish_reason=event.get("finish_reason"),
                                usage=event.get("usage"),
                                latency_seconds=duration,
                                attempts=counter.total,
                                used_config=config.name,
                                used_model=config.model,
                                circuit_breaker_state=metadata["circuit_breaker_state"],
                            )
                        )
                        logger.info(f"[流式输出完成] 耗时: {duration:.2f}秒")
                        yield enriched
                        return

                    yield event

            except Exception as e:
                duration = time.time() - start_time
                self._log_error(e, duration)

                if circuit_breaker:
                    circuit_breaker.record_failure(e)

                errors.append(e)
                last_error = e

                if started:
                    yield {
                        "type": "stream_failed",
                        "text": "".join(partial_parts),
                        "finish_reason": None,
                        "error": {"type": type(e).__name__, "message": str(e)},
                        "used_config": config.name,
                        "used_model": config.model,
                        "attempts": counter.total,
                        "latency_seconds": duration,
                        "circuit_breaker_state": (
                            circuit_breaker.state.value if circuit_breaker else None
                        ),
                    }
                    return
                continue

        _raise_final_error(last_error, errors, tried)

    async def achat(
        self,
        messages: List[Dict],
        temperature: Optional[float] = None,
        model: Optional[str] = None,
        mode: str = "instruct",
        config_name: Optional[str] = None,
        max_tokens: Optional[int] = None,
        tools: Optional[List[Dict]] = None
    ) -> str:
        """异步 chat：返回纯文本（None 内容退化为空串）。"""
        result = await self.achat_result(
            messages,
            temperature=temperature,
            model=model,
            mode=mode,
            config_name=config_name,
            max_tokens=max_tokens,
            tools=tools,
        )
        return result.text or ""

    async def achat_result(
        self,
        messages: List[Dict],
        temperature: Optional[float] = None,
        model: Optional[str] = None,
        mode: str = "instruct",
        config_name: Optional[str] = None,
        max_tokens: Optional[int] = None,
        tools: Optional[List[Dict]] = None
    ) -> ChatResult:
        """异步 chat_result：返回完整结果（含元数据）。"""
        env_mode = os.getenv("FORCE_LLM_MODE")
        if env_mode:
            mode = env_mode

        self._validate_inputs(messages, tools)
        temp = temperature if temperature is not None else self._config.temperature
        effective_max_tokens = max_tokens if max_tokens is not None else self._config.max_tokens
        processed_messages = self._prepare_messages(messages, mode)

        target_config_name, explicit_config = _resolve_target_config_name(
            model,
            config_name,
            self._config.default_model,
        )
        if explicit_config and not target_config_name:
            raise _format_missing_config_error(target_config_name, self._config.models)
        model_configs = self._resolve_model_configs(target_config_name, explicit_config)

        if not model_configs:
            raise _format_missing_config_error(target_config_name, self._config.models)

        last_error = None
        errors: List[Exception] = []
        counter = _CallCounter()
        tried = 0

        for config in model_configs:
            circuit_breaker = self._circuit_breakers.get(config.name)

            if circuit_breaker and not circuit_breaker.can_execute():
                logger.warning(f"熔断器已打开，跳过配置 {config.name}")
                continue

            tried += 1
            self._log_request(config.name, config.model, config.base_url, mode, processed_messages)
            start_time = time.time()

            try:
                result = await self._call_with_retry_async(
                    config, processed_messages, temp, self._config.timeout,
                    effective_max_tokens, tools, counter,
                )

                duration = time.time() - start_time
                result.latency_seconds = duration
                result.attempts = counter.total
                result.used_config = config.name
                result.used_model = config.model
                result.circuit_breaker_state = (
                    circuit_breaker.state.value if circuit_breaker else None
                )
                self._log_response(result.text, duration)

                if circuit_breaker:
                    circuit_breaker.record_success()

                self._emit_usage_callback(result)
                return result

            except Exception as e:
                duration = time.time() - start_time
                self._log_error(e, duration)

                if circuit_breaker:
                    circuit_breaker.record_failure(e)

                errors.append(e)
                last_error = e
                continue

        _raise_final_error(last_error, errors, tried)

    async def achat_stream(
        self,
        messages: List[Dict],
        temperature: Optional[float] = None,
        model: Optional[str] = None,
        mode: str = "instruct",
        config_name: Optional[str] = None,
        max_tokens: Optional[int] = None,
        tools: Optional[List[Dict]] = None
    ):
        """异步 chat_stream：只产出纯文本 delta；中途失败抛 LLMStreamError（携带 partial_text）。"""
        async for event in self.achat_stream_events(
            messages,
            temperature=temperature,
            model=model,
            mode=mode,
            config_name=config_name,
            max_tokens=max_tokens,
            tools=tools,
        ):
            if event["type"] == "delta":
                yield event["text"]
            elif event["type"] == "stream_failed":
                raise LLMStreamError(
                    f"流式输出中途失败: {event['error']['message']}",
                    partial_text=event.get("text", ""),
                )

    async def achat_stream_events(
        self,
        messages: List[Dict],
        temperature: Optional[float] = None,
        model: Optional[str] = None,
        mode: str = "instruct",
        config_name: Optional[str] = None,
        max_tokens: Optional[int] = None,
        tools: Optional[List[Dict]] = None
    ):
        """异步 chat_stream_events：语义与同步版一致（首 delta 前失败换 Provider，之后失败产出 stream_failed）。"""
        env_mode = os.getenv("FORCE_LLM_MODE")
        if env_mode:
            mode = env_mode

        self._validate_inputs(messages, tools)
        temp = temperature if temperature is not None else self._config.temperature
        effective_max_tokens = max_tokens if max_tokens is not None else self._config.max_tokens
        processed_messages = self._prepare_messages(messages, mode)

        target_config_name, explicit_config = _resolve_target_config_name(
            model,
            config_name,
            self._config.default_model,
        )
        if explicit_config and not target_config_name:
            raise _format_missing_config_error(target_config_name, self._config.models)
        model_configs = self._resolve_model_configs(target_config_name, explicit_config)

        if not model_configs:
            raise _format_missing_config_error(target_config_name, self._config.models)

        last_error = None
        errors: List[Exception] = []
        counter = _CallCounter()
        tried = 0
        started = False
        partial_parts: List[str] = []

        for config in model_configs:
            circuit_breaker = self._circuit_breakers.get(config.name)

            if circuit_breaker and not circuit_breaker.can_execute():
                logger.warning(f"熔断器已打开，跳过配置 {config.name}")
                continue

            tried += 1
            self._log_request(config.name, config.model, config.base_url, mode, processed_messages)
            start_time = time.time()

            try:
                async for event in self._call_openai_stream_events_async(
                    config, processed_messages, temp, self._config.timeout,
                    effective_max_tokens, tools, counter,
                ):
                    if event["type"] == "delta":
                        started = True
                        partial_parts.append(event["text"])
                        yield event
                        continue

                    if event["type"] == "done":
                        duration = time.time() - start_time
                        if circuit_breaker:
                            circuit_breaker.record_success()

                        metadata = {
                            "used_config": config.name,
                            "used_model": config.model,
                            "attempts": counter.total,
                            "latency_seconds": duration,
                            "circuit_breaker_state": (
                                circuit_breaker.state.value if circuit_breaker else None
                            ),
                        }
                        enriched = dict(event)
                        enriched.update(metadata)

                        self._emit_usage_callback(
                            ChatResult(
                                text="".join(partial_parts),
                                finish_reason=event.get("finish_reason"),
                                usage=event.get("usage"),
                                latency_seconds=duration,
                                attempts=counter.total,
                                used_config=config.name,
                                used_model=config.model,
                                circuit_breaker_state=metadata["circuit_breaker_state"],
                            )
                        )
                        logger.info(f"[流式输出完成] 耗时: {duration:.2f}秒")
                        yield enriched
                        return

                    yield event

            except Exception as e:
                duration = time.time() - start_time
                self._log_error(e, duration)

                if circuit_breaker:
                    circuit_breaker.record_failure(e)

                errors.append(e)
                last_error = e

                if started:
                    yield {
                        "type": "stream_failed",
                        "text": "".join(partial_parts),
                        "finish_reason": None,
                        "error": {"type": type(e).__name__, "message": str(e)},
                        "used_config": config.name,
                        "used_model": config.model,
                        "attempts": counter.total,
                        "latency_seconds": duration,
                        "circuit_breaker_state": (
                            circuit_breaker.state.value if circuit_breaker else None
                        ),
                    }
                    return
                continue

        _raise_final_error(last_error, errors, tried)

    def _call_with_retry(
        self,
        config: LLMModelConfig,
        messages: List[Dict],
        temperature: float,
        timeout_config: TimeoutConfig,
        max_tokens: Optional[int] = None,
        tools: Optional[List[Dict]] = None,
        counter: Optional[_CallCounter] = None
    ) -> ChatResult:
        """带重试机制的 API 调用（同步）。"""
        retry_config = self._config.retry
        last_error = None

        for attempt in range(retry_config.max_retries + 1):
            try:
                result = self._call_openai(
                    config, messages, temperature, timeout_config, max_tokens, tools, counter
                )
                if counter is not None:
                    result.attempts = counter.total
                else:
                    result.attempts = attempt + 1
                return result

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

        _raise_mapped(last_error)

    async def _call_with_retry_async(
        self,
        config: LLMModelConfig,
        messages: List[Dict],
        temperature: float,
        timeout_config: TimeoutConfig,
        max_tokens: Optional[int] = None,
        tools: Optional[List[Dict]] = None,
        counter: Optional[_CallCounter] = None
    ) -> ChatResult:
        """带重试机制的 API 调用（异步）。"""
        retry_config = self._config.retry
        last_error = None

        for attempt in range(retry_config.max_retries + 1):
            try:
                result = await self._call_openai_async(
                    config, messages, temperature, timeout_config, max_tokens, tools, counter
                )
                if counter is not None:
                    result.attempts = counter.total
                else:
                    result.attempts = attempt + 1
                return result

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
                    await asyncio.sleep(delay)
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

        _raise_mapped(last_error)

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
                self._config.circuit_breaker
            )
            logger.info(f"已重置熔断器: {config_name}")


def _shorten_messages_for_retry(messages: List[Dict]) -> List[Dict]:
    """把最长的一条消息内容截半，用于截断重试（P0.2 通用策略）。"""
    if not messages:
        return messages
    longest_idx = max(
        range(len(messages)),
        key=lambda i: len(str(messages[i].get("content", ""))),
    )
    content = str(messages[longest_idx].get("content", ""))
    if not content:
        return messages
    half = max(len(content) // 2, 1)
    shortened = list(messages)
    shortened[longest_idx] = {**messages[longest_idx], "content": content[:half]}
    return shortened


def chat_result_guarded(
    client: "LLMClient",
    messages: List[Dict],
    *,
    temperature: Optional[float] = None,
    model: Optional[str] = None,
    mode: str = "instruct",
    config_name: Optional[str] = None,
    max_tokens: Optional[int] = None,
    tools: Optional[List[Dict]] = None,
) -> ChatResult:
    """调用 chat_result 并应用截断守卫（P5/P0.2）。

    finish_reason == "length" 时：把最长消息内容截半后重试一次；
    重试仍截断（或输入无法再缩短）则抛 LLMTruncatedError——截断绝不静默当成成功。
    """
    result = client.chat_result(
        messages,
        temperature=temperature,
        model=model,
        mode=mode,
        config_name=config_name,
        max_tokens=max_tokens,
        tools=tools,
    )
    if result.finish_reason != "length":
        return result

    shortened = _shorten_messages_for_retry(messages)
    if shortened == messages:
        raise LLMTruncatedError("LLM 输出被截断（输入无法继续缩短）", partial_text=result.text)

    result = client.chat_result(
        shortened,
        temperature=temperature,
        model=model,
        mode=mode,
        config_name=config_name,
        max_tokens=max_tokens,
        tools=tools,
    )
    if result.finish_reason != "length":
        return result
    raise LLMTruncatedError("LLM 输出被截断（重试后仍截断）", partial_text=result.text)


async def achat_result_guarded(
    client: "LLMClient",
    messages: List[Dict],
    *,
    temperature: Optional[float] = None,
    model: Optional[str] = None,
    mode: str = "instruct",
    config_name: Optional[str] = None,
    max_tokens: Optional[int] = None,
    tools: Optional[List[Dict]] = None,
) -> ChatResult:
    """异步版 chat_result_guarded，语义一致。"""
    result = await client.achat_result(
        messages,
        temperature=temperature,
        model=model,
        mode=mode,
        config_name=config_name,
        max_tokens=max_tokens,
        tools=tools,
    )
    if result.finish_reason != "length":
        return result

    shortened = _shorten_messages_for_retry(messages)
    if shortened == messages:
        raise LLMTruncatedError("LLM 输出被截断（输入无法继续缩短）", partial_text=result.text)

    result = await client.achat_result(
        shortened,
        temperature=temperature,
        model=model,
        mode=mode,
        config_name=config_name,
        max_tokens=max_tokens,
        tools=tools,
    )
    if result.finish_reason != "length":
        return result
    raise LLMTruncatedError("LLM 输出被截断（重试后仍截断）", partial_text=result.text)


class _LLMClientProxy:
    """模块级懒加载代理，使 llm_client.xxx 自动触发 get_llm_client()。"""

    def __getattr__(self, name):
        return getattr(get_llm_client(), name)

    def __bool__(self):
        return True


_llm_client_instance: Optional[LLMClient] = None
_llm_client_lock = threading.Lock()
llm_client: LLMClient = _LLMClientProxy()


def get_llm_client(config_name: Optional[str] = None) -> LLMClient:
    """获取全局 LLM 客户端实例（懒加载单例，线程安全）。"""
    global _llm_client_instance
    if _llm_client_instance is None:
        with _llm_client_lock:
            if _llm_client_instance is None:
                _llm_client_instance = LLMClient()
    target_config_name, explicit_config = _resolve_target_config_name(
        None,
        config_name,
        _llm_client_instance._config.default_model,
    )
    if explicit_config and not target_config_name:
        raise _format_missing_config_error(target_config_name, _llm_client_instance._config.models)
    if target_config_name and not _llm_client_instance._get_model_configs(target_config_name):
        raise _format_missing_config_error(target_config_name, _llm_client_instance._config.models)
    return _llm_client_instance


def set_llm_client(client: LLMClient):
    """设置全局 LLM 客户端实例。"""
    global _llm_client_instance
    _llm_client_instance = client


def reset_llm_client():
    """重置全局 LLM 客户端（主要用于测试）。"""
    global _llm_client_instance
    with _llm_client_lock:
        _llm_client_instance = None
