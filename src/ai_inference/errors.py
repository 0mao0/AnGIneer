"""ai-inference 统一错误层级。

调用方可按类型精确处理，而不是只能捕获裸 Exception：

- ``LLMError``：所有错误的基类；
- ``ProviderUnavailableError``：连接失败 / 读取超时 / 5xx；
- ``ProviderAuthError``：API Key 无效等鉴权失败；
- ``RateLimitedError``：Provider 限流（429）；
- ``LLMTruncatedError``：输出被 max_tokens 截断；
- ``LLMStreamError``：流式输出中途失败（携带已产出部分内容）；
- ``AllProvidersFailedError``：所有可用 Provider 均失败。
"""

from typing import List, Optional


class LLMError(Exception):
    """所有 ai-inference LLM 错误的基类。"""


class ProviderUnavailableError(LLMError):
    """Provider 不可用：连接失败 / 读取超时 / 服务端 5xx。"""


class ProviderAuthError(LLMError):
    """Provider 鉴权失败（API Key 无效等）。"""


class RateLimitedError(LLMError):
    """Provider 限流（HTTP 429）。"""


class LLMTruncatedError(LLMError):
    """LLM 输出被 max_tokens 截断（finish_reason == "length"）。"""

    def __init__(self, message: str, partial_text: str = ""):
        super().__init__(message)
        self.partial_text = partial_text


class LLMStreamError(LLMError):
    """流式输出中途失败，已产出部分内容。"""

    def __init__(
        self,
        message: str,
        partial_text: str = "",
        error: Optional[Exception] = None,
    ):
        super().__init__(message)
        self.partial_text = partial_text
        self.error = error


class AllProvidersFailedError(LLMError):
    """所有可用 Provider 均失败。"""

    def __init__(
        self,
        message: str,
        last_error: Optional[Exception] = None,
        errors: Optional[List[Exception]] = None,
    ):
        super().__init__(message)
        self.last_error = last_error
        self.errors = errors or []
