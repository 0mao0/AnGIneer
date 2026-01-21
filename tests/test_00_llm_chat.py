
import sys
import os
import argparse
import unittest

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from backend.src.core.llm import LLMClient

class TestLLMChat(unittest.TestCase):
    def test_llm_chat(self):
        print("\n[测试 00] LLM 对话能力测试")
        target_config = os.environ.get("TEST_LLM_CONFIG")
        custom_query = os.environ.get("TEST_LLM_QUERY")

        if not target_config:
            parser = argparse.ArgumentParser()
            parser.add_argument("--config", type=str)
            args, _ = parser.parse_known_args()
            target_config = args.config

        client = LLMClient()
        configs_to_test = client.configs
        if target_config:
            configs_to_test = [c for c in configs_to_test if c["name"] == target_config]

        print("  -> 步骤 1: 解析测试配置")
        if not configs_to_test:
            print("     未找到可用配置")
            print("     响应内容预览: 未找到配置...")
            return

        query = custom_query or "你好，请自我介绍一下，并确认你现在的模型版本。"
        messages = [{"role": "user", "content": query}]

        for config in configs_to_test:
            print(f"  -> 步骤 2: 校验配置 {config['name']}")
            if not config.get("api_key") or not config.get("base_url") or not config.get("model"):
                print(f"     配置未就绪: {config['name']}")
                print("     响应内容预览: 配置未就绪...")
                continue

            original_configs = client.configs
            try:
                client.configs = [config]
                print("  -> 步骤 3: 发送对话请求")
                print("     [CALL] src/core/llm.py -> LLMClient.chat()")
                response = client.chat(messages)
                self.assertTrue(isinstance(response, str))
                self.assertGreater(len(response), 0)
                preview = response[:150].replace("\n", " ")
                print(f"     响应内容预览: {preview}...")
            finally:
                client.configs = original_configs

        print("[结果] LLM 对话测试结束")

if __name__ == "__main__":
    unittest.main()
