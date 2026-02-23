
import sys
import os
import unittest
import json
import time
import re

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "../services/angineer-core/src")))
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "../services/engtools/src")))

from engtools.BaseTool import ToolRegistry
from angineer_core.core.llm import LLMClient

"""
基础资源加载验证脚本 (Test 01)
目的：验证 Tool (工具) 的注册与加载情况，并进行 LLM 工具识别与调用测试。
"""

SAMPLE_QUERIES = [
    {"label": "执行资源加载验证", "query": "all"}
]

class TestResourceLoading(unittest.TestCase):
    def setUp(self):
        """初始化测试模式。"""
        self.mode = os.environ.get("TEST_LLM_QUERY", "all")

    def test_resources(self):
        """统一测试入口，根据指令分发任务"""
        print(f"\n[Test 01] 资源加载测试 (Mode: {self.mode})")
        
        results = {
            "mode": self.mode,
            "tools": [],
            "llm_tools": []
        }

        if self.mode == "check_tools" or self.mode == "all":
            results["tools"] = self._check_tools()
            
        if self.mode == "check_llm_tools" or self.mode == "all":
            results["llm_tools"] = self._check_llm_tools()

        # 输出 JSON 供前端解析
        print("\n__JSON_START__")
        print(json.dumps(results, ensure_ascii=False, indent=2))
        print("__JSON_END__")

    def _check_tools(self):
        """检查 ToolRegistry 中的核心工具注册情况。"""
        print("\n>>> 正在验证工具注册表 (ToolRegistry)...")
        tools = ToolRegistry.list_tools()
        tool_names = list(tools.keys())
        
        print(f"  -> [统计] 已注册工具数量: {len(tool_names)}")
        print(f"  -> [列表] {', '.join(tool_names)}")

        # 核心工具检查清单
        required_tools = ["calculator", "weather", "web_search", "sop_run", "file_reader", "table_lookup"]
        
        check_results = []
        missing_tools = []
        
        for name in required_tools:
            item = {"name": name, "type": "tool", "status": "ok", "desc": ""}
            if name not in tools:
                missing_tools.append(name)
                item["status"] = "missing"
                print(f"  -> [ERROR] 缺少核心工具: {name}")
            else:
                meta = tools[name]
                desc = meta.get("zh") or meta.get("en") or "No description"
                item["desc"] = desc
                print(f"  -> [OK] Found tool '{name}': {desc[:40]}...")
            check_results.append(item)
                
        self.assertEqual(len(missing_tools), 0, f"缺少核心工具: {missing_tools}")
        print("  -> [SUCCESS] 所有核心工具验证通过。")
        return check_results

    def _check_llm_tools(self):
        """使用 LLM 进行工具识别并调用目标工具进行验证。"""
        print("\n>>> 正在验证模型工具识别与调用 (LLM + ToolRegistry)...")
        tools = ToolRegistry.list_tools()
        tool_names = list(tools.keys())
        client = LLMClient()
        configs_to_test = client.configs
        test_file = os.path.abspath(__file__)
        prompt_tasks = [
            {
                "id": "calc_1",
                "request": "计算 12.5 + 3.5",
                "expected_tool": "calculator",
                "hint_inputs": {"expression": "12.5 + 3.5"}
            },
            {
                "id": "weather_1",
                "request": "查询上海天气",
                "expected_tool": "weather",
                "hint_inputs": {"city": "上海"}
            },
            {
                "id": "search_1",
                "request": "搜索 2025 AI 市场趋势",
                "expected_tool": "web_search",
                "hint_inputs": {"query": "2025 AI 市场趋势"}
            },
            {
                "id": "echo_1",
                "request": "原样返回 hello",
                "expected_tool": "echo",
                "hint_inputs": {"message": "hello"}
            },
            {
                "id": "read_1",
                "request": f"读取文件 {test_file}",
                "expected_tool": "file_reader",
                "hint_inputs": {"file_path": test_file}
            },
            {
                "id": "sop_1",
                "request": "执行子流程 code_review.md，问题: 请审查指定文件",
                "expected_tool": "sop_run",
                "hint_inputs": {"filename": "code_review.md", "question": "请审查指定文件"}
            },
            {
                "id": "table_1",
                "request": "从《海港水文规范》.md 查表：杂货船设计船型尺度，DWT=40000，目标列 满载吃水T(m)",
                "expected_tool": "table_lookup",
                "hint_inputs": {
                    "table_name": "杂货船设计船型尺度",
                    "query_conditions": "DWT=40000",
                    "target_column": "满载吃水T(m)",
                    "file_name": "《海港水文规范》.md"
                }
            },
            {
                "id": "knowledge_1",
                "request": "知识检索：查询 通航宽度，文件《海港水文规范》.md",
                "expected_tool": "knowledge_search",
                "hint_inputs": {"query": "通航宽度", "file_name": "《海港水文规范》.md"}
            },
            {
                "id": "email_1",
                "request": "发送邮件给 test@example.com，主题 进度，内容 OK",
                "expected_tool": "email_sender",
                "hint_inputs": {"recipient": "test@example.com", "subject": "进度", "body": "OK"}
            },
            {
                "id": "lint_1",
                "request": "检查代码是否有除零: def a():\n    return 1/0",
                "expected_tool": "code_linter",
                "hint_inputs": {"code": "def a():\n    return 1/0"}
            },
            {
                "id": "report_1",
                "request": "生成报告，标题 日报，数据 OK",
                "expected_tool": "report_generator",
                "hint_inputs": {"title": "日报", "data": "OK"}
            },
            {
                "id": "summary_1",
                "request": "摘要以下文字为 20 字以内：这是一段用于摘要的测试文本。",
                "expected_tool": "summarizer",
                "hint_inputs": {"text": "这是一段用于摘要的测试文本。", "max_words": 20}
            },
            {
                "id": "gis_1",
                "request": "计算疏浚工程量：深度12.5、宽150、长度1000",
                "expected_tool": "gis_section_volume_calc",
                "hint_inputs": {"design_depth": 12.5, "design_width": 150, "length": 1000}
            }
        ]
        usable_tasks = [t for t in prompt_tasks if t["expected_tool"] in tool_names]
        tasks_payload = [
            {"id": t["id"], "request": t["request"], "expected_tool": t["expected_tool"], "hint_inputs": t["hint_inputs"]}
            for t in usable_tasks
        ]
        tools_desc = ToolRegistry.list_tools()
        tools_str = "\n".join([f"- {name}: {desc}" for name, desc in tools_desc.items()])
        system_prompt = f"""
你是一个工具编排助手。你必须根据任务描述，选择最合适的工具并给出输入参数。
可用工具列表:
{tools_str}
请返回 JSON 数组，每一项包含:
{{"id": "...", "tool": "...", "inputs": {{...}}}}
仅返回 JSON，不要输出其它内容。
"""
        user_prompt = f"任务列表:\n{json.dumps(tasks_payload, ensure_ascii=False)}"
        model_results = []
        errors = []
        
        def parse_plan(raw_text: str):
            cleaned = raw_text.strip() if isinstance(raw_text, str) else ""
            if "```json" in cleaned:
                cleaned = cleaned.split("```json")[1].split("```")[0]
            elif "```" in cleaned:
                cleaned = cleaned.split("```")[1].split("```")[0]
            try:
                data = json.loads(cleaned)
                if isinstance(data, list):
                    return data, None
            except Exception:
                pass
            match = re.search(r"\[[\s\S]*\]", cleaned)
            if match:
                try:
                    data = json.loads(match.group(0))
                    if isinstance(data, list):
                        return data, None
                except Exception:
                    return None, "解析失败"
            return None, "解析失败"

        for config in configs_to_test:
            print(f"\n  -> [模型] {config['name']}")
            if not config.get("api_key") or not config.get("base_url") or not config.get("model"):
                model_results.append({
                    "model": config["name"],
                    "status": "skipped",
                    "reason": "配置未就绪",
                    "duration": None,
                    "tools": []
                })
                print("     配置未就绪，跳过")
                continue

            start = time.perf_counter()
            try:
                response = client.chat(
                    [{"role": "system", "content": system_prompt}, {"role": "user", "content": user_prompt}],
                    mode="instruct",
                    config_name=config["name"]
                )
                duration = time.perf_counter() - start
            except Exception as e:
                duration = time.perf_counter() - start
                model_results.append({
                    "model": config["name"],
                    "status": "fail",
                    "reason": str(e),
                    "duration": duration,
                    "tools": []
                })
                errors.append(f"{config['name']} | LLM调用失败: {str(e)}")
                print(f"     LLM 调用失败: {str(e)}")
                continue
            
            plan, parse_error = parse_plan(response)
            if parse_error:
                retry_start = time.perf_counter()
                try:
                    retry_response = client.chat(
                        [{"role": "system", "content": system_prompt}, {"role": "user", "content": user_prompt + "\n请严格只输出 JSON 数组，不要包含解释。"}],
                        mode="instruct",
                        config_name=config["name"]
                    )
                    duration += time.perf_counter() - retry_start
                    plan, parse_error = parse_plan(retry_response)
                except Exception as e:
                    parse_error = str(e)
            if parse_error:
                model_results.append({
                    "model": config["name"],
                    "status": "fail",
                    "reason": f"解析失败: {parse_error}",
                    "duration": duration,
                    "tools": []
                })
                errors.append(f"{config['name']} | 解析失败: {parse_error}")
                print(f"     解析失败: {parse_error}")
                continue

            tool_rows = []
            tool_errors = 0
            exec_start = time.perf_counter()
            for item in plan:
                tool_name = item.get("tool")
                inputs = item.get("inputs") or {}
                item_id = item.get("id")
                expected = next((t for t in tasks_payload if t["id"] == item_id), None)
                expected_tool = expected["expected_tool"] if expected else None
                match_ok = (tool_name == expected_tool) if expected_tool else True
                tool = ToolRegistry.get_tool(tool_name) if tool_name else None
                exec_ok = False
                output_preview = ""
                if tool and match_ok:
                    try:
                        result = tool.run(**inputs)
                        exec_ok = True
                        output_preview = str(result)[:120].replace("\n", " ")
                    except Exception as e:
                        output_preview = f"执行异常: {str(e)}"
                        exec_ok = False
                else:
                    output_preview = "工具缺失或匹配失败"
                status = "ok" if exec_ok and match_ok else "fail"
                if status != "ok":
                    tool_errors += 1
                tool_rows.append({
                    "id": item_id,
                    "expected_tool": expected_tool,
                    "tool": tool_name,
                    "status": status,
                    "output": output_preview
                })
            exec_duration = time.perf_counter() - exec_start

            model_status = "ok" if tool_errors == 0 else "fail"
            model_results.append({
                "model": config["name"],
                "status": model_status,
                "reason": "",
                "duration": duration,
                "exec_duration": exec_duration,
                "tools": tool_rows
            })
            print(f"     识别耗时: {duration:.2f}s | 执行耗时: {exec_duration:.2f}s | 状态: {model_status}")
            for row in tool_rows:
                print(f"       - {row['id']} | {row['expected_tool']} => {row['tool']} | {row['status']}")

        print("\n[模型工具调用汇总]")
        for item in model_results:
            dur_text = f"{item['duration']:.2f}s" if item.get("duration") is not None else "-"
            exec_text = f"{item.get('exec_duration', 0):.2f}s" if item.get("exec_duration") is not None else "-"
            print(f" - {item['model']} | {item['status']} | 识别: {dur_text} | 执行: {exec_text}")
            
        ok_count = len([m for m in model_results if m.get("status") == "ok"])
        if ok_count == 0 and errors:
            self.fail("模型工具调用失败:\n" + "\n".join(errors))

        return model_results

if __name__ == "__main__":
    unittest.main()


if __name__ == "__main__":
    unittest.main()




'''结果显示Qwen\Deepseek\MiniMax能够准确调用工具，并且返回有效的JSON格式
[模型工具调用汇总]
 - Qwen3VL-30B-A3B (Private) | ok   | 识别: 31.06s  | 执行: 1.42s
 - Qwen2.5-7B (SiliconFlow)  | ok   | 识别: 10.92s  | 执行: 1.47s
 - Qwen3-4B (Public)         | ok   | 识别: 5.69s   | 执行: 1.37s
 - DeepSeek_V3.2             | ok   | 识别: 10.79s  | 执行: 1.46s
 - GLM-4.7-Flash             | fail | 识别: 35.06s  | 执行: -
 - Nemotron30BA3B (NVIDIA)   | fail | 识别: 17.86s  | 执行: -
 - Kimi/Moonshot (NVIDIA源)   | ok   | 识别: 57.67s | 执行: 1.53s
 - MiniMax (NVIDIA源)         | ok   | 识别: 27.01s | 执行: 1.40s
'''
