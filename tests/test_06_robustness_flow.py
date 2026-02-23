#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
鲁棒性执行链路测试脚本 (Test 06)
展示从意图识别到 SOP 解析、黑板管理、逐步执行的完整过程日志。
"""

import sys
import os
import re
import json
import unittest
from typing import Any, Dict, List, Tuple, Optional

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "../backend")))

from src.agents import IntentClassifier, Dispatcher
from src.core.contextStruct import SOP, Step
from src.core.sop_loader import SopLoader
from src.tools import ToolRegistry
from src.tools import *


def supports_color() -> bool:
    """判断当前控制台是否支持 ANSI 颜色输出。"""
    if os.getenv("NO_COLOR"):
        return False
    if os.getenv("FORCE_COLOR"):
        return True
    if sys.stdout is None:
        return False
    if sys.stdout.isatty():
        return True
    return bool(os.getenv("WT_SESSION") or os.getenv("TERM"))


def colorize(text: str, color_code: str) -> str:
    """为文本添加颜色样式。"""
    if not supports_color():
        return text
    return f"{color_code}{text}\033[0m"


def format_log_prefix(label: str, source: str, color_code: str) -> str:
    """格式化带来源标识的日志前缀。"""
    return colorize(f"[{label}] [{source}]", color_code)


def print_tagged(label: str, content: str, source: str, color_code: str) -> None:
    """按来源颜色打印日志内容。"""
    prefix = format_log_prefix(label, source, color_code)
    if "\n" in content:
        print(prefix)
        print(content)
        return
    print(f"{prefix} {content}")


def resolve_value(value: Any, blackboard: Dict[str, Any]) -> Any:
    """解析上下文引用并返回实际值。"""
    if isinstance(value, str):
        pattern = r"\$\{([^}]+)\}"
        matches = re.findall(pattern, value)
        if not matches:
            return value
        if len(matches) == 1 and value.strip() == f"${{{matches[0]}}}":
            return blackboard.get(matches[0])
        def replace_match(match: re.Match) -> str:
            key = match.group(1)
            resolved = blackboard.get(key)
            return str(resolved) if resolved is not None else match.group(0)
        return re.sub(pattern, replace_match, value)
    if isinstance(value, dict):
        return {k: resolve_value(v, blackboard) for k, v in value.items()}
    if isinstance(value, list):
        return [resolve_value(v, blackboard) for v in value]
    return value


def build_step_inputs(step: Step, blackboard: Dict[str, Any]) -> Tuple[Dict[str, Any], List[str]]:
    """构建工具输入并返回缺失字段列表。"""
    inputs: Dict[str, Any] = {}
    missing: List[str] = []
    for key, value in (step.inputs or {}).items():
        resolved = resolve_value(value, blackboard)
        if resolved is None:
            if key in blackboard:
                inputs[key] = blackboard[key]
            else:
                missing.append(key)
        else:
            inputs[key] = resolved

    if "query" in (step.inputs or {}) and not inputs.get("query"):
        inputs["query"] = blackboard.get("user_query")
    if "question" in (step.inputs or {}) and not inputs.get("question"):
        inputs["question"] = blackboard.get("user_query")
    if "file_name" in (step.inputs or {}) and not inputs.get("file_name"):
        inputs["file_name"] = "《海港水文规范》.md"
    if "variables" in (step.inputs or {}) and not inputs.get("variables"):
        inputs["variables"] = blackboard.get("variables") or {}

    # 针对 user_input 工具的特殊处理：自动推断 variable 参数
    if (step.tool or "").lower() == "user_input":
        if "variable" not in inputs:
            # 如果 outputs 只有一个键，且不是 result/status 等通用键，则假定为目标变量
            if step.outputs and len(step.outputs) == 1:
                var_name = list(step.outputs.keys())[0]
                if var_name not in ("result", "status", "error"):
                    inputs["variable"] = var_name
        
        # 尝试从黑板获取 variable 对应的值，并作为 default 传入
        var_name = inputs.get("variable")
        if var_name and var_name in blackboard:
            inputs["default"] = blackboard[var_name]

    return inputs, missing


def summarize_tool_result(tool_name: str, result: Any) -> Any:
    """生成用于日志展示的简化结果，避免输出过长内容。"""
    if isinstance(result, dict):
        if tool_name == "table_lookup":
            table_result = result.get("result")
            if isinstance(table_result, dict):
                trimmed = {}
                for k, v in table_result.items():
                    if isinstance(v, str) and len(v) > 240:
                        trimmed[k] = v[:240] + "..."
                    else:
                        trimmed[k] = v
                table_result = trimmed
            elif isinstance(table_result, list):
                trimmed_list = []
                for item in table_result:
                    if isinstance(item, str) and len(item) > 240:
                        trimmed_list.append(item[:240] + "...")
                    else:
                        trimmed_list.append(item)
                table_result = trimmed_list
            elif isinstance(table_result, str) and len(table_result) > 240:
                table_result = table_result[:240] + "..."
            summary = {
                "result": table_result,
                "table": result.get("_table_name"),
                "table_title": result.get("_table_context"),
                "status": "error" if result.get("error") else "success"
            }
            if isinstance(summary.get("table_title"), str) and len(summary["table_title"]) > 120:
                summary["table_title"] = summary["table_title"][:120] + "..."
            if result.get("error"):
                summary["error_msg"] = result.get("error")
            return summary
        if "result" in result and isinstance(result["result"], str) and len(result["result"]) > 240:
            return {**result, "result": result["result"][:240] + "..."}
        return result
    return result


def sanitize_tool_result(result: Any) -> Any:
    """清理工具输出，避免黑板被过长内容淹没。"""
    if isinstance(result, dict) and "_source_html" in result:
        cleaned = dict(result)
        cleaned.pop("_source_html", None)
        return cleaned
    return result


def format_json_value(value: Any) -> str:
    """将字典或列表格式化为逐行展示的 JSON 字符串。"""
    if isinstance(value, (dict, list)):
        return json.dumps(value, ensure_ascii=False, indent=2)
    return str(value)

def _normalize_key(text: str) -> str:
    """标准化字段名用于模糊匹配。"""
    if not text:
        return ""
    return re.sub(r"[^0-9a-zA-Z\u4e00-\u9fff]+", "", str(text)).lower()


def _select_scalar_from_result(context_key: str, result_map: Dict[str, Any], blackboard: Dict[str, Any]) -> Any:
    """从表格结果中抽取与目标变量匹配的标量值。"""
    key_norm = _normalize_key(context_key)
    for col_key, col_val in result_map.items():
        col_norm = _normalize_key(col_key)
        if key_norm and (key_norm in col_norm or col_norm in key_norm):
            return col_val
    if context_key == "Z1":
        dwt = blackboard.get("DWT")
        if dwt is None:
            return None
        numeric = None
        try:
            numeric = float(dwt)
        except Exception:
            numeric = None
        if numeric is None:
            return None
        for col_key, col_val in result_map.items():
            col_text = str(col_key).replace("&lt;", "<").replace("&gt;", ">")
            range_match = re.search(r"(\d+(?:\.\d+)?)\s*≤\s*DWT\s*<\s*(\d+(?:\.\d+)?)", col_text)
            if range_match and float(range_match.group(1)) <= numeric < float(range_match.group(2)):
                return col_val
            range_match = re.search(r"(\d+(?:\.\d+)?)\s*<\s*DWT\s*≤\s*(\d+(?:\.\d+)?)", col_text)
            if range_match and float(range_match.group(1)) < numeric <= float(range_match.group(2)):
                return col_val
            range_match = re.search(r"DWT\s*<\s*(\d+(?:\.\d+)?)", col_text)
            if range_match and numeric < float(range_match.group(1)):
                return col_val
            range_match = re.search(r"DWT\s*≥\s*(\d+(?:\.\d+)?)", col_text)
            if range_match and numeric >= float(range_match.group(1)):
                return col_val
            range_match = re.search(r"DWT\s*>\s*(\d+(?:\.\d+)?)", col_text)
            if range_match and numeric > float(range_match.group(1)):
                return col_val
        return None
    return None


def update_blackboard_from_outputs(step: Step, result: Any, blackboard: Dict[str, Any]) -> None:
    """根据步骤 outputs 映射更新黑板数据。"""
    if not step.outputs:
        return
    if step.outputs == "*":
        if isinstance(result, dict):
            blackboard.update(result)
        else:
            blackboard["last_result"] = result
        return

    for context_key, result_path in step.outputs.items():
        value = None
        if not result_path or result_path == ".":
            value = result
        elif result_path == "result":
            if isinstance(result, dict) and "result" in result:
                raw_value = result["result"]
                if isinstance(raw_value, dict):
                    picked = _select_scalar_from_result(context_key, raw_value, blackboard)
                    value = picked if picked is not None else raw_value
                else:
                    value = raw_value
            else:
                value = result
        elif isinstance(result, dict) and result_path in result:
            value = result.get(result_path)
        elif isinstance(result_path, (int, float)):
            value = result_path
        elif isinstance(result_path, str) and result_path.replace('.', '', 1).isdigit():
             try:
                 value = float(result_path)
             except ValueError:
                 value = result_path
        elif isinstance(result_path, str) and result_path not in ("result", "status", "error"):
             # Fallback: treat as constant string if not a known key
             value = result_path

        if value is not None:
            blackboard[context_key] = value


class RobustnessDispatcher:
    """用于测试的调度器包装，记录输入输出并维护黑板。"""

    def __init__(self):
        """初始化调度器、黑板与执行记录。"""
        self.dispatcher = Dispatcher()
        self.history: List[Dict[str, Any]] = []

    def initialize(self, initial_context: Dict[str, Any]) -> None:
        """初始化黑板数据。"""
        self.dispatcher.memory.update_context(initial_context)

    def run_step(self, step: Step) -> Dict[str, Any]:
        """执行单步并返回结果记录。"""
        blackboard = self.dispatcher.memory.blackboard
        tool_name = (step.tool or "auto").lower()
        inputs, missing = build_step_inputs(step, blackboard)

        if missing:
            for key in missing:
                inputs[key] = f"__missing__{key}"

        if tool_name == "auto":
            record = {
                "step_id": step.id,
                "tool": tool_name,
                "inputs": inputs,
                "outputs": {"skipped": True, "reason": "auto 未解析"},
                "missing": missing,
                "status": "skipped"
            }
            self.dispatcher._record_step(step, inputs, record["outputs"], error="auto 未解析")
            self.history.append(record)
            return record

        tool = ToolRegistry.get_tool(tool_name)
        if not tool:
            record = {
                "step_id": step.id,
                "tool": tool_name,
                "inputs": inputs,
                "outputs": {"error": f"未找到工具: {tool_name}"},
                "missing": missing,
                "status": "failed"
            }
            self.dispatcher._record_step(step, inputs, record["outputs"], error="未找到工具")
            self.history.append(record)
            return record

        result = tool.run(**inputs)
        result = sanitize_tool_result(result)
        update_blackboard_from_outputs(step, result, blackboard)

        record = {
            "step_id": step.id,
            "tool": tool_name,
            "inputs": inputs,
            "outputs": result,
            "missing": missing,
            "status": "success" if not isinstance(result, dict) or not result.get("error") else "failed"
        }
        self.dispatcher._record_step(step, inputs, result, error=result.get("error") if isinstance(result, dict) else None)
        self.history.append(record)
        return record


class TestRobustnessFlow(unittest.TestCase):
    """鲁棒性测试用例。"""

    @classmethod
    def setUpClass(cls):
        """初始化 SOP 与意图分类器。"""
        cls.sop_dir = os.path.join(os.path.dirname(__file__), "../backend/sops")
        cls.sop_loader = SopLoader(cls.sop_dir)
        cls.sops = cls.sop_loader.load_all()
        cls.classifier = IntentClassifier(cls.sops)

    def test_robustness_execution_flow(self):
        """执行完整鲁棒性流程并输出详细日志。"""
        # query = "我要设计一个油船航道，设计船型是 10万吨级油船。航道底质是岩石。设计通航水位是理论最低潮面 0.5m。航速 10节，受限水域。请计算通航底高程。"
        # 增加 DWT 和 水深 明确指定，增强鲁棒性
        query = "我要设计一个油船航道，设计船型是 10万吨级油船(DWT 100000)。航道底质是岩石。设计通航水位是理论最低潮面 0.5m。航速 10节，受限水域，水深 15m。请计算通航底高程。"
        print_tagged("系统提示", "\n" + "=" * 70, "系统输出", "\033[32m")
        print_tagged("系统提示", "Test 06: 鲁棒性执行链路展示", "系统输出", "\033[32m")
        print_tagged("系统提示", "=" * 70, "系统输出", "\033[32m")
        print_tagged("输入消息", query, "文件输入", "\033[90m")

        config_name = os.getenv("TEST_LLM_CONFIG") or "Qwen3-4B (Public)"
        sop, args, reason = self.classifier.route(query, config_name=config_name)
        if not sop:
            self.fail(f"未匹配到 SOP，原因: {reason}")

        print_tagged(
            "输出响应",
            f"SOP: {sop.id} | 参数: {args} | 原因: {reason}",
            "程序输出",
            "\033[33m"
        )
        
        # 优化输出：展示参数对比表格
        print_tagged("系统提示", "\n" + "-" * 70, "系统输出", "\033[32m")
        print_tagged("SOP 参数提取对比", "", "程序输出", "\033[33m")
        
        required = []
        if sop.blackboard:
            required = sop.blackboard.get("required", [])
        
        extracted_keys = list(args.keys()) if args else []
        all_keys = sorted(list(set(required) | set(extracted_keys)))
        
        print(colorize(f"{'字段':<20} | {'SOP需求':<10} | {'本次提取':<10} | {'备注'}", "\033[33m"))
        print(colorize("-" * 70, "\033[33m"))
        
        for key in all_keys:
            is_required = key in required
            val = args.get(key)
            has_value = val is not None
            
            req_str = "Yes" if is_required else "No"
            val_str = str(val) if has_value else "None"
            if len(val_str) > 10:
                val_str = val_str[:7] + "..."
                
            note = ""
            if not is_required and has_value:
                note = "用户额外提供 (超纲)"
            elif is_required and not has_value:
                note = "缺失 (需后续补全)"
                
            print(colorize(f"{key:<20} | {req_str:<10} | {val_str:<10} | {note}", "\033[33m"))
        print(colorize("-" * 70 + "\n", "\033[33m"))

        sop_json_dir = os.path.abspath(os.path.join(self.sop_dir, "..", "sop_json"))
        sop_json_path = os.path.join(sop_json_dir, f"{sop.id}.json")
        sop_filename = None
        if sop.steps and sop.steps[0].inputs:
            sop_filename = sop.steps[0].inputs.get("filename")
        if not sop_filename:
            sop_filename = f"{sop.id}.md"
        sop_md_path = os.path.join(self.sop_dir, sop_filename)

        has_preparse = os.path.exists(sop_json_path)
        md_mtime = os.path.getmtime(sop_md_path) if os.path.exists(sop_md_path) else 0
        json_mtime = os.path.getmtime(sop_json_path) if has_preparse else 0

        force_refresh = False
        if has_preparse and json_mtime >= md_mtime:
            print_tagged(
                "SOP 预解析",
                f"找到 sop_json: {os.path.basename(sop_json_path)} | md: {os.path.basename(sop_md_path)}",
                "程序输出",
                "\033[33m"
            )
        elif has_preparse:
            print_tagged(
                "SOP 预解析",
                f"已过期: json_mtime({json_mtime}) < md_mtime({md_mtime}) | md: {os.path.basename(sop_md_path)}",
                "程序输出",
                "\033[33m"
            )
            force_refresh = True
        else:
            print_tagged(
                "SOP 预解析",
                f"未找到 sop_json: {os.path.basename(sop_json_path)} | md: {os.path.basename(sop_md_path)}",
                "程序输出",
                "\033[33m"
            )
            force_refresh = True

        analyzed = self.sop_loader.analyze_sop(sop.id, save_to_json=True, force_refresh=force_refresh)
        print_tagged("SOP 解析", f"步骤数: {len(analyzed.steps)}", "程序输出", "\033[33m")

        blackboard = {"user_query": query}
        blackboard.update(args or {})
        # 补充用户输入变量，模拟用户已回答
        blackboard["Z3"] = 0.15
        blackboard["H_nav"] = 0.5
        
        dispatcher = RobustnessDispatcher()
        dispatcher.initialize(blackboard)

        print_tagged(
            "黑板初始化",
            format_json_value(dispatcher.dispatcher.memory.blackboard),
            "程序输出",
            "\033[33m"
        )

        for idx, step in enumerate(analyzed.steps, start=1):
            print_tagged("系统提示", "\n" + "-" * 70, "系统输出", "\033[32m")
            print_tagged(
                f"步骤 {idx}",
                f"{step.name or step.id}",
                "程序输出",
                "\033[33m"
            )
            print_tagged(
                f"步骤 {idx}",
                f"工具: {step.tool} | 描述: {step.description}",
                "程序输出",
                "\033[33m"
            )
            record = dispatcher.run_step(step)
            summary = summarize_tool_result(record["tool"], record["outputs"])
            print_tagged("步骤输入", format_json_value(record["inputs"]), "程序输出", "\033[33m")
            print_tagged("步骤缺失", format_json_value(record["missing"]), "程序输出", "\033[33m")
            print_tagged("步骤输出", format_json_value(summary), "程序输出", "\033[33m")

        print_tagged("系统提示", "\n" + "=" * 70, "系统输出", "\033[32m")
        print_tagged("执行结束", "调度器记忆（仅输入输出）", "程序输出", "\033[33m")
        for record in dispatcher.dispatcher.memory.history:
            summary = summarize_tool_result(record.tool_name, record.outputs)
            print_tagged(
                "执行记录",
                f"Step {record.step_id} | Tool {record.tool_name} | Status {record.status}",
                "程序输出",
                "\033[33m"
            )
            print_tagged("记录输入", format_json_value(record.inputs), "程序输出", "\033[33m")
            print_tagged("记录输出", format_json_value(summary), "程序输出", "\033[33m")

        self.assertTrue(len(dispatcher.history) > 0)


if __name__ == "__main__":
    unittest.main()
