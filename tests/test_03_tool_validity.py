import sys
import os
import json
import re
from typing import Any, Dict

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "../backend")))

from src.tools import ToolRegistry

SOP_JSON_PATH = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "backend", "sop_json", "航道通航底高程.json"))


def run_step1_demo() -> None:
    """加载 sop_json 并执行 step1-7，按步骤输出带颜色的过程信息。"""
    gray = "\033[90m"
    yellow = "\033[33m"
    green = "\033[32m"
    red = "\033[31m"
    reset = "\033[0m"

    def print_colored(title: str, content: Any, color: str) -> None:
        """打印带颜色的标题与内容块。"""
        text = json.dumps(content, ensure_ascii=False, indent=2) if isinstance(content, (dict, list)) else str(content)
        print(f"{color}[{title}]{reset}")
        print(f"{color}{text}{reset}")

    if not os.path.exists(SOP_JSON_PATH):
        print_colored("错误", f"未找到 SOP JSON: {SOP_JSON_PATH}", green)
        return

    with open(SOP_JSON_PATH, "r", encoding="utf-8") as f:
        sop_data = json.load(f)

    steps = sop_data.get("steps") or []
    if not steps:
        print_colored("错误", "SOP JSON 中未找到步骤", green)
        return

    def resolve_value(value: Any, context: Dict[str, Any]) -> Any:
        """解析 ${变量} 引用并返回实际值。"""
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
            return {k: resolve_value(v, context) for k, v in value.items()}
        if isinstance(value, list):
            return [resolve_value(v, context) for v in value]
        return value

    blackboard = sop_data.get("blackboard") or {}
    base_context = {
        "船型": "油船",
        "吨级": 100000,
        "航速": 10,
        "水深": 15,
        "DWT": 100000,
        "土质": "岩石",
        "水域条件": "受限水域"
    }
    blackboard_values = dict(base_context)

    def print_blackboard(values: Dict[str, Any], updates: Dict[str, Any]) -> None:
        """打印黑板并高亮本步更新的值。"""
        print(f"{green}[更新后的 blackboard]{reset}")
        for key in sorted(values.keys()):
            value = values.get(key)
            if key in updates:
                print(f"{red}{key}: {value}{reset}")
            else:
                print(f"{key}: {value}")

    def pick_range_value(value_map: Dict[str, Any], dwt_value: Any) -> Any:
        """从区间表头中根据 DWT 选择对应值。"""
        if dwt_value is None:
            return value_map
        try:
            numeric = float(dwt_value)
        except (TypeError, ValueError):
            return value_map
        for col_key, col_val in value_map.items():
            col_text = str(col_key).replace("&lt;", "<").replace("&gt;", ">")
            range_match = re.search(r"(\d+(?:\.\d+)?)\s*≤\s*DWT\s*<\s*(\d+(?:\.\d+)?)", col_text)
            if range_match and float(range_match.group(1)) <= numeric < float(range_match.group(2)):
                return col_val
            lt_match = re.search(r"DWT\s*<\s*(\d+(?:\.\d+)?)", col_text)
            if lt_match and numeric < float(lt_match.group(1)):
                return col_val
            ge_match = re.search(r"DWT\s*≥\s*(\d+(?:\.\d+)?)", col_text)
            if ge_match and numeric >= float(ge_match.group(1)):
                return col_val
        return value_map

    def extract_output_value(output_key: str, output_rule: Any, tool_result: Any, context: Dict[str, Any]) -> Any:
        """根据 SOP 输出规则从工具返回中提取值。"""
        if output_rule == "result":
            if isinstance(tool_result, dict):
                raw_result = tool_result.get("result", tool_result)
                if isinstance(raw_result, dict):
                    if output_key in raw_result:
                        return raw_result.get(output_key)
                    if output_key == "T":
                        return raw_result.get("满载吃水T") or raw_result.get("满载吃水T(m)") or raw_result.get("T")
                    if output_key == "Z0":
                        return raw_result.get("Z0(m)") or raw_result.get("Z0")
                    if output_key == "Z2":
                        return raw_result.get("Z2 (m)") or raw_result.get("Z2")
                    if output_key == "Z1":
                        return pick_range_value(raw_result, context.get("DWT"))
                return raw_result
            return tool_result
        if output_rule == "input":
            if isinstance(tool_result, dict):
                return tool_result.get("input") or tool_result.get("value") or tool_result.get("result")
            return tool_result
        if isinstance(output_rule, (int, float)):
            return output_rule
        if isinstance(output_rule, str):
            try:
                return float(output_rule)
            except ValueError:
                return output_rule
        return value

    def generate_step_summary(step_name: str, tool_name: str, resolved_inputs: Any, result: Any, updates: Dict[str, Any]) -> str:
        """模拟 LLM 对每一步执行结果的自然语言小结。"""
        # 如果是 auto，直接使用 description
        if tool_name == "auto":
            return f"本步骤为最终输出步骤，基于上下文整理并展示了所有关键参数的计算结果。"
            
        summary = f"在步骤“{step_name}”中，"
        
        # 根据工具类型生成不同的话术
        if tool_name == "table_lookup":
            table_name = resolved_inputs.get("table_name", "未知表格")
            conditions = resolved_inputs.get("query_conditions", {})
            cond_str = ", ".join([f"{k}={v}" for k, v in conditions.items()])
            summary += f"我查阅了 **{table_name}**。根据条件 {cond_str}，"
            if "error" in result:
                summary += f"查询失败，错误信息为：{result['error']}。"
            else:
                res_val = result.get("result", {})
                # 简化显示，只显示更新的值
                if updates:
                    updates_str = ", ".join([f"{k}={v}" for k, v in updates.items()])
                    summary += f"成功获取到数据，更新了：{updates_str}。"
                else:
                    summary += "获取到了数据，但未触发 Blackboard 更新。"
                    
        elif tool_name == "calculator":
            expression = resolved_inputs.get("expression", "")
            summary += f"我执行了计算。公式为 `{expression}`。"
            if "error" in result:
                summary += f"计算出错：{result['error']}。"
            else:
                val = result.get("result")
                if updates:
                    updates_str = ", ".join([f"{k}={v}" for k, v in updates.items()])
                    summary += f"计算结果为 {val}，更新了：{updates_str}。"
                else:
                    summary += f"计算结果为 {val}。"

        elif tool_name == "user_input":
            var = resolved_inputs.get("variable", "")
            default = resolved_inputs.get("default", "")
            summary += f"我请求获取输入变量 `{var}`（默认值：{default}）。"
            val = result.get("result")
            summary += f"最终确定的值为 {val}。"
            
        else:
            summary += f"调用了工具 `{tool_name}`，执行完成。"
            
        return summary

    result_md_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "result.md"))
    # 初始化 result.md
    with open(result_md_path, "w", encoding="utf-8") as f:
        f.write("# SOP 执行日志 (LLM 风格小结版)\n\n")
        f.write("> **说明**: 本日志展示了每一步的执行小结与 Blackboard 状态快照。更新的内容已高亮显示。\n\n---\n\n")

    for step in steps[:9]:
        print_colored("步骤提取", {"step": step, "blackboard": blackboard_values}, gray)
        raw_inputs = step.get("inputs") or {}
        resolved_inputs = resolve_value(raw_inputs, blackboard_values)
        tool_name = (step.get("tool") or "").strip().lower()
        step_id = step.get("id", "")
        step_name = step.get("name", "")
        description = step.get("description", "")

        if tool_name == "auto":
            print_colored("工具使用过程", {"tool": tool_name, "inputs": blackboard_values, "description": description}, yellow)
            # 收集 blackboard 中所有已知参数
            known_params = {k: v for k, v in blackboard_values.items()}
            # 尝试识别出是"结果"的参数（这里简单假设 outputs 列表里的 key 算结果，或者根据 key pattern）
            # 为了通用，直接列出所有 blackboard 内容作为"当前上下文"
            
            lines = [
                f"步骤说明：{description}" if description else "步骤说明：",
                "",
                "当前 Blackboard 状态："
            ]
            for k, v in known_params.items():
                lines.append(f"- {k}: {v}")
            
            summary_text = "\n".join(lines)
            
            # auto 工具的特殊逻辑：它本身就是生成总结，所以这里的 summary_text 可以更定制化
            # 恢复之前的逻辑：区分已知参数和计算结果
            summary_keys = ["D0", "E_nav", "T", "Z0", "Z1", "Z2", "Z3", "H_nav"]
            summary_dict = {k: blackboard_values.get(k) for k in summary_keys if k in blackboard_values}
            known_dict = {k: v for k, v in blackboard_values.items() if k not in summary_dict}
            
            lines = [
                f"步骤说明：{description}" if description else "步骤说明：",
                "",
                "已知参数："
            ]
            if known_dict:
                lines.extend([f"- {k}: {v}" for k, v in known_dict.items()])
            else:
                lines.append("- 无")
            lines.append("")
            lines.append("计算结果：")
            if summary_dict:
                lines.extend([f"- {k}: {v}" for k, v in summary_dict.items()])
            else:
                lines.append("- 无")
            
            final_summary_text = "\n".join(lines)

            auto_result = {
                "description": description,
                "summary": summary_dict,
                "summary_text": final_summary_text
            }
            
            # 追加写入 result.md
            with open(result_md_path, "a", encoding="utf-8") as f:
                f.write(f"## {step_id}: {step_name}\n\n")
                f.write(f"**LLM 小结**:\n\n{generate_step_summary(step_name, tool_name, {}, auto_result, {})}\n\n")
                f.write(final_summary_text + "\n\n---\n\n")

            print_colored("工具返回", auto_result, yellow)
            print_colored("结果", {"should_update_blackboard": False}, green)
            print_blackboard(blackboard_values, {})
            continue

        if tool_name == "user_input":
            outputs = step.get("outputs") or {}
            output_key = next(iter(outputs.keys()), None)
            default_value = None
            if output_key and output_key in blackboard_values:
                default_value = blackboard_values.get(output_key)
            elif output_key == "Z3":
                default_value = 0.15
            elif output_key == "H_nav":
                default_value = 0.5
            resolved_inputs = {"variable": output_key, "default": default_value}
            print_colored("工具使用过程", {"tool": tool_name, "inputs": resolved_inputs}, yellow)
        else:
            print_colored("工具使用过程", {"tool": tool_name, "inputs": resolved_inputs}, yellow)

        tool = ToolRegistry.get_tool(tool_name)
        if not tool:
            print_colored("结果", f"未找到工具: {tool_name}", green)
            # 记录错误到 md
            with open(result_md_path, "a", encoding="utf-8") as f:
                f.write(f"## {step_id}: {step_name}\n\n")
                f.write(f"**错误**: 未找到工具 `{tool_name}`\n\n---\n\n")
            continue

        result = tool.run(**resolved_inputs)
        print_colored("工具返回", result, yellow)

        should_update = isinstance(result, dict) and "error" not in result
        updates = {}
        if should_update:
            outputs = step.get("outputs") or {}
            for key, rule in outputs.items():
                updates[key] = extract_output_value(key, rule, result, blackboard_values)
            blackboard_values.update(updates)
        
        # 追加写入 result.md
        with open(result_md_path, "a", encoding="utf-8") as f:
            f.write(f"## {step_id}: {step_name}\n\n")
            
            # 1. 写入 LLM 小结
            llm_summary = generate_step_summary(step_name, tool_name, resolved_inputs, result, updates)
            f.write(f"**LLM 小结**:\n\n{llm_summary}\n\n")
            
            # 2. 写入 Blackboard 更新表格
            f.write(f"**Blackboard 状态**:\n\n")
            f.write("| Key | Value | Status |\n")
            f.write("| --- | --- | --- |\n")
            
            # 排序 key，把 updates 放前面
            all_keys = sorted(blackboard_values.keys())
            # 将更新的 key 放到列表最前面展示
            updated_keys = sorted(updates.keys())
            other_keys = [k for k in all_keys if k not in updates]
            
            for k in updated_keys:
                val = blackboard_values.get(k)
                f.write(f"| **{k}** | **{val}** | 🟢 Updated |\n")
            
            for k in other_keys:
                val = blackboard_values.get(k)
                f.write(f"| {k} | {val} | |\n")
                
            f.write("\n")
            
            # 3. 详细工具日志（折叠）
            f.write("<details>\n<summary>点击查看工具调用详情</summary>\n\n")
            f.write(f"**说明**: {description}\n\n")
            f.write(f"**工具**: `{tool_name}`\n\n")
            f.write("**输入**:\n")
            f.write(f"```json\n{json.dumps(resolved_inputs, ensure_ascii=False, indent=2)}\n```\n\n")
            f.write("**输出**:\n")
            f.write(f"```json\n{json.dumps(result, ensure_ascii=False, indent=2)}\n```\n\n")
            f.write("</details>\n\n")
            f.write("---\n\n")

        print_colored("结果", {"should_update_blackboard": should_update}, green)
        print_blackboard(blackboard_values, updates)


if __name__ == "__main__":
    run_step1_demo()
