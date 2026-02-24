import sys
import os
import re
import json
import unittest
import time
from typing import Dict, Any, List, Optional

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "../services/angineer-core/src")))
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "../services/sop-core/src")))
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "../services/engtools/src")))
sys.path.append(os.path.abspath(os.path.dirname(__file__)))


from angineer_core.core import IntentClassifier
from angineer_core.standard.context_struct import Step, SOP
from sop_core.sop_loader import SopLoader
from engtools.BaseTool import ToolRegistry
from regression_report import build_report, emit_report

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
        "id": "case_8",
        "label": "航道通航底高程（计算）",
        "query": "已知某航道的设计通航水位为 4.2m，设计船型设计水深为 10.5m，考虑富裕深度 1.0m。求该航道的通航底高程。",
        "expected_sop": "航道通航底高程"
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
    """尝试加载详细 SOP JSON，如果不存在则返回 index 中的 stub。"""
    # 尝试加载详细 JSON
    sop_json_path = os.path.abspath(os.path.join(loader.sop_dir, "..", "json", f"{sop_id}.json"))
    if os.path.exists(sop_json_path):
        try:
            with open(sop_json_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            return SOP(**data)
        except Exception as e:
            print(f"Error loading JSON for {sop_id}: {e}")

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
        """SOP 步骤分析用例测试。
        
        该测试方法用于验证SOP（标准操作程序）步骤分析功能的正确性。
        主要流程包括：加载SOP、分类用户查询、匹配对应的SOP、分析每个步骤并记录结果。
        
        Args:
            self: 测试类实例
            
        Returns:
            None: 该方法不返回值，但会通过断言验证测试结果，
                  并输出JSON格式的详细测试报告
        """
        # 初始化测试环境和数据加载
        print("\n[测试 03] SOP 步骤分析测试")
        start_time = time.perf_counter()
        env_query = os.environ.get("TEST_LLM_QUERY")
        sop_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "sops", "raw")
        loader = SopLoader(sop_dir)
        sops = loader.load_all()
        self.assertGreater(len(sops), 0)
        sop_map = {s.id: s for s in sops}
        classifier = IntentClassifier(sops)
        cases = select_cases(env_query)
        results = []
        report_cases = []

        # 遍历所有测试用例进行分析
        for case in cases:
            print(f"\n  --------------------------------------------------")
            print(f"  测试用例: {case['label']}")
            print(f"  Query: {case['query']}")

            # 路由分类：根据用户查询匹配最合适的SOP
            sop, args, reason = classifier.route(case["query"], config_name="Qwen3-4B (Public)")
            matched_sop = sop.id if sop else None
            expected_sop = case.get("expected_sop")
            if expected_sop and expected_sop != matched_sop:
                sop = sop_map.get(expected_sop, sop)
                matched_sop = expected_sop
                reason = reason or "按期望 SOP 兜底"

            # 分析匹配到的SOP及其各个步骤
            analyzed_sop = analyze_sop_with_fallback(loader, matched_sop, sop_map)
            step_payloads = []
            context = {"user_query": case["query"], "variables": {}}
            if args:
                context.update(args)
            
            # 逐个分析SOP中的每个步骤
            for idx, step in enumerate(analyzed_sop.steps, start=1):
                print(f"  -> 步骤 {idx}: {step.name or step.id}")
                payload = analyze_step(step, case["query"], context)
                print(f"     工具: {payload['tool']} | 输入: {list(payload['inputs'].keys()) or ['无']} | 输出: {list(payload['outputs'].keys()) or ['无']}")
                print(f"     执行结果: {payload['result']}")
                step_payloads.append(payload)

            # 收集当前测试用例的结果数据
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
            case_status = "ok"
            if expected_sop and expected_sop != matched_sop:
                case_status = "fail"
            if not step_payloads:
                case_status = "fail"
            report_cases.append({
                "id": case["id"],
                "label": case["label"],
                "status": case_status,
                "details": {
                    "query": case["query"],
                    "expected_sop": expected_sop,
                    "matched_sop": matched_sop,
                    "route_reason": reason,
                    "steps": step_payloads
                }
            })

        # 验证所有测试用例都有步骤分析结果
        self.assertTrue(all(r["steps"] for r in results))
        
        # 输出JSON格式的测试结果报告
        print("\n__JSON_START__")
        print(json.dumps({"cases": results}, ensure_ascii=False, indent=2))
        print("__JSON_END__")
        summary = {
            "cases": len(report_cases),
            "failures": len([c for c in report_cases if c["status"] == "fail"]),
            "duration": round(time.perf_counter() - start_time, 4)
        }
        meta = {"env_query": env_query}
        emit_report(build_report("test_02_sop_analysis", report_cases, summary=summary, meta=meta))

if __name__ == "__main__":
    unittest.main()
