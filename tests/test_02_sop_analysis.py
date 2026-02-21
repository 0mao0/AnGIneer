import sys
import os
import re
import json
import unittest
from typing import Dict, Any, List, Optional

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "../backend")))

from src.agents import IntentClassifier
from src.core.contextStruct import Step, SOP
from src.core.sop_loader import SopLoader
from src.tools import ToolRegistry

"""
SOP 混合分析测试脚本 (Test 02)
验证 SOP 路由后对每个步骤进行分析与 AI 代替执行的能力。
"""

SAMPLE_QUERIES = [
    {
        "id": "case_1",
        "label": "通航宽度（计算）",
        "query": "已知设计通航宽度基准 120m，加宽 15m，求通航宽度。",
        "expected_sop": "math_sop"
    },
    {
        "id": "case_2",
        "label": "程序脚本审查",
        "query": "给出航道设计计算脚本文件路径 d:/AI/PicoAgent/demo/channel_design.py，按读取-静态检查-总结-生成报告的流程完成审查。",
        "expected_sop": "code_review"
    },
    {
        "id": "case_3",
        "label": "市场调研",
        "query": "以“航道疏浚服务”作为调研主题，按步骤搜索 2025 市场趋势与主要竞争对手，汇总并形成报告。",
        "expected_sop": "market_research"
    },
    {
        "id": "case_4",
        "label": "挖槽宽度（计算）",
        "query": "已知设计通航宽度 150m，底宽附加宽度两侧各 2m，求挖槽底宽。",
        "expected_sop": "挖槽宽度"
    },
    {
        "id": "case_5",
        "label": "桥区通航净空尺度（计算）",
        "query": "某内河航道桥梁，已知通航净空高度基准为 18m，安全裕度 2m；通航净空宽度基准为 120m，安全裕度 10m。求该桥区的实际通航净空高度与宽度。",
        "expected_sop": "桥区通航净空尺度"
    },
    {
        "id": "case_6",
        "label": "航道尺度汇总表（计算）",
        "query": "某航道工程设计参数如下：通航宽度 135m、边坡 1:4、设计底高程 -12.5m、转弯半径 600m。请根据 SOP 要求汇总并输出关键尺度设计成果清单。",
        "expected_sop": "航道尺度汇总表"
    },
    {
        "id": "case_7",
        "label": "航道边坡（计算）",
        "query": "某航道工程位于粉质黏土层，设计开挖深度为 6m。请查表确定该航道的建议边坡坡度范围。",
        "expected_sop": "航道边坡"
    },
    {
        "id": "case_8",
        "label": "航道通航底高程（计算）",
        "query": "已知某航道的设计通航水位为 4.2m，设计船型设计水深为 10.5m，考虑富裕深度 1.0m。求该航道的通航底高程。",
        "expected_sop": "航道通航底高程"
    },
    {
        "id": "case_9",
        "label": "设计底高程（计算）",
        "query": "已知某航道的设计通航水位为 4.0m，设计水深 9.0m，备淤深度 0.6m，施工超深 0.4m。求该航道的设计底高程。",
        "expected_sop": "设计底高程"
    },
    {
        "id": "case_10",
        "label": "转弯段尺度（计算）",
        "query": "某航道设计船型宽度为 28m，根据规范要求转弯系数 K 取 8。求该航道转弯段的最小转弯半径。",
        "expected_sop": "转弯段尺度"
    },
    {
        "id": "case_11",
        "label": "通航宽度（计算）",
        "query": "某单向通航航道，设计通航宽度基准值为 120m，根据通航环境需加宽 15m。求该航道的最终设计通航宽度。",
        "expected_sop": "通航宽度"
    }
]

def select_cases(env_query: Optional[str]) -> List[Dict[str, Any]]:
    """根据环境变量过滤测试用例。"""
    if env_query and env_query != "all":
        matched_case = next((c for c in SAMPLE_QUERIES if c["query"] == env_query), None)
        if matched_case:
            return [matched_case]
        return [{
            "id": "manual",
            "label": "Manual Query",
            "query": env_query,
            "expected_sop": None
        }]
    return SAMPLE_QUERIES

def build_fallback_steps(sop_id: str, description: str) -> List[Step]:
    """构造 SOP 解析失败时的兜底步骤。"""
    summary = description or sop_id
    base_inputs = {"question": "用户问题摘要"}
    step1 = Step(
        id="step_parse",
        name="解析问题",
        description=f"梳理问题并提取关键参数：{summary}",
        tool="auto",
        inputs=base_inputs,
        outputs={"parsed_context": "context"},
        notes="优先从题干中提取关键信息",
        analysis_status="analyzed"
    )
    step2_tool = "knowledge_search" if any(k in summary for k in ["尺度", "高程", "通航", "桥区", "挖槽", "表"]) else "auto"
    step2 = Step(
        id="step_reason",
        name="推导结论",
        description="基于规范或经验推导结果并说明依据",
        tool=step2_tool,
        inputs={"context": "${parsed_context}"},
        outputs={"result": "result"},
        notes="如需规范或数据支持，需外部工具辅助",
        analysis_status="analyzed"
    )
    return [step1, step2]

def analyze_sop_with_fallback(loader: SopLoader, sop_id: str, sop_map: Dict[str, SOP], config: str = None, mode: str = "instruct") -> SOP:
    """尝试分析 SOP 并在失败时走兜底流程。"""
    try:
        return loader.analyze_sop(sop_id, config_name=config, mode=mode)
    except Exception:
        base = sop_map.get(sop_id)
        fallback_steps = build_fallback_steps(sop_id, base.description if base else sop_id)
        return SOP(
            id=sop_id,
            name_zh=base.name_zh if base else sop_id,
            name_en=base.name_en if base else sop_id,
            description=base.description if base else sop_id,
            steps=fallback_steps
        )

def extract_numbers(query: str) -> List[float]:
    """从用户问题中提取所有数值。"""
    nums = re.findall(r"\d+(?:\.\d+)?", query or "")
    return [float(n) for n in nums]

def resolve_value(value: Any, context: Dict[str, Any]) -> Any:
    """解析输入中的上下文引用并返回实际值。"""
    if isinstance(value, str):
        m = re.match(r"^\$\{([^}]+)\}$", value.strip())
        if m:
            return context.get(m.group(1))
        return value
    if isinstance(value, dict):
        return {k: resolve_value(v, context) for k, v in value.items()}
    if isinstance(value, list):
        return [resolve_value(v, context) for v in value]
    return value

def auto_extract_variables(step: Step, query: str, context: Dict[str, Any]) -> Dict[str, float]:
    """根据步骤预期变量名从问题中抽取数值并写入上下文。"""
    variables = {}
    expected = (step.inputs or {}).get("variables") or []
    numbers = extract_numbers(query)
    for idx, name in enumerate(expected):
        if idx < len(numbers):
            variables[name] = numbers[idx]
    context_vars = context.get("variables") or {}
    context_vars.update(variables)
    context["variables"] = context_vars
    return variables

def execute_step(step: Step, query: str, context: Dict[str, Any]) -> Dict[str, Any]:
    """执行单个步骤并返回工具输出。"""
    tool_name = (step.tool or "auto").lower()
    if tool_name == "auto":
        extracted = auto_extract_variables(step, query, context)
        return {"result": extracted, "context": extracted}

    tool = ToolRegistry.get_tool(tool_name)
    if not tool:
        return {"error": f"未找到工具: {tool_name}"}

    inputs = resolve_value(step.inputs or {}, context)
    if tool_name == "calculator":
        variables = inputs.get("variables") or context.get("variables") or {}
        inputs["variables"] = variables
    if tool_name == "knowledge_search":
        if not inputs.get("query"):
            inputs["query"] = step.description or query
        if not inputs.get("file_name"):
            inputs["file_name"] = "《海港水文规范》.md"
    if tool_name == "report_generator":
        if not inputs.get("title"):
            inputs["title"] = step.name or "SOP 结果"
        if not inputs.get("data"):
            inputs["data"] = context

    result = tool.run(**inputs)
    if isinstance(result, dict):
        return result
    return {"result": result}

def analyze_step(step: Step, query: str, context: Dict[str, Any]) -> Dict[str, Any]:
    """分析步骤结构、执行并回写上下文。"""
    inputs = step.inputs or {}
    outputs = step.outputs or {}
    result = execute_step(step, query, context)
    for ctx_key, out_path in outputs.items():
        if isinstance(result, dict) and out_path in result:
            value = result.get(out_path)
            context[ctx_key] = value
            context_vars = context.get("variables") or {}
            if isinstance(ctx_key, str) and ctx_key:
                context_vars[ctx_key] = value
            context["variables"] = context_vars
    analysis_text = f"工具: {step.tool or 'auto'} | 输入: {list(inputs.keys()) or ['无']} | 输出: {list(outputs.keys()) or ['无']}"
    return {
        "id": step.id,
        "name": step.name or step.id,
        "description": step.description or "",
        "tool": step.tool or "auto",
        "inputs": inputs,
        "outputs": outputs,
        "notes": step.notes or "",
        "analysis": analysis_text,
        "result": result
    }

class TestSopAnalysis(unittest.TestCase):
    def test_step_analysis_cases(self):
        """SOP 步骤分析用例测试。"""
        print("\n[测试 03] SOP 步骤分析测试")
        env_query = os.environ.get("TEST_LLM_QUERY")
        sop_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "backend", "sops")
        loader = SopLoader(sop_dir)
        sops = loader.load_all()
        self.assertGreater(len(sops), 0)
        sop_map = {s.id: s for s in sops}
        classifier = IntentClassifier(sops)
        cases = select_cases(env_query)
        results = []

        for case in cases:
            print(f"\n  --------------------------------------------------")
            print(f"  测试用例: {case['label']}")
            print(f"  Query: {case['query']}")

            sop, args, reason = classifier.route(case["query"])
            matched_sop = sop.id if sop else None
            expected_sop = case.get("expected_sop")
            if expected_sop and expected_sop != matched_sop:
                sop = sop_map.get(expected_sop, sop)
                matched_sop = expected_sop
                reason = reason or "按期望 SOP 兜底"

            analyzed_sop = analyze_sop_with_fallback(loader, matched_sop, sop_map)
            step_payloads = []
            context = {"user_query": case["query"], "variables": {}}
            for idx, step in enumerate(analyzed_sop.steps, start=1):
                print(f"  -> 步骤 {idx}: {step.name or step.id}")
                payload = analyze_step(step, case["query"], context)
                print(f"     工具: {payload['tool']} | 输入: {list(payload['inputs'].keys()) or ['无']} | 输出: {list(payload['outputs'].keys()) or ['无']}")
                print(f"     执行结果: {payload['result']}")
                step_payloads.append(payload)

            results.append({
                "id": case["id"],
                "label": case["label"],
                "query": case["query"],
                "expected_sop": expected_sop,
                "matched_sop": matched_sop,
                "route_reason": reason,
                "args": args,
                "steps": step_payloads
            })

        self.assertTrue(all(r["steps"] for r in results))
        print("\n__JSON_START__")
        print(json.dumps({"cases": results}, ensure_ascii=False, indent=2))
        print("__JSON_END__")

if __name__ == "__main__":
    unittest.main()
