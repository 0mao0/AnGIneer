
import sys
import os
import argparse
import unittest
import time

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "../services/angineer-core/src")))

from angineer_core.core.llm import LLMClient

"""
LLM 对话能力测试脚本 (Test 00)
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

        errors = []
        results = []

        for q_idx, query in enumerate(queries_to_run):
            print(f"\n  [测试样本 {q_idx+1}/{len(queries_to_run)}] 用户输入: '{query}'")
            messages = [{"role": "user", "content": query}]
            per_query_rows = []

            for config in configs_to_test:
                print(f"  -> 步骤 2: 校验配置 {config['name']}")
                if not config.get("api_key") or not config.get("base_url") or not config.get("model"):
                    print(f"     配置未就绪: {config['name']}")
                    print("     响应内容预览: 配置未就绪...")
                    errors.append({"query": query, "config": config["name"], "error": "配置未就绪"})
                    per_query_rows.append({"config": config["name"], "duration": None, "ok": False, "preview": "配置未就绪"})
                    continue

                print("  -> 步骤 3: 发送对话请求")
                print(f"     模式: {target_mode or '默认'}")
                print("     [CALL] src/core/llm.py -> LLMClient.chat()")
                start = time.perf_counter()
                try:
                    response = client.chat(messages, mode=target_mode, config_name=config["name"])
                    duration = time.perf_counter() - start
                    ok = isinstance(response, str) and len(response) > 0
                    if not ok:
                        errors.append({"query": query, "config": config["name"], "error": "空响应"})
                    preview = (response or "").replace("\n", " ")[:150]
                    print(f"     响应内容预览: {preview}...")
                except Exception as e:
                    duration = time.perf_counter() - start
                    ok = False
                    preview = f"异常: {str(e)}"
                    print(f"     响应内容预览: {preview}")
                    errors.append({"query": query, "config": config["name"], "error": str(e)})

                per_query_rows.append({
                    "config": config["name"],
                    "duration": duration,
                    "ok": ok,
                    "preview": preview
                })
                results.append({
                    "query": query,
                    "config": config["name"],
                    "duration": duration,
                    "ok": ok,
                    "preview": preview
                })

            print("\n  [本题汇总]")
            for row in per_query_rows:
                dur_text = f"{row['duration']:.2f}s" if row["duration"] is not None else "-"
                status = "OK" if row["ok"] else "FAIL"
                print(f"   - {row['config']} | {dur_text} | {status} | {row['preview']}")

        print("\n[全部问题汇总]")
        for item in results:
            dur_text = f"{item['duration']:.2f}s" if item["duration"] is not None else "-"
            status = "OK" if item["ok"] else "FAIL"
            print(f" - {item['config']} | {dur_text} | {status} | {item['query']}")

        if errors:
            error_messages = [f"{e['config']} | {e['query']} | {e['error']}" for e in errors]
            self.fail("LLM 测试失败:\n" + "\n".join(error_messages))

        print("\n[结果] LLM 对话测试结束")

if __name__ == "__main__":
    unittest.main()



''' Qwen3-4B是最快的、Qwen2.5-7B也快但不太稳定。
[全部测试汇总]
 - Qwen3VL-30B-A3B (Private) | 6.73s | OK | 你好，请简要介绍一下你自己。
 - Qwen2.5-7B (SiliconFlow) | 1.36s | OK | 你好，请简要介绍一下你自己。 
 - Qwen3-4B (Public) | 1.24s | OK | 你好，请简要介绍一下你自己。        
 - DeepSeek_V3.2 | 5.60s | OK | 你好，请简要介绍一下你自己。
 - GLM-4.7-Flash | 10.15s | OK | 你好，请简要介绍一下你自己。
 - Nemotron30BA3B (NVIDIA) | 1.94s | OK | 你好，请简要介绍一下你自己。  
 - Kimi/Moonshot (NVIDIA源) | 8.63s | OK | 你好，请简要介绍一下你自己。 
 - MiniMax (NVIDIA源) | 3.23s | OK | 你好，请简要介绍一下你自己。       
 - Qwen3VL-30B-A3B (Private) | 13.05s | OK | 你能帮我分析一下这张 GIS 表格的数据吗？
 - Qwen2.5-7B (SiliconFlow) | 2.25s | OK | 你能帮我分析一下这张 GIS 表格的数据吗？
 - Qwen3-4B (Public) | 4.47s | OK | 你能帮我分析一下这张 GIS 表格的数据 吗？
 - DeepSeek_V3.2 | 4.76s | OK | 你能帮我分析一下这张 GIS 表格的数据吗？ 
 - GLM-4.7-Flash | 23.14s | OK | 你能帮我分析一下这张 GIS 表格的数据吗？
 - Nemotron30BA3B (NVIDIA) | 3.36s | OK | 你能帮我分析一下这张 GIS 表格 的数据吗？
 - Kimi/Moonshot (NVIDIA源) | 9.52s | OK | 你能帮我分析一下这张 GIS 表格的数据吗？
 - MiniMax (NVIDIA源) | 9.40s | OK | 你能帮我分析一下这张 GIS 表格的数据吗？
 - Qwen3VL-30B-A3B (Private) | 37.58s | OK | 解释一下什么是数字孪生。   
 - Qwen2.5-7B (SiliconFlow) | 2.09s | OK | 解释一下什么是数字孪生。     
 - Qwen3-4B (Public) | 7.05s | OK | 解释一下什么是数字孪生。
 - DeepSeek_V3.2 | 14.02s | OK | 解释一下什么是数字孪生。
 - GLM-4.7-Flash | 2.19s | FAIL | 解释一下什么是数字孪生。
 - Nemotron30BA3B (NVIDIA) | 8.10s | OK | 解释一下什么是数字孪生。      
 - Kimi/Moonshot (NVIDIA源) | 14.48s | OK | 解释一下什么是数字孪生。    
 - MiniMax (NVIDIA源) | 21.59s | OK | 解释一下什么是数字孪生。
 - Qwen3VL-30B-A3B (Private) | 3.33s | OK | 请严格按照步骤执行：1. 查找 数据 2. 计算总和。
 - Qwen2.5-7B (SiliconFlow) | 13.65s | OK | 请严格按照步骤执行：1. 查找 数据 2. 计算总和。
 - Qwen3-4B (Public) | 2.00s | OK | 请严格按照步骤执行：1. 查找数据 2.  计算总和。
 - DeepSeek_V3.2 | 3.92s | OK | 请严格按照步骤执行：1. 查找数据 2. 计算 总和。
 - GLM-4.7-Flash | 21.88s | FAIL | 请严格按照步骤执行：1. 查找数据 2. 计算总和。
 - Nemotron30BA3B (NVIDIA) | 4.42s | OK | 请严格按照步骤执行：1. 查找数 据 2. 计算总和。
 - Kimi/Moonshot (NVIDIA源) | 9.90s | OK | 请严格按照步骤执行：1. 查找数据 2. 计算总和。
 - MiniMax (NVIDIA源) | 21.70s | OK | 请严格按照步骤执行：1. 查找数据 2. 计算总和。
 - Qwen3VL-30B-A3B (Private) | 62.56s | OK | 如果我想创建一个 3D 地图， 需要哪些核心技术？
 - Qwen2.5-7B (SiliconFlow) | 11.74s | OK | 如果我想创建一个 3D 地图，需要哪些核心技术？
 - Qwen3-4B (Public) | 8.99s | OK | 如果我想创建一个 3D 地图，需要哪些核心技术？
 - DeepSeek_V3.2 | 20.84s | OK | 如果我想创建一个 3D 地图，需要哪些核心 技术？
 - GLM-4.7-Flash | 15.12s | FAIL | 如果我想创建一个 3D 地图，需要哪些核 心技术？
 - Nemotron30BA3B (NVIDIA) | 8.62s | OK | 如果我想创建一个 3D 地图，需要哪些核心技术？
 - Kimi/Moonshot (NVIDIA源) | 32.76s | OK | 如果我想创建一个 3D 地图，需要哪些核心技术？
 - MiniMax (NVIDIA源) | 29.20s | OK | 如果我想创建一个 3D 地图，需要哪些核心技术？

失败如下（因为限流）
GLM-4.7-Flash | 解释一下什么是数字孪生。 | Error code: 429 - {'error': {'code': '1302', 'message': '您的账户已达到速率限制，请您控制请求频率'}} 
GLM-4.7-Flash | 请严格按照步骤执行：1. 查找数据 2. 计算总和。 | 空响应  
GLM-4.7-Flash | 如果我想创建一个 3D 地图，需要哪些核心技术？ | 空响应
'''
