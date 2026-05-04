"""
结构化日志系统模块，提供统一的日志配置与管理。
"""
import logging
import sys
import os
from datetime import datetime
from typing import Optional
from functools import wraps
from dotenv import load_dotenv

load_dotenv()


class AnGIneerFormatter(logging.Formatter):
    """
    自定义日志格式化器，支持彩色输出和结构化格式。
    """
    
    COLORS = {
        'DEBUG': '\033[36m',     # Cyan
        'INFO': '\033[32m',      # Green
        'WARNING': '\033[33m',   # Yellow
        'ERROR': '\033[31m',     # Red
        'CRITICAL': '\033[35m',  # Magenta
        'RESET': '\033[0m'       # Reset
    }
    
    def __init__(self, use_color: bool = True, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.use_color = use_color and self._supports_color()
    
    @staticmethod
    def _supports_color() -> bool:
        """检测终端是否支持彩色输出。"""
        if sys.platform == 'win32':
            return os.environ.get('ANSICON') is not None or 'WT_SESSION' in os.environ
        return hasattr(sys.stdout, 'isatty') and sys.stdout.isatty()
    
    def format(self, record: logging.LogRecord) -> str:
        """格式化日志记录。"""
        if self.use_color:
            color = self.COLORS.get(record.levelname, self.COLORS['RESET'])
            reset = self.COLORS['RESET']
            record.levelname = f"{color}{record.levelname}{reset}"
        
        return super().format(record)


def get_logger(
    name: str,
    level: Optional[str] = None,
    log_file: Optional[str] = None
) -> logging.Logger:
    """
    获取配置好的 Logger 实例。
    
    Args:
        name: 日志器名称，通常使用 __name__
        level: 日志级别 (DEBUG, INFO, WARNING, ERROR, CRITICAL)
        log_file: 可选的日志文件路径
    
    Returns:
        配置好的 Logger 实例
    """
    logger = logging.getLogger(name)
    
    if logger.handlers:
        return logger
    
    log_level = level or os.getenv('ANGINEER_LOG_LEVEL', 'INFO').upper()
    logger.setLevel(getattr(logging, log_level, logging.INFO))
    
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(logging.DEBUG)
    
    formatter = AnGIneerFormatter(
        fmt='%(asctime)s | %(levelname)-8s | %(name)s | %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )
    console_handler.setFormatter(formatter)
    logger.addHandler(console_handler)
    
    if log_file:
        file_handler = logging.FileHandler(log_file, encoding='utf-8')
        file_handler.setLevel(logging.DEBUG)
        file_formatter = logging.Formatter(
            fmt='%(asctime)s | %(levelname)-8s | %(name)s | %(message)s',
            datefmt='%Y-%m-%d %H:%M:%S'
        )
        file_handler.setFormatter(file_formatter)
        logger.addHandler(file_handler)
    
    logger.propagate = False
    
    return logger


def log_execution(logger: Optional[logging.Logger] = None, level: int = logging.DEBUG):
    """
    函数执行日志装饰器，记录函数入口、出口和执行时间。
    
    Args:
        logger: 可选的 Logger 实例，默认使用被装饰函数所在模块的 logger
        level: 日志级别
    
    Example:
        @log_execution()
        def my_function(arg1, arg2):
            return arg1 + arg2
    """
    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            nonlocal logger
            if logger is None:
                logger = get_logger(func.__module__)
            
            func_name = func.__qualname__
            logger.log(level, f"[{func_name}] 开始执行")
            
            start_time = datetime.now()
            try:
                result = func(*args, **kwargs)
                duration = (datetime.now() - start_time).total_seconds()
                logger.log(level, f"[{func_name}] 执行成功，耗时: {duration:.3f}s")
                return result
            except Exception as e:
                duration = (datetime.now() - start_time).total_seconds()
                logger.error(f"[{func_name}] 执行失败，耗时: {duration:.3f}s，错误: {e}")
                raise
        
        return wrapper
    return decorator


class LoggerAdapter(logging.LoggerAdapter):
    """
    日志适配器，支持添加额外的上下文信息。
    """
    
    def process(self, msg, kwargs):
        if self.extra:
            extra_str = ' | '.join(f"{k}={v}" for k, v in self.extra.items())
            return f"[{extra_str}] {msg}", kwargs
        return msg, kwargs


_default_logger: Optional[logging.Logger] = None


def get_default_logger() -> logging.Logger:
    """
    获取全局默认 Logger 实例。
    """
    global _default_logger
    if _default_logger is None:
        _default_logger = get_logger('angineer')
    return _default_logger


def set_default_logger(logger: logging.Logger) -> None:
    """
    设置全局默认 Logger 实例。
    """
    global _default_logger
    _default_logger = logger
