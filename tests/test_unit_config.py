"""
单元测试：配置管理模块。
"""
import unittest
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../services/angineer-core/src")))

from angineer_core.config import (
    AnGIneerConfig,
    LLMClientConfig,
    LLMModelConfig,
    MemoryConfig,
    DispatcherConfig,
    LoggingConfig,
    RetryConfig,
    CircuitBreakerConfig,
    TimeoutConfig,
    get_config,
    set_config,
    reset_config,
    load_config_from_env,
)


class TestConfigModels(unittest.TestCase):
    """测试配置模型。"""
    
    def test_llm_model_config(self):
        """测试 LLM 模型配置。"""
        config = LLMModelConfig(
            name="Test Model",
            api_key="test_key",
            base_url="https://api.test.com",
            model="test-model",
            priority=5
        )
        self.assertEqual(config.name, "Test Model")
        self.assertEqual(config.priority, 5)
        self.assertTrue(config.enabled)
    
    def test_retry_config(self):
        """测试重试配置。"""
        config = RetryConfig(
            max_retries=5,
            initial_delay=2.0,
            max_delay=60.0,
            exponential_base=3.0
        )
        self.assertEqual(config.max_retries, 5)
        self.assertEqual(config.initial_delay, 2.0)
    
    def test_circuit_breaker_config(self):
        """测试熔断器配置。"""
        config = CircuitBreakerConfig(
            failure_threshold=10,
            recovery_timeout=120.0
        )
        self.assertEqual(config.failure_threshold, 10)
        self.assertEqual(config.recovery_timeout, 120.0)
    
    def test_timeout_config(self):
        """测试超时配置。"""
        config = TimeoutConfig(
            connect=5.0,
            read=30.0,
            total=60.0
        )
        self.assertEqual(config.connect, 5.0)
        self.assertEqual(config.read, 30.0)
        self.assertEqual(config.total, 60.0)
    
    def test_memory_config(self):
        """测试内存配置。"""
        config = MemoryConfig(
            strict_mode=True,
            none_replacement="<缺失>",
            max_context_length=5000
        )
        self.assertTrue(config.strict_mode)
        self.assertEqual(config.none_replacement, "<缺失>")
    
    def test_dispatcher_config(self):
        """测试调度器配置。"""
        config = DispatcherConfig(
            mode="thinking",
            enable_summary=False
        )
        self.assertEqual(config.mode, "thinking")
        self.assertFalse(config.enable_summary)
    
    def test_logging_config(self):
        """测试日志配置。"""
        config = LoggingConfig(
            level="DEBUG",
            log_file="/var/log/angineer.log"
        )
        self.assertEqual(config.level, "DEBUG")
        self.assertEqual(config.log_file, "/var/log/angineer.log")


class TestLLMClientConfig(unittest.TestCase):
    """测试 LLM 客户端配置。"""
    
    def test_default_values(self):
        """测试默认值。"""
        config = LLMClientConfig()
        self.assertEqual(config.models, [])
        self.assertEqual(config.temperature, 0.1)
        self.assertEqual(config.max_tokens, 16384)
    
    def test_with_models(self):
        """测试带模型列表的配置。"""
        models = [
            LLMModelConfig(name="Model1", priority=1),
            LLMModelConfig(name="Model2", priority=2)
        ]
        config = LLMClientConfig(models=models)
        self.assertEqual(len(config.models), 2)


class TestAnGIneerConfig(unittest.TestCase):
    """测试全局配置。"""
    
    def test_default_config(self):
        """测试默认配置。"""
        config = AnGIneerConfig()
        self.assertIsInstance(config.llm, LLMClientConfig)
        self.assertIsInstance(config.memory, MemoryConfig)
        self.assertIsInstance(config.dispatcher, DispatcherConfig)
        self.assertIsInstance(config.logging, LoggingConfig)


class TestConfigSingleton(unittest.TestCase):
    """测试配置单例模式。"""
    
    def setUp(self):
        """每个测试前重置配置。"""
        reset_config()
    
    def tearDown(self):
        """每个测试后重置配置。"""
        reset_config()
    
    def test_get_config_returns_singleton(self):
        """测试 get_config 返回单例。"""
        config1 = get_config()
        config2 = get_config()
        self.assertIs(config1, config2)
    
    def test_set_config(self):
        """测试设置配置。"""
        custom_config = AnGIneerConfig(
            memory=MemoryConfig(strict_mode=True)
        )
        set_config(custom_config)
        
        config = get_config()
        self.assertIs(config, custom_config)
        self.assertTrue(config.memory.strict_mode)
    
    def test_reset_config(self):
        """测试重置配置。"""
        config1 = get_config()
        reset_config()
        config2 = get_config()
        self.assertIsNot(config1, config2)


class TestEnvLoading(unittest.TestCase):
    """测试环境变量加载。"""
    
    def test_load_config_from_env(self):
        """测试从环境变量加载配置。"""
        original_level = os.environ.get("ANGINEER_LOG_LEVEL")
        original_strict = os.environ.get("ANGINEER_MEMORY_STRICT_MODE")
        
        try:
            os.environ["ANGINEER_LOG_LEVEL"] = "DEBUG"
            os.environ["ANGINEER_MEMORY_STRICT_MODE"] = "true"
            
            config = load_config_from_env()
            self.assertEqual(config.logging.level, "DEBUG")
            self.assertTrue(config.memory.strict_mode)
            
        finally:
            if original_level:
                os.environ["ANGINEER_LOG_LEVEL"] = original_level
            else:
                os.environ.pop("ANGINEER_LOG_LEVEL", None)
            
            if original_strict:
                os.environ["ANGINEER_MEMORY_STRICT_MODE"] = original_strict
            else:
                os.environ.pop("ANGINEER_MEMORY_STRICT_MODE", None)


class TestConfigValidation(unittest.TestCase):
    """测试配置校验。"""
    
    def test_retry_config_validation(self):
        """测试重试配置校验。"""
        with self.assertRaises(Exception):
            RetryConfig(max_retries=-1)
        
        with self.assertRaises(Exception):
            RetryConfig(initial_delay=-1.0)
    
    def test_timeout_config_validation(self):
        """测试超时配置校验。"""
        with self.assertRaises(Exception):
            TimeoutConfig(connect=0)
        
        with self.assertRaises(Exception):
            TimeoutConfig(read=-1.0)
    
    def test_memory_config_validation(self):
        """测试内存配置校验。"""
        with self.assertRaises(Exception):
            MemoryConfig(max_context_length=100)


if __name__ == "__main__":
    unittest.main()
