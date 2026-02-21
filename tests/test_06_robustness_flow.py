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


def parse_user_context(query: str) -> Dict[str, Any]:
    """从用户问题中解析基础条件并构建黑板初始数据。"""
    context: Dict[str, Any] = {"user_query": query, "variables": {}}
    if "油船" in query:
        context["ship_type"] = "油船"
    if "岩石" in query:
        context["bottom_material"] = "岩石"
    if "受限" in query:
        context["navigation_area"] = "受限"

    dwt_match = re.search(r"(\d+)\s*万吨", query)
    if dwt_match:
        context["dwt"] = int(dwt_match.group(1)) * 10000

    water_level_match = re.search(r"设计通航水位.*?([0-9]+(?:\.[0-9]+)?)\s*m", query)
    if water_level_match:
        context["H_nav"] = float(water_level_match.group(1))

    speed_match = re.search(r"航速\s*([0-9]+(?:\.[0-9]+)?)\s*节", query)
    if speed_match:
        context["nav_speed_kn"] = float(speed_match.group(1))

    return context


def resolve_value(value: Any, blackboard: Dict[str, Any]) -> Any:
    """解析上下文引用并返回实际值。"""
    if isinstance(value, str):
        match = re.match(r"^\$\{([^}]+)\}$", value.strip())
        if match:
            return blackboard.get(match.group(1))
        return value
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

    return inputs, missing


def summarize_tool_result(tool_name: str, result: Any) -> Any:
    """生成用于日志展示的简化结果，避免输出过长内容。"""
    if isinstance(result, dict):
        if tool_name == "table_lookup":
            return {
                "result": result.get("result"),
                "headers": result.get("_table_headers"),
                "table": result.get("_table_name"),
                "status": "error" if result.get("error") else "success"
            }
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
                value = result["result"]
            else:
                value = result
        elif isinstance(result, dict) and result_path in result:
            value = result.get(result_path)

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
        blackboard = self.dispatcher.memory.global_context
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
        query = "我要设计一个油船航道，设计船型是 10万吨级油船。航道底质是岩石。设计通航水位是理论最低潮面 0.5m。航速 10节，受限水域。请计算通航底高程。"
        print("\n" + "=" * 70)
        print("Test 06: 鲁棒性执行链路展示")
        print("=" * 70)
        print(f"[输入] {query}")

        sop, args, reason = self.classifier.route(query)
        if not sop:
            self.fail(f"未匹配到 SOP，原因: {reason}")

        print(f"[意图识别] SOP: {sop.id} | 参数: {args} | 原因: {reason}")

        sop_json_dir = os.path.abspath(os.path.join(self.sop_dir, "..", "sop_json"))
        sop_json_path = os.path.join(sop_json_dir, f"{sop.id}.json")
        sop_md_path = os.path.join(self.sop_dir, f"{sop.id}.md")

        has_preparse = os.path.exists(sop_json_path)
        md_mtime = os.path.getmtime(sop_md_path) if os.path.exists(sop_md_path) else 0
        json_mtime = os.path.getmtime(sop_json_path) if has_preparse else 0

        if has_preparse and json_mtime >= md_mtime:
            print(f"[SOP 预解析] 找到 sop_json: {os.path.basename(sop_json_path)}")
        else:
            print(f"[SOP 预解析] 未找到或已过期，将通过 sop_loader 生成解析结果")

        analyzed = self.sop_loader.analyze_sop(sop.id)
        print(f"[SOP 解析] 步骤数: {len(analyzed.steps)}")

        blackboard = parse_user_context(query)
        blackboard.update(args or {})
        dispatcher = RobustnessDispatcher()
        dispatcher.initialize(blackboard)

        print("[黑板初始化]")
        print(format_json_value(dispatcher.dispatcher.memory.global_context))

        for idx, step in enumerate(analyzed.steps, start=1):
            print("\n" + "-" * 70)
            print(f"[步骤 {idx}] {step.name or step.id}")
            print(f"  工具: {step.tool} | 描述: {step.description}")
            record = dispatcher.run_step(step)
            summary = summarize_tool_result(record["tool"], record["outputs"])
            print("  输入:")
            print(format_json_value(record["inputs"]))
            print("  缺失:")
            print(format_json_value(record["missing"]))
            print("  输出:")
            print(format_json_value(summary))

        print("\n" + "=" * 70)
        print("[执行结束] 调度器记忆（仅输入输出）")
        for record in dispatcher.dispatcher.memory.history:
            summary = summarize_tool_result(record.tool_name, record.outputs)
            print(f"- Step {record.step_id} | Tool {record.tool_name} | Status {record.status}")
            print("  Inputs:")
            print(format_json_value(record.inputs))
            print("  Outputs:")
            print(format_json_value(summary))

        self.assertTrue(len(dispatcher.history) > 0)


if __name__ == "__main__":
    unittest.main()
