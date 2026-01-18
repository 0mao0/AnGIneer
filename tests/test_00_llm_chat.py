
import sys
import os
import argparse
import unittest

# 将项目根目录添加到路径中
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from backend.src.core.llm import LLMClient

class TestLLMChat(unittest.TestCase):
    """测试 LLM 的基础对话能力。"""

    def test_specific_config(self):
        # 优先从环境变量获取参数，方便 Web 端调用
        target_config = os.environ.get("TEST_LLM_CONFIG")
        custom_query = os.environ.get("TEST_LLM_QUERY")
        
        # 兼容命令行参数
        if not target_config:
            parser = argparse.ArgumentParser()
            parser.add_argument("--config", type=str, help="LLM 配置名称")
            args, unknown = parser.parse_known_args()
            target_config = args.config
        
        client = LLMClient()
        
        # 如果指定了配置，则只测试该配置
        configs_to_test = client.configs
        if target_config:
            configs_to_test = [c for c in client.configs if c["name"] == target_config]
            if not configs_to_test:
                print(f"错误: 未找到配置 '{target_config}'")
                return

        for config in configs_to_test:
            if not config["api_key"]:
                print(f"\n[跳过] {config['name']} (未配置 API Key)")
                continue

            print(f"\n[测试 00] 正在启动 LLM 对话能力验证: {config['name']}")
            print(f"  -> 步骤 1: 检查配置详情")
            print(f"     模型名称: {config['model']}")
            print(f"     基础 URL: {config['base_url']}")
            
            query = custom_query if custom_query else "你好，请自我介绍一下，并确认你现在的模型版本。"
            messages = [{"role": "user", "content": query}]
            print(f"  -> 步骤 2: 发送测试消息: \"{messages[0]['content']}\"")
            
            try:
                # 暂时修改 client.configs 使其只包含当前要测试的配置
                original_configs = client.configs
                client.configs = [config]
                
                print(f"  -> 步骤 3: 正在连接 API 端点...")
                print(f"     [CALL] src/core/llm.py -> LLMClient.chat()")
                response = client.chat(messages)
                
                print(f"  -> 步骤 4: 验证响应内容...")
                self.assertIsNotNone(response)
                self.assertGreater(len(response), 0)
                
                print(f"     [OK] 响应成功 (长度: {len(response)} 字符)")
                print(f"     [OK] 响应内容预览: {response[:150].replace('\n', ' ')}...")
                
                client.configs = original_configs
                print(f"\n[结果] 模型 {config['name']} 验证通过。")
            except Exception as e:
                print(f"     [FAILED] {config['name']} 调用出错: {str(e)}")
                self.fail(f"模型 {config['name']} 测试失败")

if __name__ == "__main__":
    unittest.main(argv=['first-arg-is-ignored'], exit=False)
