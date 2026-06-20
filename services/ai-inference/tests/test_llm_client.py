"""LLM 客户端配置解析的回归测试。"""

import os
import sys
import unittest
from pathlib import Path
from unittest.mock import patch


AI_INFERENCE_SRC = Path(__file__).resolve().parents[1] / "src"
if str(AI_INFERENCE_SRC) not in sys.path:
    sys.path.insert(0, str(AI_INFERENCE_SRC))

from ai_inference.llm_client import get_llm_client, reset_llm_client


class LlmClientConfigResolutionTests(unittest.TestCase):
    """验证缺省 config_name 时返回可操作的错误信息。"""

    def test_missing_default_config_raises_actionable_error(self) -> None:
        """缺省配置缺失时，错误消息应提示可用配置。"""
        with patch.dict(os.environ, {}, clear=True):
            reset_llm_client()
            try:
                with self.assertRaisesRegex(ValueError, "可用配置"):
                    get_llm_client(config_name="")
            finally:
                reset_llm_client()

    def test_default_model_alias_resolves_to_available_config(self) -> None:
        """默认模型名指向底层模型别名时，应回落到已注册配置名。"""
        llm_configs = (
            '[{"name":"Qwen3.6-A3B","model":"Qwen3.6-35B-A3B-FP8",'
            '"api_key":"demo","base_url":"https://example.com","priority":10}]'
        )
        with patch.dict(
            os.environ,
            {
                "ANGINEER_DEFAULT_MODEL": "Qwen3.6-35B-A3B",
                "LLM_CONFIGS": llm_configs,
            },
            clear=True,
        ):
            reset_llm_client()
            try:
                client = get_llm_client()
            finally:
                reset_llm_client()

        self.assertEqual(client._config.default_model, "Qwen3.6-35B-A3B")
        self.assertEqual(client._get_model_configs("Qwen3.6-A3B")[0].name, "Qwen3.6-A3B")


if __name__ == "__main__":
    unittest.main()
