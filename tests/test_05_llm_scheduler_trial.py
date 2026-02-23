import os
import sys
import json
import re
import time
from typing import Dict, Any, List

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "../backend")))

from src.tools import ToolRegistry
from src.core.llm import LLMClient

# 颜色定义
GRAY = "\033[90m"
YELLOW = "\033[33m"
GREEN = "\033[32m"
RED = "\033[31m"
RESET = "\033[0m"

SOP_JSON_PATH = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "backend", "sop_json", "航道通航底高程.json"))

def print_colored(title: str, content: Any, color: str) -> None:
    text = json.dumps(content, ensure_ascii=False, indent=2) if isinstance(content, (dict, list)) else str(content)
    print(f"{color}[{title}]{RESET}")
    print(f"{color}{text}{RESET}")

def print_blackboard(values: Dict[str, Any], updates: Dict[str, Any]) -> None:
    print(f"{GREEN}[更新后的 blackboard]{RESET}")
    # 排序 key，把 updates 放前面
    all_keys = sorted(values.keys())
    updated_keys = sorted(updates.keys())
    other_keys = [k for k in all_keys if k not in updates]
    
    for k in updated_keys:
        val = values.get(k)
        print(f"{RED}{k}: {val} (Updated){RESET}")
    for k in other_keys:
        val = values.get(k)
        print(f"{GREEN}{k}: {val}{RESET}")

class SOPAgent:
    def __init__(self, sop_path: str):
        with open(sop_path, "r", encoding="utf-8") as f:
            self.sop_data = json.load(f)
        
        # 初始化 Blackboard
        base_context = {
            "船型": "油船",
            "吨级": 100000,
            "航速": 10,
            "水深": 15,
            "DWT": 100000,
            "土质": "岩石",
            "水域条件": "受限水域"
        }
        self.blackboard = dict(base_context)
        self.steps = self.sop_data.get("steps", [])
        self.executed_steps = set()
        
        # 初始化 LLM
        self.llm_client = LLMClient()
        self.config_name = "Qwen2.5-7B (SiliconFlow)"  # 尝试使用 test_00 中验证过的配置

    def _resolve_value(self, value: Any, context: Dict[str, Any]) -> Any:
        """解析 ${变量} 引用。"""
        if isinstance(value, str):
            pattern = r"\$\{([^}]+)\}"
            matches = re.findall(pattern, value)
            if not matches:
                return value
            if len(matches) == 1 and value.strip() == f"${{{matches[0]}}}":
                return context.get(matches[0])
            def replace_match(match: re.Match) -> str:
                key = match.group(1)
                resolved = context.get(key)
                return str(resolved) if resolved is not None else match.group(0)
            return re.sub(pattern, replace_match, value)
        if isinstance(value, dict):
            return {k: self._resolve_value(v, context) for k, v in value.items()}
        if isinstance(value, list):
            return [self._resolve_value(v, context) for v in value]
        return value

    def _execute_tool(self, tool_name: str, inputs: Dict[str, Any]) -> Any:
        """执行具体的工具。"""
        # 特殊处理 user_input
        if tool_name == "user_input":
            var_name = inputs.get("variable")
            default_val = inputs.get("default")
            # 模拟用户输入：直接使用默认值
            # 也可以在这里加上真正的 input()
            if var_name == "Z3": return 0.15
            if var_name == "H_nav": return 0.5
            return default_val

        # 特殊处理 auto
        if tool_name == "auto":
            return {"status": "success", "message": "已完成总结"}

        tool = ToolRegistry.get_tool(tool_name)
        if not tool:
            return {"error": f"未找到工具 {tool_name}"}
        
        try:
            return tool.run(**inputs)
        except Exception as e:
            return {"error": str(e)}

    def run_step(self) -> bool:
        """运行一次 LLM 调度决策循环。返回是否继续。"""
        
        # 1. 构造 Prompt
        # 提取未执行的步骤
        available_steps = [s for s in self.steps if s["id"] not in self.executed_steps]
        if not available_steps:
            print_colored("Agent", "所有步骤已执行完毕。", GREEN)
            return False

        # 简化步骤描述给 LLM
        steps_desc = []
        for s in available_steps:
            inputs_needed = [k for k in re.findall(r"\$\{([^}]+)\}", json.dumps(s.get("inputs", {})))]
            outputs_produced = list(s.get("outputs", {}).keys())
            steps_desc.append(f"- ID: {s['id']}, Name: {s['name']}, Needs: {inputs_needed}, Produces: {outputs_produced}")
        
        steps_text = "\n".join(steps_desc)
        blackboard_keys = list(self.blackboard.keys())
        
        system_prompt = (
            "你是一个智能 SOP 调度器。你的任务是根据当前 Blackboard（黑板）中已有的变量，"
            "从给定的可用步骤（Available Steps）中选择下一个**最合适**执行的步骤。\n"
            "规则：\n"
            "1. 优先选择依赖参数（Needs）已经在 Blackboard 中存在的步骤。\n"
            "2. 如果步骤不需要依赖（Needs 为空），可以直接执行。\n"
            "3. 如果有多个步骤满足条件，按列表顺序选择第一个。\n"
            "4. 返回格式必须是 JSON：{\"step_id\": \"步骤ID\", \"reason\": \"选择理由\"}。\n"
            "5. 不要输出任何其他废话，只输出 JSON。"
        )
        
        user_prompt = (
            f"当前 Blackboard 变量: {blackboard_keys}\n\n"
            f"可用步骤 (Available Steps):\n{steps_text}\n\n"
            "请决策下一步执行哪个步骤？"
        )
        
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt}
        ]

        print_colored("LLM 思考中...", user_prompt[:200] + "...", GRAY)
        
        try:
            # 调用 LLM
            response = self.llm_client.chat(messages, config_name=self.config_name)
            # 尝试提取 JSON
            json_match = re.search(r"\{.*\}", response, re.DOTALL)
            if not json_match:
                print_colored("错误", f"LLM 返回格式错误: {response}", RED)
                return False
            
            decision = json.loads(json_match.group(0))
            step_id = decision.get("step_id")
            reason = decision.get("reason")
            
            print_colored("LLM 决策", decision, YELLOW)
            
            # 2. 查找对应步骤
            target_step = next((s for s in self.steps if s["id"] == step_id), None)
            if not target_step:
                print_colored("错误", f"LLM 选择了不存在的步骤: {step_id}", RED)
                return False

            # 3. 准备执行参数
            print_colored("执行步骤", target_step["name"], GREEN)
            raw_inputs = target_step.get("inputs", {})
            resolved_inputs = self._resolve_value(raw_inputs, self.blackboard)
            tool_name = target_step.get("tool", "").lower()

            # 4. 执行工具
            print_colored("工具调用", {"tool": tool_name, "inputs": resolved_inputs}, YELLOW)
            result = self._execute_tool(tool_name, resolved_inputs)
            print_colored("工具返回", result, YELLOW)
            
            # 5. 更新 Blackboard
            updates = {}
            if isinstance(result, dict) and "error" not in result:
                outputs_map = target_step.get("outputs", {})
                for key, rule in outputs_map.items():
                    # 简化提取逻辑，假设 result 结构匹配
                    if rule == "result":
                        val = result.get("result")
                        # 处理复杂结构提取（这里简化处理，假设直接在 result 或 result['result'] 中）
                        if isinstance(val, dict):
                             # 尝试从字典中提取 key
                            val = val.get(key, val)
                        updates[key] = val
                    else:
                        updates[key] = result # 默认情况

                # 补充逻辑：针对 table_lookup 的复杂提取
                if tool_name == "table_lookup" and "result" in result:
                    res_dict = result["result"]
                    if isinstance(res_dict, dict):
                         for key in outputs_map.keys():
                            # 尝试模糊匹配或直接匹配
                            if key in res_dict:
                                updates[key] = res_dict[key]
                            # 特殊映射处理 (硬编码演示)
                            if key == "T" and "满载吃水T" in res_dict: updates[key] = res_dict["满载吃水T"]
                            if key == "Z0" and "Z0(m)" in res_dict: updates[key] = res_dict["Z0(m)"]
                            if key == "Z1": 
                                # 简单模拟 Z1 提取逻辑
                                updates[key] = "0.80" # 演示用，实际应复用 test_03 的逻辑
                            if key == "Z2" and "Z2 (m)" in res_dict: updates[key] = res_dict["Z2 (m)"]

            self.blackboard.update(updates)
            self.executed_steps.add(step_id)
            
            print_blackboard(self.blackboard, updates)
            return True

        except Exception as e:
            print_colored("异常", str(e), RED)
            return False

def run_llm_scheduler_demo():
    print_colored("启动", "LLM 驱动 SOP 调度演示", GREEN)
    agent = SOPAgent(SOP_JSON_PATH)
    
    # 限制最大步数防止死循环
    max_steps = 10
    for i in range(max_steps):
        print(f"\n--- Round {i+1} ---")
        should_continue = agent.run_step()
        if not should_continue:
            break

if __name__ == "__main__":
    run_llm_scheduler_demo()
