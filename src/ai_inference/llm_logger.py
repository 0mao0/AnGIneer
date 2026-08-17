"""AI Inference LLM 日志模块。"""
import logging
import sys
import os


def get_logger(name: str, level: str = None) -> logging.Logger:
    """获取配置好的 Logger 实例。"""
    logger = logging.getLogger(name)
    if logger.handlers:
        return logger
    log_level = level or os.getenv("ANGINEER_LOG_LEVEL", "INFO").upper()
    logger.setLevel(getattr(logging, log_level, logging.INFO))
    handler = logging.StreamHandler(sys.stdout)
    handler.setLevel(logging.DEBUG)
    formatter = logging.Formatter(
        fmt="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    handler.setFormatter(formatter)
    logger.addHandler(handler)
    logger.propagate = False
    return logger
