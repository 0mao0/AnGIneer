
import sys
import os
import argparse
import unittest

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from backend.src.core.llm import LLMClient

"""
LLM 对话能力测试脚本 (Test 00)
支持测试所有在 LLMClient 中配置的模型，包括 NVIDIA 系列和新增的智谱 AI (GLM-4.7-Flash)。
"""

# 定义模块级常量供外部调用
SAMPLE_QUERIES = [
    {"label": "自我介绍", "query": "你好，请简要介绍一下你自己。"},
    {"label": "GIS 分析", "query": "你能帮我分析一下这张 GIS 表格的数据吗？"},
    {"label": "解释术语", "query": "解释一下什么是数字孪生。"},
    {"label": "执行指令", "query": "请严格按照步骤执行：1. 查找数据 2. 计算总和。"},
    {"label": "技术咨询", "query": "如果我想创建一个 3D 地图，需要哪些核心技术？"}
]

class TestLLMChat(unittest.TestCase):
    def test_llm_chat(self):
        print("\n[测试 00] LLM 对话能力测试")
        target_config = os.environ.get("TEST_LLM_CONFIG")
        custom_query = os.environ.get("TEST_LLM_QUERY")
        target_mode = os.environ.get("TEST_LLM_MODE")

        if not target_config:
            parser = argparse.ArgumentParser()
            parser.add_argument("--config", type=str)
            parser.add_argument("--mode", type=str)
            parser.add_argument("--query", type=str)
            args, _ = parser.parse_known_args()
            target_config = args.config
            target_mode = args.mode or target_mode
            custom_query = args.query or custom_query

        client = LLMClient()
        configs_to_test = client.configs
        if target_config:
            configs_to_test = [c for c in configs_to_test if c["name"] == target_config]

        print("  -> 步骤 1: 解析测试配置")
        if not configs_to_test:
            print("     未找到可用配置")
            print("     响应内容预览: 未找到配置...")
            return

        # 决定要运行的查询列表
        queries_to_run = []
        if custom_query:
            queries_to_run = [custom_query]
        else:
            print(f"  -> 未指定查询，将运行 {len(SAMPLE_QUERIES)} 个默认样本...")
            queries_to_run = [item["query"] for item in SAMPLE_QUERIES]

        for q_idx, query in enumerate(queries_to_run):
            print(f"\n  [测试样本 {q_idx+1}/{len(queries_to_run)}] 用户输入: '{query}'")
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
                    print(f"     模式: {target_mode or '默认'}")
                    print("     [CALL] src/core/llm.py -> LLMClient.chat()")
                    response = client.chat(messages, mode=target_mode)
                    self.assertTrue(isinstance(response, str))
                    self.assertGreater(len(response), 0)
                    preview = response[:150].replace("\n", " ")
                    print(f"     响应内容预览: {preview}...")
                finally:
                    client.configs = original_configs

        print("\n[结果] LLM 对话测试结束")

if __name__ == "__main__":
    unittest.main()
