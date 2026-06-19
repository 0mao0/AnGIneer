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


if __name__ == "__main__":
    unittest.main()
