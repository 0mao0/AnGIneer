"""
基础工具模块，提供异常分类等通用能力。
"""
import threading


FATAL_EXCEPTIONS = (KeyboardInterrupt, SystemExit, SystemError)


def is_fatal_exception(exc: BaseException) -> bool:
    """判断异常是否为致命异常（不应被捕获，应直接向上抛出）。"""
    return isinstance(exc, FATAL_EXCEPTIONS)
