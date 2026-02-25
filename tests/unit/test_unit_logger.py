"""
单元测试：日志系统模块。
"""
import unittest
import logging
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../../services/angineer-core/src")))

from angineer_core.infra.logger import (
    get_logger,
    get_default_logger,
    set_default_logger,
    log_execution,
    AnGIneerFormatter,
    LoggerAdapter,
)


class TestLogger(unittest.TestCase):
    """测试日志系统功能。"""
    
    def setUp(self):
        """每个测试前的准备工作。"""
        self.logger = get_logger("test_logger")
    
    def test_get_logger_returns_logger(self):
        """测试 get_logger 返回有效的 Logger 实例。"""
        self.assertIsInstance(self.logger, logging.Logger)
        self.assertEqual(self.logger.name, "test_logger")
    
    def test_get_logger_singleton(self):
        """测试相同名称返回同一个 Logger 实例。"""
        logger1 = get_logger("same_name")
        logger2 = get_logger("same_name")
        self.assertIs(logger1, logger2)
    
    def test_logger_has_handler(self):
        """测试 Logger 至少有一个 Handler。"""
        self.assertTrue(len(self.logger.handlers) > 0)
    
    def test_logger_level_from_env(self):
        """测试日志级别可以从环境变量读取。"""
        original = os.environ.get("ANGINEER_LOG_LEVEL")
        try:
            os.environ["ANGINEER_LOG_LEVEL"] = "DEBUG"
            logger = get_logger("test_env_level")
            self.assertEqual(logger.level, logging.DEBUG)
        finally:
            if original:
                os.environ["ANGINEER_LOG_LEVEL"] = original
            else:
                os.environ.pop("ANGINEER_LOG_LEVEL", None)
    
    def test_default_logger(self):
        """测试全局默认 Logger。"""
        logger1 = get_default_logger()
        logger2 = get_default_logger()
        self.assertIs(logger1, logger2)
    
    def test_set_default_logger(self):
        """测试设置全局默认 Logger。"""
        custom_logger = get_logger("custom_default")
        set_default_logger(custom_logger)
        self.assertIs(get_default_logger(), custom_logger)
        
        from angineer_core.infra.logger import _default_logger
        self.assertIs(_default_logger, custom_logger)


class TestLogExecutionDecorator(unittest.TestCase):
    """测试 log_execution 装饰器。"""
    
    def test_decorator_returns_same_function(self):
        """测试装饰器返回可调用对象。"""
        @log_execution()
        def sample_func():
            return 42
        
        self.assertTrue(callable(sample_func))
    
    def test_decorator_preserves_result(self):
        """测试装饰器不改变函数返回值。"""
        @log_execution()
        def add(a, b):
            return a + b
        
        result = add(3, 5)
        self.assertEqual(result, 8)
    
    def test_decorator_reraises_exception(self):
        """测试装饰器重新抛出异常。"""
        @log_execution()
        def raise_error():
            raise ValueError("test error")
        
        with self.assertRaises(ValueError):
            raise_error()


class TestAnGIneerFormatter(unittest.TestCase):
    """测试自定义日志格式化器。"""
    
    def test_format_creates_string(self):
        """测试格式化生成字符串。"""
        formatter = AnGIneerFormatter(
            fmt='%(levelname)s | %(message)s',
            use_color=False
        )
        record = logging.LogRecord(
            name="test",
            level=logging.INFO,
            pathname="test.py",
            lineno=1,
            msg="test message",
            args=(),
            exc_info=None
        )
        result = formatter.format(record)
        self.assertIn("test message", result)
        self.assertIn("INFO", result)
    
    def test_format_with_color(self):
        """测试带颜色的格式化。"""
        formatter = AnGIneerFormatter(
            fmt='%(levelname)s | %(message)s',
            use_color=True
        )
        record = logging.LogRecord(
            name="test",
            level=logging.INFO,
            pathname="test.py",
            lineno=1,
            msg="test message",
            args=(),
            exc_info=None
        )
        result = formatter.format(record)
        self.assertIn("test message", result)


class TestLoggerAdapter(unittest.TestCase):
    """测试日志适配器。"""
    
    def test_adapter_adds_extra_context(self):
        """测试适配器添加额外上下文。"""
        logger = get_logger("adapter_test")
        adapter = LoggerAdapter(logger, {"request_id": "12345"})
        
        self.assertEqual(adapter.extra["request_id"], "12345")


if __name__ == "__main__":
    unittest.main()
